from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


def _model_frame(n: int = 96) -> pd.DataFrame:
    time = np.arange(1.0, n + 1.0)
    x = np.zeros(n)
    y = np.zeros(n)
    for index in range(1, n):
        x[index] = 0.55 * x[index - 1] + np.sin(index / 9.0) + 0.1
        y[index] = 0.25 * y[index - 1] + 0.45 * x[index - 1] + np.cos(index / 11.0)
    return pd.DataFrame({"time": time, "x": x, "y": y})


def _cointegrated_frame(n: int = 160) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    x = np.cumsum(rng.normal(size=n))
    y = x + 0.15 * rng.normal(size=n)
    return pd.DataFrame({"time": np.arange(1.0, n + 1.0), "x": x, "y": y})


def _independent_random_walk_frame(n: int = 160) -> pd.DataFrame:
    rng = np.random.default_rng(23)
    x = np.cumsum(rng.normal(size=n))
    y = np.cumsum(rng.normal(size=n))
    return pd.DataFrame({"time": np.arange(1.0, n + 1.0), "x": x, "y": y})


def _unstable_var_frame(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(99)
    x = np.zeros(n)
    y = np.zeros(n)
    for index in range(1, n):
        x[index] = 1.08 * x[index - 1] + rng.normal(scale=0.4)
        y[index] = 0.5 * y[index - 1] + 0.2 * x[index - 1] + rng.normal(scale=0.4)
    return pd.DataFrame({"time": np.arange(1.0, n + 1.0), "x": x, "y": y})


def _stable_var_frame(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(31)
    x = np.zeros(n)
    y = np.zeros(n)
    for index in range(2, n):
        x[index] = 0.45 * x[index - 1] + 0.10 * x[index - 2] + rng.normal(scale=0.3)
        y[index] = 0.25 * y[index - 1] + 0.35 * x[index - 1] + rng.normal(scale=0.3)
    return pd.DataFrame({"time": np.arange(1.0, n + 1.0), "x": x, "y": y})


def test_cointegration_reports_ordered_engle_granger_and_johansen_rank_evidence():
    from workbench.engine.packs.time_series import run_cointegration

    frame = _cointegrated_frame()
    engle_granger = run_cointegration(
        frame,
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        method="engle_granger",
        max_lag=1,
        confidence_level=0.95,
    )
    johansen = run_cointegration(
        frame,
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        method="johansen",
        det_order=0,
        k_ar_diff=1,
        confidence_level=0.95,
    )
    assert engle_granger["operation_id"] == "time_series.cointegration"
    assert engle_granger["result"]["method"] == "engle_granger"
    assert engle_granger["result"]["ordered_pair"] == {"dependent": "x", "regressor": "y"}
    assert johansen["result"]["method"] == "johansen"
    assert johansen["result"]["rank_decision"]["trace_rank"] == 1
    assert johansen["result"]["rank_decision"]["maximum_eigenvalue_rank"] == 1
    assert len(johansen["result"]["trace_tests"]) == 2
    json.dumps(johansen, allow_nan=False)


def test_vecm_derives_rank_and_returns_explicit_equilibrium_parameters():
    from workbench.engine.packs.time_series import fit_vecm

    result = fit_vecm(
        _cointegrated_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        det_order=0,
        k_ar_diff=1,
        deterministic="co",
        forecast_horizon=3,
        confidence_level=0.9,
    )
    payload = result["result"]
    assert result["operation_id"] == "time_series.vecm"
    assert payload["rank"] == 1
    assert payload["rank_policy"] == "johansen_trace"
    assert len(payload["alpha"]) == 2
    assert len(payload["beta"]) == 2
    assert len(payload["gamma"]) == 2
    assert len(payload["forecast"]["mean"]) == 3
    json.dumps(result, allow_nan=False)


def test_vecm_rejects_rank_zero_instead_of_fabricating_an_equilibrium_model():
    from workbench.engine.packs.time_series import fit_vecm

    result = fit_vecm(
        _independent_random_walk_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        det_order=0,
        k_ar_diff=1,
        deterministic="co",
        forecast_horizon=2,
        confidence_level=0.9,
    )
    assert result["status"] == "rejected"
    assert result["reason_code"] == "TIME_SERIES_NO_COINTEGRATION"
    assert result["result"]["rank"] == 0
    assert "alpha" not in result["result"]


def test_engle_granger_rejects_more_than_two_series_without_coercion():
    from workbench.engine.packs.time_series import run_cointegration
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    frame = _cointegrated_frame().assign(z=lambda value: value["x"] * 0.5)
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        run_cointegration(
            frame,
            time_column="time",
            value_columns=["x", "y", "z"],
            time_order="declared_monotonic",
            method="engle_granger",
            max_lag=1,
            confidence_level=0.95,
        )


def test_johansen_packet_matches_direct_statsmodels_reference_call():
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    from workbench.engine.packs.time_series import run_cointegration

    frame = _cointegrated_frame()
    expected = coint_johansen(frame[["x", "y"]].to_numpy(), 0, 1)
    result = run_cointegration(
        frame,
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        method="johansen",
        det_order=0,
        k_ar_diff=1,
        confidence_level=0.95,
    )
    trace_test = result["result"]["trace_tests"][0]
    assert trace_test["statistic"] == pytest.approx(expected.lr1[0], rel=1e-12, abs=1e-12)
    assert trace_test["critical_value"] == pytest.approx(expected.cvt[0, 1], rel=1e-12, abs=1e-12)


def test_irf_bands_and_stability_match_direct_statsmodels_reference_call():
    from scipy.stats import norm
    from statsmodels.tsa.api import VAR

    from workbench.engine.packs.time_series import run_irf

    frame = _stable_var_frame()
    values = frame[["x", "y"]].to_numpy()
    expected_fit = VAR(values).fit(2, trend="c")
    expected_irf = expected_fit.irf(periods=4)
    expected_response = expected_irf.irfs
    expected_se = expected_irf.stderr(orth=False)
    critical_value = norm.ppf(0.5 + 0.9 / 2.0)
    result = run_irf(
        frame,
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        lags=2,
        trend="c",
        horizon=4,
        orthogonalized=False,
        confidence_level=0.9,
        ci_method="asymptotic_normal",
    )
    assert np.allclose(result["result"]["responses"], expected_response, rtol=1e-12, atol=1e-12)
    assert np.allclose(
        result["result"]["lower"],
        expected_response - critical_value * expected_se,
        rtol=1e-12,
        atol=1e-12,
    )
    assert result["result"]["stability"]["is_stable"] == bool(expected_fit.is_stable())


def test_arima_and_sarima_keep_explicit_orders_and_bound_forecasts():
    from workbench.engine.packs.time_series import fit_arima

    frame = _model_frame()
    arima = fit_arima(
        frame,
        time_column="time",
        value_column="y",
        time_order="declared_monotonic",
        order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 0),
        trend="c",
        forecast_horizon=4,
        confidence_level=0.9,
    )
    sarima = fit_arima(
        frame,
        time_column="time",
        value_column="y",
        time_order="declared_monotonic",
        order=(0, 0, 0),
        seasonal_order=(1, 0, 0, 4),
        trend="c",
        forecast_horizon=3,
        confidence_level=0.9,
    )
    assert arima["operation_id"] == "time_series.arima"
    assert arima["result"]["policy"]["order"] == [1, 0, 0]
    assert arima["result"]["policy"]["seasonal_order"] == [0, 0, 0, 0]
    assert len(arima["result"]["forecast"]["mean"]) == 4
    assert len(arima["result"]["forecast"]["lower"]) == 4
    assert sarima["result"]["policy"]["seasonal_order"] == [1, 0, 0, 4]
    json.dumps(arima, allow_nan=False)
    json.dumps(sarima, allow_nan=False)


def test_arima_rejects_implicit_selection_and_unbounded_forecasts():
    from workbench.engine.packs.time_series import fit_arima
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        fit_arima(
            _model_frame(),
            time_column="time",
            value_column="y",
            time_order="declared_monotonic",
            order=(1, 0),
            seasonal_order=(0, 0, 0, 0),
            trend="c",
            forecast_horizon=2,
            confidence_level=0.9,
        )
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        fit_arima(
            _model_frame(),
            time_column="time",
            value_column="y",
            time_order="declared_monotonic",
            order=(1, 0, 0),
            seasonal_order=(0, 0, 0, 0),
            trend="c",
            forecast_horizon=201,
            confidence_level=0.9,
        )


def test_var_is_explicitly_lagged_and_returns_bounded_forecasts():
    from workbench.engine.packs.time_series import fit_var

    result = fit_var(
        _stable_var_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        lags=2,
        trend="c",
        forecast_horizon=3,
        confidence_level=0.9,
    )
    assert result["operation_id"] == "time_series.var"
    assert result["result"]["policy"]["lags"] == 2
    assert result["result"]["policy"]["trend"] == "c"
    assert len(result["result"]["forecast"]["mean"]) == 3
    assert len(result["result"]["forecast"]["mean"][0]) == 2
    assert set(result["result"]["parameters"]) == {"x", "y"}
    json.dumps(result, allow_nan=False)


def test_var_reports_companion_stability_and_rejects_unstable_fit_by_default():
    from workbench.engine.packs.time_series import fit_var
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    stable = fit_var(
        _stable_var_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        lags=2,
        trend="c",
        forecast_horizon=2,
        confidence_level=0.9,
    )
    assert stable["result"]["stability"]["is_stable"] is True
    assert stable["result"]["stability"]["max_modulus"] < 1.0
    assert len(stable["result"]["stability"]["companion_eigenvalues"]) == 4

    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_UNSTABLE"):
        fit_var(
            _unstable_var_frame(),
            time_column="time",
            value_columns=["x", "y"],
            time_order="declared_monotonic",
            lags=1,
            trend="c",
            forecast_horizon=2,
            confidence_level=0.9,
        )
    report_only = fit_var(
        _unstable_var_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        lags=1,
        trend="c",
        forecast_horizon=2,
        confidence_level=0.9,
        stability_policy="report_only",
    )
    assert report_only["result"]["stability"]["is_stable"] is False
    assert report_only["result"]["policy"]["stability_policy"] == "report_only"


def test_granger_direction_is_predictive_precedence_not_causality():
    from workbench.engine.packs.time_series import run_granger

    result = run_granger(
        _model_frame(),
        time_column="time",
        cause="x",
        effect="y",
        time_order="declared_monotonic",
        max_lag=2,
        test="ssr_ftest",
    )
    assert result["operation_id"] == "time_series.granger"
    assert result["result"]["tested_direction"] == {"cause": "x", "effect": "y"}
    assert result["result"]["interpretation"] == "predictive_precedence_only"
    assert "causal_claim" not in result["result"]
    assert len(result["result"]["lags"]) == 2
    json.dumps(result, allow_nan=False)


def test_irf_horizon_and_orthogonalization_are_explicit():
    from workbench.engine.packs.time_series import run_irf

    result = run_irf(
        _stable_var_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        lags=2,
        trend="c",
        horizon=4,
        orthogonalized=False,
        confidence_level=0.9,
        ci_method="asymptotic_normal",
    )
    assert result["operation_id"] == "time_series.irf"
    assert result["result"]["policy"]["horizon"] == 4
    assert result["result"]["policy"]["orthogonalized"] is False
    assert result["result"]["policy"]["ci_method"] == "asymptotic_normal"
    assert len(result["result"]["lower"]) == 5
    assert len(result["result"]["upper"]) == 5
    assert len(result["result"]["lower"][0]) == 2
    assert len(result["result"]["responses"]) == 5
    json.dumps(result, allow_nan=False)


def test_var_family_rejects_unsafe_options():
    from workbench.engine.packs.time_series import fit_var, run_irf
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        fit_var(
            _stable_var_frame(),
            time_column="time",
            value_columns=["x", "y"],
            time_order="declared_monotonic",
            lags=0,
            trend="c",
            forecast_horizon=2,
            confidence_level=0.9,
        )
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        run_irf(
            _model_frame(),
            time_column="time",
            value_columns=["x", "y"],
            time_order="declared_monotonic",
            lags=2,
            trend="c",
            horizon=201,
            orthogonalized=False,
        )
