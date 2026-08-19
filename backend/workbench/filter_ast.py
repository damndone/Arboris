"""Closed, typed predicates for bounded DataFrame filtering.

The public input is deliberately a small JSON-shaped tree.  Binding resolves
column names against a server-owned column set and freezes the tree into
dataclasses.  Execution then evaluates each leaf with an explicit pandas mask;
no expression language is involved.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from numbers import Integral, Real
from typing import Any, Literal, TypeAlias

import pandas as pd


FilterOperator = Literal[
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
    "not_in",
    "between",
    "is_missing",
    "not_missing",
]
LogicalOperator = Literal["and", "or", "not"]

FILTER_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "in",
        "not_in",
        "between",
        "is_missing",
        "not_missing",
    }
)
LOGICAL_OPERATORS = frozenset({"and", "or", "not"})
VALUE_OPERATORS = FILTER_OPERATORS - {"is_missing", "not_missing"}
ORDERED_OPERATORS = {"lt", "le", "gt", "ge", "between"}

MAX_FILTER_DEPTH = 8
MAX_FILTER_NODES = 64
MAX_FILTER_LIST_SIZE = 64
MAX_INTEGER_BITS = 256


class FilterValidationError(ValueError):
    """Raised when a filter tree or its typed execution is unsafe or invalid."""


# Keep the alternative spelling available to callers that use ``AST`` in the
# error name, while retaining one concrete exception type.
FilterASTError = FilterValidationError
FilterAstError = FilterValidationError


@dataclass(frozen=True)
class FilterLimits:
    """Resource limits applied while binding a filter tree."""

    max_depth: int = MAX_FILTER_DEPTH
    max_nodes: int = MAX_FILTER_NODES
    max_list_size: int = MAX_FILTER_LIST_SIZE

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_nodes", "max_list_size"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_FILTER_LIMITS = FilterLimits()
_MISSING = object()


@dataclass(frozen=True)
class FilterPredicate:
    """A single typed column predicate."""

    column: str
    op: str
    value: Any = _MISSING

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"column": self.column, "op": self.op}
        if self.value is not _MISSING:
            result["value"] = _literal_to_json(self.value)
        return result


@dataclass(frozen=True)
class FilterLogical:
    """A logical node with one child for ``not`` or many for ``and``/``or``."""

    op: str
    children: tuple["FilterNode", ...]

    def to_dict(self) -> dict[str, Any]:
        if self.op == "not":
            return {"op": self.op, "child": self.children[0].to_dict()}
        return {"op": self.op, "children": [child.to_dict() for child in self.children]}


FilterNode: TypeAlias = FilterPredicate | FilterLogical
FilterAST: TypeAlias = FilterNode
FilterExpression: TypeAlias = FilterNode


def _literal_to_json(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_literal_to_json(item) for item in value]
    return value


def _normalise_columns(columns: Iterable[str]) -> frozenset[str]:
    if isinstance(columns, (str, bytes)):
        raise FilterValidationError("server column set must be an iterable of column names")
    try:
        values = tuple(columns)
    except TypeError as exc:
        raise FilterValidationError("server column set must be an iterable of column names") from exc
    if any(not isinstance(column, str) or not column.strip() for column in values):
        raise FilterValidationError("server column set must contain non-empty strings")
    if len(set(values)) != len(values):
        raise FilterValidationError("server column set must not contain duplicates")
    return frozenset(values)


def _scalar_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, Integral):
        return "integer"
    if isinstance(value, Real):
        return "real"
    if isinstance(value, str):
        return "string"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, (timedelta, pd.Timedelta)):
        return "timedelta"
    return "unsupported"


def _normalise_scalar(value: Any, name: str) -> Any:
    if value is pd.NA or value is pd.NaT:
        raise FilterValidationError(f"{name} must use an explicit missing operator")
    kind = _scalar_kind(value)
    if kind == "unsupported":
        raise FilterValidationError(
            f"{name} must be a JSON-like scalar; arbitrary objects and expressions are not allowed"
        )
    if kind == "integer":
        normalised_integer = int(value)
        if normalised_integer.bit_length() > MAX_INTEGER_BITS:
            raise FilterValidationError(
                f"{name} exceeds the maximum integer size of {MAX_INTEGER_BITS} bits"
            )
        return normalised_integer
    if kind == "real":
        normalised = float(value)
        if not math.isfinite(normalised):
            raise FilterValidationError(f"{name} must be finite; NaN and Infinity are not allowed")
        return normalised
    return value


def _normalise_value(value: Any, name: str, *, list_allowed: bool, max_list_size: int) -> Any:
    if isinstance(value, list):
        if not list_allowed:
            raise FilterValidationError(f"{name} must be a scalar")
        if not value:
            raise FilterValidationError(f"{name} must be a non-empty list")
        if len(value) > max_list_size:
            raise FilterValidationError(
                f"{name} exceeds the maximum filter list size of {max_list_size}"
            )
        return tuple(
            _normalise_scalar(item, f"{name}[{index}]") for index, item in enumerate(value)
        )
    if isinstance(value, (tuple, set, frozenset, Mapping)):
        raise FilterValidationError(f"{name} must be a scalar or an explicit list")
    return _normalise_scalar(value, name)


def _require_exact_keys(node: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(node)
    if actual != expected:
        unknown = actual - expected
        missing = expected - actual
        details: list[str] = []
        if unknown:
            details.append(f"unsupported fields: {sorted(unknown)}")
        if missing:
            details.append(f"missing fields: {sorted(missing)}")
        raise FilterValidationError(f"{name} has an invalid shape ({'; '.join(details)})")


def _bind_node(
    raw: Any,
    columns: frozenset[str],
    limits: FilterLimits,
    *,
    depth: int,
    state: list[int],
    name: str,
) -> FilterNode:
    if depth > limits.max_depth:
        raise FilterValidationError(
            f"{name} exceeds the maximum filter depth of {limits.max_depth}"
        )
    state[0] += 1
    if state[0] > limits.max_nodes:
        raise FilterValidationError(
            f"filter AST exceeds the maximum node count of {limits.max_nodes}"
        )
    if not isinstance(raw, Mapping):
        raise FilterValidationError(f"{name} must be an object, not a query or code string")
    if "op" not in raw:
        raise FilterValidationError(f"{name}.op is required")
    op = raw["op"]
    if not isinstance(op, str) or not op.strip():
        raise FilterValidationError(f"{name}.op must be a non-empty operator name")
    if op in LOGICAL_OPERATORS:
        if op == "not":
            _require_exact_keys(raw, {"op", "child"}, name)
            child = _bind_node(
                raw["child"],
                columns,
                limits,
                depth=depth + 1,
                state=state,
                name=f"{name}.child",
            )
            return FilterLogical(op=op, children=(child,))
        _require_exact_keys(raw, {"op", "children"}, name)
        children = raw["children"]
        if not isinstance(children, list) or not children:
            raise FilterValidationError(f"{name}.children must be a non-empty list")
        if len(children) > limits.max_list_size:
            raise FilterValidationError(
                f"{name}.children exceeds the maximum filter list size of {limits.max_list_size}"
            )
        bound_children = tuple(
            _bind_node(
                child,
                columns,
                limits,
                depth=depth + 1,
                state=state,
                name=f"{name}.children[{index}]",
            )
            for index, child in enumerate(children)
        )
        return FilterLogical(op=op, children=bound_children)
    if op not in FILTER_OPERATORS:
        raise FilterValidationError(f"{name}.op {op!r} is not a supported filter operator")

    expected = {"column", "op"}
    if op in VALUE_OPERATORS:
        expected.add("value")
    _require_exact_keys(raw, expected, name)
    column = raw["column"]
    if not isinstance(column, str) or not column.strip():
        raise FilterValidationError(f"{name}.column must be a non-empty string")
    if column not in columns:
        raise FilterValidationError(f"{name}.column {column!r} is not in the server column set")
    if op in {"is_missing", "not_missing"}:
        return FilterPredicate(column=column, op=op)

    list_allowed = op in {"in", "not_in", "between"}
    if list_allowed and not isinstance(raw["value"], list):
        raise FilterValidationError(f"{name}.value must be an explicit list for {op}")
    value = _normalise_value(
        raw["value"],
        f"{name}.value",
        list_allowed=list_allowed,
        max_list_size=limits.max_list_size,
    )
    if op in {"in", "not_in"} and len(value) < 1:
        raise FilterValidationError(f"{name}.value must be a non-empty list")
    if op == "between":
        if len(value) != 2:
            raise FilterValidationError(f"{name}.value must contain exactly two bounds")
        lower, upper = value
        try:
            if lower > upper:
                raise FilterValidationError(f"{name}.value lower bound must not exceed upper bound")
        except TypeError as exc:
            raise FilterValidationError(f"{name}.value bounds must have a common ordered type") from exc
    return FilterPredicate(column=column, op=op, value=value)


def bind_filter_ast(
    expression: Any,
    columns: Iterable[str],
    *,
    limits: FilterLimits | None = None,
) -> FilterNode:
    """Bind a JSON-shaped filter tree to the server-owned column set."""

    resolved_limits = limits or DEFAULT_FILTER_LIMITS
    if not isinstance(resolved_limits, FilterLimits):
        raise FilterValidationError("limits must be a FilterLimits instance")
    return _bind_node(
        expression,
        _normalise_columns(columns),
        resolved_limits,
        depth=1,
        state=[0],
        name="filter",
    )


def _is_missing_scalar(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    result = pd.isna(value)
    return isinstance(result, bool) and result


def _ensure_numeric_float_is_exact(value: Any, name: str) -> None:
    if isinstance(value, Integral) and not isinstance(value, bool):
        as_float = float(value)
        if not math.isfinite(as_float) or int(as_float) != int(value):
            raise FilterValidationError(f"{name} would require lossy implicit coercion")


def _ensure_value_compatible(series: pd.Series, value: Any, op: str, name: str) -> None:
    if value is None:
        if op in ORDERED_OPERATORS:
            raise FilterValidationError(f"{name} cannot order a null literal")
        return

    kind = _scalar_kind(value)
    dtype = series.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        _ensure_value_compatible(pd.Series(series.cat.categories), value, op, name)
        return
    if pd.api.types.is_bool_dtype(dtype):
        compatible = kind == "bool"
    elif pd.api.types.is_integer_dtype(dtype):
        compatible = kind == "integer"
    elif pd.api.types.is_float_dtype(dtype):
        compatible = kind in {"integer", "real"}
        if compatible:
            _ensure_numeric_float_is_exact(value, name)
    elif pd.api.types.is_datetime64_any_dtype(dtype):
        compatible = kind == "datetime"
    elif pd.api.types.is_timedelta64_dtype(dtype):
        compatible = kind == "timedelta"
    elif pd.api.types.is_object_dtype(dtype):
        observed = {
            _scalar_kind(item)
            for item in series
            if not _is_missing_scalar(item)
        }
        if not observed:
            compatible = kind != "unsupported"
        elif len(observed) == 1:
            observed_kind = next(iter(observed))
            compatible = kind == observed_kind
        else:
            compatible = False
    elif pd.api.types.is_string_dtype(dtype):
        compatible = kind == "string"
    else:
        compatible = False
    if not compatible:
        raise FilterValidationError(
            f"{name} has type {kind!r}, incompatible with column dtype {dtype!s}; "
            "lossy implicit coercion is not allowed"
        )


def _predicate_mask(frame: pd.DataFrame, predicate: FilterPredicate) -> pd.Series:
    if predicate.column not in frame.columns:
        raise FilterValidationError(
            f"bound filter column {predicate.column!r} is not present in the execution frame"
        )
    series = frame[predicate.column]
    if not isinstance(series, pd.Series):
        raise FilterValidationError(f"filter column {predicate.column!r} is not unique")
    op = predicate.op
    if op in {"is_missing", "not_missing"}:
        mask = series.isna() if op == "is_missing" else series.notna()
        return mask.fillna(False).astype(bool)

    value = predicate.value
    values = value if isinstance(value, tuple) else (value,)
    for index, item in enumerate(values):
        _ensure_value_compatible(series, item, op, f"{predicate.column}.{op}.value[{index}]")
    try:
        if op == "eq":
            mask = series.eq(value)
        elif op == "ne":
            mask = series.notna() & series.ne(value)
        elif op == "lt":
            mask = series.notna() & series.lt(value)
        elif op == "le":
            mask = series.notna() & series.le(value)
        elif op == "gt":
            mask = series.notna() & series.gt(value)
        elif op == "ge":
            mask = series.notna() & series.ge(value)
        elif op in {"in", "not_in"}:
            membership = series.isin(list(value))
            mask = membership if op == "in" else series.notna() & ~membership
        elif op == "between":
            lower, upper = value
            mask = series.notna() & series.ge(lower) & series.le(upper)
        else:  # pragma: no cover - bound nodes cannot contain another operator.
            raise FilterValidationError(f"unsupported bound filter operator: {op}")
    except FilterValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise FilterValidationError(
            f"filter {predicate.column!r} with operator {op!r} could not be applied: {exc}"
        ) from exc
    if not isinstance(mask, pd.Series):
        raise FilterValidationError("filter did not produce a row mask")
    return mask.fillna(False).astype(bool)


def _evaluate_bound(frame: pd.DataFrame, node: FilterNode) -> pd.Series:
    if isinstance(node, FilterPredicate):
        return _predicate_mask(frame, node)
    child_masks = [_evaluate_bound(frame, child) for child in node.children]
    if node.op == "and":
        mask = pd.Series(True, index=frame.index, dtype=bool)
        for child_mask in child_masks:
            mask = mask & child_mask
        return mask.fillna(False).astype(bool)
    if node.op == "or":
        mask = pd.Series(False, index=frame.index, dtype=bool)
        for child_mask in child_masks:
            mask = mask | child_mask
        return mask.fillna(False).astype(bool)
    if node.op == "not":
        return (~child_masks[0]).fillna(False).astype(bool)
    raise FilterValidationError(f"unsupported bound logical operator: {node.op}")


def execute_filter_ast(
    frame: pd.DataFrame,
    expression: FilterNode | Mapping[str, Any],
    *,
    limits: FilterLimits | None = None,
) -> pd.Series:
    """Execute a bound tree using explicit pandas boolean masks."""

    if not isinstance(frame, pd.DataFrame):
        raise FilterValidationError("filter execution requires a pandas DataFrame")
    if isinstance(expression, Mapping):
        bound = bind_filter_ast(expression, frame.columns, limits=limits)
    elif isinstance(expression, (FilterPredicate, FilterLogical)):
        bound = bind_filter_ast(expression.to_dict(), frame.columns, limits=limits)
    else:
        raise FilterValidationError("filter execution requires a bound filter AST")
    return _evaluate_bound(frame, bound).reindex(frame.index, fill_value=False).astype(bool)


def referenced_columns(expression: FilterNode) -> frozenset[str]:
    """Return the columns named by a bound tree for conflict checks."""

    if isinstance(expression, FilterPredicate):
        return frozenset({expression.column})
    if isinstance(expression, FilterLogical):
        return frozenset(
            column
            for child in expression.children
            for column in referenced_columns(child)
        )
    raise FilterValidationError("referenced_columns requires a bound filter AST")


# Explicit aliases keep the package-local API readable for callers that call
# the operation "compile" or "evaluate" rather than "bind" or "execute".
compile_filter_ast = bind_filter_ast
parse_filter_ast = bind_filter_ast
evaluate_filter_ast = execute_filter_ast
apply_filter_ast = execute_filter_ast
