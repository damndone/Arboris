"""Table transforms (merge, append, reshape, subset, dedupe, rename, aggregate, fill, tsset, lag)."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
import numpy as np
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
from .specs import AGGREGATE_FUNCTIONS, DataColumnCastValidationError, DataTransformPreview, DataTransformSpecV1, FILL_MISSING_STRATEGIES, FeatureRecipeEffect, TSSET_FREQUENCIES
from .frames import _read_frame, _schema_fingerprint, _write_frame_artifact
from .common import _enforce_growth_policy, _growth_policy, _reject_unknown_parameters, _require_columns_exist, _require_nested_keys, _require_non_empty_string, _require_string_list, _schema_signature, _subset_filter_mask, _transform_source_spec
from .graph import _commit_data_transform_graph_child, _ensure_node_index_entry, _ensure_registered_artifact, _graph_store_for, _resolve_source


def _execute_append(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_merge(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_reshape(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_subset(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
    _reject_unknown_parameters(
        parameters,
        {"columns", "equals", "filters", "row_indices", "row_index_range", "row_range", "exclude_row_indices"},
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
    excluded = parameters.get("exclude_row_indices")
    if excluded is not None:
        # A named leave-out (e.g. high-influence rows): positions are counted
        # after the filters, like row_indices, and every other row is kept.
        if row_indices is not None or row_index_range is not None:
            raise DataColumnCastValidationError(
                "DATA_SUBSET_ROW_INDEX_INVALID: exclude_row_indices cannot be combined with row_indices or row_index_range"
            )
        if (
            not isinstance(excluded, list)
            or not excluded
            or any(type(index) is not int for index in excluded)
            or len(set(excluded)) != len(excluded)
            or any(index < 0 or index >= len(result) for index in excluded)
            or len(excluded) >= len(result)
        ):
            raise DataColumnCastValidationError(
                "DATA_SUBSET_ROW_INDEX_INVALID: exclude_row_indices must be unique, non-negative, in range, and keep at least one row"
            )
        keep = np.ones(len(result), dtype=bool)
        keep[excluded] = False
        result = result.iloc[keep]
    return result.reset_index(drop=True)


def _execute_dedupe(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
    _reject_unknown_parameters(parameters, {"columns", "keep"}, "dedupe")
    columns = _require_string_list(parameters.get("columns"), "dedupe.columns")
    _require_columns_exist(left, columns, "dedupe")
    keep = parameters.get("keep")
    if keep not in {"first", "last"}:
        raise DataColumnCastValidationError("dedupe.keep must be first or last")
    return left.drop_duplicates(subset=columns, keep=keep, ignore_index=True)


def _execute_rename(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_aggregate(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_fill_missing(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_tsset(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_lag(
    left: pd.DataFrame,
    parameters: Mapping[str, Any],
    right: pd.DataFrame | None = None,
) -> pd.DataFrame:
    parameters = dict(parameters)
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


def _execute_data_transform(
    left: pd.DataFrame,
    spec: DataTransformSpecV1,
    right: pd.DataFrame | None,
) -> pd.DataFrame:
    from ..data_operation_registry import get_data_operation

    declaration = get_data_operation(spec.operation)
    if declaration is None:
        raise DataColumnCastValidationError(f"unsupported data operation: {spec.operation}")
    if declaration.secondary_input and right is None:
        raise DataColumnCastValidationError(f"{spec.operation} requires a secondary frame")
    return declaration.run(left, dict(spec.parameters), right)


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
