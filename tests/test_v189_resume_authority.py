from __future__ import annotations

import dataclasses

import pytest

from tests.test_workflow_resume import _execute
from tests.workflow_fixtures import compile_fixture_workflow
from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowStepResult,
    WorkflowStateStore,
)


def _resume_fixture(workflow_id: str):
    return compile_fixture_workflow(
        workflow_id=workflow_id,
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


def _first_pass(step, _previous):
    if step.step_id == "consume":
        raise WorkflowExecutionError("stop after publish")
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
    )


def test_resume_rejects_tampered_persisted_artifact_before_dependent_callback(tmp_path) -> None:
    draft = _resume_fixture("wf-resume-artifact-authority")
    first = _execute(tmp_path, draft, _first_pass)
    store = WorkflowStateStore(tmp_path, draft.workflow_id)
    forged_publish = dataclasses.replace(
        first.steps["publish"], artifact_ids=("forged-artifact",)
    )
    store.append(
        dataclasses.replace(
            first,
            steps={**first.steps, "publish": forged_publish},
            status="failed",
        )
    )

    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[])

    with pytest.raises(WorkflowExecutionError, match="dependency|artifact|completion"):
        _execute(tmp_path, draft, resume_pass)
    assert callback_steps == []


def test_resume_rejects_tampered_persisted_bindings_and_lineage_before_callback(
    tmp_path,
) -> None:
    draft = _resume_fixture("wf-resume-metadata-authority")
    first = _execute(tmp_path, draft, _first_pass)
    store = WorkflowStateStore(tmp_path, draft.workflow_id)
    forged_publish = dataclasses.replace(
        first.steps["publish"],
        output_bindings={
            "dataset": {
                **first.steps["publish"].output_bindings["dataset"],
                "artifact_id": "forged-artifact",
            }
        },
        lineage={"output_identity": {"artifact_id": "forged-artifact"}},
    )
    store.append(
        dataclasses.replace(
            first,
            steps={**first.steps, "publish": forged_publish},
            status="failed",
        )
    )

    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[])

    with pytest.raises(WorkflowExecutionError, match="dependency|binding|lineage"):
        _execute(tmp_path, draft, resume_pass)
    assert callback_steps == []
