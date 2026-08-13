"""Typed, preview-first data operations for the V11 vertical slice."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

import pandas as pd

from .artifacts import (
    register_artifact,
    read_json,
    sha256_file,
    write_bytes_durable,
    write_json,
    write_text_durable,
)
from .graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from .predictive_research.contracts import FeatureRecipeV1
from .predictive_research.feature_recipe import apply_feature_recipe

DataCastTarget = Literal["numeric", "string", "datetime"]
ALLOWED_CAST_TARGETS = frozenset({"numeric", "string", "datetime"})

DataCastOutputFormat = Literal["csv", "xlsx"]
ALLOWED_OUTPUT_FORMATS = frozenset({"csv", "xlsx"})
_SCHEMA_SIDECAR_SUFFIX = ".schema.json"


class DataColumnCastValidationError(ValueError):
    """Raised when a typed cast cannot be resolved or safely previewed."""


@dataclass(frozen=True)
class FeatureRecipeOperationSpecV1:
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    recipe: FeatureRecipeV1
    operation_id: str = "data.feature_recipe"
    operation_version: str = "v1"

    def __post_init__(self) -> None:
        for field_name in ("source_run_id", "source_node_id", "source_artifact_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.recipe, FeatureRecipeV1):
            raise TypeError("recipe must be a FeatureRecipeV1")
        self.recipe.validate()
        if self.recipe.source_artifact != self.source_artifact_id:
            raise ValueError("recipe source_artifact must match source_artifact_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
            "recipe": self.recipe.to_dict(),
        }


@dataclass(frozen=True)
class FeatureRecipePreview:
    spec: FeatureRecipeOperationSpecV1
    source_sha256: str
    row_count: int
    input_columns: tuple[str, ...]
    output_columns: tuple[str, ...]
    schema_fingerprint_before: str
    schema_fingerprint_after: str
    fingerprint: str
    downstream_invalidation: tuple[str, ...] = ()
    status: str = "ready"
    reason: str | None = None
    next_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.spec.operation_id,
            "operation_version": self.spec.operation_version,
            "source_run_id": self.spec.source_run_id,
            "source_node_id": self.spec.source_node_id,
            "source_artifact_id": self.spec.source_artifact_id,
            "recipe": self.spec.recipe.to_dict(),
            "source_sha256": self.source_sha256,
            "row_count": self.row_count,
            "input_columns": list(self.input_columns),
            "output_columns": list(self.output_columns),
            "schema_fingerprint_before": self.schema_fingerprint_before,
            "schema_fingerprint_after": self.schema_fingerprint_after,
            "fingerprint": self.fingerprint,
            "downstream_invalidation": list(self.downstream_invalidation),
            "status": self.status,
            "reason": self.reason,
            "next_step": self.next_step,
        }


@dataclass(frozen=True)
class FeatureRecipeEffect:
    execution_key: str
    artifact_id: str
    artifact_path: str
    recipe_artifact_id: str
    recipe_path: str
    child_node_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
        }


DataTransformOperation = Literal[
    "merge",
    "append",
    "reshape",
    "subset",
    "dedupe",
    "rename",
    "aggregate",
    "fill_missing",
    "tsset",
    "lag",
]
ALLOWED_DATA_TRANSFORM_OPERATIONS = frozenset(
    {
        "merge",
        "append",
        "reshape",
        "subset",
        "dedupe",
        "rename",
        "aggregate",
        "fill_missing",
        "tsset",
        "lag",
    }
)
SUBSET_FILTER_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "gt",
        "ge",
        "lt",
        "le",
        "in",
        "not_in",
        "between",
        "is_missing",
        "not_missing",
    }
)
AGGREGATE_FUNCTIONS = frozenset(
    {"sum", "mean", "median", "min", "max", "count", "std"}
)
FILL_MISSING_STRATEGIES = frozenset(
    {"drop_rows", "constant", "mean", "median", "mode"}
)
TSSET_FREQUENCIES = frozenset({"D", "W", "M", "Q", "Y"})


@dataclass(frozen=True)
class DataTransformSpecV1:
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    operation: DataTransformOperation
    parameters: Mapping[str, Any] = field(default_factory=dict)
    secondary_run_id: str | None = None
    secondary_node_id: str | None = None
    secondary_artifact_id: str | None = None
    operation_version: str = "v1"

    def __post_init__(self) -> None:
        for field_name in ("source_run_id", "source_node_id", "source_artifact_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.operation not in ALLOWED_DATA_TRANSFORM_OPERATIONS:
            raise DataColumnCastValidationError(
                "operation must be one of: "
                + ", ".join(sorted(ALLOWED_DATA_TRANSFORM_OPERATIONS))
            )
        if self.operation in {"merge", "append"}:
            if not all((self.secondary_run_id, self.secondary_node_id, self.secondary_artifact_id)):
                raise ValueError(f"{self.operation} requires a secondary source artifact")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": f"data.{self.operation}",
            "operation_version": self.operation_version,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
            "secondary_run_id": self.secondary_run_id,
            "secondary_node_id": self.secondary_node_id,
            "secondary_artifact_id": self.secondary_artifact_id,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class DataTransformPreview:
    spec: DataTransformSpecV1
    source_sha256: str
    secondary_source_sha256: str | None
    row_count_before: int
    row_count_after: int
    input_columns: tuple[str, ...]
    output_columns: tuple[str, ...]
    schema_fingerprint_before: str
    schema_fingerprint_after: str
    fingerprint: str
    downstream_invalidation: tuple[str, ...] = ()
    status: str = "ready"
    reason: str | None = None
    next_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.spec.to_dict(),
            "source_sha256": self.source_sha256,
            "secondary_source_sha256": self.secondary_source_sha256,
            "row_count_before": self.row_count_before,
            "row_count_after": self.row_count_after,
            "input_columns": list(self.input_columns),
            "output_columns": list(self.output_columns),
            "schema_fingerprint_before": self.schema_fingerprint_before,
            "schema_fingerprint_after": self.schema_fingerprint_after,
            "fingerprint": self.fingerprint,
            "downstream_invalidation": list(self.downstream_invalidation),
            "status": self.status,
            "reason": self.reason,
            "next_step": self.next_step,
        }


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
            mask = series.eq(value)
        elif operator == "ne":
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


def _execute_data_transform(
    left: pd.DataFrame,
    spec: DataTransformSpecV1,
    right: pd.DataFrame | None,
) -> pd.DataFrame:
    parameters = dict(spec.parameters)
    if spec.operation == "append":
        _reject_unknown_parameters(
            parameters, {"schema_policy", "row_growth_policy", "max_growth_factor"}, "append"
        )
        if right is None:
            raise DataColumnCastValidationError("append requires a secondary frame")
        schema_policy = parameters.get("schema_policy", "exact")
        if not isinstance(schema_policy, str) or schema_policy not in {"exact", "union"}:
            raise DataColumnCastValidationError(
                "append schema_policy must be exact or union"
            )
        if schema_policy == "exact" and _schema_signature(left) != _schema_signature(right):
            raise DataColumnCastValidationError(
                "DATA_APPEND_SCHEMA_INCOMPATIBLE; "
                "next_step=choose schema_policy=union or align columns and dtypes"
            )
        output = pd.concat([left, right], ignore_index=True, sort=False)
        _enforce_growth_policy(
            len(output),
            len(left),
            operation_code="DATA_APPEND",
            growth_error_code="DATA_APPEND_ROW_GROWTH_BLOCKED",
            policy=_growth_policy(
                parameters,
                parameter_name="row_growth_policy",
                legacy_factor_name="max_growth_factor",
            ),
        )
        return output
    if spec.operation == "merge":
        _reject_unknown_parameters(
            parameters,
            {"keys", "how", "indicator", "growth_policy", "max_growth_factor"},
            "merge",
        )
        if right is None:
            raise DataColumnCastValidationError("merge requires a secondary frame")
        keys = _require_string_list(parameters.get("keys"), "merge.keys")
        missing_left = [key for key in keys if key not in left.columns]
        missing_right = [key for key in keys if key not in right.columns]
        if missing_left or missing_right:
            raise DataColumnCastValidationError(
                f"merge keys missing: left={missing_left}, right={missing_right}"
            )
        if left.duplicated(keys).any() and right.duplicated(keys).any():
            raise DataColumnCastValidationError(
                "DATA_MERGE_MANY_TO_MANY_BLOCKED; next_step=declare a one-to-one or one-to-many key contract"
            )
        how = parameters.get("how", "left")
        if not isinstance(how, str) or how not in {"left", "right", "inner", "outer"}:
            raise DataColumnCastValidationError("merge how must be left, right, inner, or outer")
        indicator = parameters.get("indicator")
        if indicator is not None:
            if indicator is True:
                indicator_name = "_merge"
            elif isinstance(indicator, str) and indicator.strip():
                indicator_name = indicator
            else:
                raise DataColumnCastValidationError(
                    "merge.indicator must be true or a non-empty output-column name"
                )
            if indicator_name in left.columns or indicator_name in right.columns:
                raise DataColumnCastValidationError(
                    f"merge indicator column collides with an existing column: {indicator_name}"
                )
        else:
            indicator_name = False
        try:
            merged = left.merge(
                right,
                on=keys,
                how=how,
                suffixes=("_left", "_right"),
                validate="many_to_one",
                indicator=indicator_name,
            )
        except (pd.errors.MergeError, ValueError) as exc:
            raise DataColumnCastValidationError(f"merge key contract rejected: {exc}") from exc
        _enforce_growth_policy(
            len(merged),
            len(left),
            operation_code="DATA_MERGE",
            policy=_growth_policy(
                parameters,
                parameter_name="growth_policy",
                legacy_factor_name="max_growth_factor",
            ),
        )
        return merged
    if spec.operation == "reshape":
        _reject_unknown_parameters(
            parameters,
            {
                "direction",
                "id_columns",
                "value_columns",
                "index",
                "columns",
                "values",
                "var_name",
                "value_name",
            },
            "reshape",
        )
        direction = parameters.get("direction")
        if direction == "wide_to_long":
            id_columns = _require_string_list(parameters.get("id_columns"), "reshape.id_columns")
            value_columns = _require_string_list(
                parameters.get("value_columns"), "reshape.value_columns"
            )
            _require_columns_exist(left, [*id_columns, *value_columns], "reshape")
            var_name = _require_non_empty_string(
                parameters.get("var_name", "variable"), "reshape.var_name"
            )
            value_name = _require_non_empty_string(
                parameters.get("value_name", "value"), "reshape.value_name"
            )
            if var_name == value_name or var_name in id_columns or value_name in id_columns:
                raise DataColumnCastValidationError(
                    "wide_to_long output names must not collide with id_columns"
                )
            return left.melt(
                id_vars=id_columns,
                value_vars=value_columns,
                var_name=var_name,
                value_name=value_name,
            )
        if direction == "long_to_wide":
            index = _require_string_list(parameters.get("index"), "reshape.index")
            columns = _require_non_empty_string(parameters.get("columns"), "reshape.columns")
            values = _require_non_empty_string(parameters.get("values"), "reshape.values")
            _require_columns_exist(left, [*index, columns, values], "reshape")
            try:
                return left.pivot(index=index, columns=columns, values=values).reset_index()
            except (ValueError, KeyError) as exc:
                raise DataColumnCastValidationError(
                    f"long_to_wide has duplicate or missing keys: {exc}"
                ) from exc
        raise DataColumnCastValidationError("reshape direction must be wide_to_long or long_to_wide")
    if spec.operation == "subset":
        _reject_unknown_parameters(
            parameters,
            {"columns", "equals", "filters", "row_indices", "row_index_range", "row_range"},
            "subset",
        )
        columns = _require_string_list(parameters.get("columns"), "subset.columns")
        _require_columns_exist(left, columns, "subset")
        legacy_equals = parameters.get("equals", {})
        if not isinstance(legacy_equals, Mapping):
            raise DataColumnCastValidationError("subset.equals must be an object")
        if any(not isinstance(column, str) or not column.strip() for column in legacy_equals):
            raise DataColumnCastValidationError("subset.equals keys must be non-empty strings")
        _require_columns_exist(left, list(legacy_equals), "subset.equals")
        filters = parameters.get("filters")
        if filters is None:
            filters = []
        if not isinstance(filters, list):
            raise DataColumnCastValidationError("subset.filters must be a list")
        filter_columns: list[str] = []
        for index, filter_spec in enumerate(filters):
            parsed = _require_nested_keys(
                filter_spec,
                name=f"subset.filters[{index}]",
                required={"column", "op"},
                optional={"value"},
            )
            filter_column = _require_non_empty_string(
                parsed["column"], f"subset.filters[{index}].column"
            )
            filter_columns.append(filter_column)
            _require_columns_exist(left, [filter_column], "subset.filters")
            _subset_filter_mask(left[filter_column], parsed, f"subset.filters[{index}]")
        overlap = set(legacy_equals) & set(filter_columns)
        if overlap:
            raise DataColumnCastValidationError(
                "subset.equals and subset.filters cannot both declare: "
                + ", ".join(sorted(overlap))
            )
        mask = pd.Series(True, index=left.index)
        for column, value in legacy_equals.items():
            mask &= left[column].eq(value).fillna(False)
        for index, filter_spec in enumerate(filters):
            column = str(filter_spec["column"])
            mask &= _subset_filter_mask(
                left[column], filter_spec, f"subset.filters[{index}]"
            )
        result = left.loc[mask].loc[:, columns].copy()
        row_indices = parameters.get("row_indices")
        if "row_index_range" in parameters and "row_range" in parameters:
            raise DataColumnCastValidationError(
                "DATA_SUBSET_ROW_INDEX_INVALID: row_index_range and row_range are aliases"
            )
        row_index_range = parameters.get("row_index_range", parameters.get("row_range"))
        if row_indices is not None and row_index_range is not None:
            raise DataColumnCastValidationError(
                "DATA_SUBSET_ROW_INDEX_INVALID: row_indices and row_index_range are mutually exclusive"
            )
        if row_indices is not None:
            if (
                not isinstance(row_indices, list)
                or not row_indices
                or any(type(index) is not int for index in row_indices)
                or len(set(row_indices)) != len(row_indices)
                or any(index < 0 or index >= len(result) for index in row_indices)
            ):
                raise DataColumnCastValidationError(
                    "DATA_SUBSET_ROW_INDEX_INVALID: row_indices must be unique, non-negative, and in range"
                )
            result = result.iloc[row_indices]
        elif row_index_range is not None:
            if isinstance(row_index_range, Mapping):
                unknown = set(row_index_range) - {"start", "stop"}
                if unknown:
                    raise DataColumnCastValidationError(
                        "DATA_SUBSET_ROW_INDEX_INVALID: row_index_range contains unsupported fields"
                    )
                start = row_index_range.get("start")
                stop = row_index_range.get("stop")
            elif isinstance(row_index_range, (list, tuple)) and len(row_index_range) == 2:
                start, stop = row_index_range
            else:
                start = stop = None
            if (
                type(start) is not int
                or type(stop) is not int
                or start < 0
                or stop < start
                or stop > len(result)
                ):
                raise DataColumnCastValidationError(
                    "DATA_SUBSET_ROW_INDEX_INVALID: row_index_range must be a bounded [start, stop) range"
                )
            result = result.iloc[start:stop]
        return result.reset_index(drop=True)
    if spec.operation == "dedupe":
        _reject_unknown_parameters(parameters, {"columns", "keep"}, "dedupe")
        columns = _require_string_list(parameters.get("columns"), "dedupe.columns")
        _require_columns_exist(left, columns, "dedupe")
        keep = parameters.get("keep")
        if keep not in {"first", "last"}:
            raise DataColumnCastValidationError("dedupe.keep must be first or last")
        return left.drop_duplicates(subset=columns, keep=keep, ignore_index=True)
    if spec.operation == "rename":
        _reject_unknown_parameters(parameters, {"mapping"}, "rename")
        mapping = parameters.get("mapping")
        if not isinstance(mapping, Mapping) or not mapping:
            raise DataColumnCastValidationError("rename.mapping must be a non-empty object")
        if any(
            not isinstance(old, str)
            or not old.strip()
            or not isinstance(new, str)
            or not new.strip()
            for old, new in mapping.items()
        ):
            raise DataColumnCastValidationError(
                "rename.mapping keys and values must be non-empty strings"
            )
        old_columns = list(mapping)
        new_columns = list(mapping.values())
        _require_columns_exist(left, old_columns, "rename")
        if len(set(new_columns)) != len(new_columns):
            raise DataColumnCastValidationError("rename.mapping new names must be distinct")
        untouched = set(left.columns) - set(old_columns)
        collisions = sorted(set(new_columns) & untouched)
        if collisions:
            raise DataColumnCastValidationError(
                f"rename.mapping collides with existing columns: {collisions}"
            )
        # pandas 3.0 keeps Copy-on-Write active and deprecates the rename
        # ``copy`` keyword; preserve the old eager-copy contract explicitly.
        return left.rename(columns=dict(mapping)).copy()
    if spec.operation == "aggregate":
        _reject_unknown_parameters(parameters, {"group_by", "aggregations"}, "aggregate")
        group_by = _require_string_list(parameters.get("group_by"), "aggregate.group_by")
        _require_columns_exist(left, group_by, "aggregate")
        aggregations = parameters.get("aggregations")
        if not isinstance(aggregations, list) or not aggregations:
            raise DataColumnCastValidationError(
                "aggregate.aggregations must be a non-empty list"
            )
        named: dict[str, pd.NamedAgg] = {}
        for index, aggregation in enumerate(aggregations):
            parsed = _require_nested_keys(
                aggregation,
                name=f"aggregate.aggregations[{index}]",
                required={"column", "func", "output"},
            )
            column = _require_non_empty_string(
                parsed["column"], f"aggregate.aggregations[{index}].column"
            )
            function = _require_non_empty_string(
                parsed["func"], f"aggregate.aggregations[{index}].func"
            )
            output = _require_non_empty_string(
                parsed["output"], f"aggregate.aggregations[{index}].output"
            )
            _require_columns_exist(left, [column], "aggregate")
            if function not in AGGREGATE_FUNCTIONS:
                raise DataColumnCastValidationError(
                    f"aggregate function must be one of: {', '.join(sorted(AGGREGATE_FUNCTIONS))}"
                )
            if output in group_by or output in named:
                raise DataColumnCastValidationError(
                    f"aggregate output collides with an existing output: {output}"
                )
            named[output] = pd.NamedAgg(column=column, aggfunc=function)
        try:
            return left.groupby(group_by, dropna=False, sort=False).agg(**named).reset_index()
        except (TypeError, ValueError, KeyError) as exc:
            raise DataColumnCastValidationError(f"aggregate failed: {exc}") from exc
    if spec.operation == "fill_missing":
        _reject_unknown_parameters(parameters, {"strategies"}, "fill_missing")
        strategies = parameters.get("strategies")
        if not isinstance(strategies, list) or not strategies:
            raise DataColumnCastValidationError(
                "fill_missing.strategies must be a non-empty list"
            )
        result = left.copy()
        seen_columns: set[str] = set()
        for index, strategy_spec in enumerate(strategies):
            parsed = _require_nested_keys(
                strategy_spec,
                name=f"fill_missing.strategies[{index}]",
                required={"column", "strategy"},
                optional={"value"},
            )
            column = _require_non_empty_string(
                parsed["column"], f"fill_missing.strategies[{index}].column"
            )
            strategy = _require_non_empty_string(
                parsed["strategy"], f"fill_missing.strategies[{index}].strategy"
            )
            _require_columns_exist(result, [column], "fill_missing")
            if column in seen_columns:
                raise DataColumnCastValidationError(
                    f"fill_missing may declare one strategy per column: {column}"
                )
            seen_columns.add(column)
            if strategy not in FILL_MISSING_STRATEGIES:
                raise DataColumnCastValidationError(
                    "fill_missing strategy must be one of: "
                    + ", ".join(sorted(FILL_MISSING_STRATEGIES))
                )
            has_value = "value" in parsed
            if strategy == "constant":
                if not has_value:
                    raise DataColumnCastValidationError(
                        f"fill_missing.strategies[{index}].value is required for constant"
                    )
                result[column] = result[column].fillna(parsed["value"])
                continue
            if has_value:
                raise DataColumnCastValidationError(
                    f"fill_missing.strategies[{index}].value is only allowed for constant"
                )
            if strategy == "drop_rows":
                result = result.dropna(subset=[column])
                continue
            series = result[column]
            if not series.notna().any():
                raise DataColumnCastValidationError(
                    f"fill_missing cannot calculate {strategy} for all-missing column {column}"
                )
            try:
                if strategy == "mean":
                    fill_value = series.mean()
                elif strategy == "median":
                    fill_value = series.median()
                else:
                    modes = series.mode(dropna=True)
                    if modes.empty:
                        raise DataColumnCastValidationError(
                            f"fill_missing cannot calculate mode for column {column}"
                        )
                    fill_value = modes.iloc[0]
                if pd.isna(fill_value):
                    raise DataColumnCastValidationError(
                        f"fill_missing calculated a missing {strategy} for column {column}"
                    )
                result[column] = series.fillna(fill_value)
            except DataColumnCastValidationError:
                raise
            except (TypeError, ValueError) as exc:
                raise DataColumnCastValidationError(
                    f"fill_missing {strategy} failed for column {column}: {exc}"
                ) from exc
        return result.reset_index(drop=True)
    if spec.operation == "tsset":
        _reject_unknown_parameters(
            parameters, {"time_column", "frequency", "panel_id_column"}, "tsset"
        )
        time_column = _require_non_empty_string(
            parameters.get("time_column"), "tsset.time_column"
        )
        frequency = _require_non_empty_string(parameters.get("frequency"), "tsset.frequency")
        if frequency not in TSSET_FREQUENCIES:
            raise DataColumnCastValidationError(
                "tsset.frequency must be one of: " + ", ".join(sorted(TSSET_FREQUENCIES))
            )
        panel_column = parameters.get("panel_id_column")
        if panel_column is not None:
            panel_column = _require_non_empty_string(panel_column, "tsset.panel_id_column")
        required_columns = [time_column] + ([panel_column] if panel_column else [])
        _require_columns_exist(left, required_columns, "tsset")
        # Explicitly allow heterogeneous user-supplied date spellings. This
        # keeps pandas from falling back to the deprecated implicit parser
        # while retaining its per-value coercion semantics.
        converted = pd.to_datetime(left[time_column], format="mixed", errors="coerce")
        if converted.isna().any():
            raise DataColumnCastValidationError(
                f"tsset.time_column contains missing or invalid time values: {time_column}"
            )
        duplicate_keys = [panel_column, time_column] if panel_column else [time_column]
        if panel_column and left[panel_column].isna().any():
            raise DataColumnCastValidationError("tsset.panel_id_column must not contain missing values")
        if left.duplicated(duplicate_keys).any():
            raise DataColumnCastValidationError(
                "tsset rejects duplicate time keys for the declared panel"
            )
        working = left.copy()
        sort_key = "__workbench_tsset_time__"
        while sort_key in working.columns:
            sort_key = f"_{sort_key}"
        working[sort_key] = converted
        sort_columns = ([panel_column] if panel_column else []) + [sort_key]
        return (
            working.sort_values(sort_columns, kind="mergesort")
            .drop(columns=[sort_key])
            .reset_index(drop=True)
        )
    if spec.operation == "lag":
        _reject_unknown_parameters(parameters, {"columns", "lags", "difference"}, "lag")
        columns = _require_string_list(parameters.get("columns"), "lag.columns")
        _require_columns_exist(left, columns, "lag")
        lags = parameters.get("lags")
        if not isinstance(lags, list) or not lags or any(
            type(lag) is not int or lag <= 0 for lag in lags
        ):
            raise DataColumnCastValidationError(
                "lag.lags must be a non-empty list of positive integers"
            )
        if len(set(lags)) != len(lags):
            raise DataColumnCastValidationError("lag.lags must not contain duplicates")
        difference = parameters.get("difference", 0)
        if type(difference) is not int or difference < 0:
            raise DataColumnCastValidationError(
                "lag.difference must be a non-negative integer"
            )
        output_names = [f"{column}_lag{lag}" for column in columns for lag in lags]
        if len(set(output_names)) != len(output_names) or set(output_names) & set(left.columns):
            raise DataColumnCastValidationError(
                f"lag output columns collide with existing columns: {output_names}"
            )
        result = left.copy()
        for column in columns:
            base = result[column].diff(difference) if difference else result[column]
            for lag in lags:
                result[f"{column}_lag{lag}"] = base.shift(lag)
        return result
    raise DataColumnCastValidationError(f"unsupported data operation: {spec.operation}")


def preview_data_transform(project_root: Path | str, spec: DataTransformSpecV1) -> DataTransformPreview:
    left_root, graph, _node, left_artifact, left_path = _resolve_source(
        project_root, _transform_source_spec(spec.source_run_id, spec.source_node_id, spec.source_artifact_id)
    )
    left = _read_frame(left_path)
    right = None
    right_artifact = None
    if spec.secondary_run_id and spec.secondary_node_id and spec.secondary_artifact_id:
        _right_root, _right_graph, _right_node, right_artifact, right_path = _resolve_source(
            project_root,
            _transform_source_spec(spec.secondary_run_id, spec.secondary_node_id, spec.secondary_artifact_id),
        )
        right = _read_frame(right_path)
    output = _execute_data_transform(left, spec, right)
    source_sha = str(left_artifact.get("sha256") or sha256_file(left_path))
    secondary_sha = (
        str(right_artifact.get("sha256") or "") if right_artifact is not None else None
    )
    before = _schema_fingerprint(left)
    after = _schema_fingerprint(output)
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "secondary_source_sha256": secondary_sha,
        "schema_before": before,
        "schema_after": after,
        "row_count_after": len(output),
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DataTransformPreview(
        spec=spec,
        source_sha256=source_sha,
        secondary_source_sha256=secondary_sha,
        row_count_before=len(left),
        row_count_after=len(output),
        input_columns=tuple(str(column) for column in left.columns),
        output_columns=tuple(str(column) for column in output.columns),
        schema_fingerprint_before=before,
        schema_fingerprint_after=after,
        fingerprint=fingerprint,
        downstream_invalidation=tuple(
            node_id for node_id, candidate in graph.nodes.items() if candidate.kind == NodeKind.MODEL
        ),
    )


def apply_data_transform(
    project_root: Path | str,
    spec: DataTransformSpecV1,
    preview: DataTransformPreview,
    *,
    execution_key_value: str | None = None,
) -> FeatureRecipeEffect:
    if preview.spec != spec:
        raise DataColumnCastValidationError("preview spec does not match data operation spec")
    fresh = preview_data_transform(project_root, spec)
    if fresh.fingerprint != preview.fingerprint:
        raise DataColumnCastValidationError("data operation preview is stale")
    left_root, graph, _node, left_artifact, left_path = _resolve_source(
        project_root, _transform_source_spec(spec.source_run_id, spec.source_node_id, spec.source_artifact_id)
    )
    right = None
    secondary_graph = None
    secondary_node = None
    if spec.secondary_run_id and spec.secondary_node_id and spec.secondary_artifact_id:
        _right_root, secondary_graph, secondary_node, _right_artifact, right_path = _resolve_source(
            project_root,
            _transform_source_spec(spec.secondary_run_id, spec.secondary_node_id, spec.secondary_artifact_id),
        )
        right = _read_frame(right_path)
    output = _execute_data_transform(_read_frame(left_path), spec, right)
    execution = execution_key_value or f"exec_{fresh.fingerprint[:32]}"
    suffix = execution.removeprefix("exec_")
    artifact_id = f"{spec.operation}_{suffix}"
    recipe_artifact_id = f"{spec.operation}_recipe_{suffix}"
    relative_dir = Path("derived") / "data_operations" / spec.operation / suffix
    artifact_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = left_root / artifact_rel
    recipe_path = left_root / recipe_rel
    _write_frame_artifact(artifact_path, output, "csv")
    recipe_payload = {
        "payload_schema": "workbench.data-operation",
        "schema_version": 1,
        "execution_key": execution,
        "spec": spec.to_dict(),
        "preview": fresh.to_dict(),
        "result": {"artifact_id": artifact_id, "path": artifact_rel},
    }
    if recipe_path.exists() and read_json(recipe_path) != recipe_payload:
        raise DataColumnCastValidationError("deterministic data operation path is occupied")
    if not recipe_path.exists():
        write_json(recipe_path, recipe_payload)
    inputs = [spec.source_artifact_id]
    if spec.secondary_artifact_id:
        inputs.append(spec.secondary_artifact_id)
    _ensure_registered_artifact(left_root, artifact_id=artifact_id, path=artifact_path, artifact_type="derived_data", step=f"data.{spec.operation}", inputs=inputs)
    _ensure_registered_artifact(left_root, artifact_id=recipe_artifact_id, path=recipe_path, artifact_type="metadata", step=f"data.{spec.operation}", inputs=inputs + [artifact_id])
    child_node_id = f"data-{spec.operation}:{suffix}"
    _graph_store_for(left_root).mutate(
        spec.source_run_id,
        lambda current: current if child_node_id in current.nodes else _commit_data_transform_graph_child(
            current,
            spec=spec,
            preview=fresh,
            artifact_rel=artifact_rel,
            recipe_rel=recipe_rel,
            child_node_id=child_node_id,
            execution_key=execution,
            node_hash=sha256_file(artifact_path),
            secondary_graph=secondary_graph,
            secondary_node=secondary_node,
        ),
    )
    _ensure_node_index_entry(
        left_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(artifact_path),
        artifact_rel=artifact_rel,
        producing_stage=f"data.{spec.operation}",
        create_if_missing=True,
    )
    return FeatureRecipeEffect(execution, artifact_id, artifact_rel, recipe_artifact_id, recipe_rel, child_node_id)


@dataclass(frozen=True)
class DataColumnCastSpecV1:
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    column: str
    target_dtype: DataCastTarget
    operation_id: str = "data.column.cast"
    operation_version: str = "v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
            "column",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ).strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.target_dtype not in ALLOWED_CAST_TARGETS:
            raise ValueError(
                "target_dtype must be one of: "
                + ", ".join(sorted(ALLOWED_CAST_TARGETS))
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
            "column": self.column,
            "target_dtype": self.target_dtype,
        }


@dataclass(frozen=True)
class DataColumnCastPreview:
    spec: DataColumnCastSpecV1
    source_sha256: str
    row_count: int
    before_dtype: str
    after_dtype: str
    success_count: int
    failure_count: int
    failure_examples: tuple[str, ...]
    new_missing_count: int
    schema_fingerprint_before: str
    schema_fingerprint_after: str
    fingerprint: str
    downstream_invalidation: tuple[str, ...] = field(default_factory=tuple)
    status: str = "ready"

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_examples", tuple(self.failure_examples))
        object.__setattr__(
            self,
            "downstream_invalidation",
            tuple(self.downstream_invalidation),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.spec.operation_id,
            "operation_version": self.spec.operation_version,
            "source_run_id": self.spec.source_run_id,
            "source_node_id": self.spec.source_node_id,
            "source_artifact_id": self.spec.source_artifact_id,
            "column": self.spec.column,
            "target_dtype": self.spec.target_dtype,
            "source_sha256": self.source_sha256,
            "row_count": self.row_count,
            "before_dtype": self.before_dtype,
            "after_dtype": self.after_dtype,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "failure_examples": list(self.failure_examples),
            "new_missing_count": self.new_missing_count,
            "schema_fingerprint_before": self.schema_fingerprint_before,
            "schema_fingerprint_after": self.schema_fingerprint_after,
            "fingerprint": self.fingerprint,
            "downstream_invalidation": list(self.downstream_invalidation),
            "status": self.status,
        }


@dataclass(frozen=True)
class DataColumnCastEffect:
    execution_key: str
    artifact_id: str
    artifact_path: str
    recipe_artifact_id: str
    recipe_path: str
    child_node_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
        }


def preview_feature_recipe(
    project_root: Path | str,
    spec: FeatureRecipeOperationSpecV1,
) -> FeatureRecipePreview:
    """Preview one registered FeatureRecipe without mutating project state."""

    source_spec = DataColumnCastSpecV1(
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        column=str(spec.recipe.inputs[0]),
        target_dtype="string",
    )
    run_root, graph, _node, artifact, source_path = _resolve_source(project_root, source_spec)
    frame = _read_frame(source_path)
    before = _schema_fingerprint(frame)
    try:
        output = apply_feature_recipe(frame, spec.recipe)
    except Exception as exc:  # noqa: BLE001 - convert engine failures to preview evidence
        raise DataColumnCastValidationError(str(exc)) from exc
    outputs = tuple(spec.recipe.outputs)
    if spec.recipe.missing_policy == "fail_closed":
        missing_outputs = [column for column in outputs if output[column].isna().any()]
        if missing_outputs:
            raise DataColumnCastValidationError(
                "FeatureRecipe produced missing values in fail-closed output(s): "
                + ", ".join(missing_outputs)
            )
    after = _schema_fingerprint(output)
    source_sha = str(artifact.get("sha256") or sha256_file(source_path))
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "schema_before": before,
        "schema_after": after,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return FeatureRecipePreview(
        spec=spec,
        source_sha256=source_sha,
        row_count=len(output),
        input_columns=tuple(str(column) for column in frame.columns),
        output_columns=tuple(str(column) for column in output.columns),
        schema_fingerprint_before=before,
        schema_fingerprint_after=after,
        fingerprint=fingerprint,
        downstream_invalidation=tuple(
            node_id for node_id, candidate in graph.nodes.items() if candidate.kind == NodeKind.MODEL
        ),
    )


def apply_feature_recipe_operation(
    project_root: Path | str,
    spec: FeatureRecipeOperationSpecV1,
    preview: FeatureRecipePreview,
    *,
    execution_key_value: str | None = None,
) -> FeatureRecipeEffect:
    """Materialize a deterministic typed FeatureRecipe child and Graph node."""

    if preview.spec != spec:
        raise DataColumnCastValidationError("preview spec does not match operation spec")
    fresh = preview_feature_recipe(project_root, spec)
    if fresh.fingerprint != preview.fingerprint:
        raise DataColumnCastValidationError("feature recipe preview is stale")
    if fresh.status != "ready":
        raise DataColumnCastValidationError("feature recipe preview is blocked")
    source_spec = DataColumnCastSpecV1(
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        column=str(spec.recipe.inputs[0]),
        target_dtype="string",
    )
    run_root, graph, _node, source_artifact, source_path = _resolve_source(project_root, source_spec)
    frame = _read_frame(source_path)
    output = apply_feature_recipe(frame, spec.recipe)
    execution = execution_key_value or f"exec_{fresh.fingerprint[:32]}"
    suffix = execution.removeprefix("exec_")
    artifact_id = f"feature_recipe_{suffix}"
    recipe_artifact_id = f"feature_recipe_recipe_{suffix}"
    relative_dir = Path("derived") / "feature_recipe" / suffix
    artifact_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = run_root / artifact_rel
    recipe_path = run_root / recipe_rel
    _write_frame_artifact(artifact_path, output, "csv")
    recipe_payload = {
        **spec.recipe.to_dict(),
        "execution_key": execution,
        "source_sha256": str(source_artifact.get("sha256") or sha256_file(source_path)),
        "result": {"artifact_id": artifact_id, "path": artifact_rel},
    }
    if recipe_path.exists() and read_json(recipe_path) != recipe_payload:
        raise DataColumnCastValidationError("deterministic feature recipe path is occupied")
    if not recipe_path.exists():
        write_json(recipe_path, recipe_payload)
    _ensure_registered_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="derived_data",
        step=spec.recipe.operation_id,
        inputs=[spec.source_artifact_id],
    )
    _ensure_registered_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step=spec.recipe.operation_id,
        inputs=[spec.source_artifact_id, artifact_id],
    )
    child_node_id = f"feature-recipe:{suffix}"
    _graph_store_for(run_root).mutate(
        spec.source_run_id,
        lambda current: current if child_node_id in current.nodes else _commit_feature_recipe_graph_child(
            current,
            spec=spec,
            preview=fresh,
            artifact_rel=artifact_rel,
            recipe_rel=recipe_rel,
            child_node_id=child_node_id,
            execution_key=execution,
            node_hash=sha256_file(artifact_path),
        ),
    )
    _ensure_node_index_entry(
        run_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(artifact_path),
        artifact_rel=artifact_rel,
        producing_stage=spec.recipe.operation_id,
        create_if_missing=True,
    )
    return FeatureRecipeEffect(
        execution_key=execution,
        artifact_id=artifact_id,
        artifact_path=artifact_rel,
        recipe_artifact_id=recipe_artifact_id,
        recipe_path=recipe_rel,
        child_node_id=child_node_id,
    )


def preview_data_column_cast(
    project_root: Path | str,
    spec: DataColumnCastSpecV1,
) -> DataColumnCastPreview:
    """Read and strictly preview a cast without creating project metadata."""

    _run_root, graph, node, artifact, source_path = _resolve_source(project_root, spec)
    frame = _read_frame(source_path)
    if spec.column not in frame.columns:
        raise DataColumnCastValidationError(
            f"column {spec.column!r} is not present in source artifact"
        )

    source = frame[spec.column]
    converted, failures = _convert_strict(source, spec.target_dtype)
    before_missing = int(source.isna().sum())
    after_missing = int(converted.isna().sum())
    schema_before = _schema_fingerprint(frame)
    after_frame = frame.copy()
    after_frame[spec.column] = converted
    schema_after = _schema_fingerprint(after_frame)
    source_sha = str(artifact.get("sha256") or sha256_file(source_path))
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "schema_before": schema_before,
        "schema_after": schema_after,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    failure_examples = tuple(str(value) for value in source[failures].head(5).tolist())
    downstream = tuple(
        node_id
        for node_id, candidate in graph.nodes.items()
        if candidate.kind == NodeKind.MODEL
    )
    return DataColumnCastPreview(
        spec=spec,
        source_sha256=source_sha,
        row_count=len(frame),
        before_dtype=str(source.dtype),
        after_dtype=str(converted.dtype),
        success_count=int((~failures & ~source.isna()).sum()),
        failure_count=int(failures.sum()),
        failure_examples=failure_examples,
        new_missing_count=max(0, after_missing - before_missing),
        schema_fingerprint_before=schema_before,
        schema_fingerprint_after=schema_after,
        fingerprint=fingerprint,
        downstream_invalidation=downstream,
        status="blocked" if bool(failures.any()) else "ready",
    )


def resolve_data_column_cast_context(
    project_root: Path | str,
    *,
    source_run_id: str,
    source_node_id: str,
) -> dict[str, Any]:
    """Resolve the read-only UI context for a dataset-node cast.

    The graph node owns the payload reference; the artifact index owns the
    durable artifact identity. Keeping this lookup here prevents the browser
    from guessing an artifact id from display text or from an Agent message.
    """

    root = Path(project_root).expanduser().resolve()
    runs_root = root / "runs"
    run_root = (runs_root / source_run_id).resolve()
    try:
        run_root.relative_to(runs_root.resolve())
    except ValueError as exc:
        raise DataColumnCastValidationError("source run is outside project runs") from exc
    if not run_root.is_dir():
        raise DataColumnCastValidationError("source run was not found")

    from .graph_store import GraphStore

    graph = GraphStore(runs_root).read(source_run_id)
    try:
        node = graph.nodes[source_node_id]
    except KeyError as exc:
        raise DataColumnCastValidationError("source graph node was not found") from exc
    if node.kind != NodeKind.DATASET_STAGE:
        raise DataColumnCastValidationError("source node must be a dataset_stage node")
    index = read_json(run_root / "artifacts_index.json")
    records = index.get("artifacts", [])
    if node.payload_ref:
        try:
            artifact = next(
                item for item in records if item.get("path") == node.payload_ref
            )
        except StopIteration as exc:
            raise DataColumnCastValidationError("source node artifact was not found") from exc
    elif source_node_id in {"stage:raw", "stage:source"}:
        raw_artifacts = [
            item
            for item in records
            if item.get("artifact_type") == "raw_data"
            and str(item.get("path") or "").startswith("raw_snapshot/")
        ]
        if len(raw_artifacts) != 1:
            raise DataColumnCastValidationError(
                "raw source node does not resolve to exactly one raw artifact"
            )
        artifact = raw_artifacts[0]
    else:
        raise DataColumnCastValidationError("source dataset node has no materialized artifact")

    relative = artifact.get("path")
    if not isinstance(relative, str) or not relative:
        raise DataColumnCastValidationError("source artifact has no path")
    source_path = (run_root / relative).resolve()
    try:
        source_path.relative_to(run_root.resolve())
    except ValueError as exc:
        raise DataColumnCastValidationError("source artifact escapes run root") from exc
    if not source_path.is_file():
        raise DataColumnCastValidationError("source artifact file is missing")
    expected_sha = artifact.get("sha256")
    actual_sha = sha256_file(source_path)
    if expected_sha and expected_sha != actual_sha:
        raise DataColumnCastValidationError("source artifact fingerprint changed")

    frame = _read_frame(source_path)
    return {
        "operation_id": "data.column.cast",
        "operation_version": "v1",
        "source_run_id": source_run_id,
        "source_node_id": source_node_id,
        "source_artifact_id": artifact.get("artifact_id"),
        "source_artifact_path": relative,
        "source_sha256": actual_sha,
        "row_count": len(frame),
        "columns": [
            {"name": str(column), "dtype": str(frame[column].dtype)}
            for column in frame.columns
        ],
        "downstream_invalidation": [
            node_id
            for node_id, candidate in graph.nodes.items()
            if candidate.kind == NodeKind.MODEL
        ],
    }
def data_column_cast_execution_key(
    spec: DataColumnCastSpecV1,
    preview: DataColumnCastPreview,
) -> str:
    identity = {
        "spec": spec.to_dict(),
        "preview_fingerprint": preview.fingerprint,
        "source_sha256": preview.source_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"exec_{digest[:32]}"


def apply_data_column_cast(
    project_root: Path | str,
    spec: DataColumnCastSpecV1,
    preview: DataColumnCastPreview,
    *,
    execution_key_value: str | None = None,
) -> DataColumnCastEffect:
    """Materialize one deterministic child artifact and graph node.

    The function is deliberately idempotent for one execution key. It is the
    domain effect hook used by the shared Agent lifecycle and by focused tests.
    """

    if preview.spec != spec:
        raise DataColumnCastValidationError("preview spec does not match operation spec")
    fresh = preview_data_column_cast(project_root, spec)
    if fresh.fingerprint != preview.fingerprint:
        raise DataColumnCastValidationError("cast preview is stale")
    if fresh.status != "ready":
        raise DataColumnCastValidationError("cast preview is blocked")

    run_root, graph, source_node, source_artifact, source_path = _resolve_source(
        project_root, spec
    )
    execution = execution_key_value or data_column_cast_execution_key(spec, fresh)
    artifact_id = f"data_cast_{execution.removeprefix('exec_')}"
    recipe_artifact_id = f"data_cast_recipe_{execution.removeprefix('exec_')}"
    relative_dir = Path("derived") / "data_column_cast" / execution.removeprefix("exec_")
    artifact_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = run_root / artifact_rel
    recipe_path = run_root / recipe_rel

    frame = _read_frame(source_path)
    converted, failures = _convert_strict(frame[spec.column], spec.target_dtype)
    if bool(failures.any()):
        raise DataColumnCastValidationError("cast preview is blocked")
    output_frame = frame.copy()
    output_frame[spec.column] = converted
    _write_frame_artifact(artifact_path, output_frame, "csv")

    recipe = {
        "schema_version": "data-column-cast.v1",
        "execution_key": execution,
        "spec": spec.to_dict(),
        "preview": fresh.to_dict(),
        "source": {
            "artifact_id": spec.source_artifact_id,
            "sha256": source_artifact.get("sha256"),
            "path": source_artifact.get("path"),
        },
        "result": {
            "artifact_id": artifact_id,
            "path": artifact_rel,
            "schema_fingerprint": fresh.schema_fingerprint_after,
        },
    }
    if recipe_path.exists() and read_json(recipe_path) != recipe:
        raise DataColumnCastValidationError("deterministic cast recipe path is occupied")
    if not recipe_path.exists():
        write_json(recipe_path, recipe)

    _ensure_registered_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="derived_data",
        step="data.column.cast",
        inputs=[spec.source_artifact_id],
    )
    _ensure_registered_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="data.column.cast",
        inputs=[spec.source_artifact_id, artifact_id],
    )

    child_node_id = f"data-cast:{execution.removeprefix('exec_')}"
    store = _graph_store_for(run_root)
    store.mutate(
        spec.source_run_id,
        lambda current: (
            current
            if child_node_id in current.nodes
            else _commit_graph_child(
                current,
                spec=spec,
                preview=fresh,
                artifact_rel=artifact_rel,
                recipe_rel=recipe_rel,
                child_node_id=child_node_id,
                execution_key=execution,
                node_hash=sha256_file(artifact_path),
            )
        ),
    )
    _ensure_node_index_entry(
        run_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(artifact_path),
        artifact_rel=artifact_rel,
    )

    return DataColumnCastEffect(
        execution_key=execution,
        artifact_id=artifact_id,
        artifact_path=artifact_rel,
        recipe_artifact_id=recipe_artifact_id,
        recipe_path=recipe_rel,
        child_node_id=child_node_id,
    )


# ── Batch cast (data.columns.cast) — N columns → one immutable child ──────────
#
# Same typed lifecycle as the singular data.column.cast, but the operation grain
# matches user intent: "cast these N columns" is one Operation Record, one child
# node, one artifact, one recipe, one diff — instead of N sibling nodes that each
# apply only one cast and never yield a fully-cast dataset. Leaf helpers
# (_convert_strict / _schema_fingerprint / _resolve_source / _read_frame) are
# shared with the singular path, which is left untouched.


@dataclass(frozen=True)
class DataCastItem:
    column: str
    target_dtype: DataCastTarget

    def __post_init__(self) -> None:
        if not isinstance(self.column, str) or not self.column.strip():
            raise ValueError("column must be a non-empty string")
        if self.target_dtype not in ALLOWED_CAST_TARGETS:
            raise ValueError(
                "target_dtype must be one of: " + ", ".join(sorted(ALLOWED_CAST_TARGETS))
            )

    def to_dict(self) -> dict[str, str]:
        return {"column": self.column, "target_dtype": self.target_dtype}


@dataclass(frozen=True)
class DataColumnsCastSpecV1:
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    casts: tuple[DataCastItem, ...]
    output_format: DataCastOutputFormat = "csv"
    operation_id: str = "data.columns.cast"
    operation_version: str = "v1"

    def __post_init__(self) -> None:
        for field_name in ("source_run_id", "source_node_id", "source_artifact_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        items = tuple(
            item if isinstance(item, DataCastItem) else DataCastItem(item[0], item[1])
            for item in self.casts
        )
        object.__setattr__(self, "casts", items)
        if not items:
            raise ValueError("casts must contain at least one column")
        columns = [item.column for item in items]
        if len(columns) != len(set(columns)):
            raise ValueError("casts must not contain a duplicate column")
        if self.output_format not in ALLOWED_OUTPUT_FORMATS:
            raise ValueError(
                "output_format must be one of: " + ", ".join(sorted(ALLOWED_OUTPUT_FORMATS))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
            "casts": [item.to_dict() for item in self.casts],
            "output_format": self.output_format,
        }


@dataclass(frozen=True)
class DataColumnCastItemResult:
    column: str
    target_dtype: DataCastTarget
    before_dtype: str
    after_dtype: str
    success_count: int
    failure_count: int
    failure_examples: tuple[str, ...]
    new_missing_count: int
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "target_dtype": self.target_dtype,
            "before_dtype": self.before_dtype,
            "after_dtype": self.after_dtype,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "failure_examples": list(self.failure_examples),
            "new_missing_count": self.new_missing_count,
            "status": self.status,
        }


@dataclass(frozen=True)
class DataColumnsCastPreview:
    spec: DataColumnsCastSpecV1
    source_sha256: str
    row_count: int
    items: tuple[DataColumnCastItemResult, ...]
    schema_fingerprint_before: str
    schema_fingerprint_after: str
    fingerprint: str
    downstream_invalidation: tuple[str, ...] = field(default_factory=tuple)
    status: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.spec.operation_id,
            "operation_version": self.spec.operation_version,
            "source_run_id": self.spec.source_run_id,
            "source_node_id": self.spec.source_node_id,
            "source_artifact_id": self.spec.source_artifact_id,
            "casts": [item.to_dict() for item in self.spec.casts],
            "source_sha256": self.source_sha256,
            "row_count": self.row_count,
            "items": [item.to_dict() for item in self.items],
            "schema_fingerprint_before": self.schema_fingerprint_before,
            "schema_fingerprint_after": self.schema_fingerprint_after,
            "fingerprint": self.fingerprint,
            "downstream_invalidation": list(self.downstream_invalidation),
            "status": self.status,
        }


@dataclass(frozen=True)
class DataColumnsCastEffect:
    execution_key: str
    artifact_id: str
    artifact_path: str
    recipe_artifact_id: str
    recipe_path: str
    child_node_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
        }


def _resolve_batch_source(project_root: Path | str, spec: DataColumnsCastSpecV1):
    """Reuse the singular resolver by projecting the batch spec onto its shape."""

    probe = DataColumnCastSpecV1(
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        column=spec.casts[0].column,
        target_dtype=spec.casts[0].target_dtype,
    )
    return _resolve_source(project_root, probe)


def preview_data_columns_cast(
    project_root: Path | str,
    spec: DataColumnsCastSpecV1,
) -> DataColumnsCastPreview:
    """Strictly preview N casts against one source without writing project state."""

    run_root, graph, node, artifact, source_path = _resolve_batch_source(project_root, spec)
    frame = _read_frame(source_path)
    for item in spec.casts:
        if item.column not in frame.columns:
            raise DataColumnCastValidationError(
                f"column {item.column!r} is not present in source artifact"
            )

    schema_before = _schema_fingerprint(frame)
    after_frame = frame.copy()
    results: list[DataColumnCastItemResult] = []
    for item in spec.casts:
        source = frame[item.column]
        converted, failures = _convert_strict(source, item.target_dtype)
        after_frame[item.column] = converted
        before_missing = int(source.isna().sum())
        after_missing = int(converted.isna().sum())
        results.append(
            DataColumnCastItemResult(
                column=item.column,
                target_dtype=item.target_dtype,
                before_dtype=str(source.dtype),
                after_dtype=str(converted.dtype),
                success_count=int((~failures & ~source.isna()).sum()),
                failure_count=int(failures.sum()),
                failure_examples=tuple(
                    str(value) for value in source[failures].head(5).tolist()
                ),
                new_missing_count=max(0, after_missing - before_missing),
                status="blocked" if bool(failures.any()) else "ready",
            )
        )
    schema_after = _schema_fingerprint(after_frame)
    source_sha = str(artifact.get("sha256") or sha256_file(source_path))
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "schema_before": schema_before,
        "schema_after": schema_after,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    downstream = tuple(
        node_id
        for node_id, candidate in graph.nodes.items()
        if candidate.kind == NodeKind.MODEL
    )
    return DataColumnsCastPreview(
        spec=spec,
        source_sha256=source_sha,
        row_count=len(frame),
        items=tuple(results),
        schema_fingerprint_before=schema_before,
        schema_fingerprint_after=schema_after,
        fingerprint=fingerprint,
        downstream_invalidation=downstream,
        status="ready" if all(r.status == "ready" for r in results) else "blocked",
    )


def data_columns_cast_execution_key(
    spec: DataColumnsCastSpecV1,
    preview: DataColumnsCastPreview,
) -> str:
    identity = {
        "spec": spec.to_dict(),
        "preview_fingerprint": preview.fingerprint,
        "source_sha256": preview.source_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"exec_{digest[:32]}"


def apply_data_columns_cast(
    project_root: Path | str,
    spec: DataColumnsCastSpecV1,
    preview: DataColumnsCastPreview,
    *,
    execution_key_value: str | None = None,
) -> DataColumnsCastEffect:
    """Materialize one deterministic child (all N casts) — idempotent per key."""

    if preview.spec != spec:
        raise DataColumnCastValidationError("preview spec does not match operation spec")
    fresh = preview_data_columns_cast(project_root, spec)
    if fresh.fingerprint != preview.fingerprint:
        raise DataColumnCastValidationError("cast preview is stale")
    if fresh.status != "ready":
        raise DataColumnCastValidationError("cast preview is blocked")

    run_root, graph, source_node, source_artifact, source_path = _resolve_batch_source(
        project_root, spec
    )
    execution = execution_key_value or data_columns_cast_execution_key(spec, fresh)
    key = execution.removeprefix("exec_")
    data_ext = "xlsx" if spec.output_format == "xlsx" else "csv"
    artifact_id = f"data_casts_{key}"
    recipe_artifact_id = f"data_casts_recipe_{key}"
    relative_dir = Path("derived") / "data_columns_cast" / key
    artifact_rel = (relative_dir / f"data.{data_ext}").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = run_root / artifact_rel
    recipe_path = run_root / recipe_rel

    frame = _read_frame(source_path)
    output_frame = frame.copy()
    for item in spec.casts:
        converted, failures = _convert_strict(frame[item.column], item.target_dtype)
        if bool(failures.any()):
            raise DataColumnCastValidationError("cast preview is blocked")
        output_frame[item.column] = converted
    _write_frame_artifact(artifact_path, output_frame, spec.output_format)

    recipe = {
        "schema_version": "data-columns-cast.v1",
        "execution_key": execution,
        "spec": spec.to_dict(),
        "preview": fresh.to_dict(),
        "casts": [item.to_dict() for item in spec.casts],
        "source": {
            "artifact_id": spec.source_artifact_id,
            "sha256": source_artifact.get("sha256"),
            "path": source_artifact.get("path"),
        },
        "result": {
            "artifact_id": artifact_id,
            "path": artifact_rel,
            "schema_fingerprint": fresh.schema_fingerprint_after,
        },
    }
    if recipe_path.exists() and read_json(recipe_path) != recipe:
        raise DataColumnCastValidationError("deterministic cast recipe path is occupied")
    if not recipe_path.exists():
        write_json(recipe_path, recipe)

    _ensure_registered_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="derived_data",
        step="data.columns.cast",
        inputs=[spec.source_artifact_id],
    )
    _ensure_registered_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="data.columns.cast",
        inputs=[spec.source_artifact_id, artifact_id],
    )

    child_node_id = f"data-casts:{key}"
    store = _graph_store_for(run_root)
    store.mutate(
        spec.source_run_id,
        lambda current: (
            current
            if child_node_id in current.nodes
            else _commit_batch_graph_child(
                current,
                spec=spec,
                preview=fresh,
                artifact_rel=artifact_rel,
                recipe_rel=recipe_rel,
                child_node_id=child_node_id,
                execution_key=execution,
                node_hash=sha256_file(artifact_path),
            )
        ),
    )
    _ensure_node_index_entry(
        run_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(artifact_path),
        artifact_rel=artifact_rel,
        producing_stage="data.columns.cast",
    )

    return DataColumnsCastEffect(
        execution_key=execution,
        artifact_id=artifact_id,
        artifact_path=artifact_rel,
        recipe_artifact_id=recipe_artifact_id,
        recipe_path=recipe_rel,
        child_node_id=child_node_id,
    )


def _batch_cast_label(spec: DataColumnsCastSpecV1) -> str:
    if len(spec.casts) == 1:
        item = spec.casts[0]
        return f"Cast {item.column} → {item.target_dtype}"
    return f"Cast {len(spec.casts)} columns"


def _commit_batch_graph_child(
    graph: Graph,
    *,
    spec: DataColumnsCastSpecV1,
    preview: DataColumnsCastPreview,
    artifact_rel: str,
    recipe_rel: str,
    child_node_id: str,
    execution_key: str,
    node_hash: str,
) -> Graph:
    branch_id = f"data-casts:{execution_key.removeprefix('exec_')[:20]}"
    columns_summary = ", ".join(f"{i.column}→{i.target_dtype}" for i in preview.items)
    child = Node(
        id=child_node_id,
        kind=NodeKind.DATASET_STAGE,
        display_label=_batch_cast_label(spec),
        created_at=datetime.now(timezone.utc).isoformat(),
        parent_stage_id=spec.source_node_id,
        branch_id=branch_id,
        trust=Trust.OK,
        payload_ref=artifact_rel,
        summary=(
            f"{len(spec.casts)} columns cast ({columns_summary}); "
            f"{preview.row_count} rows; downstream rerun required"
        ),
        annotations=(
            {
                "type": "data_operation",
                "operation_id": spec.operation_id,
                "execution_key": execution_key,
                "recipe_path": recipe_rel,
                "schema_fingerprint": preview.schema_fingerprint_after,
                "casts": [item.to_dict() for item in spec.casts],
            },
        ),
        stage=Stage.TRANSFORM,
        node_hash=node_hash,
    )
    nodes = dict(graph.nodes)
    nodes[child_node_id] = child
    nodes = _mark_downstream_invalidation(
        nodes,
        reason="data_columns_cast",
        source_node_id=spec.source_node_id,
        child_node_id=child_node_id,
    )
    edges = dict(graph.edges)
    edge_id = f"edge:{child_node_id}"
    edges[edge_id] = Edge(
        id=edge_id,
        source_id=spec.source_node_id,
        target_id=child_node_id,
        op=spec.operation_id,
        params={
            "casts": [item.to_dict() for item in spec.casts],
            "execution_key": execution_key,
            "schema_fingerprint_before": preview.schema_fingerprint_before,
            "schema_fingerprint_after": preview.schema_fingerprint_after,
        },
    )
    branches = dict(graph.branches)
    branches[branch_id] = BranchRef(
        id=branch_id,
        forked_from_node_id=spec.source_node_id,
        head_node_ids=(child_node_id,),
    )
    return Graph(
        schema_version=graph.schema_version,
        run_id=graph.run_id,
        nodes=nodes,
        edges=edges,
        branches=branches,
        legacy=graph.legacy,
    )


def _resolve_source(
    project_root: Path | str,
    spec: DataColumnCastSpecV1,
) -> tuple[Path, Any, Any, dict[str, Any], Path]:
    root = Path(project_root).expanduser().resolve()
    runs_root = root / "runs"
    run_root = (runs_root / spec.source_run_id).resolve()
    try:
        run_root.relative_to(runs_root.resolve())
    except ValueError as exc:
        raise DataColumnCastValidationError("source run is outside project runs") from exc
    if not run_root.is_dir():
        raise DataColumnCastValidationError("source run was not found")
    from .graph_store import GraphStore

    graph = GraphStore(runs_root).read(spec.source_run_id)
    try:
        node = graph.nodes[spec.source_node_id]
    except KeyError as exc:
        raise DataColumnCastValidationError("source graph node was not found") from exc
    if node.kind != NodeKind.DATASET_STAGE:
        raise DataColumnCastValidationError("source node must be a dataset_stage node")
    index = read_json(run_root / "artifacts_index.json")
    records = index.get("artifacts", [])
    try:
        artifact = next(
            item for item in records if item.get("artifact_id") == spec.source_artifact_id
        )
    except StopIteration as exc:
        raise DataColumnCastValidationError("source artifact was not found") from exc
    relative = artifact.get("path")
    if not isinstance(relative, str) or not relative:
        raise DataColumnCastValidationError("source artifact has no path")
    source_path = (run_root / relative).resolve()
    try:
        source_path.relative_to(run_root.resolve())
    except ValueError as exc:
        raise DataColumnCastValidationError("source artifact escapes run root") from exc
    if not source_path.is_file():
        raise DataColumnCastValidationError("source artifact file is missing")
    expected_sha = artifact.get("sha256")
    actual_sha = sha256_file(source_path)
    if expected_sha and expected_sha != actual_sha:
        raise DataColumnCastValidationError("source artifact fingerprint changed")
    if node.payload_ref and node.payload_ref != relative:
        raise DataColumnCastValidationError("source node payload does not match artifact")
    return run_root, graph, node, artifact, source_path


def _ensure_registered_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> None:
    index_path = run_root / "artifacts_index.json"
    index = read_json(index_path)
    existing = [item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id]
    if existing:
        if len(existing) != 1 or existing[0].get("sha256") != sha256_file(path):
            raise DataColumnCastValidationError("artifact binding is not deterministic")
        return
    register_artifact(run_root, artifact_id, path, artifact_type, step, inputs)


def _ensure_node_index_entry(
    run_root: Path,
    *,
    child_node_id: str,
    node_hash: str,
    artifact_rel: str,
    producing_stage: str = "data.column.cast",
    create_if_missing: bool = False,
) -> None:
    """Give the derived child node a Merkle identity in node_index.json.

    The derived artifact's content hash is the child's natural identity (same
    convention as stage:raw using the upload hash). Legacy runs without a
    node_index stay opaque unless the operation explicitly opts into creating a
    child-only index. New typed data-management operations use that opt-in so
    their graph nodes remain addressable even when the source run predates the
    incremental lineage index.
    """

    from .lineage.node_index import NODE_INDEX_FILENAME

    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        if not create_if_missing:
            return
        index = {}
    else:
        index = read_json(index_path)
    entry = {
        "node_hash": node_hash,
        "producing_stage": producing_stage,
        "cas_ref": {"node_hash": node_hash, "artifact": artifact_rel},
    }
    existing = index.get(child_node_id)
    if existing == entry:
        return
    if existing is not None:
        raise DataColumnCastValidationError("node index entry is not deterministic")
    index[child_node_id] = entry
    write_json(index_path, index)


def _mark_downstream_invalidation(
    nodes: dict[str, Node],
    *,
    reason: str,
    source_node_id: str,
    child_node_id: str,
) -> dict[str, Node]:
    """Flag every model node as needing a rerun after an upstream data operation.

    Shared by every data operation that derives a new dataset child, so a new
    operation cannot silently forget to invalidate what it invalidated.
    """

    updated = dict(nodes)
    for node_id, node in tuple(updated.items()):
        if node_id == child_node_id or node.kind != NodeKind.MODEL:
            continue
        annotations = tuple(node.annotations) + (
            {
                "type": "downstream_invalidation",
                "reason": reason,
                "source_node_id": source_node_id,
                "child_node_id": child_node_id,
                "rerun_required": True,
            },
        )
        updated[node_id] = Node(
            id=node.id,
            kind=node.kind,
            display_label=node.display_label,
            created_at=node.created_at,
            parent_stage_id=node.parent_stage_id,
            branch_id=node.branch_id,
            trust=Trust.CAUTION,
            trust_reason="data source changed; rerun required",
            archived=node.archived,
            payload_ref=node.payload_ref,
            decision_points=node.decision_points,
            summary=node.summary,
            annotations=annotations,
            stage=node.stage,
        )
    return updated


def _graph_store_for(run_root: Path):
    from .graph_store import GraphStore

    return GraphStore(run_root.parent)


def _commit_graph_child(
    graph: Graph,
    *,
    spec: DataColumnCastSpecV1,
    preview: DataColumnCastPreview,
    artifact_rel: str,
    recipe_rel: str,
    child_node_id: str,
    execution_key: str,
    node_hash: str,
) -> Graph:
    branch_id = f"data-cast:{execution_key.removeprefix('exec_')[:20]}"
    child = Node(
        id=child_node_id,
        kind=NodeKind.DATASET_STAGE,
        display_label=f"Cast {spec.column} → {spec.target_dtype}",
        created_at=datetime.now(timezone.utc).isoformat(),
        parent_stage_id=spec.source_node_id,
        branch_id=branch_id,
        trust=Trust.OK,
        payload_ref=artifact_rel,
        summary=(
            f"{spec.column}: {preview.before_dtype} → {preview.after_dtype}; "
            f"{preview.row_count} rows; downstream rerun required"
        ),
        annotations=(
            {
                "type": "data_operation",
                "operation_id": spec.operation_id,
                "execution_key": execution_key,
                "recipe_path": recipe_rel,
                "schema_fingerprint": preview.schema_fingerprint_after,
            },
        ),
        stage=Stage.TRANSFORM,
        node_hash=node_hash,
    )
    nodes = dict(graph.nodes)
    nodes[child_node_id] = child
    nodes = _mark_downstream_invalidation(
        nodes,
        reason="data_column_cast",
        source_node_id=spec.source_node_id,
        child_node_id=child_node_id,
    )
    edges = dict(graph.edges)
    edge_id = f"edge:{child_node_id}"
    edges[edge_id] = Edge(
        id=edge_id,
        source_id=spec.source_node_id,
        target_id=child_node_id,
        op=spec.operation_id,
        params={
            "column": spec.column,
            "target_dtype": spec.target_dtype,
            "execution_key": execution_key,
            "schema_fingerprint_before": preview.schema_fingerprint_before,
            "schema_fingerprint_after": preview.schema_fingerprint_after,
        },
    )
    branches = dict(graph.branches)
    branches[branch_id] = BranchRef(
        id=branch_id,
        forked_from_node_id=spec.source_node_id,
        head_node_ids=(child_node_id,),
    )
    return Graph(
        schema_version=graph.schema_version,
        run_id=graph.run_id,
        nodes=nodes,
        edges=edges,
        branches=branches,
        legacy=graph.legacy,
    )


def _commit_feature_recipe_graph_child(
    graph: Graph,
    *,
    spec: FeatureRecipeOperationSpecV1,
    preview: FeatureRecipePreview,
    artifact_rel: str,
    recipe_rel: str,
    child_node_id: str,
    execution_key: str,
    node_hash: str,
) -> Graph:
    branch_id = f"feature-recipe:{execution_key.removeprefix('exec_')[:20]}"
    child = Node(
        id=child_node_id,
        kind=NodeKind.DATASET_STAGE,
        display_label=f"Derived {spec.recipe.operation_id}",
        created_at=datetime.now(timezone.utc).isoformat(),
        parent_stage_id=spec.source_node_id,
        branch_id=branch_id,
        trust=Trust.OK,
        payload_ref=artifact_rel,
        summary=(
            f"{spec.recipe.operation_id} → {', '.join(spec.recipe.outputs)}; "
            f"{preview.row_count} rows; downstream rerun required"
        ),
        annotations=(
            {
                "type": "data_operation",
                "operation_id": spec.recipe.operation_id,
                "execution_key": execution_key,
                "recipe_path": recipe_rel,
                "schema_fingerprint": preview.schema_fingerprint_after,
                "typed_payload": spec.recipe.to_dict(),
            },
        ),
        stage=Stage.TRANSFORM,
        node_hash=node_hash,
    )
    nodes = _mark_downstream_invalidation(
        {**graph.nodes, child_node_id: child},
        reason="feature_recipe",
        source_node_id=spec.source_node_id,
        child_node_id=child_node_id,
    )
    edges = dict(graph.edges)
    edge_id = f"edge:{child_node_id}"
    edges[edge_id] = Edge(
        id=edge_id,
        source_id=spec.source_node_id,
        target_id=child_node_id,
        op=spec.operation_id,
        params={
            "recipe_operation_id": spec.recipe.operation_id,
            "recipe_id": spec.recipe.recipe_id,
            "execution_key": execution_key,
            "schema_fingerprint_before": preview.schema_fingerprint_before,
            "schema_fingerprint_after": preview.schema_fingerprint_after,
        },
    )
    branches = dict(graph.branches)
    branches[branch_id] = BranchRef(
        id=branch_id,
        forked_from_node_id=spec.source_node_id,
        head_node_ids=(child_node_id,),
    )
    return Graph(
        schema_version=graph.schema_version,
        run_id=graph.run_id,
        nodes=nodes,
        edges=edges,
        branches=branches,
        legacy=graph.legacy,
    )


def _commit_data_transform_graph_child(
    graph: Graph,
    *,
    spec: DataTransformSpecV1,
    preview: DataTransformPreview,
    artifact_rel: str,
    recipe_rel: str,
    child_node_id: str,
    execution_key: str,
    node_hash: str,
    secondary_graph: Graph | None = None,
    secondary_node: Node | None = None,
) -> Graph:
    branch_id = f"data-{spec.operation}:{execution_key.removeprefix('exec_')[:20]}"
    child = Node(
        id=child_node_id,
        kind=NodeKind.DATASET_STAGE,
        display_label=f"{spec.operation.title()} data",
        created_at=datetime.now(timezone.utc).isoformat(),
        parent_stage_id=spec.source_node_id,
        branch_id=branch_id,
        trust=Trust.OK,
        payload_ref=artifact_rel,
        summary=(
            f"{spec.operation}: {preview.row_count_before} → {preview.row_count_after} rows; "
            "downstream rerun required"
        ),
        annotations=(
            {
                "type": "data_operation",
                "operation_id": f"data.{spec.operation}",
                "execution_key": execution_key,
                "recipe_path": recipe_rel,
                "schema_fingerprint": preview.schema_fingerprint_after,
                "typed_payload": spec.to_dict(),
            },
        ),
        stage=Stage.TRANSFORM,
        node_hash=node_hash,
    )
    nodes = {**graph.nodes, child_node_id: child}
    secondary_id: str | None = None
    if spec.secondary_node_id and spec.secondary_run_id:
        if spec.secondary_run_id == graph.run_id and spec.secondary_node_id in nodes:
            secondary_id = spec.secondary_node_id
        else:
            if secondary_graph is None or secondary_node is None:
                raise DataColumnCastValidationError(
                    "merge/append secondary graph projection is unavailable"
                )
            secondary_id = f"{spec.secondary_run_id}:{spec.secondary_node_id}"
            nodes.setdefault(
                secondary_id,
                Node(
                    id=secondary_id,
                    kind=secondary_node.kind,
                    display_label=secondary_node.display_label,
                    created_at=secondary_node.created_at,
                    parent_stage_id=None,
                    branch_id=f"external:{spec.secondary_run_id}",
                    trust=secondary_node.trust,
                    trust_reason=secondary_node.trust_reason,
                    archived=secondary_node.archived,
                    payload_ref=None,
                    summary=(
                        f"External input from run {spec.secondary_run_id}; "
                        f"artifact {spec.secondary_artifact_id}"
                    ),
                    annotations=(
                        {
                            "type": "external_input",
                            "external_run_id": spec.secondary_run_id,
                            "external_node_id": spec.secondary_node_id,
                            "external_artifact_id": spec.secondary_artifact_id,
                            "external_payload_ref": secondary_node.payload_ref,
                        },
                    ),
                    stage=secondary_node.stage,
                    node_hash=secondary_node.node_hash,
                ),
            )
    nodes = _mark_downstream_invalidation(
        nodes,
        reason=f"data_{spec.operation}",
        source_node_id=spec.source_node_id,
        child_node_id=child_node_id,
    )
    edges = dict(graph.edges)
    edge_id = f"edge:{child_node_id}"
    edges[edge_id] = Edge(
        id=edge_id,
        source_id=spec.source_node_id,
        target_id=child_node_id,
        op=f"data.{spec.operation}",
        params={"execution_key": execution_key, "parameters": dict(spec.parameters)},
    )
    if secondary_id is not None:
        edges[f"edge:{child_node_id}:secondary"] = Edge(
            id=f"edge:{child_node_id}:secondary",
            source_id=secondary_id,
            target_id=child_node_id,
            op=f"data.{spec.operation}",
            params={
                "role": "secondary_input",
                "execution_key": execution_key,
                "run_id": spec.secondary_run_id,
                "node_id": spec.secondary_node_id,
                "artifact_id": spec.secondary_artifact_id,
            },
        )
    branches = dict(graph.branches)
    branches[branch_id] = BranchRef(branch_id, spec.source_node_id, (child_node_id,))
    return Graph(
        schema_version=graph.schema_version,
        run_id=graph.run_id,
        nodes=nodes,
        edges=edges,
        branches=branches,
        legacy=graph.legacy,
    )


def _read_frame(path: Path) -> pd.DataFrame:
    """Read a tabular artifact, restoring exact dtypes from a schema sidecar.

    CSV and Excel both lose pandas dtypes on read (a string column of digits
    re-infers as int64). When a derived artifact was written by a data
    operation we co-locate a ``<stem>.schema.json`` recording the exact dtypes,
    so re-reads (e.g. a chained cast on a cast child) are dtype-exact. Source
    artifacts without a sidecar (parquet is already self-describing) read as
    before.
    """

    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path)
    elif suffix in {".parquet", ".pq"}:
        frame = pd.read_parquet(path)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        raise DataColumnCastValidationError(
            f"unsupported tabular artifact format: {path.suffix or '<none>'}"
        )
    return _apply_schema_sidecar(path, frame)


def _schema_sidecar_path(data_path: Path) -> Path:
    return data_path.with_name(data_path.stem + _SCHEMA_SIDECAR_SUFFIX)


def _apply_schema_sidecar(data_path: Path, frame: pd.DataFrame) -> pd.DataFrame:
    sidecar = _schema_sidecar_path(data_path)
    if not sidecar.is_file():
        return frame
    dtypes = read_json(sidecar).get("dtypes", {})
    for column, dtype in dtypes.items():
        if column in frame.columns:
            frame[column] = _coerce_to_dtype(frame[column], str(dtype))
    return frame


def _coerce_to_dtype(series: pd.Series, dtype: str) -> pd.Series:
    if dtype.startswith("datetime64"):
        return pd.to_datetime(series, errors="coerce")
    try:
        return series.astype(dtype)
    except (TypeError, ValueError):
        return series


def _frame_dtypes(frame: pd.DataFrame) -> dict[str, str]:
    return {str(name): str(frame[name].dtype) for name in frame.columns}


def _write_frame_artifact(data_path: Path, frame: pd.DataFrame, fmt: str) -> None:
    """Write the derived data file plus its dtype sidecar, idempotently.

    The sidecar is written first so a crash never leaves a data file without
    its schema. The existence guard compares by re-read frame equality (not raw
    bytes) because xlsx serialization is not byte-deterministic.
    """

    write_json(_schema_sidecar_path(data_path), {"dtypes": _frame_dtypes(frame)})
    if data_path.exists():
        if not _read_frame(data_path).equals(frame):
            raise DataColumnCastValidationError(
                "deterministic cast artifact path is occupied"
            )
        return
    if fmt == "csv":
        write_text_durable(data_path, frame.to_csv(index=False))
    elif fmt == "xlsx":
        import io

        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        write_bytes_durable(data_path, buffer.getvalue())
    else:
        raise DataColumnCastValidationError(f"unsupported output format: {fmt!r}")


def _convert_strict(series: pd.Series, target_dtype: DataCastTarget) -> tuple[pd.Series, pd.Series]:
    if target_dtype == "numeric":
        converted = pd.to_numeric(series, errors="coerce")
    elif target_dtype == "datetime":
        converted = pd.to_datetime(series, errors="coerce")
    else:
        converted = series.astype("string")
    failures = series.notna() & converted.isna()
    return converted, failures


def _schema_fingerprint(frame: pd.DataFrame) -> str:
    payload = {
        "columns": [{"name": str(name), "dtype": str(frame[name].dtype)} for name in frame.columns],
        "row_count": len(frame),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "ALLOWED_CAST_TARGETS",
    "DataColumnCastPreview",
    "DataColumnCastSpecV1",
    "DataColumnCastValidationError",
    "DataColumnCastEffect",
    "DataCastItem",
    "DataColumnsCastSpecV1",
    "DataColumnCastItemResult",
    "DataColumnsCastPreview",
    "DataColumnsCastEffect",
    "apply_data_column_cast",
    "apply_data_columns_cast",
    "data_column_cast_execution_key",
    "data_columns_cast_execution_key",
    "preview_data_column_cast",
    "preview_data_columns_cast",
    "resolve_data_column_cast_context",
]
