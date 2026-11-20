"""Typed, source-bound statistical exploration contracts. (compute)."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping
import numpy as np
import pandas as pd
from .statistical_exploration_spec import (
    ExplorationSpec,
    FilterSpec,
    GROUPABLE_OPERATIONS,
    SCHEMA_VERSION,
    STATA_QUANTILE_METHOD,
    StatisticalExplorationValidationError,
)


def execute_exploration(frame: Any, spec: ExplorationSpec) -> dict[str, Any]:
    """Execute one typed operation over an in-memory source frame."""
    _validate_frame(frame)
    filtered = _apply_filters(frame, spec.filters)
    base = {
        "schema_version": SCHEMA_VERSION,
        "operation": spec.operation,
        "filters": [item.to_dict() for item in spec.filters],
        "source_row_count": int(len(frame)),
        "filtered_row_count": int(len(filtered)),
    }

    # Grouping is a property of the request, not of one operation. Handling it
    # only inside `summarize` meant `summarize_detail` with group_by silently
    # returned ONE pooled summary: a complete-looking result that answered a
    # different question than the one asked. Dispatch it once, for every
    # operation that can express it, and refuse it where it cannot.
    group_by = spec.options.get("group_by")
    if group_by is not None:
        if spec.operation not in GROUPABLE_OPERATIONS:
            raise StatisticalExplorationValidationError(
                f"{spec.operation} does not support group_by; "
                "groupable operations are: " + ", ".join(sorted(GROUPABLE_OPERATIONS))
            )
        groups = _summarize_groups(
            frame,
            spec,
            group_by=group_by,
            group_values=spec.options.get("group_values"),
        )
        return {
            **base,
            "group_by": _require_column(frame, group_by),
            "groups": groups,
            # Group values are typed by hand.  A mistyped year matches no
            # row and otherwise produces a plausible-looking, entirely
            # empty group that reads as a real result.
            "empty_group_values": [
                group["value"] for group in groups if group["filtered_row_count"] == 0
            ],
        }

    if spec.operation == "summarize":
        numeric, skipped = _split_numeric(filtered, spec.selected_columns)
        return {
            **base,
            "missing_policy": "variablewise",
            "variables": _summary_variables(filtered, tuple(numeric)),
            **({"non_numeric_columns": skipped} if skipped else {}),
        }

    if spec.operation == "summarize_detail":
        quantile_method = _quantile_method(spec.options)
        numeric, skipped = _split_numeric(filtered, spec.selected_columns)
        return {
            **base,
            "missing_policy": "variablewise",
            "quantile_method": quantile_method,
            "variables": _detail_variables(filtered, tuple(numeric), spec.options),
            **({"non_numeric_columns": skipped} if skipped else {}),
        }

    if spec.operation == "tabulate":
        weights = None
        if (column := spec.options.get('frequency_weight')) is not None:
            column = _require_column(frame, column)
            counts = filtered[column]
            if not pd.api.types.is_numeric_dtype(counts) or pd.api.types.is_bool_dtype(counts):
                raise StatisticalExplorationValidationError('frequency weights must be finite nonnegative integer counts')
            import numpy as np
            values = counts.to_numpy(dtype=float, na_value=np.nan)
            if (not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any()
                    or not 0 < values.sum() <= 2 ** 53):
                raise StatisticalExplorationValidationError('frequency weights must be finite nonnegative integer counts with positive total at most 2^53')
            weights = counts.astype('int64')
            if weights.sum() > 2 ** 53:
                raise StatisticalExplorationValidationError('frequency total exceeds the exact-count limit 2^53')
        result = {**base, "missing_policy": "variablewise", **_frequency_tables(filtered, spec.selected_columns, weights)}
        if weights is not None:
            result.update(frequency_weight=column, weighted_count=int(weights.sum()),
                          observation_unit='represented individuals; source_row_count counts stored rows')
        return result

    if spec.operation == "misstable":
        columns = _selected_columns(frame, spec.selected_columns)
        return {
            **base,
            "missing_policy": "variablewise",
            "variables": {
                column: {
                    "missing": int(filtered[column].isna().sum()),
                    "nonmissing": int(filtered[column].notna().sum()),
                }
                for column in columns
            },
        }

    if spec.operation == "corr":
        return _correlation_result(base, filtered, spec.selected_columns, spec.options)

    if spec.operation == "derive_boolean":
        return {
            **base,
            "missing_policy": "variablewise",
            "derived": _derived_boolean_result(filtered, spec),
        }

    if spec.operation == "scatter":
        x_column, y_column = _scatter_columns(frame, spec)
        aligned = pd.concat(
            [
                pd.to_numeric(filtered[x_column], errors="coerce").rename("x"),
                pd.to_numeric(filtered[y_column], errors="coerce").rename("y"),
            ],
            axis=1,
        ).dropna()
        return {
            **base,
            "missing_policy": "complete_case_for_plot",
            "plot": {
                "x_column": x_column,
                "y_column": y_column,
                "plotted_row_count": int(len(aligned)),
            },
        }

    raise StatisticalExplorationValidationError(
        f"exploration operation is not implemented: {spec.operation}"
    )


def _scatter_columns(frame: pd.DataFrame, spec: ExplorationSpec) -> tuple[str, str]:
    x_column = spec.options.get("x_column")
    y_column = spec.options.get("y_column")
    if not isinstance(x_column, str) or not isinstance(y_column, str):
        raise StatisticalExplorationValidationError(
            "scatter requires x_column and y_column"
        )
    for column in (x_column, y_column):
        _require_column(frame, column)
        if not pd.api.types.is_numeric_dtype(frame[column]):
            raise StatisticalExplorationValidationError(
                f"scatter column must be numeric: {column}"
            )
    if x_column == y_column:
        raise StatisticalExplorationValidationError("scatter x_column and y_column must differ")
    return x_column, y_column


def _validate_frame(frame: Any) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise StatisticalExplorationValidationError("source frame must be a pandas DataFrame")


def _require_column(frame: pd.DataFrame, column: Any) -> str:
    if not isinstance(column, str) or column not in frame.columns:
        raise StatisticalExplorationValidationError(
            f"source column was not found: {column}"
        )
    return column


def _selected_columns(frame: pd.DataFrame, selected: tuple[str, ...]) -> list[str]:
    columns = list(selected) if selected else list(frame.columns)
    for column in columns:
        _require_column(frame, column)
    return columns


def _split_numeric(frame: pd.DataFrame, selected: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Numeric columns to summarise, and the others, reported rather than refused.

    A mean of a text column does not exist; like Stata's summarize, such a
    column is left out -- but named in the result, and a request with no
    numeric column at all is refused with where to go instead.
    """

    columns = _selected_columns(frame, selected)
    numeric = [
        column for column in columns
        if pd.api.types.is_numeric_dtype(frame[column]) and not pd.api.types.is_bool_dtype(frame[column])
    ]
    skipped = [column for column in columns if column not in numeric]
    if not numeric:
        raise StatisticalExplorationValidationError(
            "no numeric columns to summarize ("
            + ", ".join(skipped)
            + "); use tabulate for frequency tables of categorical variables"
        )
    return numeric, skipped


