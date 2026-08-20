from __future__ import annotations

import dataclasses
import json

import pytest

from tests.test_workflow_resume import _execute
from tests.workflow_fixtures import compile_fixture_workflow
from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowStepState,
    WorkflowStepResult,
    WorkflowStateStore,
)
from workbench.agent.workflow_runtime import _completion_seal


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


def test_live_model_completion_rejects_legacy_branches_before_persisting_completion(
    tmp_path,
) -> None:
    draft = compile_fixture_workflow(
        workflow_id="wf-resume-terminal-model-branch",
        steps=[
            {
                "step_id": "model",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": "unadjusted",
                    "branches": [
                        {
                            "branch_id": "m1",
                            "outcome": "outcome",
                            "predictors": ["rate_a"],
                        }
                    ],
                },
            }
        ],
    )

    def first_pass(_step, _previous):
        return WorkflowStepResult(
            artifact_ids=["ols_1"],
            lineage={
                "branches": [
                    {
                        "branch_id": "m1",
                        "run_id": "run-1",
                        "artifact_ids": ["ols_1"],
                        "model_artifact_id": "ols_1",
                        "workflow_id": draft.workflow_id,
                        "workflow_step_id": "model",
                        "source_run_id": "run-1",
                        "source_artifact_id": "raw-1",
                        "source_sha256": "sha256:source-1",
                        "branch_spec": {
                            "model_family": "ols",
                            "outcome": "forged-outcome",
                            "predictors": ["rate_a"],
                            "covariance": "unadjusted",
                        },
                    }
                ]
            },
            output_bindings={
                "legacy_model_branches": {
                    "binding_type": "legacy_model_branches",
                    "branches": [
                        {
                            "branch_id": "m1",
                            "run_id": "run-1",
                            "artifact_ids": ["ols_1"],
                            "model_artifact_id": "ols_1",
                            "workflow_id": draft.workflow_id,
                            "workflow_step_id": "model",
                            "source_run_id": "run-1",
                            "source_artifact_id": "raw-1",
                            "source_sha256": "sha256:source-1",
                            "branch_spec": {
                                "model_family": "ols",
                                "outcome": "forged-outcome",
                                "predictors": ["rate_a"],
                                "covariance": "unadjusted",
                            },
                        }
                    ],
                }
            },
        )

    first = _execute(tmp_path, draft, first_pass)
    assert first.status == "failed"
    assert first.steps["model"].status == "failed"
    assert "canonical model branch binding" in first.steps["model"].error
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )
    evidence = evidence_path.read_text(encoding="utf-8")
    assert '"record_type": "workflow_completion"' not in evidence
    assert '"record_type": "workflow_abort"' in evidence


def test_generic_resume_preserves_empty_completion_metadata_compatibility(tmp_path) -> None:
    """A legacy generic completion without optional metadata remains readable."""

    draft = _resume_fixture("wf-resume-empty-completion-metadata")

    def first_pass(step, _previous):
        if step.step_id == "consume":
            raise WorkflowExecutionError("stop after generic publish")
        return WorkflowStepResult(artifact_ids=["artifact-publish"])

    first = _execute(tmp_path, draft, first_pass)
    assert first.status == "failed"
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def remove_optional_completion_metadata(records):
        matches = [
            record
            for record in records
            if record.get("record_type") == "workflow_completion"
            and record.get("step_id") == "publish"
        ]
        assert len(matches) == 1
        matches[0].pop("output_bindings", None)
        matches[0]["completion_seal"] = _completion_seal(matches[0])

    _rewrite_evidence_records(evidence_path, remove_optional_completion_metadata)

    second_calls: list[str] = []

    def second_pass(step, _previous):
        second_calls.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[f"artifact-{step.step_id}"])

    second = _execute(tmp_path, draft, second_pass)

    assert second.status == "completed"
    assert second_calls == ["consume"]


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


def _rewrite_evidence_records(path, mutate):
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(records)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


@pytest.mark.parametrize("admission_status", ["revoked", "aborted"])
def test_resume_requires_exactly_admitted_persisted_admission_before_callback(
    tmp_path, admission_status
) -> None:
    draft = _resume_fixture(f"wf-resume-admission-{admission_status}")
    _execute(tmp_path, draft, _first_pass)
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def revoke_publish(records):
        matches = [
            record
            for record in records
            if record.get("record_type") == "workflow_admission"
            and record.get("step_id") == "publish"
        ]
        assert len(matches) == 1
        matches[0]["status"] = admission_status

    _rewrite_evidence_records(evidence_path, revoke_publish)
    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[])

    with pytest.raises(WorkflowExecutionError, match="admission|revoked|aborted|authority"):
        _execute(tmp_path, draft, resume_pass)
    assert callback_steps == []


def test_resume_rejects_a_missing_persisted_admission_before_callback(tmp_path) -> None:
    draft = _resume_fixture("wf-resume-admission-missing")
    _execute(tmp_path, draft, _first_pass)
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def remove_publish_admission(records):
        records[:] = [
            record
            for record in records
            if not (
                record.get("record_type") == "workflow_admission"
                and record.get("step_id") == "publish"
            )
        ]

    _rewrite_evidence_records(evidence_path, remove_publish_admission)
    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[])

    with pytest.raises(WorkflowExecutionError, match="admission|authority"):
        _execute(tmp_path, draft, resume_pass)
    assert callback_steps == []


@pytest.mark.parametrize("corrupt_field", ["row_counts", "output_bindings", "lineage"])
def test_resume_validates_completion_seal_before_rehydrating_corrupt_metadata(
    tmp_path, corrupt_field
) -> None:
    draft = _resume_fixture(f"wf-resume-completion-{corrupt_field}")
    _execute(tmp_path, draft, _first_pass)
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def corrupt_publish_completion(records):
        matches = [
            record
            for record in records
            if record.get("record_type") == "workflow_completion"
            and record.get("step_id") == "publish"
        ]
        assert len(matches) == 1
        if corrupt_field == "row_counts":
            matches[0]["row_counts"] = {"source": "not-an-int"}
        elif corrupt_field == "output_bindings":
            matches[0]["output_bindings"] = "not-an-object"
        else:
            matches[0]["lineage"] = "not-an-object"

    _rewrite_evidence_records(evidence_path, corrupt_publish_completion)
    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[])

    with pytest.raises(WorkflowExecutionError, match="completion integrity seal"):
        _execute(tmp_path, draft, resume_pass)
    assert callback_steps == []


@pytest.mark.parametrize(
    "row_count",
    [True, 10**400, 1.25, float("inf"), "12"],
)
def test_persisted_row_counts_reject_non_finite_or_unbounded_values_as_typed_errors(
    row_count,
) -> None:
    with pytest.raises(WorkflowExecutionError, match="row_counts"):
        WorkflowStepState.from_dict(
            {
                "step_id": "publish",
                "fingerprint": "step-fingerprint",
                "status": "completed",
                "artifact_ids": [],
                "row_counts": {"source": row_count},
            }
        )
