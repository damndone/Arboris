"""Exploratory factor analysis with explicit factorability gates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd
import scipy
from scipy.stats import chi2
from statsmodels.multivariate.factor import Factor
import statsmodels

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native, prepare_numeric_frame


EFA_EXTRACTIONS = frozenset({"principal_axis", "maximum_likelihood"})
EFA_ROTATIONS = frozenset({"none", "varimax", "promax", "oblimin"})
_EXTRACTION_METHODS = {
    "principal_axis": "pa",
    "maximum_likelihood": "ml",
}


def _validate_efa_options(
    *,
    n_factors: int,
    extraction: str,
    rotation: str,
    kmo_threshold: float,
    bartlett_alpha: float,
    n_variables: int,
) -> None:
    if type(n_factors) is not int or not 1 <= n_factors < n_variables:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "n_factors must be an integer between one and the number of variables minus one",
        )
    if type(extraction) is not str or extraction not in EFA_EXTRACTIONS:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION",
            f"extraction must be one of {sorted(EFA_EXTRACTIONS)}",
        )
    if type(rotation) is not str or rotation not in EFA_ROTATIONS:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION",
            f"rotation must be one of {sorted(EFA_ROTATIONS)}",
        )
    if (
        type(kmo_threshold) is not float
        or not np.isfinite(kmo_threshold)
        or not 0.0 <= kmo_threshold <= 1.0
    ):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "kmo_threshold must be a finite float in [0, 1]",
        )
    if (
        type(bartlett_alpha) is not float
        or not np.isfinite(bartlett_alpha)
        or not 0.0 < bartlett_alpha < 1.0
    ):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "bartlett_alpha must be a finite float in (0, 1)",
        )


def _correlation_factorability(
    values: np.ndarray,
) -> tuple[np.ndarray, float, float, int, float]:
    n_observations, n_variables = values.shape
    centered = values - values.mean(axis=0)
    standard_deviations = centered.std(axis=0, ddof=1)
    if np.any(standard_deviations <= 0.0) or not np.isfinite(standard_deviations).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "EFA requires non-constant finite columns",
        )
    correlation = np.corrcoef(values, rowvar=False)
    if not np.isfinite(correlation).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "the correlation matrix contains non-finite values",
        )
    try:
        precision = np.linalg.inv(correlation)
    except np.linalg.LinAlgError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_FACTORABILITY_FAILED",
            "the correlation matrix is singular and KMO cannot be established",
        ) from exc
    diagonal = np.sqrt(np.diag(precision))
    if np.any(diagonal <= 0.0) or not np.isfinite(diagonal).all():
        raise MultivariatePackError(
            "MULTIVARIATE_FACTORABILITY_FAILED",
            "the correlation precision matrix is invalid",
        )
    partial = -precision / np.outer(diagonal, diagonal)
    np.fill_diagonal(partial, 0.0)
    zero_diagonal_correlation = np.array(correlation, copy=True)
    np.fill_diagonal(zero_diagonal_correlation, 0.0)
    correlation_sum = float(np.square(zero_diagonal_correlation).sum())
    partial_sum = float(np.square(partial).sum())
    denominator = correlation_sum + partial_sum
    kmo = correlation_sum / denominator if denominator > 0.0 else 0.0

    sign, log_determinant = np.linalg.slogdet(correlation)
    if sign <= 0.0 or not np.isfinite(log_determinant):
        raise MultivariatePackError(
            "MULTIVARIATE_FACTORABILITY_FAILED",
            "the correlation determinant is not positive",
        )
    bartlett_statistic = float(
        -(n_observations - 1.0 - (2.0 * n_variables + 5.0) / 6.0)
        * log_determinant
    )
    bartlett_df = n_variables * (n_variables - 1) // 2
    bartlett_p_value = float(chi2.sf(bartlett_statistic, bartlett_df))
    return correlation, kmo, bartlett_statistic, bartlett_df, bartlett_p_value


def _normalize_loading_signs(loadings: np.ndarray) -> np.ndarray:
    normalized = np.array(loadings, dtype=float, copy=True)
    for factor_index in range(normalized.shape[1]):
        column = normalized[:, factor_index]
        pivot = int(np.argmax(np.abs(column)))
        if column[pivot] < 0.0:
            normalized[:, factor_index] *= -1.0
    return normalized


def _real_loading_array(value: object) -> np.ndarray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        imaginary_magnitude = float(np.max(np.abs(raw.imag)))
        if imaginary_magnitude > 1e-10:
            raise MultivariatePackError(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                "the EFA estimator produced materially complex loadings",
            )
        raw = raw.real
    return np.asarray(raw, dtype=float)


def fit_efa(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    n_factors: int,
    extraction: Literal["principal_axis", "maximum_likelihood"],
    rotation: Literal["none", "varimax", "promax", "oblimin"],
    kmo_threshold: float,
    bartlett_alpha: float,
    missing_policy: str = "complete_case_v1",
) -> dict[str, object]:
    """Fit EFA only after declared KMO and Bartlett hard gates pass."""

    if isinstance(columns, (str, bytes)):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be an array of column names"
        )
    try:
        requested_columns = list(columns)
    except TypeError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be an array of column names"
        ) from exc
    prepared = prepare_numeric_frame(
        frame,
        requested_columns,
        missing_policy=missing_policy,
    )
    values = prepared.frame.to_numpy(dtype=float)
    n_observations, n_variables = values.shape
    _validate_efa_options(
        n_factors=n_factors,
        extraction=extraction,
        rotation=rotation,
        kmo_threshold=kmo_threshold,
        bartlett_alpha=bartlett_alpha,
        n_variables=n_variables,
    )
    correlation, kmo, bartlett_statistic, bartlett_df, bartlett_p_value = (
        _correlation_factorability(values)
    )
    if kmo < kmo_threshold:
        raise MultivariatePackError(
            "MULTIVARIATE_FACTORABILITY_FAILED",
            f"KMO {kmo:.6g} is below the declared threshold {kmo_threshold:.6g}",
        )
    if bartlett_p_value >= bartlett_alpha:
        raise MultivariatePackError(
            "MULTIVARIATE_FACTORABILITY_FAILED",
            "Bartlett's test is not significant at the declared alpha",
        )

    try:
        fitted = Factor(
            corr=correlation,
            n_factor=n_factors,
            method=_EXTRACTION_METHODS[extraction],
            nobs=n_observations,
            endog_names=list(prepared.columns),
        ).fit(maxiter=100, tol=1e-8)
        if rotation != "none":
            fitted.rotate(rotation)
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "the declared EFA estimator or rotation could not fit this matrix",
        ) from exc
    loadings = _normalize_loading_signs(_real_loading_array(fitted.loadings))
    if not np.isfinite(loadings).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "the EFA estimator produced non-finite loadings",
        )
    result = {
        "n_factors": n_factors,
        "factor_labels": [f"factor_{index}" for index in range(1, n_factors + 1)],
        "extraction": extraction,
        "rotation": rotation,
        "loadings": loadings,
        "communalities": _real_loading_array(fitted.communality),
        "uniqueness": _real_loading_array(fitted.uniqueness),
        "kmo": kmo,
        "kmo_threshold": kmo_threshold,
        "bartlett": {
            "statistic": bartlett_statistic,
            "df": bartlett_df,
            "p_value": bartlett_p_value,
            "alpha": bartlett_alpha,
        },
        "factorability_policy": {
            "kmo_threshold": kmo_threshold,
            "bartlett_alpha": bartlett_alpha,
            "gates": ["kmo_at_or_above_threshold", "bartlett_p_below_alpha"],
        },
        "estimator": {
            "backend": "statsmodels.multivariate.factor.Factor",
            "statsmodels_version": statsmodels.__version__,
            "scipy_version": scipy.__version__,
        },
        "missing_policy": prepared.missing_policy,
        "retained_positions": list(prepared.retained_positions),
    }
    return make_result_envelope(
        operation_id="multivariate.efa",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        columns=prepared.columns,
        result=json_native(result),
    )


__all__ = ["EFA_EXTRACTIONS", "EFA_ROTATIONS", "fit_efa"]
