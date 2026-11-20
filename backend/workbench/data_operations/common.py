"""Parameter checks and row helpers shared by data operations."""

from __future__ import annotations

import difflib

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
import pandas as pd
from ..artifacts import (
    register_artifact,
    read_json,
    sha256_file,
    write_bytes_durable,
    write_json,
    write_text_durable,
)
from ..tabular_io import STATISTICAL_FORMATS, read_table
from ..graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from ..predictive_research.contracts import FeatureRecipeV1
from ..predictive_research.feature_recipe import apply_feature_recipe
from .specs import DataColumnCastSpecV1, DataColumnCastValidationError, SUBSET_FILTER_OPERATORS


def _transform_source_spec(run_id: str, node_id: str, artifact_id: str) -> DataColumnCastSpecV1:
    return DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id=node_id,
        source_artifact_id=artifact_id,
        column="__data_operation_source__",
        target_dtype="string",
    )


def _growth_policy(
    parameters: Mapping[str, Any],
    *,
    parameter_name: str,
    legacy_factor_name: str | None = None,
    default_factor: float = 3.0,
) -> tuple[int | None, float | None]:
    """Resolve an explicit row-growth policy without silently widening limits."""

    raw_policy = parameters.get(parameter_name)
    if raw_policy is None:
        if legacy_factor_name and legacy_factor_name in parameters:
            raw_policy = {"max_growth_factor": parameters[legacy_factor_name]}
        else:
            raw_policy = {"max_growth_factor": default_factor}
    if not isinstance(raw_policy, Mapping):
        raise DataColumnCastValidationError(f"{parameter_name} must be an object")
    unknown = set(raw_policy) - {"max_rows", "max_growth_factor"}
    if unknown:
        raise DataColumnCastValidationError(
            f"{parameter_name} contains unsupported fields: {sorted(unknown)}"
        )
    if not raw_policy:
        raise DataColumnCastValidationError(
            f"{parameter_name} must declare max_rows or max_growth_factor"
        )

    max_rows: int | None = None
    if "max_rows" in raw_policy:
        candidate = raw_policy["max_rows"]
        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
            raise DataColumnCastValidationError(
                f"{parameter_name}.max_rows must be a non-negative integer"
            )
        max_rows = candidate

    max_growth_factor: float | None = None
    if "max_growth_factor" in raw_policy:
        try:
            candidate = float(raw_policy["max_growth_factor"])
        except (TypeError, ValueError) as exc:
            raise DataColumnCastValidationError(
                f"{parameter_name}.max_growth_factor must be finite and positive"
            ) from exc
        if not math.isfinite(candidate) or candidate <= 0:
            raise DataColumnCastValidationError(
                f"{parameter_name}.max_growth_factor must be finite and positive"
            )
        max_growth_factor = candidate
    return max_rows, max_growth_factor


def _enforce_growth_policy(
    row_count: int,
    source_row_count: int,
    *,
    operation_code: str,
    growth_error_code: str | None = None,
    policy: tuple[int | None, float | None],
) -> None:
    max_rows, max_growth_factor = policy
    error_code = growth_error_code or f"{operation_code}_ROW_EXPANSION_BLOCKED"
    if max_rows is not None and row_count > max_rows:
        raise DataColumnCastValidationError(
            f"{error_code}; "
            f"next_step=lower the input rows or raise the explicit max_rows limit"
        )
    if max_growth_factor is not None and row_count > max(1, source_row_count) * max_growth_factor:
        raise DataColumnCastValidationError(
            f"{error_code}; "
            f"next_step=inspect key uniqueness or raise the explicit growth limit"
        )


def _schema_signature(frame: pd.DataFrame) -> tuple[tuple[str, str], ...]:
    return tuple((str(column), str(frame[column].dtype)) for column in frame.columns)


def _reject_unknown_parameters(
    parameters: Mapping[str, Any], allowed: set[str], operation: str
) -> None:
    unknown = set(parameters) - allowed
    if unknown:
        raise DataColumnCastValidationError(
            f"data.{operation} contains unsupported fields: {sorted(unknown)}"
        )


def _require_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataColumnCastValidationError(f"{name} must be a non-empty string")
    return value


def _require_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise DataColumnCastValidationError(f"{name} must be a non-empty list of strings")
    if len(set(value)) != len(value):
        raise DataColumnCastValidationError(f"{name} must not contain duplicates")
    return list(value)


