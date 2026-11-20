"""Bounded per-pair preparation preserves the complete pre-change producer contract."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import warnings
import weakref

import numpy as np
import pandas as pd
import pytest

from workbench import statistical_test_evidence as evidence
from workbench import statistical_test_pairs as pairs
from workbench import statistical_tests as producer

FIXTURE = Path(__file__).parent / "fixtures/statistical_group_preparation_a133fbdf.json.gz"


def test_whole_column_constancy_is_reused_without_reusing_a_gapped_sample(monkeypatch):
    frame = pd.DataFrame({
        "a": [1., 1., 1., 1., 3., 4.],
        "b": [1., 3., 2., 6., 4., 5.],
        "c": [4., 5., 2., 3., 1., 6.],
        "gapped": [1., 2., 4., 3., np.nan, np.nan],
    })
    names = list(frame)
    with monkeypatch.context() as reference_path:
        reference_path.setattr(producer, "_prepare_correlation_pair",
                               lambda frame, left, right, **_: pairs._prepare_correlation_pair(frame, left, right))
        reference = producer._build_core_results(frame, names, [], [], [])
    original = pairs._non_null_unique
    scans = []

    def count(sample):
        scans.append((sample.name, len(sample)))
        return original(sample)

    monkeypatch.setattr(pairs, "_non_null_unique", count)
    candidate = producer._build_core_results(frame, names, [], [], [])
    assert json.dumps(candidate, sort_keys=True) == json.dumps(reference, sort_keys=True)
    assert [name for name, length in scans if length == len(frame)] == ["a", "b", "c"]
    comparison = next(row for row in candidate["correlations"]["results"] if row["variables"] == ["a", "gapped"])
    assert comparison["nobs"] == 4 and comparison["warnings"] == ["CORRELATION_CONSTANT_INPUT"]


def automatic_cases():
    y = [1.25, 3.5, 2., 4.25, 5., 2.75, 6.5, 3.25, 7., 4.5, 8.25, 5.75]
    return {
        "ordinary": pd.DataFrame({"y": y, "z": y[::-1], "binary": [0, 1] * 6, "g": [0, 1, 2] * 4}),
        "missing_nullable": pd.DataFrame({"y": [np.nan, *y[1:]], "z": y[::-1],
            "g": pd.array([0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, None], dtype="Int64")}),
        "singletons_constants": pd.DataFrame({"y": [1., 2., 2., 3., 3., 3.],
                                               "g": ["single", "two", "two", "three", "three", "three"]}),
        "mixed_raw_labels": pd.DataFrame({"y": y, "g": [1, "1", "01", 2] * 3}),
        "nonfinite": pd.DataFrame({"y": [np.inf, -np.inf, *y[2:]], "g": [0, 1, 2] * 4}),
        "signed_zero_large_int": pd.DataFrame({"y": [0., -0., 1., -1., 2., -2., 3., -3.],
                                               "z": np.arange(2**53, 2**53 + 8, dtype=np.int64),
                                               "g": ["a", "b"] * 4}),
    }


def direct_cases():
    return {
        "coercion": pd.DataFrame({"y": ["1.5", "bad", "2.5", "3", "4.5", "5", "6", "7"],
                                   "g": [0, 0, 1, 1, 2, 2, 2, 2]}),
        "singletons_and_infinite_group": pd.DataFrame({"y": [1., 2., 3., np.inf, 5., 7., 8.],
                                                       "g": [0, 1, 1, 2, 2, 3, 3]}),
        "duplicate_index": pd.DataFrame({"y": [1., 3., 2., 5., 4., 8.], "g": [0, 0, 1, 1, 2, 2]},
                                         index=[4, 4, 2, 2, 9, 9]),
        "duplicate_column": pd.DataFrame([[1., 8., 0], [2., 7., 0], [3., 6., 1], [5., 4., 1]],
                                          columns=["y", "y", "g"]),
    }


def canonical(value):
    if isinstance(value, (float, np.floating)):
        return {"binary64": float(value).hex()}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.ndarray):
        return {"dtype": str(value.dtype), "shape": list(value.shape), "values": canonical(value.tolist())}
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


class Cancelled(RuntimeError):
    pass


def capture(call, *, cancel_after=None):
    checkpoints = 0

    def checkpoint():
        nonlocal checkpoints
        checkpoints += 1
        if cancel_after is not None and checkpoints == cancel_after:
            raise Cancelled("group preparation cancellation")

    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        try:
            value = {"result": canonical(call(checkpoint))}
        except Exception as exc:
            value = {"error": {"type": type(exc).__name__, "message": str(exc)}}
    return value | {"checkpoints": checkpoints,
                    "warnings": [{"category": item.category.__name__, "message": str(item.message)}
                                 for item in observed]}


def snapshot():
    out = {}
    for name, frame in automatic_cases().items():
        out["automatic." + name] = capture(lambda check, frame=frame: producer.run_statistical_tests(
            frame, analysis_columns=list(frame.columns), dataset_sha256="0" * 64,
            lineage_parent="group-preparation-regression", check_cancel=check))
    for name, frame in direct_cases().items():
        for function in (pairs._welch_t_test, pairs._mann_whitney_u, pairs._anova, pairs._kruskal_wallis):
            out[f"direct.{name}.{function.__name__}"] = capture(
                lambda _check, frame=frame, function=function: function(frame, "y", "g"))
        out[f"direct.{name}._finite_groups"] = capture(
            lambda check, frame=frame: evidence._finite_groups(frame, "y", "g", check_cancel=check))
    frame = automatic_cases()["ordinary"]
    out["cancel.automatic"] = capture(lambda check: producer.run_statistical_tests(
        frame, analysis_columns=list(frame.columns), dataset_sha256="0" * 64,
        lineage_parent="group-preparation-regression", check_cancel=check), cancel_after=15)
    out["cancel.finite_groups"] = capture(
        lambda check: evidence._finite_groups(frame, "y", "g", check_cancel=check), cancel_after=2)
    return out


def test_complete_prechange_bits_warnings_order_and_cancellation_are_preserved():
    baseline = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert snapshot() == baseline["cases"]


@pytest.mark.parametrize("lane,groups", [("binary", 2), ("multi", 3), ("advanced", 3)])
def test_actual_adjacent_consumers_prepare_one_pair_and_convert_each_group_once(monkeypatch, lane, groups):
    frame = pd.DataFrame({"y": [1., 3., 2., 5., 4., 7., 6., 9., 8., 11., 10., 13.],
                          "g": np.arange(12) % groups})
    counts = {"pairwise": 0, "numeric": 0}
    pairwise, numeric = pairs._pairwise, pd.to_numeric

    def prepare(*args, **kwargs):
        counts["pairwise"] += 1
        return pairwise(*args, **kwargs)

    def convert(value, *args, **kwargs):
        if isinstance(value, pd.Series) and value.name == "y":
            counts["numeric"] += 1
        return numeric(value, *args, **kwargs)

    monkeypatch.setattr(pairs, "_pairwise", prepare)
    monkeypatch.setattr(evidence, "_pairwise", prepare)
    monkeypatch.setattr(pd, "to_numeric", convert)
    if lane == "advanced":
        evidence._build_advanced_evidence_results(frame, numeric=["y"], categorical=["g"],
                                                 reference_means=None, paired_columns=None)
    else:
        producer._build_core_results(frame, ["y"], ["g"], ["g"] if lane == "binary" else [],
                                     ["g"] if lane == "multi" else [])
    assert counts == {"pairwise": 1, "numeric": groups}


def test_prepared_pair_frames_are_released_before_the_next_pair(monkeypatch):
    frame = pd.DataFrame({"y": [1., 3., 2., 5., 4., 7., 6., 9., 8., 11., 10., 13.],
                          "z": [2., 7., 4., 9., 6., 11., 8., 13., 10., 15., 12., 17.],
                          "g": np.arange(12) % 3, "h": np.arange(12) % 4})
    references = []
    pairwise = pairs._pairwise

    def prepare(*args, **kwargs):
        # No previously prepared pair frame may be retained by a call-wide map.
        assert all(reference() is None for reference in references)
        result = pairwise(*args, **kwargs)
        references.append(weakref.ref(result))
        return result

    monkeypatch.setattr(pairs, "_pairwise", prepare)
    monkeypatch.setattr(evidence, "_pairwise", prepare)
    producer._build_core_results(frame, ["y", "z"], ["g", "h"], [], ["g", "h"])
    evidence._build_advanced_evidence_results(frame, numeric=["y", "z"], categorical=["g", "h"],
                                             reference_means=None, paired_columns=None)
    assert references and all(reference() is None for reference in references)
