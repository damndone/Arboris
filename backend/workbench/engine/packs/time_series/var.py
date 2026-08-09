"""Explicit VAR, predictive-precedence, and impulse-response kernels."""

from __future__ import annotations

from collections.abc import Sequence
import warnings

import numpy as np
import pandas as pd
import statsmodels
from scipy.stats import norm
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import grangercausalitytests
from statsmodels.tsa.vector_ar.util import comp_matrix

from workbench.contracts.model.time_series_pack import make_time_series_result

from .common import json_native
from .errors import TimeSeriesPackError
from .input import PreparedTimeSeries, prepare_time_series
from .models import MAX_FORECAST_HORIZON, _validate_confidence


MAX_VAR_LAGS = 50
VAR_TRENDS = frozenset({"n", "c", "ct", "ctt"})
GRANGER_TESTS = frozenset({"ssr_ftest", "ssr_chi2test", "lrtest", "params_ftest"})
STABILITY_POLICIES = frozenset({"reject_unstable", "report_only"})
IRF_CI_METHODS = frozenset({"asymptotic_normal"})


def _validate_var_options(
    *,
    lags: int,
    trend: str,
    forecast_horizon: int | None = None,
    horizon: int | None = None,
) -> None:
    if type(lags) is not int or not 1 <= lags <= MAX_VAR_LAGS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", f"lags must be an integer in [1, {MAX_VAR_LAGS}]"
        )
    if trend not in VAR_TRENDS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "trend must be one of n, c, ct, ctt"
        )
    if forecast_horizon is not None:
        if type(forecast_horizon) is not int or not 1 <= forecast_horizon <= MAX_FORECAST_HORIZON:
            raise TimeSeriesPackError(
                "TIME_SERIES_INVALID_OPTION",
                f"forecast_horizon must be an integer in [1, {MAX_FORECAST_HORIZON}]",
            )
    if horizon is not None:
        if type(horizon) is not int or not 0 <= horizon <= MAX_FORECAST_HORIZON:
            raise TimeSeriesPackError(
                "TIME_SERIES_INVALID_OPTION",
                f"horizon must be an integer in [0, {MAX_FORECAST_HORIZON}]",
            )


def _validate_stability_policy(stability_policy: str) -> None:
    if stability_policy not in STABILITY_POLICIES:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION",
            "stability_policy must be reject_unstable or report_only",
        )


def _stability_evidence(fitted: object) -> dict[str, object]:
    try:
        coefficients = np.asarray(getattr(fitted, "coefs"), dtype=float)
        eigenvalues = np.linalg.eigvals(comp_matrix(coefficients))
    except (ValueError, np.linalg.LinAlgError, TypeError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "VAR stability could not be evaluated"
        ) from exc
    if not np.isfinite(eigenvalues.real).all() or not np.isfinite(eigenvalues.imag).all():
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "VAR stability contains non-finite eigenvalues"
        )
    moduli = np.abs(eigenvalues)
    return {
        "is_stable": bool(getattr(fitted, "is_stable")()),
        "companion_eigenvalues": [
            {
                "real": float(value.real),
                "imaginary": float(value.imag),
                "modulus": float(abs(value)),
            }
            for value in eigenvalues
        ],
        "max_modulus": float(np.max(moduli)),
        "stability_convention": "companion_eigenvalue_modulus_less_than_one",
    }


def _prepare_var(
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
            "TIME_SERIES_TOO_FEW_COLUMNS", "VAR requires at least two value columns"
        )
    return prepare_time_series(
        frame,
        time_column=time_column,
        value_columns=normalized_columns,
        time_order=time_order,
    )


def _fit_var_model(
    prepared: PreparedTimeSeries,
    *,
    lags: int,
    trend: str,
):
    values = prepared.frame.loc[:, list(prepared.value_columns)].to_numpy(dtype=float)
    if len(values) <= lags + len(prepared.value_columns) + 1:
        raise TimeSeriesPackError(
            "TIME_SERIES_TOO_FEW_OBSERVATIONS", "VAR has too few observations for the declared lag"
        )
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fitted = VAR(values).fit(maxlags=lags, ic=None, trend=trend, method="ols")
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "VAR could not be fit") from exc
    if fitted.k_ar != lags:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "VAR did not retain the declared lag order"
        )
    warning_messages = tuple(dict.fromkeys(str(item.message) for item in caught))
    return values, fitted, warning_messages


