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
        _model_frame(),
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
        _model_frame(),
        time_column="time",
        value_columns=["x", "y"],
        time_order="declared_monotonic",
        lags=2,
        trend="c",
        horizon=4,
        orthogonalized=False,
    )
    assert result["operation_id"] == "time_series.irf"
    assert result["result"]["policy"]["horizon"] == 4
    assert result["result"]["policy"]["orthogonalized"] is False
    assert len(result["result"]["responses"]) == 5
    json.dumps(result, allow_nan=False)


def test_var_family_rejects_unsafe_options():
    from workbench.engine.packs.time_series import fit_var, run_irf
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        fit_var(
            _model_frame(),
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
