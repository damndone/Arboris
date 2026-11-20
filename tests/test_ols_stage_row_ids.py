"""The OLS adapter can reuse implicit RangeIndex IDs without changing its packet."""
from __future__ import annotations

from types import SimpleNamespace
import warnings

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import write_json
from workbench.contracts.model.inference_kernel import kernel_from_fitted
from workbench.econometrics.runner import run_ols
from workbench.engine import interruptible
from workbench.engine.stages import estimation_fits


def frame_for(index_kind="range", missing=False):
    positions = np.arange(48)
    x = np.cos(positions / 5) + positions * 0.02
    frame = pd.DataFrame({
        "y": 1.5 + 2 * x + np.sin(positions * 0.7) * 0.13, "x": x,
        "group": positions // 6, "time": positions,
        "aweight": 1 + positions % 3 * 0.2, "fweight": positions % 3 + 1,
    })
    if index_kind == "offset":
        frame.index = pd.RangeIndex(11, 107, 2)
    elif index_kind == "reverse":
        frame.index = pd.RangeIndex(110, 14, -2)
    elif index_kind == "integer":
        frame.index = pd.Index(positions * 2 + 11)
    elif index_kind == "source_ids":
        frame.index = pd.Index([f"source:{index}" for index in positions])
    elif index_kind == "duplicate":
        frame.index = pd.Index(positions // 2)
    if missing:
        frame.iloc[2, frame.columns.get_loc("y")] = np.nan
        frame.iloc[7, frame.columns.get_loc("x")] = np.nan
    return frame


def stage_context(frame, covariance="robust", weights=None):
    return SimpleNamespace(
        data=SimpleNamespace(frame=frame, artifact_id="cleaned_dataset"),
        artifacts={"_normalized_y": "y", "_normalized_x": ["x"], "_covariance": covariance,
                   "_entity_col": "group" if covariance == "clustered" else "",
                   "_model_options": {"time_order": "time", "hac_lags": 2} if covariance == "hac" else {},
                   "_upload_hash": "a" * 64, **(weights or {})},
    )


def call_stage(monkeypatch, tmp_path, ctx, *, allow_refusal=False):
    observed = {}

    def runner(*args, **kwargs):
        observed["args"], observed["kwargs"] = args, kwargs
        return run_ols(*args, **kwargs)

    monkeypatch.setattr(estimation_fits, "_orch", lambda: SimpleNamespace(run_ols=runner))
    monkeypatch.setattr(interruptible, "run_interruptible", lambda env, call: call())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        error = None
        try:
            model_id, result, fitted = estimation_fits._fit_ols(ctx, SimpleNamespace(run_root=tmp_path))
        except ValueError as exc:
            if not allow_refusal:
                raise
            model_id, result, fitted, error = None, None, None, exc
    return observed, model_id, result, fitted, [(item.category, str(item.message)) for item in caught], error


def test_actual_stage_reuses_existing_implicit_range_ids(monkeypatch, tmp_path):
    observed, *_ = call_stage(monkeypatch, tmp_path, stage_context(frame_for()))
    assert observed["kwargs"]["row_ids"] is None


@pytest.mark.parametrize("covariance", ["robust", "unadjusted", "clustered", "hac"])
@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("index_kind", ["range", "offset", "reverse", "integer", "source_ids", "duplicate"])
def test_full_small_packet_fingerprints_and_rows_equal_old_stage_oracle(monkeypatch, tmp_path, covariance, missing, index_kind):
    frame = frame_for(index_kind, missing)
    assert_packet_equal_old_stage(monkeypatch, tmp_path, frame, covariance)


@pytest.mark.parametrize("weights", [{"_analysis_weight": "aweight"}, {"_frequency_weight": "fweight"},
                                     {"_analysis_weight": "  "}])
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_weighted_or_blank_declared_weight_keeps_explicit_row_ids(monkeypatch, tmp_path, weights, covariance):
    assert_packet_equal_old_stage(monkeypatch, tmp_path, frame_for(missing=True), covariance, weights)


def assert_packet_equal_old_stage(monkeypatch, tmp_path, frame, covariance, weights=None):
    ctx = stage_context(frame, covariance, weights)
    gaps = covariance == "hac" and frame[["y", "x"]].isna().any().any()
    observed, model_id, actual, fitted, actual_warnings, actual_error = call_stage(
        monkeypatch, tmp_path, ctx, allow_refusal=gaps)
    implicit = type(frame.index) is pd.RangeIndex and not weights
    assert observed["kwargs"]["row_ids"] == (None if implicit else [str(value) for value in frame.index])
    old_kwargs = {**observed["kwargs"], "row_ids": [str(value) for value in frame.index], "fitted_sink": None}
    if gaps:
        assert isinstance(actual_error, ValueError)
        assert str(actual_error).startswith("OLS_HAC_TIME_GAPS:")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ValueError) as old_error:
                run_ols(*observed["args"], **old_kwargs)
        assert str(old_error.value) == str(actual_error)
        assert actual_warnings == [(item.category, str(item.message)) for item in caught]
        return
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        expected, old_fitted = run_ols(*observed["args"], **old_kwargs)
    assert actual_warnings == [(item.category, str(item.message)) for item in caught]
    actual_path, expected_path = tmp_path / "actual.json", tmp_path / "old-stage.json"
    write_json(actual_path, actual)
    write_json(expected_path, expected)
    assert actual_path.read_bytes() == expected_path.read_bytes()
    fingerprints = [key for key in expected if key.endswith("fingerprint")]
    assert len(fingerprints) == 5
    assert {key: actual[key] for key in fingerprints} == {key: expected[key] for key in fingerprints}
    assert list(fitted.model.data.row_labels) == list(old_fitted.model.data.row_labels)
    for item in ("params", "resid"):
        np.testing.assert_array_equal(getattr(fitted, item), getattr(old_fitted, item))
    np.testing.assert_array_equal(fitted.cov_params(), old_fitted.cov_params())
    assert kernel_from_fitted(fitted, model_id=model_id, model_type="ols", nobs=int(fitted.nobs)) == kernel_from_fitted(
        old_fitted, model_id=model_id, model_type="ols", nobs=int(old_fitted.nobs))


def test_weight_validation_stays_inside_interruptible_fit(monkeypatch, tmp_path):
    class Stopped(Exception):
        pass

    def stopped(env, call):
        raise Stopped("already cancelled")

    monkeypatch.setattr(interruptible, "run_interruptible", stopped)
    ctx = stage_context(frame_for(), weights={"_analysis_weight": "aweight", "_frequency_weight": "fweight"})
    with pytest.raises(Stopped, match="already cancelled"):
        estimation_fits._fit_ols(ctx, SimpleNamespace(run_root=tmp_path))
