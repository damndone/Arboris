"""Shared, fail-closed numeric input preparation for multivariate kernels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class MultivariatePackError(ValueError):
    """A stable, machine-readable multivariate input or option failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class PreparedNumericFrame:
    """A copied complete-case numeric frame plus deterministic row provenance."""

    frame: pd.DataFrame
    columns: tuple[str, ...]
    n_input_rows: int
    n_observations: int
    retained_positions: tuple[int, ...]
    missing_policy: str


def _validate_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    if len(columns) < 2:
        raise MultivariatePackError(
            "MULTIVARIATE_TOO_FEW_COLUMNS", "at least two columns are required"
        )
    if any(type(column) is not str or not column for column in columns):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be non-empty strings"
        )
    if len(set(columns)) != len(columns):
        raise MultivariatePackError(
            "MULTIVARIATE_DUPLICATE_COLUMN", "columns must not contain duplicates"
        )
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise MultivariatePackError(
            "MULTIVARIATE_MISSING_COLUMN", "unknown columns: " + ", ".join(missing)
        )


def prepare_numeric_frame(
    frame: pd.DataFrame,
    columns: list[str] | tuple[str, ...],
    *,
    missing_policy: str = "complete_case_v1",
) -> PreparedNumericFrame:
    """Validate, select, and complete-case filter numeric columns.

    No strings are parsed and no missing-data policy is inferred.  The returned
    frame has a fresh positional index so every kernel sees the same stable
    observation order, while ``retained_positions`` preserves the source-row
    identity without exposing raw rows in a result envelope.
    """

    if not isinstance(frame, pd.DataFrame):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "frame must be a pandas DataFrame"
        )
    if missing_policy != "complete_case_v1":
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_MISSING_POLICY",
            "only complete_case_v1 is currently declared",
        )
    if isinstance(columns, (str, bytes)):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be an array of column names"
        )
    try:
        normalized_columns = list(columns)
    except TypeError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "columns must be an array of column names"
        ) from exc
    _validate_columns(frame, normalized_columns)

    selected = frame.loc[:, normalized_columns].copy()
    for column in normalized_columns:
        dtype = selected[column].dtype
        if not pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_bool_dtype(dtype):
            raise MultivariatePackError(
                "MULTIVARIATE_NON_NUMERIC_COLUMN",
                f"column {column!r} is not a real numeric column",
            )
        if pd.api.types.is_complex_dtype(dtype):
            raise MultivariatePackError(
                "MULTIVARIATE_NON_NUMERIC_COLUMN",
                f"column {column!r} is complex-valued",
            )

    complete_mask = selected.notna().all(axis=1)
    retained_positions = tuple(np.flatnonzero(complete_mask.to_numpy()).tolist())
    complete = selected.loc[complete_mask]
    if complete.empty:
        raise MultivariatePackError(
            "MULTIVARIATE_NO_COMPLETE_CASES", "no complete-case observations remain"
        )
    try:
        numeric_values = complete.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NON_NUMERIC_COLUMN", "selected columns cannot be represented as real numbers"
        ) from exc
    if not np.isfinite(numeric_values).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NON_FINITE_VALUE",
            "complete-case data contains NaN or infinite values",
        )
    if len(complete) < 2:
        raise MultivariatePackError(
            "MULTIVARIATE_TOO_FEW_OBSERVATIONS",
            "at least two complete-case observations are required",
        )

    normalized_frame = pd.DataFrame(
        numeric_values,
        columns=normalized_columns,
    )
    return PreparedNumericFrame(
        frame=normalized_frame,
        columns=tuple(normalized_columns),
        n_input_rows=len(frame),
        n_observations=len(normalized_frame),
        retained_positions=retained_positions,
        missing_policy=missing_policy,
    )


def json_native(value: Any) -> Any:
    """Convert finite NumPy/pandas scalars and arrays to JSON-shaped values."""

    if isinstance(value, np.ndarray):
        return [json_native(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        if not np.isfinite(number):
            raise MultivariatePackError(
                "MULTIVARIATE_NON_FINITE_VALUE", "result contains a non-finite number"
            )
        return number
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise MultivariatePackError(
                "MULTIVARIATE_BAD_INPUT", "result mapping keys must already be strings"
            )
        return {key: json_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        raise MultivariatePackError(
            "MULTIVARIATE_NON_FINITE_VALUE", "result contains a non-finite number"
        )
    return value


__all__ = [
    "MultivariatePackError",
    "PreparedNumericFrame",
    "json_native",
    "prepare_numeric_frame",
]
