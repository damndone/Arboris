"""Cointegration evidence and rank-derived VECM kernels."""

from __future__ import annotations

from collections.abc import Sequence
import warnings

import numpy as np
import pandas as pd
import statsmodels
from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen

from workbench.contracts.model.time_series_pack import make_time_series_result

from .common import json_native
from .errors import TimeSeriesPackError
from .input import PreparedTimeSeries, prepare_time_series
from .models import MAX_FORECAST_HORIZON, _validate_confidence


COINTEGRATION_METHODS = frozenset({"engle_granger", "johansen"})
ENGLE_GRANGER_TRENDS = frozenset({"c", "ct", "ctt", "n"})
JOHANSEN_DET_ORDERS = frozenset({-1, 0, 1})
VECM_DETERMINISTICS = frozenset({"n", "co", "ci", "lo", "li"})
MAX_COINTEGRATION_LAG = 50
_CRITICAL_VALUE_INDEX = {0.9: 0, 0.95: 1, 0.99: 2}


def _validate_cointegration_options(
    *,
    method: str,
    confidence_level: float,
    max_lag: int | None = None,
    det_order: int | None = None,
    k_ar_diff: int | None = None,
) -> None:
    if method not in COINTEGRATION_METHODS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "method must be engle_granger or johansen"
        )
    _validate_confidence(confidence_level)
    if confidence_level not in _CRITICAL_VALUE_INDEX:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "confidence_level must be 0.90, 0.95, or 0.99"
        )
    if max_lag is not None and (
        type(max_lag) is not int or not 0 <= max_lag <= MAX_COINTEGRATION_LAG
    ):
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            f"max_lag must be an integer in [0, {MAX_COINTEGRATION_LAG}]",
        )
    if det_order is not None and det_order not in JOHANSEN_DET_ORDERS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "det_order must be -1, 0, or 1"
        )
    if k_ar_diff is not None and (
        type(k_ar_diff) is not int or not 1 <= k_ar_diff <= MAX_COINTEGRATION_LAG
    ):
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            f"k_ar_diff must be an integer in [1, {MAX_COINTEGRATION_LAG}]",
        )


def _prepare_cointegration(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_columns: Sequence[str],
    time_order: str,
) -> PreparedTimeSeries:
    if isinstance(value_columns, (str, bytes)):
        raise TimeSeriesPackError("TIME_SERIES_BAD_INPUT", "value_columns must be an array")
    normalized_columns = list(value_columns)
    if len(normalized_columns) < 2:
        raise TimeSeriesPackError(
            "TIME_SERIES_TOO_FEW_COLUMNS", "cointegration requires at least two series"
        )
    return prepare_time_series(
        frame,
        time_column=time_column,
        value_columns=normalized_columns,
        time_order=time_order,
    )


def _critical_value_level(confidence_level: float) -> str:
    return {0.9: "90%", 0.95: "95%", 0.99: "99%"}[confidence_level]


def _johansen_evidence(
    values: np.ndarray,
    *,
    det_order: int,
    k_ar_diff: int,
    confidence_level: float,
) -> tuple[dict[str, object], tuple[str, ...]]:
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fitted = coint_johansen(values, det_order, k_ar_diff)
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "Johansen cointegration test could not be fit"
        ) from exc
    index = _CRITICAL_VALUE_INDEX[confidence_level]
    trace_tests: list[dict[str, object]] = []
    max_eigen_tests: list[dict[str, object]] = []
    for rank in range(values.shape[1]):
        trace_statistic = float(fitted.lr1[rank])
        trace_critical = float(fitted.cvt[rank, index])
        max_statistic = float(fitted.lr2[rank])
        max_critical = float(fitted.cvm[rank, index])
        trace_tests.append(
            {
                "null": f"rank <= {rank}",
                "rank": rank,
                "statistic": trace_statistic,
                "critical_value": trace_critical,
                "reject": trace_statistic > trace_critical,
            }
        )
        max_eigen_tests.append(
            {
                "null": f"rank = {rank}",
                "rank": rank,
                "statistic": max_statistic,
                "critical_value": max_critical,
                "reject": max_statistic > max_critical,
            }
        )

    def sequential_rank(tests: list[dict[str, object]]) -> int:
        selected = 0
        for item in tests:
            if not item["reject"]:
                break
            selected += 1
        return min(selected, values.shape[1] - 1)

    result = {
        "method": "johansen",
        "trace_tests": trace_tests,
        "maximum_eigenvalue_tests": max_eigen_tests,
        "rank_decision": {
            "policy": "sequential_rejection",
            "trace_rank": sequential_rank(trace_tests),
            "maximum_eigenvalue_rank": sequential_rank(max_eigen_tests),
            "critical_level": _critical_value_level(confidence_level),
        },
        "policy": {
            "det_order": det_order,
            "k_ar_diff": k_ar_diff,
            "confidence_level": confidence_level,
        },
        "warnings": list(dict.fromkeys(str(item.message) for item in caught)),
    }
    return json_native(result), tuple(dict.fromkeys(str(item.message) for item in caught))


