"""Two-step heteroskedastic GMM and descriptive weak-instrument evidence."""

from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Any

import numpy as np
from scipy import stats

from workbench.canonical import sha256_canonical
from workbench.contracts.model.iv_gmm import make_iv_gmm_result

from .common import (
    IVGMMPackError,
    finite_scalar,
    names,
    numeric_matrix,
    numeric_vector,
    reject,
    require_full_rank,
    solve,
    symmetric,
)


GMM_ESTIMATORS = frozenset({"one_step", "two_step"})
GMM_COVARIANCE_METHODS = frozenset({"heteroskedastic_hc0"})


def _confidence_level(value: Any) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        reject("IV_GMM_INVALID_INPUT", "confidence_level must be a finite value in (0, 1)")
    level = float(value)
    if not math.isfinite(level) or not 0.0 < level < 1.0:
        reject("IV_GMM_INVALID_INPUT", "confidence_level must be a finite value in (0, 1)")
    return level


def _prepare(
    exog: Any,
    endog: Any,
    instruments: Any,
    *,
    exog_names: Sequence[str] | None,
    endog_names: Sequence[str] | None,
    instrument_names: Sequence[str] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list[str], list[str]]:
    exog_values = numeric_matrix(exog, label="exog")
    endog_values = numeric_matrix(endog, label="endog", rows=exog_values.shape[0])
    instrument_values = numeric_matrix(
        instruments, label="instruments", rows=exog_values.shape[0]
    )
    if exog_values.shape[1] < 1 or endog_values.shape[1] < 1:
        reject("IV_GMM_INVALID_INPUT", "explicit exog and endogenous columns are required")
    parameter_exog_names = names(exog_names, prefix="exog", count=exog_values.shape[1])
    parameter_endog_names = names(endog_names, prefix="endog", count=endog_values.shape[1])
    excluded_names = names(
        instrument_names,
        prefix="instrument",
        count=instrument_values.shape[1],
    )
    all_names = parameter_exog_names + parameter_endog_names + excluded_names
    if len(set(all_names)) != len(all_names):
        reject("IV_GMM_INVALID_NAMES", "exog, endogenous, and instrument names must be disjoint")

    x = np.column_stack((exog_values, endog_values))
    z = np.column_stack((exog_values, instrument_values))
    if z.shape[1] < x.shape[1]:
        reject(
            "IV_GMM_UNDERIDENTIFIED",
            "the instrument count is smaller than the regressor count",
        )
    if exog_values.shape[0] <= x.shape[1]:
        reject("IV_GMM_INVALID_INPUT", "residual degrees of freedom must be positive")
    require_full_rank(x, label="regressor design")
    require_full_rank(z, label="instrument design")
    return (
        exog_values,
        endog_values,
        instrument_values,
        parameter_exog_names,
        parameter_endog_names,
        excluded_names,
    )


def _weak_evidence(
    exog: np.ndarray,
    endog: np.ndarray,
    instruments: np.ndarray,
    *,
    exog_names: list[str],
    endog_names: list[str],
    instrument_names: list[str],
) -> dict[str, Any]:
    n = exog.shape[0]
    excluded_count = instruments.shape[1]
    full = np.column_stack((exog, instruments))
    require_full_rank(full, label="first-stage design")
    full_xtx = full.T @ full
    full_inverse = solve(full_xtx, np.eye(full.shape[1]), label="first-stage cross-product")
    denominator_df = n - full.shape[1]
    if denominator_df <= 0:
        reject("IV_GMM_INVALID_INPUT", "first-stage residual degrees of freedom must be positive")

    by_endogenous: dict[str, dict[str, Any]] = {}
    partial_values: list[float] = []
    robust_values: list[float] = []
    for index, name in enumerate(endog_names):
        target = endog[:, index]
        restricted_beta = solve(
            exog.T @ exog,
            exog.T @ target,
            label="restricted first-stage cross-product",
        )
        full_beta = solve(
            full_xtx,
            full.T @ target,
            label="full first-stage cross-product",
        )
        restricted_residual = target - exog @ restricted_beta
        full_residual = target - full @ full_beta
        rss_restricted = float(restricted_residual @ restricted_residual)
        rss_full = float(full_residual @ full_residual)
        if not math.isfinite(rss_restricted) or not math.isfinite(rss_full) or rss_full <= 0.0:
            reject("IV_GMM_NUMERICAL_FAILURE", "first-stage residual sum of squares is invalid")
        explained = rss_restricted - rss_full
        tolerance = 1e-10 * max(1.0, rss_restricted)
        if explained < -tolerance:
            reject("IV_GMM_NUMERICAL_FAILURE", "first-stage restricted fit is inconsistent")
        explained = max(0.0, explained)
        partial_f = (explained / excluded_count) / (rss_full / denominator_df)
        partial_r2 = explained / rss_restricted if rss_restricted > 0.0 else None

        meat = full.T @ (full * (full_residual**2)[:, None])
        robust_covariance = symmetric(full_inverse @ meat @ full_inverse)
        excluded_covariance = robust_covariance[-excluded_count:, -excluded_count:]
        excluded_coefficients = full_beta[-excluded_count:]
        robust_wald = None
        robust_status = "completed"
        try:
            robust_inverse = solve(
                excluded_covariance,
                np.eye(excluded_count),
                label="robust excluded-instrument covariance",
            )
            robust_wald = float(
                excluded_coefficients @ robust_inverse @ excluded_coefficients / excluded_count
            )
            if not math.isfinite(robust_wald) or robust_wald < -1e-10:
                robust_wald = None
                robust_status = "unavailable_nonfinite"
            else:
                robust_wald = max(0.0, robust_wald)
        except IVGMMPackError:
            robust_status = "unavailable_singular_meat"

        partial_values.append(float(partial_f))
        if robust_wald is not None:
            robust_values.append(float(robust_wald))
        by_endogenous[name] = {
            "partial_f": finite_scalar(partial_f, label="partial_f"),
            "partial_r2": (
                finite_scalar(partial_r2, label="partial_r2")
                if partial_r2 is not None
                else None
            ),
            "robust_excluded_wald_f": robust_wald,
            "robust_excluded_wald_status": robust_status,
            "excluded_instrument_count": excluded_count,
            "residual_degrees_of_freedom": denominator_df,
        }

    return {
        "exog_names": list(exog_names),
        "endogenous_names": list(endog_names),
        "excluded_instrument_names": list(instrument_names),
        "diagnostic_policy": "descriptive_no_automatic_threshold_decision",
        "method": "per_endogenous_partial_f_and_robust_excluded_wald_f",
        "by_endogenous": by_endogenous,
        "minimum_partial_f": min(partial_values),
        "minimum_robust_excluded_wald_f": (
            min(robust_values) if robust_values else None
        ),
    }


