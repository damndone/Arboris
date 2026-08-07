"""Explicit univariate ARIMA/SARIMA kernels for the standalone time-series pack."""

from __future__ import annotations

from collections.abc import Sequence
import warnings

import numpy as np
import pandas as pd
import statsmodels
from statsmodels.tsa.arima.model import ARIMA

from workbench.contracts.model.time_series_pack import make_time_series_result

from .common import json_native
from .errors import TimeSeriesPackError
from .input import prepare_time_series


MAX_FORECAST_HORIZON = 200
MAX_ORDER_COMPONENT = 12
MAX_TOTAL_ORDER = 24
ARIMA_TRENDS = frozenset({"n", "c", "t", "ct"})


def _validate_confidence(confidence_level: float) -> None:
    if type(confidence_level) is not float or not 0.0 < confidence_level < 1.0:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "confidence_level must be a float in (0, 1)"
        )


def _validate_horizon(horizon: int, *, field_name: str = "forecast_horizon") -> None:
    if type(horizon) is not int or not 1 <= horizon <= MAX_FORECAST_HORIZON:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            f"{field_name} must be an integer in [1, {MAX_FORECAST_HORIZON}]",
        )


def _validate_order(order: Sequence[int], *, seasonal: bool) -> tuple[int, ...]:
    expected_length = 4 if seasonal else 3
    if isinstance(order, (str, bytes)):
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "orders must be integer arrays")
    try:
        normalized = tuple(order)
    except TypeError as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "orders must be integer arrays"
        ) from exc
    if len(normalized) != expected_length or any(
        type(component) is not int or component < 0 or component > MAX_ORDER_COMPONENT
        for component in normalized
    ):
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            f"{('seasonal_' if seasonal else '')}order must contain {expected_length} bounded non-negative integers",
        )
    if sum(normalized[:3]) > MAX_TOTAL_ORDER:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "order is too large")
    if seasonal:
        p, d, q, period = normalized
        if (p or d or q) and period < 2:
            raise TimeSeriesPackError(
                "TIME_SERIES_INVALID_OPTION",
                "seasonal period must be at least two when a seasonal term is used",
            )
        if period > MAX_ORDER_COMPONENT:
            raise TimeSeriesPackError(
                "TIME_SERIES_INVALID_OPTION", "seasonal period is too large"
            )
    return normalized


def _parameter_payload(fitted: object) -> dict[str, float]:
    params = np.asarray(getattr(fitted, "params"), dtype=float)
    if params.ndim != 1 or not np.isfinite(params).all():
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "ARIMA returned non-finite parameters"
        )
    names = tuple(str(name) for name in getattr(fitted, "param_names"))
    return {name: float(value) for name, value in zip(names, params, strict=True)}


def fit_arima(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_column: str,
    time_order: str,
    order: Sequence[int],
    seasonal_order: Sequence[int] = (0, 0, 0, 0),
    trend: str = "c",
    forecast_horizon: int = 1,
    confidence_level: float = 0.95,
) -> dict[str, object]:
    """Fit one explicitly specified ARIMA/SARIMA model.

    There is deliberately no auto-order mode.  The future time index is
    represented as relative steps because this boundary does not infer a
    frequency from the observed time column.
    """

    prepared = prepare_time_series(
        frame,
        time_column=time_column,
        value_columns=[value_column],
        time_order=time_order,
    )
    normalized_order = _validate_order(order, seasonal=False)
    normalized_seasonal_order = _validate_order(seasonal_order, seasonal=True)
    if trend not in ARIMA_TRENDS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "trend must be one of n, c, t, ct"
        )
    _validate_horizon(forecast_horizon)
    _validate_confidence(confidence_level)
    if (normalized_order[1] or normalized_seasonal_order[1]) and trend in {"c", "ct"}:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            "constant trend is not allowed with differencing; choose n or t explicitly",
        )

    values = prepared.frame[value_column].to_numpy(dtype=float)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fitted = ARIMA(
                values,
                order=normalized_order,
                seasonal_order=normalized_seasonal_order,
                trend=trend,
                enforce_stationarity=True,
                enforce_invertibility=True,
                missing="none",
            ).fit()
            forecast = fitted.get_forecast(steps=forecast_horizon)
            summary = forecast.summary_frame(alpha=1.0 - confidence_level)
        forecast_mean = summary["mean"].to_numpy(dtype=float)
        lower = summary["mean_ci_lower"].to_numpy(dtype=float)
        upper = summary["mean_ci_upper"].to_numpy(dtype=float)
        if not np.isfinite(np.concatenate((forecast_mean, lower, upper))).all():
            raise TimeSeriesPackError(
                "TIME_SERIES_NUMERIC_FAILURE", "ARIMA returned non-finite forecast values"
            )
        warning_messages = tuple(dict.fromkeys(str(item.message) for item in caught))
        result = {
            "value_column": value_column,
            "estimator": {"library": "statsmodels", "version": statsmodels.__version__},
            "parameters": _parameter_payload(fitted),
            "aic": float(fitted.aic),
            "bic": float(fitted.bic),
            "log_likelihood": float(fitted.llf),
            "forecast": {
                "steps": list(range(1, forecast_horizon + 1)),
                "mean": forecast_mean,
                "lower": lower,
                "upper": upper,
            },
            "warnings": list(warning_messages),
            "policy": {
                "time_order": time_order,
                "order": list(normalized_order),
                "seasonal_order": list(normalized_seasonal_order),
                "trend": trend,
                "forecast_horizon": forecast_horizon,
                "confidence_level": confidence_level,
                "frequency_inferred": False,
            },
            "retained_positions": list(prepared.retained_positions),
        }
    except TimeSeriesPackError:
        raise
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "ARIMA could not be fit"
        ) from exc
    return make_time_series_result(
        operation_id="time_series.arima",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=[value_column],
        result=json_native(result),
    )


__all__ = ["ARIMA_TRENDS", "MAX_FORECAST_HORIZON", "fit_arima"]