def _var_parameters(fitted: object, names: tuple[str, ...]) -> dict[str, dict[str, float]]:
    matrix = np.asarray(getattr(fitted, "params"), dtype=float)
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "VAR returned non-finite parameters"
        )
    row_names = tuple(str(name) for name in getattr(getattr(fitted, "params"), "index", []))
    if len(row_names) != matrix.shape[0]:
        row_names = tuple(f"parameter_{index + 1}" for index in range(matrix.shape[0]))
    return {
        equation: {
            row_name: float(matrix[row_index, equation_index])
            for row_index, row_name in enumerate(row_names)
        }
        for equation_index, equation in enumerate(names)
    }


def fit_var(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_columns: Sequence[str],
    time_order: str,
    lags: int,
    trend: str = "c",
    forecast_horizon: int = 1,
    confidence_level: float = 0.95,
    stability_policy: str = "reject_unstable",
) -> dict[str, object]:
    """Fit one explicitly lagged VAR model; no information-criterion selection."""

    prepared = _prepare_var(
        frame,
        time_column=time_column,
        value_columns=value_columns,
        time_order=time_order,
    )
    _validate_var_options(lags=lags, trend=trend, forecast_horizon=forecast_horizon)
    _validate_confidence(confidence_level)
    _validate_stability_policy(stability_policy)
    values, fitted, warning_messages = _fit_var_model(prepared, lags=lags, trend=trend)
    stability = _stability_evidence(fitted)
    if not stability["is_stable"] and stability_policy == "reject_unstable":
        raise TimeSeriesPackError(
            "TIME_SERIES_UNSTABLE", "VAR companion eigenvalues do not satisfy stability"
        )
    try:
        mean, lower, upper = fitted.forecast_interval(
            values[-lags:], steps=forecast_horizon, alpha=1.0 - confidence_level
        )
        if not np.isfinite(np.concatenate((mean, lower, upper))).all():
            raise TimeSeriesPackError(
                "TIME_SERIES_NUMERIC_FAILURE", "VAR returned non-finite forecast values"
            )
        result = {
            "value_columns": list(prepared.value_columns),
            "estimator": {"library": "statsmodels", "version": statsmodels.__version__},
            "parameters": _var_parameters(fitted, prepared.value_columns),
            "stability": stability,
            "aic": float(fitted.aic),
            "bic": float(fitted.bic),
            "forecast": {
                "steps": list(range(1, forecast_horizon + 1)),
                "mean": mean,
                "lower": lower,
                "upper": upper,
            },
            "warnings": list(warning_messages),
            "policy": {
                "time_order": time_order,
                "lags": lags,
                "trend": trend,
                "forecast_horizon": forecast_horizon,
                "confidence_level": confidence_level,
                "stability_policy": stability_policy,
                "frequency_inferred": False,
            },
            "retained_positions": list(prepared.retained_positions),
        }
    except TimeSeriesPackError:
        raise
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "VAR forecast could not be computed"
        ) from exc
    return make_time_series_result(
        operation_id="time_series.var",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=prepared.value_columns,
        result=json_native(result),
    )