MAX_TABULATE_VALUES = 100


def _frequency_tables(frame: pd.DataFrame, selected: tuple[str, ...], weights=None) -> dict[str, Any]:
    """Frequencies per value (SPSS FREQUENCIES / Stata tabulate), any column type."""

    columns = _selected_columns(frame, selected)
    variables: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for column in columns:
        series = frame[column]
        valid = series.dropna()
        if weights is None:
            counts = valid.value_counts(sort=True)
            total, valid_count, missing_count = len(series), len(valid), int(series.isna().sum())
        else:
            counts = weights[series.notna()].groupby(valid, observed=True, sort=False).sum()
            counts = counts[counts > 0].sort_values(ascending=False, kind='stable')
            total = int(weights.sum())
            valid_count = int(weights[series.notna()].sum())
            missing_count = total - valid_count
        shown = counts.head(MAX_TABULATE_VALUES)
        variables[column] = {
            "obs": int(total),
            "valid": int(valid_count),
            "missing": int(missing_count),
            "distinct": int(len(counts)),
            "truncated": bool(len(counts) > MAX_TABULATE_VALUES),
        }
        for value, count in shown.items():
            rows.append(
                {
                    "variable": column,
                    "value": value.item() if hasattr(value, "item") else value,
                    "count": int(count),
                    "percent": _safe_number(100.0 * count / total) if total else None,
                    "valid_percent": _safe_number(100.0 * count / valid_count) if valid_count else None,
                }
            )
        if variables[column]["missing"]:
            rows.append(
                {
                    "variable": column,
                    "value": None,
                    "count": variables[column]["missing"],
                    "percent": _safe_number(100.0 * variables[column]["missing"] / total),
                    "valid_percent": None,
                }
            )
    return {"variables": variables, "rows": rows}


