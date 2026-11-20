"""Default statistics scheduling preserves the actual serial producer contract."""
from __future__ import annotations
import contextvars
from dataclasses import dataclass
import json
import logging
import struct
import threading

import numpy as np
import pandas as pd
import pytest

from workbench import statistical_tests as statistics


def _frame(n=48):
    i = np.arange(n)
    return pd.DataFrame({"x": np.sin(i/3) + i/97, "y": np.cos(i/5) + i/101,
                         "binary": np.where(i % 2, "a", "b"),
                         "group": np.array(["a", "b", "c"], dtype=object)[i % 3]})


def _bits(value):
    if isinstance(value, float):
        return ("binary64", struct.pack(">d", value).hex())
    if isinstance(value, dict):
        return [(key, _bits(item)) for key, item in value.items()]
    if isinstance(value, (list, tuple)):
        return [_bits(item) for item in value]
    return value


@pytest.mark.parametrize("variant", ["ordinary", "nan", "constant", "ties", "typed"])
def test_default_parallel_complete_payload_bits_order_and_two_bh(monkeypatch, variant):
    data = _frame()
    if variant == "nan":
        data.loc[[1, 7], "x"] = np.nan
    elif variant == "constant":
        data["x"] = 3.0
    elif variant == "ties":
        data["x"] = np.arange(len(data)) % 7
    elif variant == "typed":
        data["x"] = np.arange(len(data), dtype=np.uint64) + np.uint64(2**53)
    kwargs = dict(analysis_columns=list(data), dataset_sha256="a"*64,
                  lineage_parent="cleaned:17", reference_means={"y": 0.0},
                  paired_columns=[("x", "y")])
    expected = statistics._run_statistical_tests_serial(data, **kwargs)
    monkeypatch.setattr(statistics, "_STATISTICS_PARALLEL_MIN_ROWS", 0)
    calls = []
    original = statistics._apply_multiple_testing_correction

    def correction(results):
        calls.append((tuple(results), threading.current_thread()))
        return original(results)

    monkeypatch.setattr(statistics, "_apply_multiple_testing_correction", correction)
    actual = statistics.run_statistical_tests(data, **kwargs)
    assert _bits(actual) == _bits(expected)
    assert json.dumps(actual, allow_nan=False) == json.dumps(expected, allow_nan=False)
    automatic = tuple(name for name, contract in statistics.TEST_FAMILIES.items() if contract.automatic)
    assert [keys for keys, _ in calls] == [automatic, ("evidence",)]
    assert all(thread is threading.current_thread() for _, thread in calls)


def test_default_actual_100k_overlaps_reversed_completion_private_frames_context(monkeypatch):
    data = _frame(100_000)
    before = data.copy(deep=True)
    barrier = threading.Barrier(2, timeout=10)
    advanced_done = threading.Event()
    marker = contextvars.ContextVar("default-stats-context", default=None)
    token = marker.set("owner-context")
    containers, completions = [], []
    core = statistics._build_core_results
    advanced = statistics._build_advanced_evidence_results

    def core_lane(private, *args, **kwargs):
        containers.append(private)
        assert marker.get() == "owner-context"
        assert private is not data and np.shares_memory(private["x"].to_numpy(), data["x"].to_numpy())
        barrier.wait()
        result = core(private, *args, **kwargs)
        assert advanced_done.wait(10)
        completions.append("core")
        return result

    def advanced_lane(private, *args, **kwargs):
        containers.append(private)
        assert marker.get() == "owner-context"
        barrier.wait()
        result = advanced(private, *args, **kwargs)
        completions.append("advanced")
        advanced_done.set()
        return result

    monkeypatch.setattr(statistics, "_build_core_results", core_lane)
    monkeypatch.setattr(statistics, "_build_advanced_evidence_results", advanced_lane)
    try:
        actual = statistics.run_statistical_tests(data, analysis_columns=list(data))
    finally:
        marker.reset(token)
    monkeypatch.setattr(statistics, "_build_core_results", core)
    monkeypatch.setattr(statistics, "_build_advanced_evidence_results", advanced)
    expected = statistics._run_statistical_tests_serial(data, analysis_columns=list(data))
    assert _bits(actual) == _bits(expected)
    assert completions == ["advanced", "core"]
    assert containers[0] is not containers[1]
    pd.testing.assert_frame_equal(data, before, check_exact=True)
    assert not any(thread.name.startswith("workbench-statistics-") for thread in threading.enumerate())


def test_small_no_overlap_and_single_binary_100k_stay_serial(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no independent work should launch threads")

    monkeypatch.setattr(statistics, "_run_statistics_lanes", forbidden)
    for data in (_frame(), _frame(100_000)[["x", "y"]],
                 pd.DataFrame({"x": np.arange(100_000) % 2})):
        assert _bits(statistics.run_statistical_tests(data, analysis_columns=list(data))) == _bits(
            statistics._run_statistical_tests_serial(data, analysis_columns=list(data)))


@pytest.mark.parametrize("core_bh", [False, True])
def test_frozen_core_or_bh_failure_has_serial_priority_and_logs_advanced(monkeypatch, caplog, core_bh):
    @dataclass(frozen=True)
    class FrozenFailure(Exception):
        message: str

    first, second = FrozenFailure("original core"), ArithmeticError("advanced failure")
    monkeypatch.setattr(statistics, "_STATISTICS_PARALLEL_MIN_ROWS", 0)

    def fail(*args, **kwargs):
        raise first

    def advanced(*args, **kwargs):
        raise second

    monkeypatch.setattr(statistics, "_build_advanced_evidence_results", advanced)
    monkeypatch.setattr(statistics, "_apply_multiple_testing_correction" if core_bh else "_build_core_results", fail)
    with caplog.at_level(logging.ERROR, logger="workbench.statistical_tests"):
        with pytest.raises(FrozenFailure) as caught:
            statistics.run_statistical_tests(_frame(), analysis_columns=list(_frame()))
    assert caught.value is first and str(caught.value) == "original core"
    assert not hasattr(first, "__notes__")
    assert any(record.exc_info and record.exc_info[1] is second for record in caplog.records)
    assert "advanced failure" in caplog.text


def test_default_cancel_joins_both_actual_threads_before_return(monkeypatch):
    data = _frame(100_000)
    entered = threading.Barrier(3, timeout=5)
    release, cancel, observed, returned = [threading.Event() for _ in range(4)]
    original = RuntimeError("owner cancelled")
    failures, workers = [], []

    def compute(*args, **kwargs):
        workers.append(threading.current_thread())
        entered.wait()
        assert release.wait(5)
        return {}

    def checkpoint():
        if cancel.is_set():
            observed.set()
            raise original

    def caller():
        try:
            statistics.run_statistical_tests(data, analysis_columns=list(data), check_cancel=checkpoint)
        except BaseException as error:
            failures.append(error)
        finally:
            returned.set()

    monkeypatch.setattr(statistics, "_build_core_results", compute)
    monkeypatch.setattr(statistics, "_build_advanced_evidence_results", compute)
    thread = threading.Thread(target=caller)
    thread.start()
    try:
        entered.wait()
        cancel.set()
        assert observed.wait(5)
        assert not returned.is_set()
    finally:
        release.set()
        thread.join(5)
    assert failures == [original]
    assert returned.is_set() and all(not worker.is_alive() for worker in workers)
