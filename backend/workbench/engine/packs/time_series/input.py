"""Strict time-series input preparation with explicit ordering semantics."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

from .errors import TimeSeriesPackError


TIME_ORDER_POLICIES = frozenset({"declared_monotonic", "sort_by_time"})


@dataclass(frozen=True)
class PreparedTimeSeries:
    frame: pd.DataFrame
    time_column: str
    value_columns: tuple[str, ...]
    n_input_rows: int
    n_observations: int
    retained_positions: tuple[int, ...]
    time_order: str
    inferred_frequency: None = None


def prepare_time_series(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_columns: Sequence[str],
    time_order: Literal["declared_monotonic", "sort_by_time"],
    missing_policy: str = "complete_case_v1",
) -> PreparedTimeSeries:
    if not isinstance(frame, pd.DataFrame):
        raise TimeSeriesPackError("TIME_SERIES_BAD_INPUT", "frame must be a pandas DataFrame")
    if time_order not in TIME_ORDER_POLICIES:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "time_order is not declared")
    if missing_policy != "complete_case_v1":
        raise TimeSeriesPackError(
            "TIME_SERIES_UNSUPPORTED_MISSING_POLICY",
            "only complete_case_v1 is declared",
        )
    if type(time_column) is not str or not time_column:
        raise TimeSeriesPackError("TIME_SERIES_BAD_INPUT", "time_column must be non-empty")
    if isinstance(value_columns, (str, bytes)):
        raise TimeSeriesPackError("TIME_SERIES_BAD_INPUT", "value_columns must be an array")
    values = list(value_columns)
    if len(values) < 1 or any(type(column) is not str or not column for column in values):
        raise TimeSeriesPackError("TIME_SERIES_BAD_INPUT", "value_columns must be non-empty names")
    if len(set(values)) != len(values) or time_column in values:
        raise TimeSeriesPackError("TIME_SERIES_BAD_INPUT", "time/value columns must be unique")
    missing = [column for column in [time_column, *values] if column not in frame.columns]
    if missing:
        raise TimeSeriesPackError("TIME_SERIES_MISSING_COLUMN", "unknown columns: " + ", ".join(missing))
    selected = frame.loc[:, [time_column, *values]].copy()
    for column in values:
        dtype = selected[column].dtype
        if (
            not pd.api.types.is_numeric_dtype(dtype)
            or pd.api.types.is_bool_dtype(dtype)
            or pd.api.types.is_complex_dtype(dtype)
        ):
            raise TimeSeriesPackError(
                "TIME_SERIES_NON_NUMERIC_VALUE", f"value column {column!r} is not real numeric"
            )
    mask = selected.notna().all(axis=1)
    retained_positions = tuple(np.flatnonzero(mask.to_numpy()).tolist())
    complete = selected.loc[mask].copy()
    if complete.empty:
        raise TimeSeriesPackError("TIME_SERIES_NO_COMPLETE_CASES", "no complete observations remain")
    try:
        numeric_values = complete.loc[:, values].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise TimeSeriesPackError(
            "TIME_SERIES_NON_NUMERIC_VALUE", "values cannot be represented as real numbers"
        ) from exc
    if not np.isfinite(numeric_values).all():
        raise TimeSeriesPackError(
            "TIME_SERIES_NON_FINITE_VALUE", "values contain NaN or infinity after filtering"
        )
    time_values = complete[time_column]
    if not (pd.api.types.is_numeric_dtype(time_values.dtype) or pd.api.types.is_datetime64_any_dtype(time_values.dtype)):
        raise TimeSeriesPackError(
            "TIME_SERIES_INVALID_TIME", "time must be numeric or datetime-like"
        )
    if pd.api.types.is_numeric_dtype(time_values.dtype):
        try:
            if not np.isfinite(time_values.to_numpy(dtype=float)).all():
                raise TimeSeriesPackError(
                    "TIME_SERIES_NON_FINITE_TIME", "time contains NaN or infinity"
                )
        except (TypeError, ValueError) as exc:
            raise TimeSeriesPackError(
                "TIME_SERIES_INVALID_TIME", "time cannot be represented as numeric values"
            ) from exc
    if time_order == "sort_by_time":
        complete = complete.sort_values(time_column, kind="mergesort").reset_index(drop=True)
    elif not time_values.is_monotonic_increasing or time_values.duplicated().any():
        raise TimeSeriesPackError(
            "TIME_SERIES_ORDER_INVALID", "declared_monotonic requires increasing unique time values"
        )
    sorted_time = complete[time_column]
    if not sorted_time.is_monotonic_increasing or sorted_time.duplicated().any():
        raise TimeSeriesPackError(
            "TIME_SERIES_ORDER_INVALID", "time values must be increasing and unique"
        )
    if len(complete) < 3:
        raise TimeSeriesPackError(
            "TIME_SERIES_TOO_FEW_OBSERVATIONS", "at least three observations are required"
        )
    normalized = pd.DataFrame(
        {time_column: complete[time_column].tolist()}
        | {column: numeric_values[:, index] for index, column in enumerate(values)}
    )
    if time_order == "sort_by_time":
        normalized = complete.reset_index(drop=True)
    return PreparedTimeSeries(
        frame=normalized,
        time_column=time_column,
        value_columns=tuple(values),
        n_input_rows=len(frame),
        n_observations=len(normalized),
        retained_positions=retained_positions,
        time_order=time_order,
    )


__all__ = ["PreparedTimeSeries", "TIME_ORDER_POLICIES", "prepare_time_series"]
