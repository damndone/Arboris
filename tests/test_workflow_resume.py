"""Failure containment and resume for a compiled workflow plan.

Previously exercised through a server-side preset; the invariants belong to the
executor, not to any assignment, so they now run on a composed plan.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.workflow_fixtures import compile_fixture_workflow, composed_plan
from workbench.artifacts import initialize_artifact_index, register_artifact, sha256_file
from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowStepResult,
)
from workbench.agent.workflow_runtime import (
    _admit_workflow_host_endpoint_from_supervisor,
    EvidencePersistencePort,
    issue_server_evidence_port,
    _ReceiptGatedWorkflowExecutor,
)



def _test_evidence_port(project_root):
    root = project_root.resolve()
    workflow_directory = root / "workbench" / "workflows"
    workflow_directory.mkdir(parents=True, exist_ok=True)
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        import workbench.agent.workflow_runtime as workflow_runtime

        endpoint = _admit_workflow_host_endpoint_from_supervisor(root, endpoint_fd)
        with patch.object(
            workflow_runtime,
            "_deployment_host_endpoint_from_supervisor",
            return_value=endpoint,
        ):
            return issue_server_evidence_port(root)
    finally:
        os.close(endpoint_fd)


EvidencePersistencePortFactory = _test_evidence_port


def _non_model_composed_plan() -> list[dict]:
    """Keep generic resume tests away from the model-family authority path."""

    return [
        {
            **spec,
            "depends_on": [
                dependency
                for dependency in spec.get("depends_on", [])
                if dependency != "models"
            ],
        }
        for spec in composed_plan()
        if spec["operation_id"] != "model.genesis"
    ]


def _ok(step_id: str) -> WorkflowStepResult:
    return WorkflowStepResult(
        artifact_ids=[f"artifact-{step_id}"],
        row_counts={"source": 24},
        payload={"result": "bounded"},
    )


def _gated(project_root, draft, callback):
    port = EvidencePersistencePortFactory(project_root)

    def invoke(step, previous, **_kwargs):
        result = callback(step, previous)
        if result.artifact_ids:
            run_root = project_root / "runs" / "run-1"
            run_root.mkdir(parents=True, exist_ok=True)
            index_path = run_root / "artifacts_index.json"
            if not index_path.exists():
                initialize_artifact_index(run_root)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            registered = {
                str(item.get("artifact_id"))
                for item in index.get("artifacts", [])
                if isinstance(item, dict)
            }
            for artifact_id in result.artifact_ids:
                artifact_path = run_root / f"{artifact_id}.json"
                artifact_path.write_text('{"test": true}\n', encoding="utf-8")
                if artifact_id not in registered:
                    register_artifact(
                        run_root,
                        artifact_id,
                        artifact_path,
                        "workflow_output",
                        step.operation_id,
                        [],
                    )
                port._admit_server_artifact(
                    port._active_receipt(),
                    run_id="run-1",
                    artifact_id=artifact_id,
                    path=artifact_path,
                    artifact_type="workflow_output",
                    producer_step=step.operation_id,
                    inputs=(),
                    expected_artifacts=step.expected_artifacts,
                )
            if result.output_bindings:
                bindings = {}
                for name, binding in result.output_bindings.items():
                    updated = dict(binding)
                    artifact_id = str(updated.get("artifact_id") or result.artifact_ids[0])
                    artifact_path = run_root / f"{artifact_id}.json"
                    updated["run_id"] = "run-1"
                    updated["artifact_id"] = artifact_id
                    updated["content_sha256"] = sha256_file(artifact_path)
                    bindings[name] = updated
                result = dataclasses.replace(result, output_bindings=bindings)
        return result

    gated = _ReceiptGatedWorkflowExecutor(invoke, draft)
    gated._bind_evidence_port(port)
    return gated, port


def _execute(project_root, draft, callback):
    gated, port = _gated(project_root, draft, callback)
    return WorkflowExecutor(project_root).execute(draft, gated, evidence_port=port)


def test_failed_step_blocks_dependents_and_preserves_completed_steps(tmp_path) -> None:
    """A dependent of a failed step is blocked, never quietly skipped."""
    draft = compile_fixture_workflow(
        workflow_id="wf-resume-a", steps=_non_model_composed_plan()
    )
    calls: list[str] = []

    def execute(step, _results):
        calls.append(step.step_id)
        if step.step_id == "split":
            return WorkflowStepResult(
                artifact_ids=[], row_counts={}, empty_group_values=[99], payload={}
            )
        return _ok(step.step_id)

    state = _execute(tmp_path, draft, execute)

    assert state.status == "failed"
    assert state.steps["detail"].status == "completed"
    assert state.steps["split"].status == "failed"
    # `compare` depends on the failure; `report` depends on `compare`.
    assert state.steps["compare"].status == "blocked"
    assert state.steps["report"].status == "blocked"
    # Independent steps that had already run keep their results.
    assert state.steps["grouped"].status == "completed"
    assert "compare" not in calls


def test_resume_reuses_completed_steps_and_rejects_a_changed_source(tmp_path) -> None:
    draft = compile_fixture_workflow(
        workflow_id="wf-resume-b", steps=_non_model_composed_plan()
    )

    def failing(step, _results):
        if step.step_id == "detail":
            raise WorkflowExecutionError("simulated step failure")
        return _ok(step.step_id)

    first = _execute(tmp_path, draft, failing)
    assert first.status == "failed"

    second_calls: list[str] = []

    def succeeding(step, _results):
        second_calls.append(step.step_id)
        return _ok(step.step_id)

    second = _execute(tmp_path, draft, succeeding)

    assert second.status == "completed"
    assert "detail" in second_calls
    # Steps that completed in the first pass are not re-executed.
    assert "grouped" not in second_calls
    assert "missing" not in second_calls

    with pytest.raises(WorkflowExecutionError, match="source fingerprint changed"):
        _execute(
            tmp_path,
            compile_fixture_workflow(
                workflow_id="wf-resume-b",
                source_fingerprint="sha256:source-2",
                steps=_non_model_composed_plan(),
            ),
            succeeding,
        )


def test_resume_rehydrates_typed_outputs_and_bounded_lineage(tmp_path) -> None:
    draft = compile_fixture_workflow(
        workflow_id="wf-resume-typed",
        steps=[
            {
                "step_id": "publish",
                "operation_id": "statistical.explore",
                "spec": {"operation": "misstable", "selected_columns": ["rate_a"]},
            },
            {
                "step_id": "consume",
                "operation_id": "statistical.explore",
                "depends_on": ["publish"],
                "spec": {"operation": "misstable", "selected_columns": ["rate_b"]},
            },
        ],
    )

    def first_pass(step, _previous):
        if step.step_id == "consume":
            raise WorkflowExecutionError("stop after typed publish")
        return WorkflowStepResult(
            artifact_ids=["artifact-publish"],
            output_bindings={
                "dataset": {
                    "binding_type": "dataset",
                    "run_id": "run-1",
                    "node_ref": "node-publish",
                    "artifact_id": "artifact-publish",
                    "content_sha256": "sha256:publish",
                }
            },
            lineage={"output_identity": {"artifact_id": "artifact-publish"}},
            payload={"unpersisted_result": {"large": ["x"] * 1000}},
        )

    first = _execute(tmp_path, draft, first_pass)
    assert first.status == "failed"

    seen: dict[str, object] = {}

    def second_pass(step, previous):
        if step.step_id == "consume":
            restored = previous["publish"]
            seen["binding"] = restored.output_bindings["dataset"]["artifact_id"]
            seen["lineage"] = restored.lineage["output_identity"]["artifact_id"]
        return WorkflowStepResult(artifact_ids=[f"artifact-{step.step_id}"])

    second = _execute(tmp_path, draft, second_pass)

    assert second.status == "completed"
    assert seen == {"binding": "artifact-publish", "lineage": "artifact-publish"}
    state_records = (tmp_path / "workbench" / "workflows" / "wf-resume-typed.jsonl").read_text(
        encoding="utf-8"
    )
    assert "unpersisted_result" not in state_records
