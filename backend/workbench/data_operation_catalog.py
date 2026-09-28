"""Declarations of every data operation.

Each operation is declared once -- fields, schemas, the columns it reads and
produces, its validation, its executor, a worked example and a readable
description -- and every surface derives from the declaration: the HTTP
transform route, the Agent's workflow vocabulary and compile checks, and the
proposal summaries people read before confirming (see
``data_operation_registry``).

The executors live in ``data_operations`` beside their helpers; the contract
metadata below was moved here from the Agent's workflow contracts unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from . import data_operations as ops
from .data_operation_registry import DataOperationDeclaration, Labels, register_data_operation

# -- contract metadata (fields, schemas, enums) -------------------------------

_AGGREGATE_CONTRACT = {'summary': 'Aggregate rows by declared groups and named functions.',
 'fields': {'group_by': 'Group-key columns.', 'aggregations': 'Named aggregation declarations.'},
 'required': ('group_by', 'aggregations'),
 'field_types': {'group_by': 'list', 'aggregations': 'list'},
 'field_schemas': {'group_by': {'type': 'array',
                                'minItems': 1,
                                'uniqueItems': True,
                                'items': {'type': 'string', 'minLength': 1}},
                   'aggregations': {'type': 'array',
                                    'minItems': 1,
                                    'items': {'type': 'object',
                                              'required': ['column', 'func', 'output'],
                                              'properties': {'column': {'type': 'string', 'minLength': 1},
                                                             'func': {'type': 'string',
                                                                      'enum': ['sum',
                                                                               'mean',
                                                                               'median',
                                                                               'min',
                                                                               'max',
                                                                               'count',
                                                                               'std']},
                                                             'output': {'type': 'string', 'minLength': 1}},
                                              'additionalProperties': False}}},
 'field_enums': {},
 'natural_language_enabled': False}

_APPEND_CONTRACT = {'summary': 'Append a declared secondary dataset with an explicit schema policy.',
 'fields': {'secondary_run_id': 'Real run id for the secondary dataset, discovered from project evidence.',
            'secondary_node_id': 'Real graph node id for the secondary dataset.',
            'secondary_artifact_id': 'Real artifact-index id for the secondary dataset.',
            'schema_policy': 'Schema policy: exact or union.',
            'row_growth_policy': 'Explicit row-growth bound.',
            'max_growth_factor': 'Legacy growth-factor bound.'},
 'required': ('secondary_run_id', 'secondary_node_id', 'secondary_artifact_id'),
 'field_types': {'secondary_run_id': 'string',
                 'secondary_node_id': 'string',
                 'secondary_artifact_id': 'string',
                 'schema_policy': 'string',
                 'row_growth_policy': 'object',
                 'max_growth_factor': 'number'},
 'field_schemas': {'secondary_run_id': {'type': 'string', 'minLength': 1},
                   'secondary_node_id': {'type': 'string', 'minLength': 1},
                   'secondary_artifact_id': {'type': 'string', 'minLength': 1},
                   'schema_policy': {'type': 'string', 'enum': ['exact', 'union']},
                   'row_growth_policy': {'type': 'object',
                                         'properties': {'max_rows': {'type': 'integer', 'minimum': 0},
                                                        'max_growth_factor': {'type': 'number',
                                                                              'exclusiveMinimum': 0}},
                                         'additionalProperties': False,
                                         'minProperties': 1},
                   'max_growth_factor': {'type': 'number', 'exclusiveMinimum': 0}},
 'field_enums': {'schema_policy': ('exact', 'union')},
 'natural_language_enabled': True}

_DEDUPE_CONTRACT = {'summary': 'Remove duplicate rows using an explicit key and keep policy.',
 'fields': {'columns': 'Deduplication key columns.', 'keep': 'first or last occurrence.'},
 'required': ('columns', 'keep'),
 'field_types': {'columns': 'list', 'keep': 'string'},
 'field_schemas': {'columns': {'type': 'array',
                               'minItems': 1,
                               'uniqueItems': True,
                               'items': {'type': 'string', 'minLength': 1}},
                   'keep': {'type': 'string', 'enum': ['first', 'last']}},
 'field_enums': {},
 'natural_language_enabled': False}

_FILL_MISSING_CONTRACT = {'summary': 'Resolve missing values with an explicit per-column strategy.',
 'fields': {'strategies': 'Per-column drop, constant, mean, median, or mode strategies.'},
 'required': ('strategies',),
 'field_types': {'strategies': 'list'},
 'field_schemas': {'strategies': {'type': 'array',
                                  'minItems': 1,
                                  'items': {'type': 'object',
                                            'required': ['column', 'strategy'],
                                            'properties': {'column': {'type': 'string', 'minLength': 1},
                                                           'strategy': {'type': 'string',
                                                                        'enum': ['drop_rows',
                                                                                 'constant',
                                                                                 'mean',
                                                                                 'median',
                                                                                 'mode']},
                                                           'value': {}},
                                            'additionalProperties': False}}},
 'field_enums': {},
 'natural_language_enabled': False}

_LAG_CONTRACT = {'summary': 'Create deterministic lag columns from an ordered dataset.',
 'fields': {'columns': 'Columns to lag.',
            'lags': 'Positive integer lag periods.',
            'difference': 'Optional non-negative difference order before lagging.'},
 'required': ('columns', 'lags'),
 'field_types': {'columns': 'list', 'lags': 'list', 'difference': 'integer'},
 'field_schemas': {'columns': {'type': 'array',
                               'minItems': 1,
                               'uniqueItems': True,
                               'items': {'type': 'string', 'minLength': 1}},
                   'lags': {'type': 'array',
                            'minItems': 1,
                            'uniqueItems': True,
                            'items': {'type': 'integer', 'minimum': 1}},
                   'difference': {'type': 'integer', 'minimum': 0}},
 'field_enums': {},
 'natural_language_enabled': False}

_MERGE_CONTRACT = {'summary': 'Merge the current dataset with a declared secondary dataset.',
 'fields': {'secondary_run_id': 'Real run id for the secondary dataset, discovered from project evidence.',
            'secondary_node_id': 'Real graph node id for the secondary dataset.',
            'secondary_artifact_id': 'Real artifact-index id for the secondary dataset.',
            'keys': 'Non-empty join-key column list present in both datasets.',
            'how': 'Join mode: left, right, inner, or outer.',
            'indicator': 'Optional true or a non-empty output-column name.',
            'growth_policy': 'Explicit row-growth bound.',
            'max_growth_factor': 'Legacy growth-factor bound.'},
 'required': ('secondary_run_id', 'secondary_node_id', 'secondary_artifact_id', 'keys'),
 'field_types': {'secondary_run_id': 'string',
                 'secondary_node_id': 'string',
                 'secondary_artifact_id': 'string',
                 'keys': 'list',
                 'how': 'string',
                 'growth_policy': 'object',
                 'max_growth_factor': 'number'},
 'field_schemas': {'secondary_run_id': {'type': 'string', 'minLength': 1},
                   'secondary_node_id': {'type': 'string', 'minLength': 1},
                   'secondary_artifact_id': {'type': 'string', 'minLength': 1},
                   'keys': {'type': 'array',
                            'minItems': 1,
                            'uniqueItems': True,
                            'items': {'type': 'string', 'minLength': 1}},
                   'how': {'type': 'string', 'enum': ['left', 'right', 'inner', 'outer']},
                   'indicator': {'type': ['boolean', 'string'], 'minLength': 1},
                   'growth_policy': {'type': 'object',
                                     'properties': {'max_rows': {'type': 'integer', 'minimum': 0},
                                                    'max_growth_factor': {'type': 'number',
                                                                          'exclusiveMinimum': 0}},
                                     'additionalProperties': False,
                                     'minProperties': 1},
                   'max_growth_factor': {'type': 'number', 'exclusiveMinimum': 0}},
 'field_enums': {'how': ('left', 'right', 'inner', 'outer')},
 'natural_language_enabled': True}

_RENAME_CONTRACT = {'summary': 'Rename existing columns with collision-checked mapping.',
 'fields': {'mapping': 'Non-empty old-column to new-column mapping.'},
 'required': ('mapping',),
 'field_types': {'mapping': 'object'},
 'field_schemas': {'mapping': {'type': 'object',
                               'minProperties': 1,
                               'additionalProperties': {'type': 'string', 'minLength': 1}}},
 'field_enums': {},
 'natural_language_enabled': False}

_RESHAPE_CONTRACT = {'summary': 'Reshape the current dataset with an explicitly declared direction.',
 'fields': {'direction': 'Direction: wide_to_long or long_to_wide.',
            'id_columns': 'Identifier columns for wide_to_long.',
            'value_columns': 'Measured wide columns for wide_to_long.',
            'index': 'Index columns for long_to_wide.',
            'columns': 'Long-form column containing wide labels.',
            'values': 'Long-form value column.',
            'var_name': 'Output variable-name column for wide_to_long.',
            'value_name': 'Output value column for wide_to_long.'},
 'required': ('direction',),
 'field_types': {'direction': 'string',
                 'id_columns': 'list',
                 'value_columns': 'list',
                 'index': 'list',
                 'columns': 'string',
                 'values': 'string',
                 'var_name': 'string',
                 'value_name': 'string'},
 'field_schemas': {'direction': {'type': 'string', 'enum': ['wide_to_long', 'long_to_wide']},
                   'id_columns': {'type': 'array',
                                  'minItems': 1,
                                  'uniqueItems': True,
                                  'items': {'type': 'string', 'minLength': 1}},
                   'value_columns': {'type': 'array',
                                     'minItems': 1,
                                     'uniqueItems': True,
                                     'items': {'type': 'string', 'minLength': 1}},
                   'index': {'type': 'array',
                             'minItems': 1,
                             'uniqueItems': True,
                             'items': {'type': 'string', 'minLength': 1}},
                   'columns': {'type': 'string', 'minLength': 1},
                   'values': {'type': 'string', 'minLength': 1},
                   'var_name': {'type': 'string', 'minLength': 1},
                   'value_name': {'type': 'string', 'minLength': 1}},
 'field_enums': {'direction': ('wide_to_long', 'long_to_wide')},
 'natural_language_enabled': True}

_SUBSET_CONTRACT = {'summary': 'Subset rows and columns with closed comparison operators.',
 'fields': {'columns': 'Explicit output columns.',
            'filters': 'ANDed closed filters with column, op, and operator value.',
            'equals': 'Legacy equality map retained for compatibility.',
            'row_indices': 'Explicit zero-based row indices.',
            'row_index_range': 'Bounded half-open row range.',
            'row_range': 'Legacy alias for row_index_range.'},
 'required': ('columns',),
 'field_types': {'columns': 'list',
                 'filters': 'list',
                 'equals': 'object',
                 'row_indices': 'list',
                 'row_index_range': 'object',
                 'row_range': 'object'},
 'field_schemas': {'columns': {'type': 'array',
                               'minItems': 1,
                               'uniqueItems': True,
                               'items': {'type': 'string', 'minLength': 1}},
                   'filters': {'type': 'array',
                               'items': {'type': 'object',
                                         'required': ['column', 'op'],
                                         'properties': {'column': {'type': 'string', 'minLength': 1},
                                                        'op': {'type': 'string',
                                                               'enum': ['eq',
                                                                        'ne',
                                                                        'gt',
                                                                        'ge',
                                                                        'lt',
                                                                        'le',
                                                                        'in',
                                                                        'not_in',
                                                                        'between',
                                                                        'is_missing',
                                                                        'not_missing']},
                                                        'value': {}},
                                         'additionalProperties': False}},
                   'equals': {'type': 'object', 'additionalProperties': {}},
                   'row_indices': {'type': 'array',
                                   'minItems': 1,
                                   'uniqueItems': True,
                                   'items': {'type': 'integer', 'minimum': 0}},
                   'row_index_range': {'type': 'object',
                                       'required': ['start', 'stop'],
                                       'properties': {'start': {'type': 'integer', 'minimum': 0},
                                                      'stop': {'type': 'integer', 'minimum': 0}},
                                       'additionalProperties': False},
                   'row_range': {'type': 'object',
                                 'required': ['start', 'stop'],
                                 'properties': {'start': {'type': 'integer', 'minimum': 0},
                                                'stop': {'type': 'integer', 'minimum': 0}},
                                 'additionalProperties': False}},
 'field_enums': {},
 'natural_language_enabled': True}

_TSSET_CONTRACT = {'summary': 'Declare and stably order a time or panel-time index.',
 'fields': {'time_column': 'Time column.',
            'frequency': 'Declared frequency: D, W, M, Q, or Y.',
            'panel_id_column': 'Optional panel identifier column.'},
 'required': ('time_column', 'frequency'),
 'field_types': {'time_column': 'string', 'frequency': 'string', 'panel_id_column': 'string'},
 'field_schemas': {'time_column': {'type': 'string', 'minLength': 1},
                   'frequency': {'type': 'string', 'enum': ['D', 'W', 'M', 'Q', 'Y']},
                   'panel_id_column': {'type': 'string', 'minLength': 1}},
 'field_enums': {'frequency': ('D', 'W', 'M', 'Q', 'Y')},
 'natural_language_enabled': False}


# -- readable descriptions ----------------------------------------------------


def _name(column: Any, labels: Labels) -> str:
    column = str(column)
    label = labels.get(column)
    return f"{column} ({label})" if label and label != column else column


def _names(columns: Sequence[Any], labels: Labels) -> str:
    return ", ".join(_name(column, labels) for column in columns)


def _value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value) if isinstance(value, str) else str(value)


_FILTER_WORDS = {
    "eq": "=", "ne": "≠", "gt": ">", "ge": "≥", "lt": "<", "le": "≤",
}


def _filter(item: Mapping[str, Any], labels: Labels) -> str:
    column, op = _name(item["column"], labels), item["op"]
    value = item.get("value")
    if op in _FILTER_WORDS:
        return f"{column} {_FILTER_WORDS[op]} {_value(value)}"
    if op == "between":
        return f"{column} is between {_value(value[0])} and {_value(value[1])}"
    if op in {"in", "not_in"}:
        values = ", ".join(_value(item) for item in value)
        return f"{column} is {'not ' if op == 'not_in' else ''}one of {values}"
    return f"{column} is {'not ' if op == 'not_missing' else ''}missing"


def _describe_subset(spec: Mapping[str, Any], labels: Labels) -> str:
    conditions = [_filter(item, labels) for item in spec.get("filters") or ()]
    conditions += [f"{_name(column, labels)} = {_value(value)}" for column, value in (spec.get("equals") or {}).items()]
    parts = [f"Keep rows where {' and '.join(conditions)}" if conditions else "Keep all rows"]
    if spec.get("row_indices") is not None:
        parts = [f"Keep rows {', '.join(str(index) for index in spec['row_indices'][:10])}"]
    elif spec.get("row_index_range") or spec.get("row_range"):
        span = spec.get("row_index_range") or spec.get("row_range")
        parts = [f"Keep rows {span.get('start', 0)} to {span.get('stop', 'end')}"]
    if spec.get("columns"):
        parts.append(f"columns {_names(spec['columns'], labels)}")
    return "; ".join(parts)


def _describe_merge(spec: Mapping[str, Any], labels: Labels) -> str:
    text = (
        f"Merge with {spec.get('secondary_node_id')} of run {spec.get('secondary_run_id')} "
        f"on {_names(spec.get('keys') or (), labels)} ({spec.get('how', 'left')} join)"
    )
    if spec.get("indicator") is not None:
        text += f", marking each row's source in {'_merge' if spec['indicator'] is True else spec['indicator']}"
    return text


def _describe_append(spec: Mapping[str, Any], labels: Labels) -> str:
    policy = spec.get("schema_policy", "exact")
    return (
        f"Append the rows of {spec.get('secondary_node_id')} of run {spec.get('secondary_run_id')} "
        + ("(columns must match exactly)" if policy == "exact" else "(union of columns; absent ones are missing)")
    )


def _describe_reshape(spec: Mapping[str, Any], labels: Labels) -> str:
    if spec.get("direction") == "wide_to_long":
        return (
            f"Reshape wide to long: stack {_names(spec.get('value_columns') or (), labels)} into "
            f"{spec.get('var_name', 'variable')} / {spec.get('value_name', 'value')}, "
            f"one row per {_names(spec.get('id_columns') or (), labels)} and column"
        )
    return (
        f"Reshape long to wide: one column per value of {_name(spec.get('columns'), labels)}, "
        f"holding {_name(spec.get('values'), labels)}, one row per {_names(spec.get('index') or (), labels)}"
    )


def _describe_dedupe(spec: Mapping[str, Any], labels: Labels) -> str:
    return f"Drop rows that repeat {_names(spec.get('columns') or (), labels)}, keeping the {spec.get('keep')} one"


def _describe_rename(spec: Mapping[str, Any], labels: Labels) -> str:
    return "Rename " + ", ".join(f"{_name(old, labels)} → {new}" for old, new in (spec.get("mapping") or {}).items())


def _describe_aggregate(spec: Mapping[str, Any], labels: Labels) -> str:
    parts = [
        f"{item['func']}({_name(item['column'], labels)}) as {item['output']}"
        for item in spec.get("aggregations") or ()
    ]
    return f"One row per {_names(spec.get('group_by') or (), labels)} with " + ", ".join(parts)


def _describe_fill_missing(spec: Mapping[str, Any], labels: Labels) -> str:
    parts = []
    for item in spec.get("strategies") or ():
        column, strategy = _name(item["column"], labels), item["strategy"]
        if strategy == "drop_rows":
            parts.append(f"drop rows missing {column}")
        elif strategy == "constant":
            parts.append(f"fill {column} with {_value(item.get('value'))}")
        else:
            parts.append(f"fill {column} with its {strategy}")
    return "Missing values: " + "; ".join(parts)


_FREQUENCY_WORDS = {"D": "daily", "W": "weekly", "M": "monthly", "Q": "quarterly", "Y": "yearly"}


def _describe_tsset(spec: Mapping[str, Any], labels: Labels) -> str:
    text = f"Declare {_FREQUENCY_WORDS.get(spec.get('frequency'), spec.get('frequency'))} time series on {_name(spec.get('time_column'), labels)}"
    if spec.get("panel_id_column"):
        text += f", panels by {_name(spec['panel_id_column'], labels)}"
    return text


def _describe_lag(spec: Mapping[str, Any], labels: Labels) -> str:
    lags = ", ".join(str(lag) for lag in spec.get("lags") or ())
    difference = spec.get("difference", 0)
    base = f"{difference}-period differences of " if difference else ""
    return f"Add lag{'s' if len(spec.get('lags') or ()) > 1 else ''} {lags} of {base}{_names(spec.get('columns') or (), labels)}"


def _rule_source(value: Any) -> str:
    if isinstance(value, Mapping):
        return f"{_value(value['low'])}–{_value(value['high'])}"
    return str(value) if value in {"missing", "else"} else _value(value)


def _describe_recode(spec: Mapping[str, Any], labels: Labels) -> str:
    rules = ", ".join(
        f"{_rule_source(rule['from'])} → {'missing' if rule['to'] is None else _value(rule['to'])}"
        for rule in spec.get("rules") or ()
    )
    return f"Recode {_name(spec.get('column'), labels)} into new variable {spec.get('output')}: {rules}"


# -- validation (moved from the Agent's workflow contracts) -------------------


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a non-empty string list")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def _validate_merge(spec: Mapping[str, Any]) -> None:
    _strings(spec.get("keys"), "keys")
    if spec.get("how", "left") not in {"left", "right", "inner", "outer"}:
        raise ValueError("how must be left, right, inner, or outer")
    indicator = spec.get("indicator")
    if indicator is not None and not (indicator is True or (isinstance(indicator, str) and indicator.strip())):
        raise ValueError("indicator must be true or a non-empty string")


def _validate_append(spec: Mapping[str, Any]) -> None:
    if spec.get("schema_policy", "exact") not in {"exact", "union"}:
        raise ValueError("schema_policy must be exact or union")


def _validate_reshape(spec: Mapping[str, Any]) -> None:
    direction = spec.get("direction")
    if direction == "wide_to_long":
        id_columns = _strings(spec.get("id_columns"), "id_columns")
        value_columns = _strings(spec.get("value_columns"), "value_columns")
        if set(id_columns) & set(value_columns):
            raise ValueError("id_columns and value_columns must be disjoint")
        if any(key in spec for key in ("index", "columns", "values")):
            raise ValueError("wide_to_long does not accept long_to_wide fields")
        var_name = _text(spec.get("var_name", "variable"), "var_name")
        value_name = _text(spec.get("value_name", "value"), "value_name")
        if var_name == value_name or var_name in id_columns or value_name in id_columns:
            raise ValueError("output names must not collide with id_columns")
    elif direction == "long_to_wide":
        index = _strings(spec.get("index"), "index")
        columns = _text(spec.get("columns"), "columns")
        values = _text(spec.get("values"), "values")
        if len(set(index + [columns, values])) != len(index) + 2:
            raise ValueError("index, columns, and values must be distinct")
        if any(key in spec for key in ("id_columns", "value_columns", "var_name", "value_name")):
            raise ValueError("long_to_wide does not accept wide_to_long fields")
    else:
        raise ValueError("direction must be wide_to_long or long_to_wide")


def _validate_subset(spec: Mapping[str, Any]) -> None:
    _strings(spec.get("columns"), "columns")
    filters = spec.get("filters", [])
    if not isinstance(filters, list):
        raise ValueError("filters must be a list")
    filter_columns: list[str] = []
    for index, item in enumerate(filters):
        if not isinstance(item, Mapping):
            raise ValueError(f"filters[{index}] must be an object")
        column = _text(item.get("column"), f"filters[{index}].column")
        operator = item.get("op")
        if operator not in ops.SUBSET_FILTER_OPERATORS:
            raise ValueError(f"filters[{index}].op is not a closed comparison operator")
        has_value = "value" in item
        if operator in {"is_missing", "not_missing"} and has_value:
            raise ValueError(f"filters[{index}] must not carry value for {operator}")
        if operator not in {"is_missing", "not_missing"} and not has_value:
            raise ValueError(f"filters[{index}] requires value for {operator}")
        if operator in {"in", "not_in"} and (not isinstance(item.get("value"), list) or not item["value"]):
            raise ValueError(f"filters[{index}] value must be a non-empty list")
        if operator == "between":
            value = item.get("value")
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError(f"filters[{index}] between requires two bounds")
            try:
                if value[0] > value[1]:
                    raise ValueError(f"filters[{index}] lower bound exceeds upper bound")
            except TypeError as exc:
                raise ValueError(f"filters[{index}] bounds are not comparable") from exc
        filter_columns.append(column)
    equals = spec.get("equals", {})
    if not isinstance(equals, Mapping):
        raise ValueError("equals must be an object")
    overlap = set(equals) & set(filter_columns)
    if overlap:
        raise ValueError(f"equals and filters overlap: {', '.join(sorted(overlap))}")
    if spec.get("row_indices") is not None and (
        spec.get("row_index_range") is not None or spec.get("row_range") is not None
    ):
        raise ValueError("row_indices and row range are mutually exclusive")


def _validate_dedupe(spec: Mapping[str, Any]) -> None:
    _strings(spec.get("columns"), "columns")
    if spec.get("keep") not in {"first", "last"}:
        raise ValueError("keep must be first or last")


def _validate_rename(spec: Mapping[str, Any]) -> None:
    mapping = spec.get("mapping")
    if not isinstance(mapping, Mapping) or not mapping:
        raise ValueError("mapping must be a non-empty object")
    old, new = list(mapping), list(mapping.values())
    if any(not isinstance(item, str) or not item.strip() for item in old + new):
        raise ValueError("mapping names must be non-empty strings")
    if len(set(new)) != len(new):
        raise ValueError("mapping values must be distinct")


def _validate_aggregate(spec: Mapping[str, Any]) -> None:
    group_by = _strings(spec.get("group_by"), "group_by")
    aggregations = spec.get("aggregations")
    if not isinstance(aggregations, list) or not aggregations:
        raise ValueError("aggregations must be non-empty")
    outputs: set[str] = set()
    for item in aggregations:
        if not isinstance(item, Mapping):
            raise ValueError("aggregation must be an object")
        if item.get("func") not in ops.AGGREGATE_FUNCTIONS:
            raise ValueError("aggregation function is not registered")
        output = _text(item.get("output"), "aggregation.output")
        if output in outputs or output in group_by:
            raise ValueError(f"aggregation output collides: {output}")
        outputs.add(output)


def _validate_fill_missing(spec: Mapping[str, Any]) -> None:
    strategies = spec.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ValueError("strategies must be non-empty")
    seen: set[str] = set()
    for item in strategies:
        if not isinstance(item, Mapping):
            raise ValueError("strategy must be an object")
        column = _text(item.get("column"), "strategy.column")
        strategy = item.get("strategy")
        if strategy not in ops.FILL_MISSING_STRATEGIES:
            raise ValueError("strategy is not registered")
        if column in seen:
            raise ValueError(f"declares duplicate column: {column}")
        seen.add(column)
        if strategy == "constant" and "value" not in item:
            raise ValueError("constant requires value")
        if strategy != "constant" and "value" in item:
            raise ValueError("value is only valid for constant")


def _validate_tsset(spec: Mapping[str, Any]) -> None:
    _text(spec.get("time_column"), "time_column")
    if spec.get("frequency") not in ops.TSSET_FREQUENCIES:
        raise ValueError("frequency is not registered")
    if spec.get("panel_id_column") == spec.get("time_column"):
        raise ValueError("panel and time columns must differ")


def _validate_lag(spec: Mapping[str, Any]) -> None:
    _strings(spec.get("columns"), "columns")
    lags = spec.get("lags")
    if not isinstance(lags, list) or not lags or any(
        type(lag) is not int or lag <= 0 for lag in lags
    ) or len(set(lags)) != len(lags):
        raise ValueError("lags must be unique positive integers")
    difference = spec.get("difference", 0)
    if type(difference) is not int or difference < 0:
        raise ValueError("difference must be non-negative")


# -- columns read and produced --------------------------------------------------


def _strs(values: Any) -> set[str]:
    return {str(item) for item in values or []}


def _subset_columns(spec: Mapping[str, Any]) -> set[str]:
    columns = _strs(spec.get("columns"))
    equals = spec.get("equals")
    if isinstance(equals, Mapping):
        columns |= _strs(equals)
    for item in spec.get("filters", []) or []:
        if isinstance(item, Mapping) and item.get("column"):
            columns.add(str(item["column"]))
    return columns


def _reshape_columns(spec: Mapping[str, Any]) -> set[str]:
    if spec.get("direction") == "wide_to_long":
        return _strs(spec.get("id_columns")) | _strs(spec.get("value_columns"))
    if spec.get("direction") == "long_to_wide":
        return _strs(spec.get("index")) | {str(spec[item]) for item in ("columns", "values") if spec.get(item)}
    return set()


def _reshape_outputs(spec: Mapping[str, Any], visible: set[str]) -> set[str]:
    if spec.get("direction") == "wide_to_long":
        return _strs(spec.get("id_columns")) | {str(spec.get("var_name", "variable")), str(spec.get("value_name", "value"))}
    # Long-to-wide output labels are data values, not declaration fields; keep
    # the deterministic index until runtime sees the materialized categories.
    return _strs(spec.get("index")) | {str(spec.get("values"))}


def _mapping_keys(spec: Mapping[str, Any], key: str) -> set[str]:
    value = spec.get(key)
    return _strs(value) if isinstance(value, Mapping) else set()


def _item_columns(spec: Mapping[str, Any], key: str) -> set[str]:
    return {str(item["column"]) for item in spec.get(key, []) or [] if isinstance(item, Mapping) and item.get("column")}


def _merge_outputs(spec: Mapping[str, Any], visible: set[str]) -> set[str]:
    # The secondary dataset's columns are a runtime-bound identity; the
    # projection keeps the known primary columns and a declared indicator.
    indicator = spec.get("indicator")
    if indicator is None:
        return set(visible)
    return {*visible, "_merge" if indicator is True else str(indicator)}


# -- declarations ----------------------------------------------------------------


def _declare(operation: str, contract: Mapping[str, Any], **parts: Any) -> None:
    register_data_operation(
        DataOperationDeclaration(
            operation=operation,
            summary=contract["summary"],
            fields=contract["fields"],
            required=tuple(contract["required"]),
            field_types=contract["field_types"],
            field_schemas=contract["field_schemas"],
            field_enums={name: tuple(values) for name, values in contract["field_enums"].items()},
            natural_language_enabled=contract["natural_language_enabled"],
            **parts,
        )
    )


def _frame(**columns: Any):
    return lambda: pd.DataFrame(columns)


_SECONDARY = {"secondary_run_id": "run_b", "secondary_node_id": "stage:raw", "secondary_artifact_id": "raw_b.csv"}

_declare(
    "merge", _MERGE_CONTRACT,
    referenced_columns=lambda spec: _strs(spec.get("keys")),
    output_columns=_merge_outputs,
    validate=_validate_merge,
    execute=ops._execute_merge,
    describe=_describe_merge,
    secondary_input=True,
    binding_fields=tuple(_SECONDARY),
    example={**_SECONDARY, "keys": ["id"], "how": "left"},
    example_frame=_frame(id=[1, 2, 3], x=[1.0, 2.0, 3.0]),
    example_secondary_frame=_frame(id=[1, 2, 3], region=["north", "south", "west"]),
)
_declare(
    "append", _APPEND_CONTRACT,
    referenced_columns=lambda spec: _strs(spec.get("keys")),
    output_columns=lambda spec, visible: set(visible),
    validate=_validate_append,
    execute=ops._execute_append,
    describe=_describe_append,
    secondary_input=True,
    binding_fields=tuple(_SECONDARY),
    example={**_SECONDARY, "schema_policy": "exact"},
    example_frame=_frame(id=[1, 2], x=[1.0, 2.0]),
    example_secondary_frame=_frame(id=[3, 4], x=[3.0, 4.0]),
)
_declare(
    "reshape", _RESHAPE_CONTRACT,
    referenced_columns=_reshape_columns,
    output_columns=_reshape_outputs,
    validate=_validate_reshape,
    execute=ops._execute_reshape,
    describe=_describe_reshape,
    example={"direction": "wide_to_long", "id_columns": ["id"], "value_columns": ["y2020", "y2021"],
             "var_name": "year", "value_name": "income"},
    example_frame=_frame(id=[1, 2], y2020=[10.0, 12.0], y2021=[11.0, 13.0]),
)
_declare(
    "subset", _SUBSET_CONTRACT,
    referenced_columns=_subset_columns,
    output_columns=lambda spec, visible: _strs(spec.get("columns")),
    validate=_validate_subset,
    execute=ops._execute_subset,
    describe=_describe_subset,
    example={"columns": ["id", "age"], "filters": [{"column": "age", "op": "between", "value": [25, 55]}]},
    example_frame=_frame(id=[1, 2, 3], age=[20.0, 30.0, 60.0], x=[1.0, 2.0, 3.0]),
)
_declare(
    "dedupe", _DEDUPE_CONTRACT,
    referenced_columns=lambda spec: _strs(spec.get("columns")),
    output_columns=lambda spec, visible: set(visible),
    validate=_validate_dedupe,
    execute=ops._execute_dedupe,
    describe=_describe_dedupe,
    example={"columns": ["id"], "keep": "first"},
    example_frame=_frame(id=[1, 1, 2], x=[1.0, 2.0, 3.0]),
)
_declare(
    "rename", _RENAME_CONTRACT,
    referenced_columns=lambda spec: _mapping_keys(spec, "mapping"),
    output_columns=lambda spec, visible: (visible - _mapping_keys(spec, "mapping"))
    | {str(value) for value in (spec.get("mapping") or {}).values()},
    validate=_validate_rename,
    execute=ops._execute_rename,
    describe=_describe_rename,
    example={"mapping": {"inc": "income"}},
    example_frame=_frame(id=[1, 2], inc=[10.0, 20.0]),
)
_declare(
    "aggregate", _AGGREGATE_CONTRACT,
    referenced_columns=lambda spec: _strs(spec.get("group_by")) | _item_columns(spec, "aggregations"),
    output_columns=lambda spec, visible: _strs(spec.get("group_by"))
    | {str(item["output"]) for item in spec.get("aggregations", []) if isinstance(item, Mapping) and item.get("output")},
    validate=_validate_aggregate,
    execute=ops._execute_aggregate,
    describe=_describe_aggregate,
    example={"group_by": ["region"], "aggregations": [{"column": "wage", "func": "mean", "output": "mean_wage"}]},
    example_frame=_frame(region=["north", "north", "south"], wage=[10.0, 12.0, 9.0]),
)
_declare(
    "fill_missing", _FILL_MISSING_CONTRACT,
    referenced_columns=lambda spec: _item_columns(spec, "strategies"),
    output_columns=lambda spec, visible: set(visible),
    validate=_validate_fill_missing,
    execute=ops._execute_fill_missing,
    describe=_describe_fill_missing,
    example={"strategies": [{"column": "hours", "strategy": "median"}]},
    example_frame=_frame(id=[1, 2, 3], hours=[40.0, None, 38.0]),
)
_declare(
    "tsset", _TSSET_CONTRACT,
    referenced_columns=lambda spec: {str(spec[key]) for key in ("time_column", "panel_id_column") if spec.get(key)},
    output_columns=lambda spec, visible: set(visible),
    validate=_validate_tsset,
    execute=ops._execute_tsset,
    describe=_describe_tsset,
    example={"time_column": "year", "frequency": "Y"},
    example_frame=_frame(year=[2020, 2021, 2022], gdp=[1.0, 1.1, 1.2]),
)
_declare(
    "lag", _LAG_CONTRACT,
    referenced_columns=lambda spec: _strs(spec.get("columns")),
    output_columns=lambda spec, visible: {*visible, *(f"{column}_lag{lag}" for column in spec.get("columns", []) for lag in spec.get("lags", []))},
    validate=_validate_lag,
    execute=ops._execute_lag,
    describe=_describe_lag,
    example={"columns": ["gdp"], "lags": [1]},
    example_frame=_frame(year=[2020, 2021, 2022], gdp=[1.0, 1.1, 1.2]),
)


def _declare_recode() -> None:
    code = {"anyOf": [{"type": "number"}, {"type": "string", "minLength": 1}, {"type": "null"}]}
    register_data_operation(
        DataOperationDeclaration(
            operation="recode",
            summary=(
                "Recode one variable into a NEW variable by ordered rules (SPSS RECODE "
                "INTO): single values, closed numeric ranges {low, high}, \"missing\", and "
                "a final \"else\". First matching rule wins; to: a code, null (missing) or "
                "\"copy\". Values no rule covers are refused unless an else rule exists."
            ),
            fields={
                "column": "Existing source column; it is not changed.",
                "output": "Name of the new variable; must not exist yet.",
                "rules": "Ordered list of {from, to}.",
            },
            required=("column", "output", "rules"),
            field_types={"column": "string", "output": "string", "rules": "list"},
            field_schemas={
                "column": {"type": "string", "minLength": 1},
                "output": {"type": "string", "minLength": 1},
                "rules": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["from", "to"],
                        "additionalProperties": False,
                        "properties": {
                            "from": {
                                "anyOf": [
                                    {"type": "number"},
                                    {"type": "string", "minLength": 1},
                                    {
                                        "type": "object",
                                        "required": ["low", "high"],
                                        "additionalProperties": False,
                                        "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                                    },
                                ]
                            },
                            "to": code,
                        },
                    },
                },
            },
            referenced_columns=lambda spec: {str(spec["column"])} if spec.get("column") else set(),
            output_columns=lambda spec, visible: visible | ({str(spec["output"])} if spec.get("output") else set()),
            validate=lambda spec: ops._recode_static_check(spec) and None,
            execute=ops._recode_into_new_column,
            describe=_describe_recode,
            example={
                "column": "age",
                "output": "age_group",
                "rules": [
                    {"from": {"low": 18, "high": 39}, "to": 1},
                    {"from": {"low": 40, "high": 120}, "to": 2},
                    {"from": "missing", "to": 9},
                ],
            },
            example_frame=lambda: pd.DataFrame({"age": [20.0, 45.0, None]}),
        )
    )


_declare_recode()