def _numeric_columns(frame: pd.DataFrame, selected: tuple[str, ...]) -> list[str]:
    columns = _selected_columns(frame, selected)
    invalid = [column for column in columns if not pd.api.types.is_numeric_dtype(frame[column])]
    if invalid:
        raise StatisticalExplorationValidationError(
            "statistical operation requires numeric columns: " + ", ".join(invalid)
        )
    return columns


def _apply_filters(frame: pd.DataFrame, filters: tuple[FilterSpec, ...]) -> pd.DataFrame:
    mask = pd.Series(True, index=frame.index)
    for item in filters:
        column = _require_column(frame, item.column)
        series = frame[column]
        _validate_filter_value(series, item)
        try:
            if item.operator == "eq":
                current = series.eq(item.value)
            elif item.operator == "neq":
                current = series.ne(item.value)
            elif item.operator == "lt":
                current = series.lt(item.value)
            elif item.operator == "lte":
                current = series.le(item.value)
            elif item.operator == "gt":
                current = series.gt(item.value)
            elif item.operator == "gte":
                current = series.ge(item.value)
            elif item.operator == "between":
                current = series.ge(item.value[0]) & series.le(item.value[1])
            elif item.operator == "in":
                current = series.isin(item.value)
            else:
                current = series.notna() & ~series.isin(item.value)
        except (TypeError, ValueError) as exc:
            raise StatisticalExplorationValidationError(
                f"filter value is incompatible with column: {item.column}"
            ) from exc
        mask &= series.notna() & current.fillna(False)
    return frame.loc[mask]


def _validate_filter_value(series: pd.Series, item: FilterSpec) -> None:
    if not pd.api.types.is_bool_dtype(series):
        return
    values = item.value if item.operator in {"in", "not_in", "between"} else [item.value]
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(value, bool) and type(value).__name__ != "bool_" for value in values
    ):
        raise StatisticalExplorationValidationError(
            f"boolean filter requires boolean value: {item.column}"
        )


def _safe_number(value: Any) -> int | float | None:
    if value is None or pd.isna(value):
        return None
    converted = value.item() if hasattr(value, "item") else value
    if isinstance(converted, bool):
        return int(converted)
    if isinstance(converted, int):
        return int(converted)
    if isinstance(converted, float):
        return float(converted)
    return float(converted)


