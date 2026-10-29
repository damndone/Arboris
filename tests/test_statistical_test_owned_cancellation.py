"""Statistics opts into owned computation; other stages retain discard mode."""
from __future__ import annotations

import contextvars
import json
import logging
from pathlib import Path
import threading
import time

import numpy as np
import pandas as pd
import pytest

from workbench.engine.context import DataHandle, ModelingContext, RunEnv, RunInterruptionRequested
from workbench.engine.interruptible import run_interruptible


def _frame():
    return pd.DataFrame({"x": np.arange(24, dtype=float),
                         "y": np.sin(np.arange(24)), "g": ["a", "b", "c"] * 8})


def test_owned_interruptible_preserves_context_result_and_original_error():
    marker = contextvars.ContextVar("stats-owned-context", default=None)
    token = marker.set("owner")
    env = RunEnv(run_root=None, run_id="owned", recorder=None, stop_reason=lambda: None)
    try:
        assert run_interruptible(env, lambda: (marker.get(), threading.current_thread().daemon),
                                 drain_on_cancel=True) == ("owner", False)
        failure = ValueError("original pure error")

        def fail():
            raise failure

        with pytest.raises(ValueError) as caught:
            run_interruptible(env, fail, drain_on_cancel=True)
        assert caught.value is failure
    finally:
        marker.reset(token)


def test_owned_interruptible_drains_actual_worker_before_original_owner_error():
    entered, release, stopped, observed, returned = [threading.Event() for _ in range(5)]
    cancelled = threading.Event()
    original = RunInterruptionRequested("cancelled")
    failures = []

    class OwnerEnv:
        stop_reason = lambda self: "cancelled" if cancelled.is_set() else None

        def checkpoint(self):
            if cancelled.is_set():
                observed.set()
                raise original

    def compute():
        entered.set()
        try:
            assert release.wait(5)
        finally:
            stopped.set()

    def caller():
        try:
            run_interruptible(OwnerEnv(), compute, drain_on_cancel=True)
        except BaseException as error:
            failures.append(error)
        finally:
            returned.set()

    caller_thread = threading.Thread(target=caller)
    caller_thread.start()
    try:
        assert entered.wait(5)
        cancelled.set()
        assert observed.wait(5)
        assert not returned.is_set()
    finally:
        release.set()
        caller_thread.join(5)
    assert stopped.is_set() and returned.is_set()
    assert failures == [original]


def test_owned_cancel_logs_genuine_worker_failure_during_drain_without_mutating_owner(caplog):
    entered, release, observed = [threading.Event() for _ in range(3)]
    cancelled = threading.Event()
    owner_error = RunInterruptionRequested("cancelled")
    native_error = RuntimeError("native failed while owner drained")
    failures = []

    class OwnerEnv:
        stop_reason = lambda self: "cancelled" if cancelled.is_set() else None

        def checkpoint(self):
            if cancelled.is_set():
                observed.set()
                raise owner_error

    def compute():
        entered.set()
        assert release.wait(5)
        raise native_error

    def caller():
        try:
            run_interruptible(OwnerEnv(), compute, drain_on_cancel=True)
        except BaseException as error:
            failures.append(error)

    with caplog.at_level(logging.ERROR, logger="workbench.engine.interruptible"):
        thread = threading.Thread(target=caller)
        thread.start()
        try:
            assert entered.wait(5)
            cancelled.set()
            assert observed.wait(5)
        finally:
            release.set()
            thread.join(5)
    assert failures == [owner_error]
    assert str(owner_error) == "cancelled"
    assert not hasattr(owner_error, "__notes__")
    record = next(record for record in caplog.records if record.exc_info)
    assert record.exc_info[1] is native_error
    assert "compute" in caplog.text and "native failed while owner drained" in caplog.text


def test_producer_accepts_existing_owner_checkpoint_and_preserves_payload():
    from workbench.statistical_tests import run_statistical_tests
    data = _frame()
    expected = run_statistical_tests(data, analysis_columns=list(data))
    calls = []
    actual = run_statistical_tests(data, analysis_columns=list(data), check_cancel=lambda: calls.append(True))
    assert calls
    assert json.dumps(actual, allow_nan=False) == json.dumps(expected, allow_nan=False)


def test_advanced_valueerror_checkpoint_is_outside_degenerate_error_handlers(monkeypatch):
    from workbench import statistical_test_evidence as evidence
    stop = threading.Event()
    failure = ValueError("owner cancellation must not become degenerate data")
    actual_effect = evidence._cohens_d_evidence

    def effect(*args, **kwargs):
        result = actual_effect(*args, **kwargs)
        stop.set()
        return result

    def checkpoint():
        if stop.is_set():
            raise failure

    monkeypatch.setattr(evidence, "_cohens_d_evidence", effect)
    with pytest.raises(ValueError) as caught:
        evidence._build_advanced_evidence_results(
            _frame(), numeric=["y"], categorical=["g"],
            reference_means=None, paired_columns=None, check_cancel=checkpoint)
    assert caught.value is failure