def _require_columns_exist(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise DataColumnCastValidationError(f"{name} columns missing: {missing}")


def _require_nested_keys(
    value: Any,
    *,
    name: str,
    required: set[str],
    optional: set[str] = set(),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataColumnCastValidationError(f"{name} must be an object")
    allowed = required | optional
    unknown = set(value) - allowed
    if unknown:
        raise DataColumnCastValidationError(
            f"{name} contains unsupported fields: {sorted(unknown)}"
        )
    missing = required - set(value)
    if missing:
        raise DataColumnCastValidationError(
            f"{name} is missing required fields: {sorted(missing)}"
        )
    return value


def _require_present_values(series: pd.Series, values: list[Any], name: str) -> None:
    """A filter on a value the column does not hold keeps or drops nothing it meant to, without any sign of it."""
    absent = [value for value in values if not series.eq(value).any()]
    if not absent:
        return
    levels = series.dropna().astype(str).unique().tolist()
    close = [match for value in absent for match in difflib.get_close_matches(str(value), levels, n=3, cutoff=0.6)]
    hint = f" Closest values: {', '.join(dict.fromkeys(close))}." if close else (
        f" Values: {', '.join(levels[:20])}." if len(levels) <= 20 else "")
    raise DataColumnCastValidationError(
        f"{name}: column {series.name} has no value {', '.join(map(repr, absent))}, so this filter would select nothing "
        f"or leave every row in place.{hint}"
    )


def _subset_filter_mask(series: pd.Series, filter_spec: Mapping[str, Any], name: str) -> pd.Series:
    filter_keys = _require_nested_keys(
        filter_spec,
        name=name,
        required={"column", "op"},
        optional={"value"},
    )
    column = _require_non_empty_string(filter_keys["column"], f"{name}.column")
    operator = _require_non_empty_string(filter_keys["op"], f"{name}.op")
    if operator not in SUBSET_FILTER_OPERATORS:
        raise DataColumnCastValidationError(
            f"{name}.op must be one of: {', '.join(sorted(SUBSET_FILTER_OPERATORS))}"
        )
    has_value = "value" in filter_keys
    if operator in {"is_missing", "not_missing"}:
        if has_value:
            raise DataColumnCastValidationError(
                f"{name}.value is not allowed for {operator}"
            )
    elif not has_value:
        raise DataColumnCastValidationError(f"{name}.value is required for {operator}")

    value = filter_keys.get("value")
    try:
        if operator == "eq":
            _require_present_values(series, [value], name)
            mask = series.eq(value)
        elif operator == "ne":
            _require_present_values(series, [value], name)
            mask = series.notna() & series.ne(value)
        elif operator == "gt":
            mask = series.notna() & series.gt(value)
        elif operator == "ge":
            mask = series.notna() & series.ge(value)
        elif operator == "lt":
            mask = series.notna() & series.lt(value)
        elif operator == "le":
            mask = series.notna() & series.le(value)
        elif operator in {"in", "not_in"}:
            if not isinstance(value, list) or not value:
                raise DataColumnCastValidationError(
                    f"{name}.value must be a non-empty list for {operator}"
                )
            _require_present_values(series, value, name)
            mask = series.isin(value)
            if operator == "not_in":
                mask = series.notna() & ~mask
        elif operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise DataColumnCastValidationError(
                    f"{name}.value must contain exactly two bounds for between"
                )
            lower, upper = value
            if lower > upper:
                raise DataColumnCastValidationError(
                    f"{name}.value lower bound must not exceed upper bound"
                )
            mask = series.notna() & series.ge(lower) & series.le(upper)
        elif operator == "is_missing":
            mask = series.isna()
        else:
            mask = series.notna()
    except DataColumnCastValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise DataColumnCastValidationError(
            f"{name} could not be applied to column {column!r}: {exc}"
        ) from exc
    if not isinstance(mask, pd.Series):
        raise DataColumnCastValidationError(f"{name} did not produce a row mask")
    return mask.fillna(False).astype(bool)


def _recode_value(value: Any, name: str) -> Any:
    if value is None or isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return value
    raise DataColumnCastValidationError(f"{name} must be a finite number, a non-empty string or null")


def _recode_static_check(parameters: Mapping[str, Any]) -> tuple[str, str]:
    """The checks that need no data: shape of the parameters and rules."""

    _reject_unknown_parameters(parameters, {"column", "output", "rules"}, "recode")
    column = _require_non_empty_string(parameters.get("column"), "recode.column")
    output = _require_non_empty_string(parameters.get("output"), "recode.output")
    rules = parameters.get("rules")
    if not isinstance(rules, list) or not rules:
        raise DataColumnCastValidationError("recode.rules must be a non-empty list")
    for index, rule in enumerate(rules):
        parsed = _require_nested_keys(rule, name=f"recode.rules[{index}]", required={"from", "to"}, optional=set())
        if parsed["from"] == "else" and index != len(rules) - 1:
            raise DataColumnCastValidationError("recode: the else rule must come last")
        origin = parsed["from"]
        if isinstance(origin, Mapping):
            if set(origin) != {"low", "high"}:
                raise DataColumnCastValidationError(f"recode.rules[{index}].from range needs exactly low and high")
            low, high = origin["low"], origin["high"]
            if not all(isinstance(bound, (int, float)) and not isinstance(bound, bool) for bound in (low, high)) or low > high:
                raise DataColumnCastValidationError(f"recode.rules[{index}].from range must be numbers with low <= high")
        elif origin not in {"else", "missing"}:
            if _recode_value(origin, f"recode.rules[{index}].from") is None:
                raise DataColumnCastValidationError(f"recode.rules[{index}].from: use \"missing\" to match missing values")
        if parsed["to"] != "copy":
            _recode_value(parsed["to"], f"recode.rules[{index}].to")
    return column, output


def _recode_into_new_column(frame: pd.DataFrame, parameters: Mapping[str, Any]) -> pd.DataFrame:
    """SPSS RECODE ... INTO: map values and closed ranges of one column to codes.

    Rules apply in order and the first match wins; ranges include both ends;
    a missing source value stays missing unless a {"from": "missing"} rule
    maps it. Unlike SPSS, a non-missing value no rule covers is refused unless
    an {"from": "else"} rule says what it becomes, so a range with a gap
    cannot silently turn valid values into missing ones.
    """

    column, output = _recode_static_check(parameters)
    _require_columns_exist(frame, [column], "recode")
    if output in frame.columns:
        raise DataColumnCastValidationError(
            f"recode.output {output!r} already exists; choose a new variable name"
        )
    rules = parameters.get("rules")
    if not isinstance(rules, list) or not rules:
        raise DataColumnCastValidationError("recode.rules must be a non-empty list")
    source = frame[column]
    numeric = pd.api.types.is_numeric_dtype(source) and not pd.api.types.is_bool_dtype(source)
    result = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    assigned = pd.Series(False, index=frame.index)
    missing = source.isna()
    has_else = False
    for index, rule in enumerate(rules):
        parsed = _require_nested_keys(rule, name=f"recode.rules[{index}]", required={"from", "to"}, optional=set())
        target = parsed["to"]
        origin = parsed["from"]
        if origin == "else":
            if index != len(rules) - 1:
                raise DataColumnCastValidationError("recode: the else rule must come last")
            has_else = True
            mask = ~assigned & ~missing
        elif origin == "missing":
            mask = ~assigned & missing
        elif isinstance(origin, Mapping):
            if set(origin) != {"low", "high"}:
                raise DataColumnCastValidationError(f"recode.rules[{index}].from range needs exactly low and high")
            low, high = origin["low"], origin["high"]
            if not all(isinstance(bound, (int, float)) and not isinstance(bound, bool) for bound in (low, high)) or low > high:
                raise DataColumnCastValidationError(f"recode.rules[{index}].from range must be numbers with low <= high")
            if not numeric:
                raise DataColumnCastValidationError(f"recode: ranges need a numeric column; {column} is not")
            mask = ~assigned & source.between(low, high)
        else:
            value = _recode_value(origin, f"recode.rules[{index}].from")
            if value is None:
                raise DataColumnCastValidationError(f"recode.rules[{index}].from: use \"missing\" to match missing values")
            if numeric and isinstance(value, str):
                raise DataColumnCastValidationError(f"recode: {value!r} cannot match numeric column {column}")
            mask = ~assigned & (source == value if numeric else source.astype("string") == str(value))
        if target == "copy":
            result[mask] = source[mask]
        else:
            result[mask] = _recode_value(target, f"recode.rules[{index}].to")
        assigned |= mask.fillna(False)
    unmatched = int((~assigned & ~missing).sum())
    if unmatched and not has_else:
        examples = ", ".join(
            f"{value:.7g}" if isinstance(value, float) else str(value)
            for value in source[~assigned & ~missing].drop_duplicates().head(5)
        )
        raise DataColumnCastValidationError(
            f"recode: {unmatched} value(s) of {column} match no rule (e.g. {examples}); "
            'add rules for them or an {"from": "else"} rule saying what they become'
        )
    converted = pd.to_numeric(result, errors="coerce")
    all_numeric = converted.notna().sum() == result.notna().sum()
    out = frame.copy()
    out[output] = converted if all_numeric else result.astype("string")
    return out
