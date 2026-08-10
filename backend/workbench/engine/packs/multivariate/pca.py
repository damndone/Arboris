"""Deterministic principal-component analysis for explicit numeric inputs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native, prepare_numeric_frame


PCA_MATRICES = frozenset({"correlation", "covariance"})
PCA_COMPONENT_SELECTIONS = frozenset(
    {"all", "fixed", "kaiser", "cumulative_variance"}
)


def _validate_choice(value: object, allowed: frozenset[str], field_name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION",
            f"{field_name} must be one of {sorted(allowed)}",
        )
    return value


def _validate_optional_component_arguments(
    *,
    component_selection: str,
    n_components: int | None,
    variance_threshold: float | None,
    n_variables: int,
    matrix: str,
) -> None:
    if component_selection == "all":
        if n_components is not None or variance_threshold is not None:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "all selection does not accept n_components or variance_threshold",
            )
    elif component_selection == "fixed":
        if (
            type(n_components) is not int
            or not 1 <= n_components <= n_variables
            or variance_threshold is not None
        ):
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "fixed selection requires an integer n_components within bounds",
            )
    elif component_selection == "kaiser":
        if matrix != "correlation":
            raise MultivariatePackError(
                "MULTIVARIATE_UNSUPPORTED_OPTION",
                "kaiser selection is defined for a correlation matrix only",
            )
        if n_components is not None or variance_threshold is not None:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "kaiser selection does not accept an explicit component count or threshold",
            )
    elif component_selection == "cumulative_variance":
        if n_components is not None or type(variance_threshold) is not float:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "cumulative_variance selection requires a float variance_threshold",
            )
        if not np.isfinite(variance_threshold) or not 0.0 < variance_threshold <= 1.0:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "variance_threshold must be finite and in (0, 1]",
            )


def _normalize_component_signs(components: np.ndarray) -> np.ndarray:
    normalized = np.array(components, dtype=float, copy=True)
    for component_index in range(normalized.shape[1]):
        column = normalized[:, component_index]
        pivot = int(np.argmax(np.abs(column)))
        if column[pivot] < 0.0:
            normalized[:, component_index] *= -1.0
    return normalized


def fit_pca(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    matrix: Literal["correlation", "covariance"],
    component_selection: Literal[
        "all", "fixed", "kaiser", "cumulative_variance"
    ],
    n_components: int | None = None,
    variance_threshold: float | None = None,
    missing_policy: str = "complete_case_v1",
    include_scores: bool = False,
    max_score_rows: int = 100,
) -> dict[str, object]:
    """Fit PCA with no implicit scale or component-selection policy.

    ``matrix`` and ``component_selection`` are required keyword arguments so a
    future Agent proposal cannot accidentally rely on a hidden statistical
    default.  Scores are opt-in and bounded; the normal result contains only
    loadings and summary diagnostics.
    """

    matrix_name = _validate_choice(matrix, PCA_MATRICES, "matrix")
    selection = _validate_choice(
        component_selection, PCA_COMPONENT_SELECTIONS, "component_selection"
    )
    if type(include_scores) is not bool:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "include_scores must be a boolean"
        )
    if type(max_score_rows) is not int or max_score_rows < 1:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "max_score_rows must be a positive integer"
        )
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
    _validate_optional_component_arguments(
        component_selection=selection,
        n_components=n_components,
        variance_threshold=variance_threshold,
        n_variables=n_variables,
        matrix=matrix_name,
    )

    centered = values - values.mean(axis=0)
    if matrix_name == "correlation":
        standard_deviations = centered.std(axis=0, ddof=1)
        if np.any(standard_deviations <= 0.0) or not np.isfinite(standard_deviations).all():
            raise MultivariatePackError(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                "correlation PCA requires non-constant finite columns",
            )
        working = centered / standard_deviations
    else:
        working = centered

    matrix_values = np.atleast_2d(np.cov(working, rowvar=False, ddof=1))
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(matrix_values)
    except np.linalg.LinAlgError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "eigendecomposition of the PCA matrix failed",
        ) from exc
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.asarray(eigenvalues[order], dtype=float)
    eigenvectors = np.asarray(eigenvectors[:, order], dtype=float)
    if np.any(eigenvalues < -1e-10) or not np.isfinite(eigenvalues).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "the covariance matrix is not positive semidefinite",
        )
    eigenvalues = np.maximum(eigenvalues, 0.0)
    eigenvectors = _normalize_component_signs(eigenvectors)
    total_variance = float(eigenvalues.sum())
    if total_variance <= 0.0 or not np.isfinite(total_variance):
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY", "total variance must be positive"
        )
    explained_ratio = eigenvalues / total_variance
    cumulative_ratio = np.cumsum(explained_ratio)

    if selection == "all":
        selected_count = n_variables
    elif selection == "fixed":
        selected_count = int(n_components)
    elif selection == "kaiser":
        selected_count = int(np.count_nonzero(eigenvalues >= 1.0))
        if selected_count < 1:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "kaiser selection retained no components",
            )
    else:
        selected_count = int(
            np.searchsorted(cumulative_ratio, float(variance_threshold), side="left") + 1
        )
    selected_vectors = eigenvectors[:, :selected_count]
    selected_loadings = selected_vectors * np.sqrt(eigenvalues[:selected_count])
    result: dict[str, object] = {
        "matrix": matrix_name,
        "component_selection": selection,
        "selection_parameters": {
            "n_components": n_components,
            "variance_threshold": variance_threshold,
        },
        "n_components": selected_count,
        "component_numbers": list(range(1, selected_count + 1)),
        "eigenvalues": eigenvalues,
        "loadings": selected_loadings,
        "explained_variance_ratio": explained_ratio,
        "cumulative_explained_variance": cumulative_ratio,
        "scores_available": include_scores,
        "missing_policy": prepared.missing_policy,
        "retained_positions": list(prepared.retained_positions),
    }
    if include_scores:
        scores = working @ selected_vectors
        bounded_count = min(max_score_rows, n_observations)
        result["scores"] = scores[:bounded_count]
        result["scores_row_count"] = bounded_count
        result["scores_truncated"] = bounded_count < n_observations
    native_result = json_native(result)
    return make_result_envelope(
        operation_id="multivariate.pca",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        columns=prepared.columns,
        result=native_result,
    )


__all__ = ["PCA_COMPONENT_SELECTIONS", "PCA_MATRICES", "fit_pca"]