def run_granger(
    frame: pd.DataFrame,
    *,
    time_column: str,
    cause: str,
    effect: str,
    time_order: str,
    max_lag: int,
    test: str = "ssr_ftest",
) -> dict[str, object]:
    """Test predictive precedence in one declared direction.

    The output intentionally avoids a causal claim: Granger's null concerns
    incremental predictive content under the tested lag specification.
    """

    if cause == effect:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "cause and effect must be different columns"
        )
    if type(max_lag) is not int or not 1 <= max_lag <= MAX_VAR_LAGS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", f"max_lag must be an integer in [1, {MAX_VAR_LAGS}]"
        )
    if test not in GRANGER_TESTS:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "test is not declared")
    prepared = _prepare_var(
        frame,
        time_column=time_column,
        value_columns=[effect, cause],
        time_order=time_order,
    )
    values = prepared.frame.loc[:, [effect, cause]].to_numpy(dtype=float)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            raw = grangercausalitytests(values, maxlag=max_lag, verbose=False)
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "Granger test could not be fit"
        ) from exc
    lags: list[dict[str, object]] = []
    for lag in range(1, max_lag + 1):
        test_values = raw[lag][0][test]
        numbers = tuple(float(value) for value in test_values)
        entry: dict[str, object] = {
            "lag": lag,
            "statistic": numbers[0],
            "p_value": numbers[1],
        }
        if len(numbers) >= 4:
            entry["degrees_of_freedom"] = {"numerator": numbers[2], "denominator": numbers[3]}
        elif len(numbers) >= 3:
            entry["degrees_of_freedom"] = numbers[2]
        lags.append(entry)
    result = {
        "tested_direction": {"cause": cause, "effect": effect},
        "null_hypothesis": f"lags of {cause} do not improve prediction of {effect}",
        "interpretation": "predictive_precedence_only",
        "test": test,
        "lags": lags,
        "warnings": list(dict.fromkeys(str(item.message) for item in caught)),
        "policy": {
            "time_order": time_order,
            "max_lag": max_lag,
            "frequency_inferred": False,
        },
        "retained_positions": list(prepared.retained_positions),
    }
    return make_time_series_result(
        operation_id="time_series.granger",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=[effect, cause],
        result=json_native(result),
    )


def run_irf(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_columns: Sequence[str],
    time_order: str,
    lags: int,
    trend: str = "c",
    horizon: int = 10,
    orthogonalized: bool = True,
    confidence_level: float = 0.95,
    ci_method: str = "asymptotic_normal",
    stability_policy: str = "reject_unstable",
) -> dict[str, object]:
    """Return a bounded VAR impulse-response surface with explicit conventions."""

    prepared = _prepare_var(
        frame,
        time_column=time_column,
        value_columns=value_columns,
        time_order=time_order,
    )
    _validate_var_options(lags=lags, trend=trend, horizon=horizon)
    _validate_confidence(confidence_level)
    _validate_stability_policy(stability_policy)
    if ci_method not in IRF_CI_METHODS:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "ci_method must be asymptotic_normal"
        )
    if type(orthogonalized) is not bool:
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_OPTION", "orthogonalized must be a boolean"
        )
    values, fitted, warning_messages = _fit_var_model(prepared, lags=lags, trend=trend)
    stability = _stability_evidence(fitted)
    if not stability["is_stable"] and stability_policy == "reject_unstable":
        raise TimeSeriesPackError(
            "TIME_SERIES_UNSTABLE", "VAR companion eigenvalues do not satisfy stability"
        )
    try:
        irf = fitted.irf(periods=horizon)
        responses = irf.orth_irfs if orthogonalized else irf.irfs
        standard_errors = irf.stderr(orth=orthogonalized)
        critical_value = norm.ppf(0.5 + confidence_level / 2.0)
        lower = responses - critical_value * standard_errors
        upper = responses + critical_value * standard_errors
        if not np.isfinite(np.concatenate((responses, lower, upper))).all():
            raise TimeSeriesPackError(
                "TIME_SERIES_NUMERIC_FAILURE", "IRF returned non-finite responses"
            )
    except TimeSeriesPackError:
        raise
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NUMERIC_FAILURE", "IRF could not be computed"
        ) from exc
    result = {
        "shock_order": list(prepared.value_columns),
        "response_order": list(prepared.value_columns),
        "responses": responses,
        "lower": lower,
        "upper": upper,
        "stability": stability,
        "warnings": list(warning_messages),
        "policy": {
            "time_order": time_order,
            "lags": lags,
            "trend": trend,
            "horizon": horizon,
            "orthogonalized": orthogonalized,
            "confidence_level": confidence_level,
            "ci_method": ci_method,
            "stability_policy": stability_policy,
            "frequency_inferred": False,
        },
        "retained_positions": list(prepared.retained_positions),
    }
    return make_time_series_result(
        operation_id="time_series.irf",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        variables=prepared.value_columns,
        result=json_native(result),
    )


__all__ = [
    "GRANGER_TESTS",
    "IRF_CI_METHODS",
    "MAX_VAR_LAGS",
    "STABILITY_POLICIES",
    "VAR_TRENDS",
    "fit_var",
    "run_granger",
    "run_irf",
]