def _summary_variables(frame: pd.DataFrame, selected: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    columns = _numeric_columns(frame, selected)
    summaries: dict[str, dict[str, Any]] = {}
    for column in columns:
        series = frame[column].dropna()
        summaries[column] = {
            "obs": int(series.size),
            "mean": _safe_number(series.mean()),
            "std_dev": _safe_number(series.std(ddof=1)),
            "min": _safe_number(series.min()),
            "max": _safe_number(series.max()),
        }
    return summaries


def _quantile_method(options: Mapping[str, Any]) -> str:
    method = options.get("quantile_method", STATA_QUANTILE_METHOD)
    if method != STATA_QUANTILE_METHOD:
        raise StatisticalExplorationValidationError(
            f"quantile method is unsupported: {method}"
        )
    return STATA_QUANTILE_METHOD


def _sorted_floats(series: pd.Series) -> np.ndarray | list[float]:
    """The column's nonmissing values as floats in ``sorted()`` order.

    ``summarize, detail`` sorted the whole column as Python floats once per
    percentile: 27 sorts of 1,000,000 values, 3 of 3.2 s. A stable NumPy sort
    uses the same ``<`` and keeps equal values in input order, so the sequence
    is the same, -0.0 and 0.0 included. Other dtypes and NaN keep the old sort.
    """
    complete = series.dropna()
    if getattr(complete.dtype, "kind", None) not in ("b", "i", "u", "f"):
        return sorted(float(value) for value in complete.tolist())
    values = complete.to_numpy(dtype=float)
    if np.isnan(values).any():
        return sorted(float(value) for value in complete.tolist())
    negative_zero = bool(np.any((values == 0.0) & np.signbit(values)))
    return np.sort(values, kind="stable" if negative_zero else "quicksort")


def _stata_percentile(series: pd.Series, percentile: float) -> float | None:
    return _percentile_of_sorted(_sorted_floats(series), percentile)


def _percentile_of_sorted(values: np.ndarray | list[float], percentile: float) -> float | None:
    if len(values) == 0:
        return None
    if percentile <= 0:
        return float(values[0])
    if percentile >= 100:
        return float(values[-1])
    position = len(values) * float(percentile) / 100.0
    if math.isclose(position, round(position), rel_tol=0.0, abs_tol=1e-12):
        index = int(round(position))
        return (float(values[index - 1]) + float(values[index])) / 2.0
    return float(values[math.ceil(position) - 1])


def _detail_variables(
    frame: pd.DataFrame,
    selected: tuple[str, ...],
    options: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    columns = _numeric_columns(frame, selected)
    percentiles = (1, 5, 10, 25, 50, 75, 90, 95, 99)
    quantile_method = _quantile_method(options or {})
    details: dict[str, dict[str, Any]] = {}
    for column, summary in _summary_variables(frame, tuple(columns)).items():
        series = frame[column].dropna().astype(float)
        ordered = _sorted_floats(series)
        details[column] = {
            **summary,
            **_stata_moments(series),
            "smallest": [_safe_number(value) for value in series.nsmallest(4).tolist()],
            "largest": [_safe_number(value) for value in series.nlargest(4).sort_values().tolist()],
            "quantile_method": quantile_method,
            "percentiles": {
                f"p{percentile}": _safe_number(_percentile_of_sorted(ordered, percentile))
                for percentile in percentiles
            },
        }
    return details


def _stata_moments(series: pd.Series) -> dict[str, Any]:
    """Variance, sum, skewness and kurtosis as ``summarize, detail`` reports them.

    Skewness and kurtosis use population moments (m3/m2^1.5 and m4/m2^2, not
    bias-corrected), so a normal variable has kurtosis near 3, as in Stata.
    """

    n = int(series.size)
    if n == 0:
        return {"variance": None, "sum": None, "skewness": None, "kurtosis": None}
    deviations = series - series.mean()
    m2 = float((deviations**2).mean())
    return {
        "variance": _safe_number(series.var(ddof=1)) if n > 1 else None,
        "sum": _safe_number(series.sum()),
        "skewness": _safe_number(float((deviations**3).mean()) / m2**1.5) if m2 > 0 else None,
        "kurtosis": _safe_number(float((deviations**4).mean()) / m2**2) if m2 > 0 else None,
    }


def _summarize_groups(
    frame: pd.DataFrame,
    spec: ExplorationSpec,
    *,
    group_by: Any,
    group_values: Any,
) -> list[dict[str, Any]]:
    if group_values is None:
        # "Group by year" means every year the column has, and a missing year is
        # a group of its own: the by-group combinator plans them (sorted, the
        # missing group last, at most 50), so every capability groups alike.
        from .combinators.by_group import ByGroupRefusal, plan_groups

        column = _require_column(frame, group_by)
        try:
            planned = plan_groups(frame, column)
        except ByGroupRefusal as refusal:
            raise StatisticalExplorationValidationError(refusal.message) from refusal
        base_spec = ExplorationSpec(
            operation=spec.operation,
            selected_columns=spec.selected_columns,
            filters=spec.filters,
            options={key: item for key, item in spec.options.items() if key not in {"group_by", "group_values"}},
        )
        groups = []
        for group in planned:
            result = execute_exploration(frame.loc[group.mask], base_spec)
            carried = {
                key: item
                for key, item in result.items()
                if key not in {"schema_version", "operation", "source_row_count"}
            }
            groups.append({"value": group.value if group.value is not None else group.key,
                           **({"missing_group": True} if group.value is None else {}), **carried})
        return groups
    if not isinstance(group_values, (list, tuple)) or not group_values:
        raise StatisticalExplorationValidationError(
            "group_values must be a non-empty list when group_by is set"
        )
    groups: list[dict[str, Any]] = []
    for value in group_values:
        group_filter = FilterSpec(column=group_by, operator="eq", value=value)
        group_spec = ExplorationSpec(
            # Each group runs the operation that was actually asked for. Pinning
            # this to "summarize" silently downgraded a grouped summarize_detail.
            operation=spec.operation,
            selected_columns=spec.selected_columns,
            filters=(*spec.filters, group_filter),
            options={key: item for key, item in spec.options.items() if key not in {"group_by", "group_values"}},
        )
        result = execute_exploration(frame, group_spec)
        # Carry the whole per-group result through: summarize_detail adds
        # percentiles and quantile_method, misstable reports different counts.
        # Naming the keys here would drop whatever a groupable operation adds.
        carried = {
            key: item
            for key, item in result.items()
            if key not in {"schema_version", "operation", "source_row_count"}
        }
        groups.append({"value": value, **carried})
    return groups


def _correlation_result(
    base: dict[str, Any],
    frame: pd.DataFrame,
    selected: tuple[str, ...],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    missing_policy = options.get("missing_policy", "listwise")
    if missing_policy != "listwise":
        raise StatisticalExplorationValidationError(
            "corr supports only listwise missing_policy"
        )
    columns = _numeric_columns(frame, selected)
    complete = frame[columns].dropna(how="any")
    matrix = complete.corr().to_numpy().tolist()
    safe_matrix = [[_safe_number(value) for value in row] for row in matrix]
    correlation_n = int(len(complete))
    # The matrix stays authoritative, but a nested array carries no names: a
    # reader asking "which variable correlates most with spending" cannot align
    # an unlabelled row index against a separate column list.  ``pairs`` is the
    # labelled projection every presentation surface renders.
    pairs = [
        {
            "a": columns[i],
            "b": columns[j],
            "r": safe_matrix[i][j],
            "n": correlation_n,
        }
        for i in range(len(columns))
        for j in range(i + 1, len(columns))
    ]
    return {
        **base,
        "missing_policy": missing_policy,
        "variables": columns,
        "correlation_n": correlation_n,
        "matrix": safe_matrix,
        "pairs": pairs,
    }


def _derived_definition(spec: ExplorationSpec) -> tuple[str, float, str, str]:
    source_column = spec.options.get("source_column")
    if source_column is None and len(spec.selected_columns) == 1:
        source_column = spec.selected_columns[0]
    percentile = spec.options.get("percentile")
    comparison = spec.options.get("comparison")
    output_name = spec.options.get("output_name")
    if not isinstance(source_column, str) or not source_column.strip():
        raise StatisticalExplorationValidationError(
            "derive_boolean requires a source_column"
        )
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)) or not 0 <= percentile <= 100:
        raise StatisticalExplorationValidationError(
            "derive_boolean percentile must be between 0 and 100"
        )
    if comparison not in {"lte", "gte"}:
        raise StatisticalExplorationValidationError(
            "derive_boolean comparison must be lte or gte"
        )
    if not isinstance(output_name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", output_name) is None:
        raise StatisticalExplorationValidationError(
            "derive_boolean output_name must be a valid column name"
        )
    return source_column, float(percentile), comparison, output_name


def _derived_boolean_series(
    frame: pd.DataFrame,
    spec: ExplorationSpec,
) -> tuple[pd.Series, dict[str, Any]]:
    source_column, percentile, comparison, output_name = _derived_definition(spec)
    _require_column(frame, source_column)
    if not pd.api.types.is_numeric_dtype(frame[source_column]):
        raise StatisticalExplorationValidationError(
            f"derive_boolean source column must be numeric: {source_column}"
        )
    source = frame[source_column]
    complete = source.dropna()
    if complete.empty:
        raise StatisticalExplorationValidationError(
            f"derive_boolean source column has no nonmissing values: {source_column}"
        )
    threshold_value = _stata_percentile(complete, percentile)
    if threshold_value is None:
        raise StatisticalExplorationValidationError(
            f"derive_boolean source column has no nonmissing values: {source_column}"
        )
    threshold = float(threshold_value)
    derived = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    if comparison == "lte":
        derived.loc[source.notna()] = source.loc[source.notna()] <= threshold
    else:
        derived.loc[source.notna()] = source.loc[source.notna()] >= threshold
    counts = {
        "true": int((derived == True).sum()),  # noqa: E712
        "false": int((derived == False).sum()),  # noqa: E712
        "missing": int(derived.isna().sum()),
    }
    definition = {
        "source_column": source_column,
        "percentile": percentile,
        "comparison": comparison,
        "output_name": output_name,
        "threshold": threshold,
        "quantile_method": STATA_QUANTILE_METHOD,
        "counts": counts,
        "preview": [None if pd.isna(value) else bool(value) for value in derived.tolist()[:20]],
    }
    return derived, definition


def _derived_boolean_result(frame: pd.DataFrame, spec: ExplorationSpec) -> dict[str, Any]:
    _derived, definition = _derived_boolean_series(frame, spec)
    return definition
