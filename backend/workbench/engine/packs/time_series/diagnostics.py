"""ACF/PACF and unit-root diagnostics with explicit policies."""

from __future__ import annotations

from typing import Literal
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, acf, kpss, pacf
from statsmodels.tools.sm_exceptions import InterpolationWarning

from workbench.contracts.model.time_series_pack import make_time_series_result

from .errors import TimeSeriesPackError
from .common import json_native
from .input import prepare_time_series


MAX_LAGS = 200
PACF_METHODS = frozenset({"ywm"})
ADF_REGRESSIONS = frozenset({"c", "ct", "ctt", "n"})
ADF_AUTOLAGS = frozenset({"aic", "bic", "t_stat", "none"})
KPSS_REGRESSIONS = frozenset({"c", "ct"})
KPSS_NLAGS = frozenset({"auto", "legacy"})


def _validate_lag(nlags: int, n_observations: int, *, pacf_mode: bool = False) -> None:
    upper = min(MAX_LAGS, n_observations - 1)
    if pacf_mode:
        upper = min(upper, n_observations // 2 - 1)
    if type(nlags) is not int or not 0 <= nlags <= upper:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            f"nlags must be an integer in [0, {upper}]",
        )


def _single_series(frame: pd.DataFrame, time_column: str, value_column: str, time_order: str):
    prepared = prepare_time_series(
        frame,
        time_column=time_column,
        value_columns=[value_column],
        time_order=time_order,
    )
    return prepared, prepared.frame[value_column].to_numpy(dtype=float)


def run_acf(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_column: str,
    time_order: str,
    nlags: int,
    adjusted: bool,
    confidence_level: float,
) -> dict[str, object]:
    prepared, values = _single_series(frame, time_column, value_column, time_order)
    _validate_lag(nlags, len(values))
    if type(adjusted) is not bool or type(confidence_level) is not float or not 0.0 < confidence_level < 1.0:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "ACF options are invalid")
    values_acf, confidence = acf(
        values,
        nlags=nlags,
        adjusted=adjusted,
        fft=False,
        alpha=1.0 - confidence_level,
    )
    result = {
        "value_column": value_column,
        "lags": list(range(nlags + 1)),
        "values": values_acf,
        "confidence_intervals": confidence,
        "policy": {
            "time_order": time_order,
            "nlags": nlags,
            "adjusted": adjusted,
            "confidence_level": confidence_level,
        },
        "retained_positions": list(prepared.retained_positions),
    }
    return make_time_series_result(
        operation_id="time_series.acf",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=[value_column],
        result=json_native(result),
    )


def run_pacf(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_column: str,
    time_order: str,
    nlags: int,
    method: str,
    confidence_level: float,
) -> dict[str, object]:
    prepared, values = _single_series(frame, time_column, value_column, time_order)
    _validate_lag(nlags, len(values), pacf_mode=True)
    if method not in PACF_METHODS or type(confidence_level) is not float or not 0.0 < confidence_level < 1.0:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "PACF options are invalid")
    values_pacf, confidence = pacf(
        values,
        nlags=nlags,
        method=method,
        alpha=1.0 - confidence_level,
    )
    result = {
        "value_column": value_column,
        "lags": list(range(nlags + 1)),
        "values": values_pacf,
        "confidence_intervals": confidence,
        "policy": {
            "time_order": time_order,
            "nlags": nlags,
            "method": method,
            "confidence_level": confidence_level,
        },
        "retained_positions": list(prepared.retained_positions),
    }
    return make_time_series_result(
        operation_id="time_series.pacf",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=[value_column],
        result=json_native(result),
    )


def run_adf(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_column: str,
    time_order: str,
    regression: str,
    autolag: str,
    max_lag: int,
) -> dict[str, object]:
    prepared, values = _single_series(frame, time_column, value_column, time_order)
    if regression not in ADF_REGRESSIONS or autolag not in ADF_AUTOLAGS or type(max_lag) is not int or not 0 <= max_lag <= MAX_LAGS:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "ADF options are invalid")
    try:
        statistic, p_value, used_lag, nobs, critical_values, icbest = adfuller(
            values,
            maxlag=max_lag,
            regression=regression,
            autolag=None if autolag == "none" else autolag.upper().replace("_", "-"),
        )
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "ADF could not be fit") from exc
    result = {
        "value_column": value_column,
        "statistic": statistic,
        "p_value": p_value,
        "p_value_status": "approximate",
        "used_lag": used_lag,
        "nobs": nobs,
        "critical_values": critical_values,
        "icbest": icbest,
        "policy": {
            "time_order": time_order,
            "regression": regression,
            "autolag": autolag,
            "max_lag": max_lag,
        },
        "retained_positions": list(prepared.retained_positions),
    }
    return make_time_series_result(
        operation_id="time_series.adf",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=[value_column],
        result=json_native(result),
    )


def run_kpss(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_column: str,
    time_order: str,
    regression: str,
    nlags: str | int,
) -> dict[str, object]:
    prepared, values = _single_series(frame, time_column, value_column, time_order)
    if regression not in KPSS_REGRESSIONS or (
        not (nlags in KPSS_NLAGS or type(nlags) is int and 0 <= nlags <= MAX_LAGS)
    ):
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "KPSS options are invalid")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", InterpolationWarning)
        try:
            statistic, p_value, n_lags, critical_values = kpss(
                values,
                regression=regression,
                nlags=nlags,
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "KPSS could not be fit") from exc
    p_value_status = "approximate"
    if caught:
        message = str(caught[0].message).lower()
        p_value_status = "lower_bound" if "smaller" in message else "upper_bound"
    result = {
        "value_column": value_column,
        "statistic": statistic,
        "p_value": p_value,
        "p_value_status": p_value_status,
        "used_lag": n_lags,
        "critical_values": critical_values,
        "policy": {
            "time_order": time_order,
            "regression": regression,
            "nlags": nlags,
        },
        "retained_positions": list(prepared.retained_positions),
    }
    return make_time_series_result(
        operation_id="time_series.kpss",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=[value_column],
        result=json_native(result),
    )


__all__ = ["run_acf", "run_adf", "run_kpss", "run_pacf"]