def _complete_envelope(
    *,
    operation_id: str,
    n_observations: int,
    parameter_names: list[str],
    result: dict[str, Any],
) -> dict[str, Any]:
    digest = sha256_canonical(
        {
            "operation_id": operation_id,
            "n_observations": n_observations,
            "parameter_names": parameter_names,
            "result": result,
        }
    )
    return make_iv_gmm_result(
        operation_id=operation_id,
        status="completed",
        reason_code="IV_GMM_COMPLETED",
        n_observations=n_observations,
        parameter_names=parameter_names,
        result=result,
        evidence_digest=digest,
    )


def diagnose_weak_instruments(
    exog: Any,
    endog: Any,
    instruments: Any,
    *,
    exog_names: Sequence[str] | None = None,
    endog_names: Sequence[str] | None = None,
    instrument_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return first-stage relevance evidence without an automatic cutoff claim."""

    (
        exog_values,
        endog_values,
        instrument_values,
        resolved_exog_names,
        resolved_endog_names,
        resolved_instrument_names,
    ) = _prepare(
        exog,
        endog,
        instruments,
        exog_names=exog_names,
        endog_names=endog_names,
        instrument_names=instrument_names,
    )
    result = _weak_evidence(
        exog_values,
        endog_values,
        instrument_values,
        exog_names=resolved_exog_names,
        endog_names=resolved_endog_names,
        instrument_names=resolved_instrument_names,
    )
    return _complete_envelope(
        operation_id="iv.weak_instruments",
        n_observations=exog_values.shape[0],
        parameter_names=resolved_endog_names,
        result=result,
    )


def fit_gmm(
    y: Any,
    exog: Any,
    endog: Any,
    instruments: Any,
    *,
    estimator: str = "two_step",
    covariance_method: str = "heteroskedastic_hc0",
    center_moments: bool = False,
    confidence_level: float = 0.95,
    exog_names: Sequence[str] | None = None,
    endog_names: Sequence[str] | None = None,
    instrument_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fit explicit one-step or two-step linear GMM with IV diagnostics."""

    if type(estimator) is not str or estimator not in GMM_ESTIMATORS:
        reject("IV_GMM_UNSUPPORTED_ESTIMATOR", "estimator is not declared")
    if type(covariance_method) is not str or covariance_method not in GMM_COVARIANCE_METHODS:
        reject("IV_GMM_INVALID_INPUT", "covariance_method is not declared")
    if type(center_moments) is not bool:
        reject("IV_GMM_INVALID_INPUT", "center_moments must be a boolean")
    level = _confidence_level(confidence_level)
    y_values = numeric_vector(y, label="y")
    (
        exog_values,
        endog_values,
        instrument_values,
        resolved_exog_names,
        resolved_endog_names,
        resolved_instrument_names,
    ) = _prepare(
        exog,
        endog,
        instruments,
        exog_names=exog_names,
        endog_names=endog_names,
        instrument_names=instrument_names,
    )
    if exog_values.shape[0] != y_values.size:
        reject("IV_GMM_INVALID_INPUT", "exog row count does not match y")
    x = np.column_stack((exog_values, endog_values))
    z = np.column_stack((exog_values, instrument_values))
    n = y_values.size
    p = x.shape[1]
    q = z.shape[1]
    normalized_moments = z.T @ z / n
    initial_weight = solve(
        normalized_moments,
        np.eye(q),
        label="initial GMM weighting matrix",
    )
    derivative = z.T @ x / n
    outcome_moments = z.T @ y_values / n
    initial_normal = symmetric(derivative.T @ initial_weight @ derivative)
    beta = solve(
        initial_normal,
        derivative.T @ initial_weight @ outcome_moments,
        label="one-step GMM normal equations",
    )
    residual = y_values - x @ beta

    if estimator == "two_step":
        moment_values = z * residual[:, None]
        if center_moments:
            moment_values = moment_values - moment_values.mean(axis=0)
        initial_s = symmetric(moment_values.T @ moment_values / n)
        weight = solve(initial_s, np.eye(q), label="two-step GMM weighting matrix")
        normal = symmetric(derivative.T @ weight @ derivative)
        beta = solve(
            normal,
            derivative.T @ weight @ outcome_moments,
            label="two-step GMM normal equations",
        )
        weighting_label = "heteroskedastic_hc0_two_step"
    else:
        weight = initial_weight
        normal = initial_normal
        weighting_label = "z'z_inverse"

    residual = y_values - x @ beta
    moment_values = z * residual[:, None]
    if center_moments:
        moment_values = moment_values - moment_values.mean(axis=0)
    covariance_moments = symmetric(moment_values.T @ moment_values / n)
    normal_inverse = solve(normal, np.eye(p), label="GMM covariance normal matrix")
    sandwich = normal_inverse @ derivative.T @ weight @ covariance_moments @ weight @ derivative @ normal_inverse
    covariance = symmetric(sandwich / n)
    diagonal = np.diag(covariance)
    if np.any(diagonal < -1e-12) or not np.isfinite(diagonal).all():
        reject("IV_GMM_NUMERICAL_FAILURE", "GMM covariance is not positive semidefinite")
    standard_errors = np.sqrt(np.maximum(diagonal, 0.0))
    if np.any(standard_errors <= 0.0) or not np.isfinite(standard_errors).all():
        reject("IV_GMM_NUMERICAL_FAILURE", "GMM standard errors are not positive")
    z_scores = beta / standard_errors
    p_values = 2.0 * stats.norm.sf(np.abs(z_scores))
    critical = float(stats.norm.ppf(1.0 - (1.0 - level) / 2.0))
    coefficients: dict[str, dict[str, Any]] = {}
    parameter_names = resolved_exog_names + resolved_endog_names
    for index, name in enumerate(parameter_names):
        coefficients[name] = {
            "estimate": finite_scalar(beta[index], label="GMM estimate"),
            "std_error": finite_scalar(standard_errors[index], label="GMM standard error"),
            "z_value": finite_scalar(z_scores[index], label="GMM z value"),
            "p_value": finite_scalar(p_values[index], label="GMM p value"),
            "confidence_interval": [
                finite_scalar(beta[index] - critical * standard_errors[index], label="CI lower"),
                finite_scalar(beta[index] + critical * standard_errors[index], label="CI upper"),
            ],
        }

    final_moments = z.T @ residual / n
    j_weight = solve(
        covariance_moments,
        np.eye(q),
        label="overidentification weighting matrix",
    )
    j_statistic = float(n * final_moments @ j_weight @ final_moments)
    if not math.isfinite(j_statistic) or j_statistic < -1e-10:
        reject("IV_GMM_NUMERICAL_FAILURE", "overidentification statistic is invalid")
    j_statistic = max(0.0, j_statistic)
    overidentification: dict[str, Any]
    if q > p:
        degrees_of_freedom = q - p
        overidentification = {
            "available": True,
            "statistic": j_statistic,
            "degrees_of_freedom": degrees_of_freedom,
            "p_value": float(stats.chi2.sf(j_statistic, degrees_of_freedom)),
            "semantics": "Hansen_J_heteroskedastic_moment_test",
        }
    else:
        overidentification = {
            "available": False,
            "statistic": None,
            "degrees_of_freedom": 0,
            "p_value": None,
            "semantics": "not_applicable_exact_identification",
        }
    weak = _weak_evidence(
        exog_values,
        endog_values,
        instrument_values,
        exog_names=resolved_exog_names,
        endog_names=resolved_endog_names,
        instrument_names=resolved_instrument_names,
    )
    result = {
        "estimator": estimator,
        "covariance_method": covariance_method,
        "confidence_level": level,
        "sample_size": n,
        "residual_degrees_of_freedom": n - p,
        "parameter_names": parameter_names,
        "coefficients": coefficients,
        "covariance": covariance.tolist(),
        "weighting": {
            "method": weighting_label,
            "center_moments": center_moments,
            "moment_count": q,
        },
        "overidentification": overidentification,
        "weak_instruments": weak,
    }
    return _complete_envelope(
        operation_id="iv.gmm",
        n_observations=n,
        parameter_names=parameter_names,
        result=result,
    )


__all__ = [
    "GMM_COVARIANCE_METHODS",
    "GMM_ESTIMATORS",
    "diagnose_weak_instruments",
    "fit_gmm",
]
