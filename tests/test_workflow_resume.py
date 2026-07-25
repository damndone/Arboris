"""Failure containment and resume for a compiled workflow plan.

Previously exercised through a server-side preset; the invariants belong to the
executor, not to any assignment, so they now run on a composed plan.
"""

from __future__ import annotations

import pytest

from tests.workflow_fixtures import compile_fixture_workflow
from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowStepResult,
)


def _ok(step_id: str) -> WorkflowStepResult:
    return WorkflowStepResult(
        artifact_ids=[f"artifact-{step_id}"],
        row_counts={"source": 24},
        payload={"result": "bounded"},
    )


def test_failed_step_blocks_dependents_and_preserves_completed_steps(tmp_path) -> None:
    """A dependent of a failed step is blocked, never quietly skipped."""
    draft = compile_fixture_workflow(workflow_id="wf-resume-a")
    calls: list[str] = []

    def execute(step, _results):
        calls.append(step.step_id)
        if step.step_id == "split":
            return WorkflowStepResult(
                artifact_ids=[], row_counts={}, empty_group_values=[99], payload={}
            )
        return _ok(step.step_id)

    state = WorkflowExecutor(tmp_path).execute(draft, execute)

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
    draft = compile_fixture_workflow(workflow_id="wf-resume-b")

    def failing(step, _results):
        if step.step_id == "detail":
            raise WorkflowExecutionError("simulated step failure")
        return _ok(step.step_id)

    first = WorkflowExecutor(tmp_path).execute(draft, failing)
    assert first.status == "failed"

    second_calls: list[str] = []

    def succeeding(step, _results):
        second_calls.append(step.step_id)
        return _ok(step.step_id)

    second = WorkflowExecutor(tmp_path).execute(draft, succeeding)

    assert second.status == "completed"
    assert "detail" in second_calls
    # Steps that completed in the first pass are not re-executed.
    assert "grouped" not in second_calls
    assert "missing" not in second_calls

    with pytest.raises(WorkflowExecutionError, match="source fingerprint changed"):
        WorkflowExecutor(tmp_path).execute(
            compile_fixture_workflow(
                workflow_id="wf-resume-b", source_fingerprint="sha256:source-2"
            ),
            succeeding,
        )
