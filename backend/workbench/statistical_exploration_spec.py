"""Typed, source-bound statistical exploration contracts. (spec)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Mapping, get_args


SCHEMA_VERSION = "statistical-exploration.v1"
STATA_QUANTILE_METHOD = "stata_summarize_detail_v1"

# Operations whose result is a per-variable summary of a row subset, so running
# them once per group is well defined. `corr` is excluded on purpose: a grouped
# correlation is a different result shape, and inventing one silently is how a
# request for pooled correlations would come back as something else.
GROUPABLE_OPERATIONS = frozenset({"summarize", "summarize_detail", "misstable", "tabulate"})


class StatisticalExplorationValidationError(ValueError):
    """Raised when a typed exploration request cannot be evaluated safely."""


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise StatisticalExplorationValidationError(
        f"filter value has unsupported type: {type(value).__name__}"
    )


ExplorationOperation = Literal[
    "summarize", "summarize_detail", "misstable", "tabulate", "corr", "derive_boolean", "scatter"
]
FilterOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte", "in", "not_in", "between"]
# Spellings with one meaning; models write them in every round.
_FILTER_SPELLINGS = {"ne": "neq", "le": "lte", "ge": "gte", "==": "eq", "!=": "neq", "<": "lt", "<=": "lte", ">": "gt", ">=": "gte"}


@dataclass(frozen=True)
class FilterSpec:
    column: str
    operator: str
    value: Any

    OPERATORS: ClassVar[frozenset[str]] = frozenset(get_args(FilterOperator))

    def __post_init__(self) -> None:
        if not isinstance(self.column, str) or not self.column.strip():
            raise StatisticalExplorationValidationError("filter column must be non-empty")
        object.__setattr__(self, "operator", _FILTER_SPELLINGS.get(self.operator, self.operator))
        if self.operator not in self.OPERATORS:
            raise StatisticalExplorationValidationError(
                f"filter operator is unsupported: {self.operator}"
            )
        _canonical_value(self.value)
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, (list, tuple)) or not self.value:
                raise StatisticalExplorationValidationError(
                    f"filter operator {self.operator} requires a non-empty list value"
                )
        if self.operator == "between" and (not isinstance(self.value, (list, tuple)) or len(self.value) != 2):
            raise StatisticalExplorationValidationError("filter operator between requires [low, high]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "operator": self.operator,
            "value": _canonical_value(self.value),
        }


@dataclass(frozen=True)
class ExplorationSpec:
    operation: str
    selected_columns: tuple[str, ...]
    filters: tuple[FilterSpec, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)
    derived_definitions: tuple[Mapping[str, Any], ...] = ()

    OPERATIONS: ClassVar[frozenset[str]] = frozenset(get_args(ExplorationOperation))

    def __post_init__(self) -> None:
        if self.operation not in self.OPERATIONS:
            raise StatisticalExplorationValidationError(
                f"exploration operation is unsupported: {self.operation}"
            )
        columns = tuple(self.selected_columns)
        if any(not isinstance(column, str) or not column.strip() for column in columns):
            raise StatisticalExplorationValidationError(
                "selected columns must contain non-empty names"
            )
        if len(set(columns)) != len(columns):
            raise StatisticalExplorationValidationError(
                "selected columns must not contain duplicates"
            )
        if not all(isinstance(item, FilterSpec) for item in self.filters):
            raise StatisticalExplorationValidationError("filters must be FilterSpec values")
        if not isinstance(self.options, Mapping):
            raise StatisticalExplorationValidationError("options must be a mapping")
        _canonical_value(self.options)
        if 'frequency_weight' in self.options:
            if self.operation != 'tabulate':
                raise StatisticalExplorationValidationError('frequency_weight is supported only for tabulate; it cannot be ignored by another operation')
            if not isinstance(self.options['frequency_weight'], str) or not self.options['frequency_weight'].strip():
                raise StatisticalExplorationValidationError('frequency_weight must name a count column')
        if not isinstance(self.derived_definitions, (list, tuple)):
            raise StatisticalExplorationValidationError(
                "derived definitions must be a list"
            )
        _canonical_value(self.derived_definitions)
        object.__setattr__(self, "selected_columns", columns)
        object.__setattr__(self, "filters", tuple(self.filters))
        object.__setattr__(self, "derived_definitions", tuple(self.derived_definitions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "operation": self.operation,
            "selected_columns": list(self.selected_columns),
            "filters": [item.to_dict() for item in self.filters],
            "options": _canonical_value(self.options),
            "derived_definitions": _canonical_value(self.derived_definitions),
        }


def canonical_spec_json(source_sha: str, spec: ExplorationSpec) -> str:
    if not isinstance(source_sha, str) or not source_sha:
        raise StatisticalExplorationValidationError("source SHA must be non-empty")
    return json.dumps(
        {"source_sha": source_sha, "spec": spec.to_dict()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def exploration_fingerprint(source_sha: str, spec: ExplorationSpec) -> str:
    return hashlib.sha256(canonical_spec_json(source_sha, spec).encode("utf-8")).hexdigest()