def test_statistics_stage_checks_cancel_at_artifact_entry(monkeypatch, tmp_path):
    from workbench import statistical_tests
    from workbench.engine.stages.statistical_tests import StatisticalTestsStage
    cancelled = threading.Event()
    callbacks = []

    def compute(*args, check_cancel=None, **kwargs):
        callbacks.append(check_cancel)
        cancelled.set()
        return {}

    writes = []
    monkeypatch.setattr(statistical_tests, "run_statistical_tests", compute)
    monkeypatch.setattr(statistical_tests, "write_statistical_test_artifacts", lambda *args: writes.append(args))
    ctx = ModelingContext(DataHandle.of(_frame(), artifact_id="cleaned", provenance=()),
                          y_col="y", x_cols=["x"],
                          artifacts={"_normalized_y": "y", "_normalized_x": ["x"]})
    env = RunEnv(run_root=tmp_path, run_id="stage", recorder=None,
                 stop_reason=lambda: "cancelled" if cancelled.is_set() else None)
    with pytest.raises(RunInterruptionRequested):
        StatisticalTestsStage().run(ctx, env)
    assert callbacks == [env.checkpoint]
    assert writes == []
    assert list(tmp_path.iterdir()) == []


def test_real_1m_statistics_http_cancel_drains_before_terminal_artifacts(tmp_path, monkeypatch, record_property):
    """Real submit/cancel/background workflow; hook only observes the rank unit.

    No artificial wait in the math callback. This proves the tested 1M core-rank
    phase, not every possible SciPy shape/family or the full fit's cancel time.
    """
    from fastapi.testclient import TestClient
    from workbench.app import app
    from workbench.artifacts import read_json
    from workbench import native_math
    from workbench.events import get_event_manager
    from workbench.engine.stages.statistical_tests import StatisticalTestsStage
    entered, stage_stopped = threading.Event(), threading.Event()
    actual_rank = native_math.average_ranks
    actual_stage = StatisticalTestsStage.run
    workers = []
    sizes = []

    def rank(matrix, *, check_cancel=None):
        workers.append(threading.current_thread())
        sizes.append(len(matrix))
        assert check_cancel is not None
        entered.set()
        return actual_rank(matrix, check_cancel=check_cancel)

    def stage(self, ctx, env):
        try:
            return actual_stage(self, ctx, env)
        finally:
            stage_stopped.set()

    monkeypatch.setattr(native_math, "average_ranks", rank)
    monkeypatch.setattr(StatisticalTestsStage, "run", stage)
    source = Path(__file__).resolve().parents[1]/"local/perf-inputs/ols/wages.csv"
    with TestClient(app) as client:
        root = client.post("/projects", json={"parent": str(tmp_path), "name": "owned-stats-http"}).json()["project_root"]
        with source.open("rb") as upload:
            response = client.post("/runs", data={"project_root": root, "mode": "auto",
                "model_type": "ols", "y": "wage", "x": "education,experience,female,hours"},
                files={"file": ("wages.csv", upload, "text/csv")})
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        assert entered.wait(30), "real workflow did not enter its statistics rank unit"
        started = time.perf_counter()
        cancelled = client.post(f"/runs/{run_id}/cancel", params={"project_root": root})
        http_seconds = time.perf_counter()-started
        assert cancelled.status_code == 200, cancelled.text
        assert stage_stopped.wait(2), "statistics stage did not drain within tested boundary"
        assert workers and sizes[0] == 1_000_000
        assert all(not worker.is_alive() for worker in workers), "terminal stage left its actual compute worker alive"
        run_root = Path(root)/"runs"/run_id
        deadline = started + 2
        while time.perf_counter() < deadline:
            manifest = read_json(run_root/"run_manifest.json")
            if manifest["status"] == "interrupted" and not get_event_manager().is_active(run_id):
                break
            time.sleep(.01)
        assert manifest["status"] == "interrupted", manifest
        elapsed = time.perf_counter()-started
        assert elapsed < 2
        assert not (run_root/"statistical_tests").exists()
        assert not list((run_root/"model_results").rglob("*.json"))
        files_after = sorted(str(path.relative_to(run_root)) for path in run_root.rglob("*") if path.is_file())
        time.sleep(.1)
        assert files_after == sorted(str(path.relative_to(run_root)) for path in run_root.rglob("*") if path.is_file())
        record_property("phase", "real_serial_statistics_core_rank")
        record_property("rows", sizes[0])
        record_property("http_cancel_seconds", http_seconds)
        record_property("cancel_to_terminal_owned_drain_seconds", elapsed)
