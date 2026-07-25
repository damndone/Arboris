from __future__ import annotations

import pytest

from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowStepResult,
    compile_class3_workflow,
)


_BINDINGS = {
    "year_column": "year",
    "spending_column": "adj_dppupil_comp",
    "black_column": "pblack",
    "poverty_column": "pfl",
    "enrollment_column": "totreg",
    "all_numeric_columns": ["year", "pfl", "pblack", "totreg", "adj_dppupil_comp"],
    "group_values": [1998, 2002, 2006, 2010, 2014, 2016],
}


def _draft(tmp_path, *, source_fingerprint="sha256:source-1"):
    return compile_class3_workflow(
        workflow_id="wf-resume",
        target={"run_id": "run-1", "node_ref": "stage:raw", "artifact_id": "raw-1"},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": source_fingerprint,
            "active_head_run_id": "run-1",
            "owner_resolution": "single_candidate",
        },
        bindings=_BINDINGS,
        available_columns=list(_BINDINGS["all_numeric_columns"]),
    )


def test_failed_step_blocks_dependents_and_preserves_completed_steps(tmp_path) -> None:
    draft = _draft(tmp_path)
    calls: list[str] = []

    def execute(step, _results):
        calls.append(step.step_id)
        if step.step_id == "step-4":
            return WorkflowStepResult(
                artifact_ids=["detail-1"],
                row_counts={"source": 4110},
                empty_group_values=[],
                payload={"result": "bounded"},
            )
        if step.step_id == "step-5":
            return WorkflowStepResult(
                artifact_ids=[],
                row_counts={},
                empty_group_values=[2012],
                payload={},
            )
        return WorkflowStepResult(
            artifact_ids=[f"artifact-{step.step_id}"],
            row_counts={"source": 4110},
            payload={"result": "bounded"},
        )

    state = WorkflowExecutor(tmp_path).execute(draft, execute)

    assert state.status == "failed"
    assert state.steps["step-1"].status == "completed"
    assert state.steps["step-4"].status == "completed"
    assert state.steps["step-5"].status == "failed"
    assert state.steps["step-6"].status == "blocked"
    assert state.steps["step-8"].status == "blocked"
    assert state.steps["step-9"].status == "blocked"
    assert calls == ["step-1", "step-2", "step-3", "step-4", "step-5"]


def test_resume_reuses_completed_steps_and_rejects_changed_source(tmp_path) -> None:
    draft = _draft(tmp_path)
    first_calls: list[str] = []

    def first_execute(step, _results):
        first_calls.append(step.step_id)
        if step.step_id == "step-4":
            raise WorkflowExecutionError("simulated step failure")
        return WorkflowStepResult(
            artifact_ids=[f"artifact-{step.step_id}"],
            row_counts={"source": 4110},
            payload={"result": "bounded"},
        )

    first = WorkflowExecutor(tmp_path).execute(draft, first_execute)
    assert first.status == "failed"

    second_calls: list[str] = []

    def second_execute(step, _results):
        second_calls.append(step.step_id)
        return WorkflowStepResult(
            artifact_ids=[f"artifact-{step.step_id}"],
            row_counts={"source": 4110},
            payload={"result": "bounded"},
        )

    second = WorkflowExecutor(tmp_path).execute(draft, second_execute)
    assert second.status == "completed"
    assert second_calls[0] == "step-4"
    assert "step-1" not in second_calls
    assert "step-3" not in second_calls

    with pytest.raises(WorkflowExecutionError, match="source fingerprint changed"):
        WorkflowExecutor(tmp_path).execute(
            _draft(tmp_path, source_fingerprint="sha256:source-2"),
            second_execute,
        )
