from __future__ import annotations

import dataclasses
import json
import multiprocessing
import os
from multiprocessing.reduction import recv_handle, send_handle
from pathlib import Path
from unittest.mock import patch

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
from workbench.agent.workflow_runtime import (
    EvidencePersistencePort,
    _admit_workflow_host_endpoint_from_supervisor,
    issue_server_evidence_port,
)


def _issued_evidence_port(project_root):
    root = Path(project_root).resolve()
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


def _spawn_validate_resumed_step(project_root: str, endpoint_connection, result_queue) -> None:
    """Create a fresh worker port from the supervisor's admitted directory FD."""

    endpoint_fd = recv_handle(endpoint_connection)
    try:
        root = Path(project_root).resolve()
        import workbench.agent.workflow_runtime as workflow_runtime

        endpoint = _admit_workflow_host_endpoint_from_supervisor(root, endpoint_fd)
        with patch.object(
            workflow_runtime,
            "_deployment_host_endpoint_from_supervisor",
            return_value=endpoint,
        ):
            port = issue_server_evidence_port(root)
        draft = _resume_fixture("wf-cross-process-resume")
        state = WorkflowStateStore(root, draft.workflow_id).current()
        assert state is not None
        resumed = port.validate_resumed_step_state(
            draft,
            draft.steps[0],
            state.steps[draft.steps[0].step_id],
        )
        result_queue.put(
            (
                "ok",
                resumed.output_bindings,
                resumed.restored_from_state,
                port._authority_id,
            )
        )
    except BaseException as error:
        result_queue.put(("error", f"{type(error).__name__}: {error}"))
    finally:
        os.close(endpoint_fd)
        endpoint_connection.close()


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


def test_spawn_worker_rebinds_completed_step_from_the_same_host_authority(
    tmp_path,
) -> None:
    """A fresh worker resumes one completion without re-calling its producer."""

    draft = _resume_fixture("wf-cross-process-resume")
    first = _execute(tmp_path, draft, _first_pass)
    assert first.status == "failed"
    before_runs = sorted(path.name for path in (tmp_path / "runs").iterdir())

    workflow_directory = tmp_path / "workbench" / "workflows"
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    context = multiprocessing.get_context("spawn")
    parent_connection, worker_connection = context.Pipe(duplex=True)
    result_queue = context.Queue()
    import workbench.agent.workflow_runtime as workflow_runtime

    endpoint = _admit_workflow_host_endpoint_from_supervisor(tmp_path, endpoint_fd)
    with patch.object(
        workflow_runtime,
        "_deployment_host_endpoint_from_supervisor",
        return_value=endpoint,
    ):
        parent_port = issue_server_evidence_port(tmp_path)
    parent_authority_id = parent_port._authority_id
    process = context.Process(
        target=_spawn_validate_resumed_step,
        args=(str(tmp_path), worker_connection, result_queue),
    )
    try:
        process.start()
        worker_connection.close()
        send_handle(parent_connection, endpoint_fd, process.pid)
        process.join(15)
        assert process.exitcode == 0
        outcome = result_queue.get(timeout=3)
    finally:
        parent_connection.close()
        os.close(endpoint_fd)
        parent_port.close()

    assert outcome[0] == "ok", outcome
    assert outcome[1]["dataset"]["artifact_id"] == "artifact-publish"
    assert outcome[2] is True
    assert outcome[3] == parent_authority_id
    assert sorted(path.name for path in (tmp_path / "runs").iterdir()) == before_runs

    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )
    records = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    assert len([item for item in records if item["record_type"] == "workflow_completion"]) == 1


def test_resume_rejects_a_draft_bound_to_another_project_or_session(tmp_path) -> None:
    draft = dataclasses.replace(
        _resume_fixture("wf-resume-scope-binding"),
        project_ref="project:resume-bound",
        session_ref="session:resume-bound",
    )
    first = _execute(tmp_path, draft, _first_pass)
    assert first.status == "failed"
    assert draft.to_dict()["project_ref"] == "project:resume-bound"
    assert draft.to_dict()["session_ref"] == "session:resume-bound"

    forged = dataclasses.replace(draft, session_ref="session:forged")
    with pytest.raises(WorkflowExecutionError, match="project/session binding"):
        _execute(tmp_path, forged, _first_pass)


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


