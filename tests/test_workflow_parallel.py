"""Bounded workflow compute with single-writer publication."""

from __future__ import annotations

import asyncio
from threading import Barrier, Event, get_ident

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent import workflow_runtime
from workbench.agent.context_compiler import read_workflow_artifact_index
from workbench.agent.workflow import WorkflowExecutor, WorkflowStateStore, compile_workflow, execute_workflow
from workbench.agent.workflow_runtime_parts import operations
from workbench.checks.ar_cancellation import cancellation_scope
from workbench.events import get_event_manager
from workbench.exploration_log import ExplorationLog


def _explore(step_id, operation, column, depends_on=()):
    return {
        "step_id": step_id,
        "operation_id": "statistical.explore",
        "depends_on": list(depends_on),
        "spec": {"operation": operation, "selected_columns": [column]},
    }


def _workflow(tmp_path, *, frame=None, steps=None):
    if frame is None:
        frame = pd.DataFrame(
            {"x": [-0.0, 0.0, 2e16, 1.5, -2e16, None] * 4, "y": list(range(24))}
        )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="bounded-exploration",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "sha256:workflow-source"},
        available_columns=list(frame.columns),
        steps=steps or [
            _explore("summary", "summarize", "x"),
            _explore("detail", "summarize_detail", "y"),
            _explore("missing", "misstable", "x", ["summary", "detail"]),
        ],
    )
    return project, draft


def _result_artifacts(project, draft):
    run_root = project / "runs" / draft.target["run_id"]
    return [
        (item["artifact_id"], item["sha256"], (run_root / item["path"]).read_bytes())
        for item in read_workflow_artifact_index(run_root)["artifacts"]
        if item["artifact_type"] == "statistical_exploration"
    ]


def _observe_compute(monkeypatch, observer):
    execute = workflow_runtime.execute_exploration

    def observed(frame, spec):
        return observer(execute, frame, spec)

    monkeypatch.setattr(workflow_runtime, "execute_exploration", observed)
    monkeypatch.setattr(operations, "execute_exploration", observed)


def test_independent_workflow_compute_overlaps_with_ordered_byte_identical_publication(
    tmp_path, monkeypatch
):
    reference, reference_draft = _workflow(tmp_path / "reference")
    serial = WorkflowExecutor(reference).execute(
        reference_draft, workflow_runtime.build_workflow_step_executor(reference, reference_draft)
    )
    assert serial.status == "completed"

    project, draft = _workflow(tmp_path / "parallel")
    coordinator = get_ident()
    roots_ready = Barrier(2, timeout=3)
    detail_computed = Event()
    worker_threads = {}

    def observe(execute, frame, spec):
        worker_threads[spec.operation] = get_ident()
        if spec.operation == "misstable":
            state = WorkflowStateStore(project, draft.workflow_id).current()
            assert state.steps["summary"].status == state.steps["detail"].status == "completed"
            assert len(_result_artifacts(project, draft)) == 2
            return execute(frame, spec)
        roots_ready.wait()
        if spec.operation == "summarize_detail":
            result = execute(frame, spec)
            detail_computed.set()
            return result
        assert detail_computed.wait(3)
        return execute(frame, spec)

    _observe_compute(monkeypatch, observe)
    state = execute_workflow(project, draft)

    assert state.status == "completed", state
    assert worker_threads["summarize"] != worker_threads["summarize_detail"]
    assert worker_threads["misstable"] == coordinator
    assert state.steps == serial.steps
    assert _result_artifacts(project, draft) == _result_artifacts(reference, reference_draft)
    log = ExplorationLog(project, workflow_id=draft.workflow_id)
    assert [(item["workflow_step_id"], item["status"]) for item in log.read_events()] == [
        ("summary", "running"),
        ("summary", "completed"),
        ("detail", "running"),
        ("detail", "completed"),
        ("missing", "running"),
        ("missing", "completed"),
    ]


@pytest.mark.parametrize(
    ("failure", "summary_status", "detail_status", "retry_order"),
    [
        ("summarize", "failed", "pending", ["summarize", "summarize_detail", "misstable"]),
        ("summarize_detail", "completed", "failed", ["summarize_detail", "misstable"]),
    ],
)
def test_failed_pair_keeps_only_published_results_on_retry(
    tmp_path, monkeypatch, failure, summary_status, detail_status, retry_order
):
    project, draft = _workflow(tmp_path)
    ready = Barrier(2, timeout=3)
    attempts = []
    retry = False

    def observe(execute, frame, spec):
        attempts.append(spec.operation)
        if not retry:
            ready.wait()
            if spec.operation == failure:
                raise ValueError("exploration failed")
        return execute(frame, spec)

    _observe_compute(monkeypatch, observe)
    initial = execute_workflow(project, draft)
    assert initial.status == "failed"
    assert initial.steps["summary"].status == summary_status
    assert initial.steps["detail"].status == detail_status
    assert initial.steps["missing"].status == "blocked"
    assert sorted(attempts) == ["summarize", "summarize_detail"]
    published = _result_artifacts(project, draft)
    assert len(published) == (1 if summary_status == "completed" else 0)

    retry = True
    attempts.clear()
    resumed = execute_workflow(project, draft)
    results = _result_artifacts(project, draft)
    assert resumed.status == "completed"
    assert len(results) == 3
    assert results[:len(published)] == published
    if published:
        assert attempts == retry_order
        assert resumed.steps["summary"] == initial.steps["summary"]
    else:
        assert attempts[-1] == "misstable"
        assert sorted(attempts) == sorted(retry_order)