def run_cointegration(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_columns: Sequence[str],
    time_order: str,
    method: str,
    confidence_level: float,
    max_lag: int = 1,
    trend: str = "c",
    det_order: int = 0,
    k_ar_diff: int = 1,
) -> dict[str, object]:
    """Return explicit Engle-Granger or Johansen cointegration evidence."""

    prepared = _prepare_cointegration(
        frame,
        time_column=time_column,
        value_columns=value_columns,
        time_order=time_order,
    )
    _validate_cointegration_options(
        method=method,
        confidence_level=confidence_level,
        max_lag=max_lag,
        det_order=det_order,
        k_ar_diff=k_ar_diff,
    )
    values = prepared.frame.loc[:, list(prepared.value_columns)].to_numpy(dtype=float)
    if method == "engle_granger":
        if len(prepared.value_columns) != 2 or trend not in ENGLE_GRANGER_TRENDS:
            raise TimeSeriesPackError(
                "TIME_SERIES_INVALID_OPTION",
                "Engle-Granger requires exactly two series and a declared trend",
            )
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                statistic, p_value, critical_values = coint(
                    values[:, 0],
                    values[:, 1],
                    trend=trend,
                    maxlag=max_lag,
                    autolag=None,
                )
        except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
            raise TimeSeriesPackError(
                "TIME_SERIES_NUMERIC_FAILURE", "Engle-Granger test could not be fit"
            ) from exc
        result = {
            "method": "engle_granger",
            "ordered_pair": {
                "dependent": prepared.value_columns[0],
                "regressor": prepared.value_columns[1],
            },
            "statistic": statistic,
            "p_value": p_value,
            "p_value_status": "approximate",
            "critical_values": {
                level: critical_values[index]
                for index, level in enumerate(("1%", "5%", "10%"))
            },
            "null_hypothesis": "no cointegration",
            "policy": {
                "time_order": time_order,
                "trend": trend,
                "max_lag": max_lag,
                "autolag": "none",
                "confidence_level": confidence_level,
                "frequency_inferred": False,
            },
            "warnings": list(dict.fromkeys(str(item.message) for item in caught)),
            "retained_positions": list(prepared.retained_positions),
        }
    else:
        result, _ = _johansen_evidence(
            values,
            det_order=det_order,
            k_ar_diff=k_ar_diff,
            confidence_level=confidence_level,
        )
        result["policy"] = {
            **result["policy"],
            "time_order": time_order,
            "frequency_inferred": False,
        }
        result["retained_positions"] = list(prepared.retained_positions)
    return make_time_series_result(
        operation_id="time_series.cointegration",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=prepared.value_columns,
        result=json_native(result),
    )


def fit_vecm(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_columns: Sequence[str],
    time_order: str,
    det_order: int,
    k_ar_diff: int,
    deterministic: str,
    forecast_horizon: int,
    confidence_level: float,
) -> dict[str, object]:
    """Fit VECM only when Johansen trace evidence supports a positive rank."""

    prepared = _prepare_cointegration(
        frame,
        time_column=time_column,
        value_columns=value_columns,
        time_order=time_order,
    )
    _validate_cointegration_options(
        method="johansen",
        confidence_level=confidence_level,
        det_order=det_order,
        k_ar_diff=k_ar_diff,
    )
    if deterministic not in VECM_DETERMINISTICS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "deterministic is not a declared VECM policy"
        )
    if type(forecast_horizon) is not int or not 1 <= forecast_horizon <= MAX_FORECAST_HORIZON:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            f"forecast_horizon must be an integer in [1, {MAX_FORECAST_HORIZON}]",
        )
    values = prepared.frame.loc[:, list(prepared.value_columns)].to_numpy(dtype=float)
    rank_evidence, warning_messages = _johansen_evidence(
        values,
        det_order=det_order,
        k_ar_diff=k_ar_diff,
        confidence_level=confidence_level,
    )
    rank = int(rank_evidence["rank_decision"]["trace_rank"])
    base_result = {
        "rank": rank,
        "rank_policy": "johansen_trace",
        "rank_evidence": rank_evidence,
        "policy": {
            "time_order": time_order,
            "det_order": det_order,
            "k_ar_diff": k_ar_diff,
            "deterministic": deterministic,
            "forecast_horizon": forecast_horizon,
            "confidence_level": confidence_level,
            "frequency_inferred": False,
        },
        "warnings": list(warning_messages),
        "retained_positions": list(prepared.retained_positions),
    }
    if rank == 0:
        return make_time_series_result(
            operation_id="time_series.vecm",
            status="rejected",
            reason_code="TIME_SERIES_NO_COINTEGRATION",
            n_observations=prepared.n_observations,
            variables=prepared.value_columns,
            result=json_native(base_result),
        )
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fitted = VECM(
                values,
                k_ar_diff=k_ar_diff,
                coint_rank=rank,
                deterministic=deterministic,
                missing="none",
            ).fit()
            forecast = fitted.predict(steps=forecast_horizon)
        result = {
            **base_result,
            "estimator": {"library": "statsmodels", "version": statsmodels.__version__},
            "alpha": fitted.alpha,
            "beta": fitted.beta,
            "gamma": fitted.gamma,
            "deterministic_coefficients": fitted.det_coef,
            "forecast": {
                "steps": list(range(1, forecast_horizon + 1)),
                "mean": forecast,
            },
            "log_likelihood": fitted.llf,
            "warnings": list(
                dict.fromkeys(
                    [*base_result["warnings"], *(str(item.message) for item in caught)]
                )
            ),
        }
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "VECM could not be fit") from exc
    return make_time_series_result(
        operation_id="time_series.vecm",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=prepared.value_columns,
        result=json_native(result),
    )


__all__ = [
    "COINTEGRATION_METHODS",
    "ENGLE_GRANGER_TRENDS",
    "VECM_DETERMINISTICS",
    "fit_vecm",
    "run_cointegration",
]
