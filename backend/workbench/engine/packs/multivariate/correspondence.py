"""Bounded correspondence analysis and indicator-CA MCA kernels."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native


MAX_CA_CATEGORIES = 100
MAX_CA_DIMENSIONS = 10
MAX_MCA_ROWS = 2000
MCA_MISSING_POLICIES = frozenset({"complete_case_v1"})


def _validate_dimensions(n_dimensions: int, *, maximum_rank: int) -> None:
    if type(n_dimensions) is not int or not 1 <= n_dimensions <= MAX_CA_DIMENSIONS:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_DIMENSIONS",
            f"n_dimensions must be an integer in [1, {MAX_CA_DIMENSIONS}]",
        )
    if n_dimensions > maximum_rank:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_DIMENSIONS",
            f"n_dimensions cannot exceed the positive table rank ({maximum_rank})",
        )


def _string_labels(labels: Sequence[Any], field_name: str) -> list[str]:
    if any(type(label) is not str or not label for label in labels):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_CATEGORY_LABEL", f"{field_name} labels must be non-empty strings"
        )
    normalized = list(labels)
    if len(set(normalized)) != len(normalized):
        raise MultivariatePackError(
            "MULTIVARIATE_DUPLICATE_CATEGORY_LABEL", f"{field_name} labels must be unique"
        )
    return normalized


def _stable_row_labels(labels: Sequence[Any]) -> list[str]:
    normalized: list[str] = []
    for label in labels:
        if type(label) is str:
            text = label
        else:
            text = f"{type(label).__name__}:{label}"
        if not text:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_CATEGORY_LABEL", "row labels must not be empty"
            )
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise MultivariatePackError(
            "MULTIVARIATE_DUPLICATE_CATEGORY_LABEL", "row labels must be unique after normalization"
        )
    return normalized


def _validate_contingency_values(table: pd.DataFrame) -> np.ndarray:
    if not isinstance(table, pd.DataFrame):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "correspondence table must be a pandas DataFrame"
        )
    if table.ndim != 2 or table.shape[0] < 2 or table.shape[1] < 2:
        raise MultivariatePackError(
            "MULTIVARIATE_TOO_FEW_CATEGORIES", "correspondence table must be at least 2 by 2"
        )
    for column in table.columns:
        dtype = table[column].dtype
        if (
            not pd.api.types.is_numeric_dtype(dtype)
            or pd.api.types.is_bool_dtype(dtype)
            or pd.api.types.is_complex_dtype(dtype)
        ):
            raise MultivariatePackError(
                "MULTIVARIATE_NON_NUMERIC_COLUMN",
                "correspondence table counts must be real numeric values",
            )
    try:
        values = table.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NON_NUMERIC_COLUMN", "correspondence table cannot be represented as numbers"
        ) from exc
    if not np.isfinite(values).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NON_FINITE_VALUE", "correspondence table contains NaN or infinity"
        )
    if (values < 0).any():
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_CATEGORY_TABLE", "correspondence counts cannot be negative"
        )
    total = float(values.sum())
    if not total > 0:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_CATEGORY_TABLE", "correspondence table total must be positive"
        )
    if (values.sum(axis=1) <= 0).any() or (values.sum(axis=0) <= 0).any():
        raise MultivariatePackError(
            "MULTIVARIATE_ZERO_MARGIN", "correspondence rows and columns must have positive mass"
        )
    if max(values.shape) > MAX_CA_CATEGORIES:
        raise MultivariatePackError(
            "MULTIVARIATE_CATEGORY_OVERFLOW",
            f"correspondence table dimensions cannot exceed {MAX_CA_CATEGORIES}",
        )
    return values


def _ca_payload(
    values: np.ndarray,
    *,
    row_labels: list[str],
    column_labels: list[str],
    n_dimensions: int,
    method: str,
    construction: str | None = None,
) -> dict[str, object]:
    row_count, column_count = values.shape
    maximum_rank = min(row_count - 1, column_count - 1)
    row_probability = values.sum(axis=1) / values.sum()
    column_probability = values.sum(axis=0) / values.sum()
    probability = values / values.sum()
    residual = probability - np.outer(row_probability, column_probability)
    standardized = residual / np.sqrt(np.outer(row_probability, column_probability))
    try:
        left, singular_values, right_transposed = np.linalg.svd(
            standardized, full_matrices=False
        )
    except np.linalg.LinAlgError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY", "correspondence SVD did not converge"
        ) from exc
    positive_rank = int(np.count_nonzero(singular_values > 1e-12))
    _validate_dimensions(n_dimensions, maximum_rank=min(maximum_rank, positive_rank))
    dimensions = slice(0, n_dimensions)
    selected_singular_values = singular_values[dimensions]
    eigenvalues = singular_values**2
    selected_eigenvalues = eigenvalues[dimensions]
    row_coordinates = left[:, dimensions] * selected_singular_values
    column_coordinates = right_transposed.T[:, dimensions] * selected_singular_values
    row_contribution_numerator = row_probability[:, None] * row_coordinates**2
    column_contribution_numerator = column_probability[:, None] * column_coordinates**2
    row_contributions = np.divide(
        row_contribution_numerator,
        selected_eigenvalues[None, :],
        out=np.zeros_like(row_contribution_numerator),
        where=selected_eigenvalues[None, :] > 1e-12,
    )
    column_contributions = np.divide(
        column_contribution_numerator,
        selected_eigenvalues[None, :],
        out=np.zeros_like(column_contribution_numerator),
        where=selected_eigenvalues[None, :] > 1e-12,
    )
    total_inertia = float(np.sum(eigenvalues))
    result: dict[str, object] = {
        "method": method,
        "source_shape": [row_count, column_count],
        "n_dimensions": n_dimensions,
        "rank": positive_rank,
        "row_labels": row_labels,
        "column_labels": column_labels,
        "row_masses": row_probability,
        "column_masses": column_probability,
        "singular_values": selected_singular_values,
        "inertia": selected_eigenvalues,
        "total_inertia": total_inertia,
        "explained_inertia_ratio": (
            selected_eigenvalues / total_inertia if total_inertia > 0 else np.zeros(n_dimensions)
        ),
        "row_principal_coordinates": row_coordinates,
        "column_principal_coordinates": column_coordinates,
        "row_contributions": row_contributions,
        "column_contributions": column_contributions,
        "label_policy": "string_identity_v1",
    }
    if construction is not None:
        result["construction"] = construction
    return result


def fit_correspondence(
    table: pd.DataFrame,
    *,
    n_dimensions: int,
) -> dict[str, object]:
    """Fit correspondence analysis to an explicit non-negative table."""

    values = _validate_contingency_values(table)
    row_labels = _stable_row_labels(list(table.index))
    column_labels = _string_labels(list(table.columns), "column")
    result = _ca_payload(
        values,
        row_labels=row_labels,
        column_labels=column_labels,
        n_dimensions=n_dimensions,
        method="ca",
    )
    return make_result_envelope(
        operation_id="multivariate.correspondence",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=table.shape[0],
        columns=column_labels,
        result=json_native(result),
    )


def _category_token(value: Any) -> tuple[str, str]:
    if isinstance(value, (list, tuple, dict, set)):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_CATEGORY", "category values must be scalar"
        )
    if isinstance(value, (float, np.floating)) and not np.isfinite(float(value)):
        raise MultivariatePackError(
            "MULTIVARIATE_NON_FINITE_VALUE", "category values must be finite"
        )
    return type(value).__name__, repr(value)


def fit_mca(
    frame: pd.DataFrame,
    *,
    columns: Sequence[str],
    n_dimensions: int,
    missing_policy: str = "complete_case_v1",
) -> dict[str, object]:
    """Fit MCA as explicitly labelled indicator-table correspondence analysis."""

    if not isinstance(frame, pd.DataFrame):
        raise MultivariatePackError("MULTIVARIATE_BAD_INPUT", "frame must be a pandas DataFrame")
    if isinstance(columns, (str, bytes)):
        raise MultivariatePackError("MULTIVARIATE_BAD_INPUT", "columns must be an array")
    selected_columns = list(columns)
    if len(selected_columns) < 2 or any(type(column) is not str or not column for column in selected_columns):
        raise MultivariatePackError(
            "MULTIVARIATE_TOO_FEW_COLUMNS", "MCA requires at least two non-empty columns"
        )
    if len(set(selected_columns)) != len(selected_columns):
        raise MultivariatePackError(
            "MULTIVARIATE_DUPLICATE_COLUMN", "MCA columns must be unique"
        )
    missing_columns = [column for column in selected_columns if column not in frame.columns]
    if missing_columns:
        raise MultivariatePackError(
            "MULTIVARIATE_MISSING_COLUMN", "unknown columns: " + ", ".join(missing_columns)
        )
    if missing_policy not in MCA_MISSING_POLICIES:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_MISSING_POLICY",
            "only complete_case_v1 is currently declared for MCA",
        )
    selected = frame.loc[:, selected_columns].copy()
    mask = selected.notna().all(axis=1)
    retained_positions = tuple(np.flatnonzero(mask.to_numpy()).tolist())
    complete = selected.loc[mask].reset_index(drop=True)
    if complete.empty:
        raise MultivariatePackError(
            "MULTIVARIATE_NO_COMPLETE_CASES", "no complete-case MCA observations remain"
        )
    if len(complete) > MAX_MCA_ROWS:
        raise MultivariatePackError(
            "MULTIVARIATE_OUTPUT_TOO_LARGE", f"MCA output is bounded at {MAX_MCA_ROWS} rows"
        )

    indicator_labels: list[str] = []
    encoded_columns: list[np.ndarray] = []
    category_counts: dict[str, int] = {}
    for column in selected_columns:
        values = list(complete[column])
        categories = sorted({_category_token(value) for value in values})
        category_counts[column] = len(categories)
        for type_name, representation in categories:
            display = representation
            if representation.startswith("'") and representation.endswith("'"):
                display = representation[1:-1]
            label = f"{column}={display}"
            indicator_labels.append(label)
            encoded_columns.append(
                np.asarray(
                    [
                        1.0 if _category_token(value) == (type_name, representation) else 0.0
                        for value in values
                    ]
                )
            )
    if len(indicator_labels) > MAX_CA_CATEGORIES:
        raise MultivariatePackError(
            "MULTIVARIATE_CATEGORY_OVERFLOW",
            f"MCA indicator categories cannot exceed {MAX_CA_CATEGORIES}",
        )
    indicator = np.column_stack(encoded_columns)
    result = _ca_payload(
        indicator,
        row_labels=[str(position) for position in retained_positions],
        column_labels=indicator_labels,
        n_dimensions=n_dimensions,
        method="mca",
        construction="indicator_ca",
    )
    result.update(
        {
            "indicator_columns": indicator_labels,
            "category_counts": category_counts,
            "n_observations": len(complete),
            "missing_policy": missing_policy,
            "retained_positions": list(retained_positions),
        }
    )
    return make_result_envelope(
        operation_id="multivariate.mca",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=len(complete),
        columns=selected_columns,
        result=json_native(result),
    )


__all__ = [
    "MAX_CA_CATEGORIES",
    "MAX_CA_DIMENSIONS",
    "MCA_MISSING_POLICIES",
    "fit_correspondence",
    "fit_mca",
]