def test_parallel_compute_drains_and_skips_publication_after_cancellation(tmp_path, monkeypatch):
    project, draft = _workflow(tmp_path)
    coordinator = get_ident()
    ready = Barrier(2, timeout=3)
    requested = Event()
    finished = []
    checked_threads = set()

    def check():
        checked_threads.add(get_ident())
        if requested.is_set():
            raise asyncio.CancelledError("test requested cancellation")

    def observe(execute, frame, spec):
        ready.wait()
        requested.set()
        try:
            return execute(frame, spec)
        finally:
            finished.append(spec.operation)

    _observe_compute(monkeypatch, observe)
    with cancellation_scope(check), pytest.raises(asyncio.CancelledError, match="requested cancellation"):
        execute_workflow(project, draft)

    assert len(checked_threads - {coordinator}) == 2
    assert sorted(finished) == ["summarize", "summarize_detail"]
    state = WorkflowStateStore(project, draft.workflow_id).current()
    assert state.status == "cancelled"
    assert {step.status for step in state.steps.values()} == {"cancelled"}
    assert _result_artifacts(project, draft) == []
    events = get_event_manager()
    assert events.try_acquire_slot()
    events.release_slot(None)


def test_workflow_uses_serial_compute_when_the_heavy_run_slot_is_owned(tmp_path, monkeypatch):
    project, draft = _workflow(tmp_path)
    coordinator = get_ident()
    events = get_event_manager()
    assert events.try_acquire_slot()

    def observe(execute, frame, spec):
        assert get_ident() == coordinator
        return execute(frame, spec)

    _observe_compute(monkeypatch, observe)
    try:
        state = execute_workflow(project, draft)
        assert state.status == "completed", state
        assert len(_result_artifacts(project, draft)) == 3
        assert not events.try_acquire_slot()
    finally:
        events.release_slot(None)


def test_larger_workflow_source_uses_serial_compute(tmp_path, monkeypatch):
    frame = pd.DataFrame({"x": list(range(8193)), "y": list(range(8193))})
    project, draft = _workflow(tmp_path, frame=frame)
    coordinator = get_ident()

    def observe(execute, frame, spec):
        assert get_ident() == coordinator
        return execute(frame, spec)

    _observe_compute(monkeypatch, observe)
    state = execute_workflow(project, draft)
    assert state.status == "completed", state


@pytest.mark.parametrize("null_field", ["selected_columns", "filters"])
def test_legacy_invalid_optional_fields_fail_at_their_own_step(tmp_path, null_field):
    summary = _explore("summary", "summarize", "x")
    detail = _explore("detail", "summarize_detail", "y")
    detail["spec"][null_field] = None
    project, draft = _workflow(tmp_path, steps=[summary, detail])
    state = execute_workflow(project, draft)

    assert state.status == "failed"
    assert state.steps["summary"].status == "completed"
    assert state.steps["detail"].status == "failed"
    assert len(_result_artifacts(project, draft)) == 1


def test_bounded_pair_releases_its_slot_before_dispatching_the_next_model(tmp_path, monkeypatch):
    frame = pd.DataFrame(
        {"x": list(range(40)), "y": [2.7 + 3.5 * x + (x % 3) * 0.2 for x in range(40)]}
    )
    model = {
        "step_id": "fit",
        "operation_id": "model.genesis",
        "spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "branches": [{"branch_id": "main", "outcome": "y", "predictors": ["x"]}],
        },
    }
    steps = [
        _explore("summary", "summarize", "x"),
        _explore("detail", "summarize_detail", "y"),
        model,
    ]
    project, draft = _workflow(tmp_path, frame=frame, steps=steps)
    coordinator = get_ident()
    events = get_event_manager()
    compute = Barrier(2, timeout=3)
    model_dispatch = workflow_runtime._execute_model_genesis_branches

    def observe(execute, frame, spec):
        compute.wait()
        if events.try_acquire_slot():
            events.release_slot(None)
            pytest.fail("parallel compute did not own the heavy run slot")
        return execute(frame, spec)

    def fit(*args, **kwargs):
        assert get_ident() == coordinator
        assert len(_result_artifacts(project, draft)) == 2
        return model_dispatch(*args, **kwargs)

    _observe_compute(monkeypatch, observe)
    monkeypatch.setattr(workflow_runtime, "_execute_model_genesis_branches", fit)
    state = execute_workflow(project, draft)
    assert state.status == "completed", state
    assert any(artifact_id.endswith(":ols_1") for artifact_id in state.steps["fit"].artifact_ids)