@pytest.mark.parametrize(
    ("field", "value"),
    (("receipt_id", None), ("attempt", "not-an-int"), ("status", "tampered")),
)
def test_active_admission_record_tampering_fails_as_a_typed_error(
    tmp_path, field, value
) -> None:
    draft = compile_fixture_workflow(workflow_id=f"wf-active-admission-{field}")
    port = _issued_evidence_port(tmp_path)
    port.admit(draft, draft.steps[0])
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def tamper_admission(records):
        matches = [
            record
            for record in records
            if record.get("record_type") == "workflow_admission"
        ]
        assert len(matches) == 1
        if value is None:
            matches[0].pop(field, None)
        else:
            matches[0][field] = value

    _rewrite_evidence_records(evidence_path, tamper_admission)

    with pytest.raises(WorkflowExecutionError, match="admission|corrupt|authority"):
        port.admit(draft, draft.steps[0])


def test_unsealed_abort_cannot_bypass_active_admission(tmp_path) -> None:
    """An abort side record is authority-bearing, not a caller hint."""

    draft = compile_fixture_workflow(workflow_id="wf-unsealed-abort-bypass")
    port = _issued_evidence_port(tmp_path)
    port.admit(draft, draft.steps[0])
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )
    records = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    admission = next(item for item in records if item["record_type"] == "workflow_admission")
    forged_abort = {
        **admission,
        "record_type": "workflow_abort",
        "status": "aborted",
        "error": "forged abort",
    }
    forged_abort.pop("admission_integrity_seal", None)
    records.append(forged_abort)
    evidence_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowExecutionError, match="abort|integrity|seal"):
        port.admit(draft, draft.steps[0])


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


def test_resume_rejects_resurrected_admission_status_tampering(tmp_path) -> None:
    """A revoked admission cannot be resurrected by rewriting status to admitted."""

    draft = _resume_fixture("wf-resume-admission-status-resurrection")
    first = _execute(tmp_path, draft, _first_pass)
    assert first.status == "failed"
    assert first.steps["publish"].status == "completed"
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def resurrect_publish_admission(records):
        matches = [
            record
            for record in records
            if record.get("record_type") == "workflow_admission"
            and record.get("step_id") == "publish"
        ]
        assert len(matches) == 1
        matches[0]["status"] = "revoked"
        matches[0].pop("admission_integrity_seal", None)
        matches[0]["admission_integrity_seal"] = _completion_seal(matches[0])
        matches[0]["status"] = "admitted"

    _rewrite_evidence_records(evidence_path, resurrect_publish_admission)
    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[f"artifact-{step.step_id}"])

    with pytest.raises(WorkflowExecutionError, match="integrity|seal"):
        _execute(tmp_path, draft, resume_pass)
    assert callback_steps == []


def test_resume_rejects_admission_without_integrity_seal(tmp_path) -> None:
    """Admissions written before the seal field cannot authorize Resume."""

    draft = _resume_fixture("wf-resume-admission-without-integrity-seal")
    first = _execute(tmp_path, draft, _first_pass)
    assert first.status == "failed"
    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )

    def remove_publish_admission_seal(records):
        matches = [
            record
            for record in records
            if record.get("record_type") == "workflow_admission"
            and record.get("step_id") == "publish"
        ]
        assert len(matches) == 1
        matches[0].pop("admission_integrity_seal", None)

    _rewrite_evidence_records(evidence_path, remove_publish_admission_seal)
    callback_steps: list[str] = []

    def resume_pass(step, _previous):
        callback_steps.append(step.step_id)
        return WorkflowStepResult(artifact_ids=[f"artifact-{step.step_id}"])

    with pytest.raises(WorkflowExecutionError, match="integrity|seal"):
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
