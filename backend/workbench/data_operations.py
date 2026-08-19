"""Typed, preview-first data operations for the V11 vertical slice."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

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
from .filter_ast import (
    MAX_FILTER_LIST_SIZE,
    FilterNode,
    FilterValidationError,
    bind_filter_ast,
    execute_filter_ast,
    referenced_columns,
)
from .predictive_research.contracts import FeatureRecipeV1
from .predictive_research.feature_recipe import apply_feature_recipe
from .metadata import (
    MetadataMutationEffectV1,
    MetadataMutationPreviewV1,
    MetadataMutationSpecV1,
    MetadataRegistryV1,
    MetadataProvenanceError,
    metadata_revision_digest,
    normalize_metadata_mutation_payload,
)

DataCastTarget = Literal["numeric", "string", "datetime"]
ALLOWED_CAST_TARGETS = frozenset({"numeric", "string", "datetime"})

DataCastOutputFormat = Literal["csv", "xlsx"]
ALLOWED_OUTPUT_FORMATS = frozenset({"csv", "xlsx"})
_SCHEMA_SIDECAR_SUFFIX = ".schema.json"


class DataColumnCastValidationError(ValueError):
    """Raised when a typed cast cannot be resolved or safely previewed."""


class DataMetadataUnavailableError(DataColumnCastValidationError):
    """Raised when an operation needs confirmed server metadata but none exists."""


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
    metadata_artifact_id: str | None = None
    metadata_artifact_path: str | None = None
    group_manifest_id: str | None = None
    group_manifest_path: str | None = None
    group_artifacts: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
            "metadata_artifact_id": self.metadata_artifact_id,
            "metadata_artifact_path": self.metadata_artifact_path,
            "group_manifest_id": self.group_manifest_id,
            "group_manifest_path": self.group_manifest_path,
            "group_artifacts": [dict(item) for item in self.group_artifacts],
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
    "sort",
    "split",
    "recode",
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
        "sort",
        "split",
        "recode",
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
MAX_SPLIT_GROUPS = 128


class _DataOperationTransaction:
    """Scoped rollback seam for package-owned data-operation persistence.

    The existing artifact/index/Graph APIs are individually atomic, but they do
    not form one multi-file transaction. This seam snapshots only the current
    operation prefix and its three package-owned identity indexes, restoring
    them on an unexpected failure after preflight.
    """

    def __init__(self, run_root: Path, operation_prefix: Path) -> None:
        self.run_root = run_root
        self.operation_root = run_root / operation_prefix
        self.state_paths = (
            run_root / "artifacts_index.json",
            run_root / "node_index.json",
            run_root.parent / run_root.name / "graph.json",
        )
        self._files: dict[Path, bytes] = {}
        self._state_files: dict[Path, bytes] = {}

    def __enter__(self) -> "_DataOperationTransaction":
        if self.operation_root.is_dir():
            for path in self.operation_root.rglob("*"):
                if path.is_file():
                    self._files[path] = path.read_bytes()
        for path in self.state_paths:
            if path.is_file():
                self._state_files[path] = path.read_bytes()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            return False
        self._rollback()
        return False

    def _rollback(self) -> None:
        if self.operation_root.exists():
            for path in sorted(self.operation_root.rglob("*"), reverse=True):
                if path.is_file() and path not in self._files:
                    path.unlink()
        for path, data in self._files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for path in self.state_paths:
            if path in self._state_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self._state_files[path])
            elif path.is_file():
                path.unlink()


def _data_operation_transaction(func):
    @wraps(func)
    def wrapped(project_root, spec, preview, *args, **kwargs):
        run_root = Path(project_root).expanduser().resolve() / "runs" / spec.source_run_id
        fingerprint = getattr(preview, "fingerprint", None)
        if not isinstance(fingerprint, str) or not fingerprint:
            return func(project_root, spec, preview, *args, **kwargs)
        class_name = type(spec).__name__
        execution_override = kwargs.get("execution_key_value")
        suffix = (
            execution_override.removeprefix("exec_")
            if isinstance(execution_override, str) and execution_override
            else fingerprint[:32]
        )
        if class_name == "DataTransformSpecV1":
            operation_prefix = Path("derived") / "data_operations" / spec.operation / suffix
        elif class_name == "DataColumnCastSpecV1":
            operation_prefix = Path("derived") / "data_column_cast" / suffix
        elif class_name == "DataColumnsCastSpecV1":
            operation_prefix = Path("derived") / "data_columns_cast" / suffix
        elif class_name == "FeatureRecipeOperationSpecV1":
            operation_prefix = Path("derived") / "feature_recipe" / suffix
        elif class_name == "MetadataMutationSpecV1":
            operation_prefix = Path("derived") / "data_operations" / "metadata_update" / suffix
        else:
            return func(project_root, spec, preview, *args, **kwargs)
        with _DataOperationTransaction(run_root, operation_prefix):
            return func(project_root, spec, preview, *args, **kwargs)

    return wrapped


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
    group_count: int | None = None
    changed_value_count: int | None = None
    group_counts: tuple[Mapping[str, Any], ...] = ()
    method: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

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
            "group_count": self.group_count,
            "changed_value_count": self.changed_value_count,
            "group_counts": [dict(item) for item in self.group_counts],
            "method": self.method,
            "evidence": dict(self.evidence),
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


def _bind_subset_filter(
    expression: Any, columns: Iterable[str], name: str
) -> FilterNode:
    try:
        return bind_filter_ast(expression, columns)
    except FilterValidationError as exc:
        raise DataColumnCastValidationError(f"{name}: {exc}") from exc


def _filter_uses_missing_semantics(node: FilterNode) -> bool:
    if hasattr(node, "op") and getattr(node, "op") in {"is_missing", "not_missing"}:
        return True
    children = getattr(node, "children", ())
    return any(_filter_uses_missing_semantics(child) for child in children)


def _subset_filter_mask(series: pd.Series, filter_spec: Mapping[str, Any], name: str) -> pd.Series:
    column = filter_spec.get("column") if isinstance(filter_spec, Mapping) else None
    if not isinstance(column, str):
        raise DataColumnCastValidationError(f"{name}.column must be a non-empty string")
    bound = _bind_subset_filter(filter_spec, [column], name)
    try:
        return execute_filter_ast(series.to_frame(name=column), bound)
    except FilterValidationError as exc:
        raise DataColumnCastValidationError(f"{name}: {exc}") from exc


def _sort_spec(parameters: Mapping[str, Any]) -> tuple[list[str], list[bool]]:
    _reject_unknown_parameters(parameters, {"keys", "by"}, "sort")
    raw_keys = parameters.get("keys", parameters.get("by"))
    if not isinstance(raw_keys, list) or not raw_keys:
        raise DataColumnCastValidationError("sort.keys must be a non-empty list")
    columns: list[str] = []
    ascending: list[bool] = []
    for index, raw_key in enumerate(raw_keys):
        if isinstance(raw_key, str):
            column = _require_non_empty_string(raw_key, f"sort.keys[{index}]")
            direction = True
        else:
            parsed = _require_nested_keys(
                raw_key,
                name=f"sort.keys[{index}]",
                required={"column"},
                optional={"ascending"},
            )
            column = _require_non_empty_string(
                parsed["column"], f"sort.keys[{index}].column"
            )
            direction = parsed.get("ascending", True)
            if type(direction) is not bool:
                raise DataColumnCastValidationError(
                    f"sort.keys[{index}].ascending must be boolean"
                )
        columns.append(column)
        ascending.append(direction)
    if len(set(columns)) != len(columns):
        raise DataColumnCastValidationError("sort.keys must not contain duplicate columns")
    return columns, ascending


def _recode_rules(
    value: Any,
    *,
    name: str,
) -> list[tuple[Any, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_FILTER_LIST_SIZE:
        raise DataColumnCastValidationError(
            f"{name} must be a non-empty list of at most {MAX_FILTER_LIST_SIZE} rules"
        )
    rules: list[tuple[Any, Any]] = []
    for index, raw_rule in enumerate(value):
        parsed = _require_nested_keys(
            raw_rule,
            name=f"{name}[{index}]",
            required={"from", "to"},
        )
        source = parsed["from"]
        target = parsed["to"]
        for candidate, candidate_name in ((source, "from"), (target, "to")):
            if isinstance(candidate, (Mapping, list, tuple, set, frozenset)):
                raise DataColumnCastValidationError(
                    f"{name}[{index}].{candidate_name} must be a scalar"
                )
        if any(source == previous for previous, _ in rules):
            raise DataColumnCastValidationError(f"{name} contains duplicate source values")
        rules.append((source, target))
    return rules


def _value_changed(before: pd.Series, after: pd.Series) -> int:
    equal = before.eq(after)
    both_missing = before.isna() & after.isna()
    return int((~(equal | both_missing)).sum())


def _execute_batch_recode(left: pd.DataFrame, parameters: Mapping[str, Any]) -> tuple[pd.DataFrame, int]:
    _reject_unknown_parameters(
        parameters,
        {"columns", "column", "mapping", "other", "missing"},
        "recode",
    )
    raw_columns = parameters.get("columns")
    if raw_columns is None:
        column = _require_non_empty_string(parameters.get("column"), "recode.column")
        mapping = parameters.get("mapping")
        if not isinstance(mapping, Mapping) or not mapping:
            raise DataColumnCastValidationError(
                "recode.mapping must be a non-empty object when recode.column is used"
            )
        raw_columns = [
            {
                "column": column,
                "rules": [{"from": source, "to": target} for source, target in mapping.items()],
                "other": parameters.get("other", "keep"),
                "missing": parameters.get("missing", "preserve"),
            }
        ]
    if not isinstance(raw_columns, list) or not raw_columns:
        raise DataColumnCastValidationError("recode.columns must be a non-empty list")
    result = left.copy()
    changed_count = 0
    seen: set[str] = set()
    for index, raw_column in enumerate(raw_columns):
        parsed = _require_nested_keys(
            raw_column,
            name=f"recode.columns[{index}]",
            required={"column", "rules"},
            optional={"other", "missing"},
        )
        column = _require_non_empty_string(
            parsed["column"], f"recode.columns[{index}].column"
        )
        if column in seen:
            raise DataColumnCastValidationError(f"recode.columns must not repeat {column}")
        seen.add(column)
        _require_columns_exist(result, [column], "recode")
        rules = _recode_rules(parsed["rules"], name=f"recode.columns[{index}].rules")
        other = parsed.get("other", "keep")
        if other not in {"keep", "missing"} and isinstance(other, (Mapping, list, tuple, set, frozenset)):
            raise DataColumnCastValidationError(
                f"recode.columns[{index}].other must be keep, missing, or a scalar"
            )
        missing = parsed.get("missing", "preserve")
        if missing not in {"preserve", "missing"}:
            raise DataColumnCastValidationError(
                f"recode.columns[{index}].missing must be preserve or missing"
            )
        source_series = result[column].copy()
        output_series = source_series.astype("object").copy()
        matched = pd.Series(False, index=source_series.index, dtype=bool)
        for source, target in rules:
            if source is None:
                current = source_series.isna()
            else:
                try:
                    current = source_series.eq(source).fillna(False)
                except (TypeError, ValueError) as exc:
                    raise DataColumnCastValidationError(
                        f"recode rule for {column!r} could not be applied: {exc}"
                    ) from exc
            if bool((matched & current).any()):
                raise DataColumnCastValidationError(
                    f"recode rules for {column!r} overlap"
                )
            output_series.loc[current] = target
            matched |= current
        non_missing_unmatched = ~source_series.isna() & ~matched
        if other == "missing":
            output_series.loc[non_missing_unmatched] = pd.NA
        elif other != "keep":
            output_series.loc[non_missing_unmatched] = other
        if missing == "missing":
            output_series.loc[source_series.isna()] = pd.NA
        changed_count += _value_changed(source_series, output_series)
        result[column] = output_series
    return result, changed_count


def _json_group_value(value: object) -> object:
    if value is None or value is pd.NA:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _split_group_frames(
    frame: pd.DataFrame,
    by: list[str],
) -> list[tuple[dict[str, object], pd.DataFrame]]:
    grouped = frame.groupby(by, dropna=False, sort=False, observed=False)
    groups: list[tuple[dict[str, object], pd.DataFrame]] = []
    for raw_key, group in grouped:
        values = raw_key if isinstance(raw_key, tuple) else (raw_key,)
        key = {column: _json_group_value(value) for column, value in zip(by, values, strict=True)}
        groups.append((key, group.reset_index(drop=True).copy()))
    groups.sort(
        key=lambda item: json.dumps(item[0], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if len(groups) > MAX_SPLIT_GROUPS:
        raise DataColumnCastValidationError(
            f"split produces {len(groups)} groups; maximum is {MAX_SPLIT_GROUPS}"
        )
    return groups


def _execute_data_transform(
    left: pd.DataFrame,
    spec: DataTransformSpecV1,
    right: pd.DataFrame | None,
    metadata_registry: MetadataRegistryV1 | None = None,
) -> pd.DataFrame:
    parameters = dict(spec.parameters)
    if metadata_registry is not None:
        left.attrs["metadata_confirmed"] = True
        left.attrs["user_missing_values"] = metadata_registry.user_missing_values(
            tuple(str(column) for column in left.columns)
        )
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
    if spec.operation == "sort":
        columns, ascending = _sort_spec(parameters)
        _require_columns_exist(left, columns, "sort")
        try:
            return left.sort_values(
                by=columns,
                ascending=ascending,
                kind="mergesort",
                na_position="last",
            ).reset_index(drop=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise DataColumnCastValidationError(f"sort failed: {exc}") from exc
    if spec.operation == "split":
        _reject_unknown_parameters(parameters, {"by", "columns", "mode"}, "split")
        by = parameters.get("by", parameters.get("columns"))
        by = _require_string_list(by, "split.by")
        _require_columns_exist(left, by, "split")
        mode = parameters.get("mode", "split_file")
        if mode not in {"split_file", "group"}:
            raise DataColumnCastValidationError("split.mode must be split_file or group")
        try:
            _split_group_frames(left, by)
            return left.sort_values(by=by, kind="mergesort", na_position="last").reset_index(drop=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise DataColumnCastValidationError(f"split failed: {exc}") from exc
    if spec.operation == "recode":
        output, _changed_count = _execute_batch_recode(left, parameters)
        return output.reset_index(drop=True)
    if spec.operation == "subset":
        _reject_unknown_parameters(
            parameters,
            {
                "columns",
                "equals",
                "filters",
                "filter",
                "filter_ast",
                "row_indices",
                "row_index_range",
                "row_range",
                "user_missing_values",
            },
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

        ast_keys = [key for key in ("filter", "filter_ast") if key in parameters]
        if len(ast_keys) > 1:
            raise DataColumnCastValidationError(
                "subset.filter and subset.filter_ast are aliases and cannot both be declared"
            )
        ast_expression = parameters.get(ast_keys[0]) if ast_keys else None
        if filters and ast_keys:
            raise DataColumnCastValidationError(
                "subset.filters and subset.filter cannot both be declared"
            )

        bound_filters: list[FilterNode] = []
        if filters:
            legacy_filter_expression: Any = filters[0]
            if len(filters) > 1:
                legacy_filter_expression = {"op": "and", "children": filters}
            bound_filters.append(
                _bind_subset_filter(legacy_filter_expression, left.columns, "subset.filters")
            )
        if ast_keys:
            bound_filters.append(
                _bind_subset_filter(ast_expression, left.columns, f"subset.{ast_keys[0]}")
            )

        uses_missing_semantics = any(
            _filter_uses_missing_semantics(bound_filter) for bound_filter in bound_filters
        )
        if uses_missing_semantics and metadata_registry is None:
            raise DataMetadataUnavailableError(
                "subset filter requires confirmed user-missing metadata from the server-owned registry"
            )

        filter_columns = set(
            column
            for bound_filter in bound_filters
            for column in referenced_columns(bound_filter)
        )
        overlap = set(legacy_equals) & filter_columns
        if overlap:
            raise DataColumnCastValidationError(
                "subset.equals and subset filters cannot both declare: "
                + ", ".join(sorted(overlap))
            )
        declared_user_missing = parameters.get("user_missing_values")
        if declared_user_missing is not None and not isinstance(
            declared_user_missing, Mapping
        ):
            raise DataColumnCastValidationError(
                "subset.user_missing_values must be a column mapping"
            )
        if declared_user_missing is not None:
            if metadata_registry is None:
                raise DataMetadataUnavailableError(
                    "subset.user_missing_values requires confirmed server-owned metadata"
                )
            confirmed_missing = metadata_registry.user_missing_values(
                tuple(str(column) for column in left.columns)
            )
            if dict(declared_user_missing) != confirmed_missing:
                raise DataColumnCastValidationError(
                    "subset.user_missing_values must match the confirmed metadata registry"
                )
            declared_user_missing = confirmed_missing
        elif metadata_registry is not None:
            declared_user_missing = metadata_registry.user_missing_values(
                tuple(str(column) for column in left.columns)
            )
        mask = pd.Series(True, index=left.index)
        for column, value in legacy_equals.items():
            bound_equals = _bind_subset_filter(
                {"column": column, "op": "eq", "value": value},
                left.columns,
                f"subset.equals[{column}]",
            )
            try:
                mask &= execute_filter_ast(
                    left,
                    bound_equals,
                    user_missing_values=declared_user_missing,
                    metadata_registry=metadata_registry,
                )
            except FilterValidationError as exc:
                raise DataColumnCastValidationError(
                    f"subset.equals[{column}]: {exc}"
                ) from exc
        for bound_filter in bound_filters:
            try:
                mask &= execute_filter_ast(
                    left,
                    bound_filter,
                    user_missing_values=declared_user_missing,
                    metadata_registry=metadata_registry,
                )
            except FilterValidationError as exc:
                raise DataColumnCastValidationError(f"subset filter: {exc}") from exc
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
        weight = None
        if metadata_registry is not None:
            candidate_weight = metadata_registry.metadata.get("weight")
            if isinstance(candidate_weight, Mapping):
                weight = candidate_weight
        if weight is not None:
            weight_column = weight.get("column")
            if not isinstance(weight_column, str) or weight_column not in left.columns:
                raise DataMetadataUnavailableError(
                    "confirmed weight declaration names a column unavailable in the source frame"
                )
            unsupported = [
                aggregation.get("func")
                for aggregation in aggregations
                if isinstance(aggregation, Mapping) and aggregation.get("func") != "mean"
            ]
            if unsupported:
                raise DataColumnCastValidationError(
                    "declared weight is supported only for aggregate mean; "
                    f"unsupported function(s): {sorted(set(unsupported))}"
                )
            weighted_rows: list[dict[str, object]] = []
            weight_total = 0.0
            try:
                grouped = left.groupby(group_by, dropna=False, sort=False, observed=False)
                for raw_key, group in grouped:
                    key_values = raw_key if isinstance(raw_key, tuple) else (raw_key,)
                    row = {
                        column: _json_group_value(value)
                        for column, value in zip(group_by, key_values, strict=True)
                    }
                    weights = pd.to_numeric(group[weight_column], errors="coerce")
                    valid_weight = weights.notna() & weights.ge(0) & weights.map(math.isfinite)
                    for aggregation in aggregations:
                        parsed = aggregation
                        column = str(parsed["column"])
                        values = pd.to_numeric(group[column], errors="coerce")
                        valid = valid_weight & values.notna()
                        denominator = float(weights[valid].sum())
                        if denominator <= 0:
                            raise DataColumnCastValidationError(
                                f"weighted mean has no positive weight for group {row}"
                            )
                        row[str(parsed["output"])] = float(
                            (values[valid] * weights[valid]).sum() / denominator
                        )
                        weight_total += denominator
                    weighted_rows.append(row)
            except DataColumnCastValidationError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise DataColumnCastValidationError(f"weighted aggregate failed: {exc}") from exc
            result = pd.DataFrame(weighted_rows, columns=[*group_by, *named])
            result.attrs["_data_operation_method"] = "weighted_mean"
            result.attrs["_data_operation_evidence"] = {
                "method": "weighted_mean",
                "weight": {
                    "column": weight_column,
                    "kind": weight.get("kind"),
                },
                "weight_consumed": True,
                "weight_sum": weight_total,
                "group_count": len(weighted_rows),
            }
            return result
        try:
            result = left.groupby(group_by, dropna=False, sort=False).agg(**named).reset_index()
            result.attrs["_data_operation_method"] = "aggregate"
            result.attrs["_data_operation_evidence"] = {
                "method": "aggregate",
                "weight_consumed": False,
            }
            return result
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
    left_root, graph, node, left_artifact, left_path = _resolve_source(
        project_root, _transform_source_spec(spec.source_run_id, spec.source_node_id, spec.source_artifact_id)
    )
    left = _read_frame(left_path)
    metadata_registry = _metadata_registry_for_source(
        left_root, node, spec.source_artifact_id
    )
    right = None
    right_artifact = None
    if spec.secondary_run_id and spec.secondary_node_id and spec.secondary_artifact_id:
        _right_root, _right_graph, _right_node, right_artifact, right_path = _resolve_source(
            project_root,
            _transform_source_spec(spec.secondary_run_id, spec.secondary_node_id, spec.secondary_artifact_id),
        )
        right = _read_frame(right_path)
    output = _execute_data_transform(left, spec, right, metadata_registry)
    source_sha = str(left_artifact.get("sha256") or sha256_file(left_path))
    secondary_sha = (
        str(right_artifact.get("sha256") or "") if right_artifact is not None else None
    )
    before = _schema_fingerprint(left)
    after = _schema_fingerprint(output)
    group_counts: tuple[Mapping[str, Any], ...] = ()
    if spec.operation == "split":
        by = spec.parameters.get("by", spec.parameters.get("columns"))
        if isinstance(by, list):
            group_counts = tuple(
                {"key": key, "count": len(group)}
                for key, group in _split_group_frames(left, by)
            )
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "secondary_source_sha256": secondary_sha,
        "schema_before": before,
        "schema_after": after,
        "row_count_after": len(output),
        "group_counts": [dict(item) for item in group_counts],
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    group_count: int | None = None
    changed_value_count: int | None = None
    if spec.operation == "split":
        group_count = len(group_counts)
    elif spec.operation == "recode":
        _recode_output, changed_value_count = _execute_batch_recode(left, dict(spec.parameters))
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
        group_count=group_count,
        changed_value_count=changed_value_count,
        group_counts=group_counts,
        method=output.attrs.get("_data_operation_method"),
        evidence=output.attrs.get("_data_operation_evidence", {}),
    )


@_data_operation_transaction
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
    left_root, graph, node, left_artifact, left_path = _resolve_source(
        project_root, _transform_source_spec(spec.source_run_id, spec.source_node_id, spec.source_artifact_id)
    )
    metadata_registry = _metadata_registry_for_source(
        left_root, node, spec.source_artifact_id
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
    output = _execute_data_transform(_read_frame(left_path), spec, right, metadata_registry)
    execution = execution_key_value or f"exec_{fresh.fingerprint[:32]}"
    suffix = execution.removeprefix("exec_")
    artifact_id = f"{spec.operation}_{suffix}"
    recipe_artifact_id = f"{spec.operation}_recipe_{suffix}"
    relative_dir = Path("derived") / "data_operations" / spec.operation / suffix
    artifact_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = left_root / artifact_rel
    recipe_path = left_root / recipe_rel
    child_node_id = f"data-{spec.operation}:{suffix}"
    output_metadata = _metadata_for_output(
        metadata_registry,
        spec=spec,
        output_columns=output.columns,
    )
    metadata_artifact_id = f"{artifact_id}_metadata"
    metadata_rel = (relative_dir / "metadata.json").as_posix()
    metadata_payload = _metadata_sidecar_payload(
        registry=metadata_registry,
        metadata=output_metadata,
        output_frame=output,
        run_id=spec.source_run_id,
        child_node_id=child_node_id,
        artifact_id=artifact_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(left_artifact.get("sha256") or sha256_file(left_path)),
        operation_id=f"data.{spec.operation}",
        preview_fingerprint=fresh.fingerprint,
        column_aliases=_metadata_column_aliases(spec),
    )
    recipe_payload = {
        "payload_schema": "workbench.data-operation",
        "schema_version": 1,
        "execution_key": execution,
        "spec": spec.to_dict(),
        "preview": fresh.to_dict(),
        "result": {
            "artifact_id": artifact_id,
            "path": artifact_rel,
            "metadata_artifact_id": metadata_artifact_id,
            "metadata_path": metadata_rel,
            "metadata_revision": metadata_payload["metadata_revision"],
            "method": fresh.method,
            "evidence": dict(fresh.evidence),
        },
    }
    inputs = [spec.source_artifact_id]
    if spec.secondary_artifact_id:
        inputs.append(spec.secondary_artifact_id)

    # Validate every deterministic output, metadata sidecar, recipe binding,
    # and child index before the first write.  A stale/occupied confirm must
    # therefore leave the run root byte-for-byte unchanged.
    _preflight_frame_artifact(artifact_path, output)
    _preflight_json_path(
        left_root / metadata_rel,
        metadata_payload,
        "deterministic metadata sidecar path is occupied",
    )
    _preflight_json_path(
        recipe_path,
        recipe_payload,
        "deterministic data operation path is occupied",
    )
    _preflight_artifact_binding(
        left_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="derived_data",
        step=f"data.{spec.operation}",
        inputs=inputs,
    )
    _preflight_artifact_binding(
        left_root,
        artifact_id=metadata_artifact_id,
        path=left_root / metadata_rel,
        artifact_type="metadata",
        step=f"data.{spec.operation}",
        inputs=inputs + [artifact_id],
    )
    _preflight_artifact_binding(
        left_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step=f"data.{spec.operation}",
        inputs=inputs + [artifact_id],
    )
    _preflight_node_index_entry(
        left_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(artifact_path) if artifact_path.exists() else None,
        artifact_rel=artifact_rel,
        producing_stage=f"data.{spec.operation}",
        create_if_missing=True,
    )
    _preflight_graph_child(
        graph,
        child_node_id=child_node_id,
        artifact_path=artifact_path,
        artifact_rel=artifact_rel,
        operation_id=f"data.{spec.operation}",
    )
    if spec.operation == "split":
        by = spec.parameters.get("by", spec.parameters.get("columns"))
        if isinstance(by, list):
            _preflight_split_groups(
                left_root,
                graph=graph,
                spec=spec,
                preview=fresh,
                output=output,
                by=by,
                relative_dir=relative_dir,
                parent_artifact_id=artifact_id,
                parent_child_node_id=child_node_id,
                source_artifact_id=spec.source_artifact_id,
                metadata_registry=metadata_registry,
            )

    _write_frame_artifact(artifact_path, output, "csv")
    _write_metadata_sidecar(
        left_root,
        relative_dir=relative_dir,
        artifact_id=artifact_id,
        output_frame=output,
        child_node_id=child_node_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(left_artifact.get("sha256") or sha256_file(left_path)),
        operation_id=f"data.{spec.operation}",
        preview_fingerprint=fresh.fingerprint,
        registry=metadata_registry,
        metadata=output_metadata,
        column_aliases=_metadata_column_aliases(spec),
    )
    if not recipe_path.exists():
        write_json(recipe_path, recipe_payload)
    _ensure_registered_artifact(left_root, artifact_id=artifact_id, path=artifact_path, artifact_type="derived_data", step=f"data.{spec.operation}", inputs=inputs)
    _ensure_registered_artifact(left_root, artifact_id=recipe_artifact_id, path=recipe_path, artifact_type="metadata", step=f"data.{spec.operation}", inputs=inputs + [artifact_id])
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
            metadata_artifact_id=metadata_artifact_id,
            metadata_rel=metadata_rel,
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
    group_artifacts: tuple[dict[str, Any], ...] = ()
    group_manifest_id: str | None = None
    group_manifest_rel: str | None = None
    if spec.operation == "split":
        by = spec.parameters.get("by", spec.parameters.get("columns"))
        if isinstance(by, list):
            group_artifacts, group_manifest_id, group_manifest_rel = _materialize_split_groups(
                left_root,
                spec=spec,
                preview=fresh,
                execution_key=execution,
                output=output,
                by=by,
                relative_dir=relative_dir,
                parent_artifact_id=artifact_id,
                parent_child_node_id=child_node_id,
                source_artifact_id=spec.source_artifact_id,
                metadata_registry=metadata_registry,
            )
    effect = FeatureRecipeEffect(
        execution_key=execution,
        artifact_id=artifact_id,
        artifact_path=artifact_rel,
        recipe_artifact_id=recipe_artifact_id,
        recipe_path=recipe_rel,
        child_node_id=child_node_id,
        metadata_artifact_id=metadata_artifact_id,
        metadata_artifact_path=metadata_rel,
    )
    return FeatureRecipeEffect(
        execution_key=effect.execution_key,
        artifact_id=effect.artifact_id,
        artifact_path=effect.artifact_path,
        recipe_artifact_id=effect.recipe_artifact_id,
        recipe_path=effect.recipe_path,
        child_node_id=effect.child_node_id,
        metadata_artifact_id=effect.metadata_artifact_id,
        metadata_artifact_path=effect.metadata_artifact_path,
        group_manifest_id=group_manifest_id,
        group_manifest_path=group_manifest_rel,
        group_artifacts=tuple(group_artifacts),
    )


def _preflight_split_groups(
    run_root: Path,
    *,
    graph: Graph,
    spec: DataTransformSpecV1,
    preview: DataTransformPreview,
    output: pd.DataFrame,
    by: list[str],
    relative_dir: Path,
    parent_artifact_id: str,
    parent_child_node_id: str,
    source_artifact_id: str,
    metadata_registry: MetadataRegistryV1 | None,
) -> None:
    """Preflight every split child, manifest, index, and graph identity."""

    groups = _split_group_frames(output, by)
    entries: list[dict[str, Any]] = []
    for key, group in groups:
        digest = hashlib.sha256(
            json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        artifact_id = f"{parent_artifact_id}_group_{digest}"
        artifact_rel = (relative_dir / "groups" / f"{digest}.csv").as_posix()
        artifact_path = run_root / artifact_rel
        child_node_id = f"{parent_child_node_id}:group:{digest}"
        metadata = _metadata_for_output(
            metadata_registry, spec=spec, output_columns=group.columns
        )
        metadata_artifact_id = f"{artifact_id}_metadata"
        metadata_rel = (relative_dir / "groups" / f"{digest}.metadata.json").as_posix()
        metadata_payload = _metadata_sidecar_payload(
            registry=metadata_registry,
            metadata=metadata,
            output_frame=group,
            run_id=spec.source_run_id,
            child_node_id=child_node_id,
            artifact_id=artifact_id,
            source_run_id=spec.source_run_id,
            source_node_id=spec.source_node_id,
            source_artifact_id=source_artifact_id,
            source_sha256=preview.source_sha256,
            operation_id="data.split",
            preview_fingerprint=preview.fingerprint,
            column_aliases=_metadata_column_aliases(spec),
        )
        _preflight_frame_artifact(artifact_path, group)
        _preflight_json_path(
            run_root / metadata_rel,
            metadata_payload,
            "deterministic split-group metadata sidecar path is occupied",
        )
        _preflight_artifact_binding(
            run_root,
            artifact_id=artifact_id,
            path=artifact_path,
            artifact_type="derived_data",
            step="data.split.group",
            inputs=[source_artifact_id, parent_artifact_id],
        )
        _preflight_artifact_binding(
            run_root,
            artifact_id=metadata_artifact_id,
            path=run_root / metadata_rel,
            artifact_type="metadata",
            step="data.split",
            inputs=[source_artifact_id, artifact_id],
        )
        _preflight_graph_child(
            graph,
            child_node_id=child_node_id,
            artifact_path=artifact_path,
            artifact_rel=artifact_rel,
            operation_id="data.split",
        )
        _preflight_node_index_entry(
            run_root,
            child_node_id=child_node_id,
            node_hash=sha256_file(artifact_path) if artifact_path.exists() else None,
            artifact_rel=artifact_rel,
            producing_stage="data.split.group",
            create_if_missing=True,
        )
        entries.append(
            {
                "key": key,
                "count": len(group),
                "artifact_id": artifact_id,
                "path": artifact_rel,
                "child_node_id": child_node_id,
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_artifact_path": metadata_rel,
                "node_hash": sha256_file(artifact_path) if artifact_path.exists() else None,
            }
        )
    manifest_rel = (relative_dir / "groups.json").as_posix()
    manifest_payload = {
        "payload_schema": "workbench.data-split-group",
        "schema_version": 1,
        "operation_id": "data.split",
        "execution_key": f"exec_{parent_child_node_id.rsplit(':', 1)[-1]}",
        "source": {
            "run_id": spec.source_run_id,
            "node_id": spec.source_node_id,
            "artifact_id": source_artifact_id,
        },
        "parent": {"node_id": parent_child_node_id, "artifact_id": parent_artifact_id},
        "by": list(by),
        "mode": spec.parameters.get("mode", "split_file"),
        "group_count": len(entries),
        "groups": entries,
        "lineage": {
            "preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        },
    }
    manifest_path = run_root / manifest_rel
    _preflight_json_path(
        manifest_path,
        manifest_payload,
        "deterministic split manifest path is occupied",
    )
    _preflight_artifact_binding(
        run_root,
        artifact_id=f"{parent_artifact_id}_groups",
        path=manifest_path,
        artifact_type="metadata",
        step="data.split.group",
        inputs=[source_artifact_id, parent_artifact_id, *[entry["artifact_id"] for entry in entries]],
    )


def _materialize_split_groups(
    run_root: Path,
    *,
    spec: DataTransformSpecV1,
    preview: DataTransformPreview,
    execution_key: str,
    output: pd.DataFrame,
    by: list[str],
    relative_dir: Path,
    parent_artifact_id: str,
    parent_child_node_id: str,
    source_artifact_id: str,
    metadata_registry: MetadataRegistryV1 | None,
) -> tuple[tuple[dict[str, Any], ...], str, str]:
    groups = _split_group_frames(output, by)
    manifest_id = f"{parent_artifact_id}_groups"
    manifest_rel = (relative_dir / "groups.json").as_posix()
    group_entries: list[dict[str, Any]] = []
    for key, group in groups:
        digest = hashlib.sha256(
            json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        artifact_id = f"{parent_artifact_id}_group_{digest}"
        artifact_rel = (relative_dir / "groups" / f"{digest}.csv").as_posix()
        artifact_path = run_root / artifact_rel
        child_node_id = f"{parent_child_node_id}:group:{digest}"
        group_metadata = _metadata_for_output(
            metadata_registry,
            spec=spec,
            output_columns=group.columns,
        )
        metadata_artifact_id = f"{artifact_id}_metadata"
        metadata_rel = (relative_dir / "groups" / f"{digest}.metadata.json").as_posix()
        metadata_payload = _metadata_sidecar_payload(
            registry=metadata_registry,
            metadata=group_metadata,
            output_frame=group,
            run_id=spec.source_run_id,
            child_node_id=child_node_id,
            artifact_id=artifact_id,
            source_run_id=spec.source_run_id,
            source_node_id=spec.source_node_id,
            source_artifact_id=source_artifact_id,
            source_sha256=preview.source_sha256,
            operation_id="data.split",
            preview_fingerprint=preview.fingerprint,
            column_aliases=_metadata_column_aliases(spec),
        )
        _preflight_frame_artifact(artifact_path, group)
        _preflight_json_path(
            run_root / metadata_rel,
            metadata_payload,
            "deterministic split-group metadata sidecar path is occupied",
        )
        _write_frame_artifact(artifact_path, group, "csv")
        _write_metadata_sidecar(
            run_root,
            relative_dir=relative_dir / "groups",
            metadata_filename=f"{digest}.metadata.json",
            artifact_id=artifact_id,
            output_frame=group,
            child_node_id=child_node_id,
            source_run_id=spec.source_run_id,
            source_node_id=spec.source_node_id,
            source_artifact_id=source_artifact_id,
            source_sha256=preview.source_sha256,
            operation_id="data.split",
            preview_fingerprint=preview.fingerprint,
            registry=metadata_registry,
            metadata=group_metadata,
            column_aliases=_metadata_column_aliases(spec),
        )
        _ensure_registered_artifact(
            run_root,
            artifact_id=artifact_id,
            path=artifact_path,
            artifact_type="derived_data",
            step="data.split.group",
            inputs=[source_artifact_id, parent_artifact_id],
        )
        group_entries.append(
            {
                "key": key,
                "count": len(group),
                "artifact_id": artifact_id,
                "path": artifact_rel,
                "child_node_id": child_node_id,
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_artifact_path": metadata_rel,
                "node_hash": sha256_file(artifact_path),
            }
        )
    manifest_payload = {
        "payload_schema": "workbench.data-split-group",
        "schema_version": 1,
        "operation_id": "data.split",
        "execution_key": execution_key,
        "source": {
            "run_id": spec.source_run_id,
            "node_id": spec.source_node_id,
            "artifact_id": source_artifact_id,
        },
        "parent": {
            "node_id": parent_child_node_id,
            "artifact_id": parent_artifact_id,
        },
        "by": list(by),
        "mode": spec.parameters.get("mode", "split_file"),
        "group_count": len(group_entries),
        "groups": group_entries,
        "lineage": {
            "preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        },
    }
    manifest_path = run_root / manifest_rel
    if manifest_path.exists() and read_json(manifest_path) != manifest_payload:
        raise DataColumnCastValidationError("deterministic split manifest path is occupied")
    if not manifest_path.exists():
        write_json(manifest_path, manifest_payload)
    _ensure_registered_artifact(
        run_root,
        artifact_id=manifest_id,
        path=manifest_path,
        artifact_type="metadata",
        step="data.split.group",
        inputs=[source_artifact_id, parent_artifact_id, *[entry["artifact_id"] for entry in group_entries]],
    )
    _graph_store_for(run_root).mutate(
        spec.source_run_id,
        lambda current: _commit_split_group_graph_children(
            current,
            spec=spec,
            parent_child_node_id=parent_child_node_id,
            manifest_id=manifest_id,
            manifest_rel=manifest_rel,
            entries=group_entries,
        ),
    )
    for entry in group_entries:
        _ensure_node_index_entry(
            run_root,
            child_node_id=entry["child_node_id"],
            node_hash=entry["node_hash"],
            artifact_rel=entry["path"],
            producing_stage="data.split.group",
            create_if_missing=True,
        )
    public_entries = tuple(
        {
            key: value
            for key, value in entry.items()
            if key != "node_hash"
        }
        for entry in group_entries
    )
    return public_entries, manifest_id, manifest_rel


def _commit_split_group_graph_children(
    graph: Graph,
    *,
    spec: DataTransformSpecV1,
    parent_child_node_id: str,
    manifest_id: str,
    manifest_rel: str,
    entries: list[dict[str, Any]],
) -> Graph:
    nodes = dict(graph.nodes)
    edges = dict(graph.edges)
    branches = dict(graph.branches)
    for entry in entries:
        child_node_id = str(entry["child_node_id"])
        if child_node_id in nodes:
            continue
        digest = child_node_id.rsplit(":", 1)[-1]
        branch_id = f"split-group:{digest[:20]}"
        nodes[child_node_id] = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=f"Split group {json.dumps(entry['key'], ensure_ascii=False, sort_keys=True)}",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=parent_child_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=entry["path"],
            summary=f"data.split group; {entry['count']} rows",
            annotations=(
                {
                    "type": "data_split_group",
                    "operation_id": "data.split",
                    "parent_child_node_id": parent_child_node_id,
                    "group_manifest_id": manifest_id,
                    "group_manifest_path": manifest_rel,
                    "group_key": entry["key"],
                    "group_count": entry["count"],
                    "artifact_id": entry["artifact_id"],
                    "metadata_artifact_id": entry["metadata_artifact_id"],
                    "metadata_artifact_path": entry["metadata_artifact_path"],
                },
            ),
            stage=Stage.TRANSFORM,
            node_hash=entry["node_hash"],
        )
        edge_id = f"edge:{child_node_id}"
        edges[edge_id] = Edge(
            id=edge_id,
            source_id=parent_child_node_id,
            target_id=child_node_id,
            op="data.split.group",
            params={
                "group_key": entry["key"],
                "group_count": entry["count"],
                "manifest_id": manifest_id,
            },
        )
        branches[branch_id] = BranchRef(
            branch_id,
            parent_child_node_id,
            (child_node_id,),
        )
    return Graph(
        schema_version=graph.schema_version,
        run_id=graph.run_id,
        nodes=nodes,
        edges=edges,
        branches=branches,
        legacy=graph.legacy,
    )


def _metadata_mutation_canonical(
    frame: pd.DataFrame,
    spec: MetadataMutationSpecV1,
    registry: MetadataRegistryV1 | None = None,
) -> dict[str, object]:
    try:
        incoming = normalize_metadata_mutation_payload(
            spec.metadata,
            weight=spec.weight,
            split=spec.split,
            group=spec.group,
            columns=tuple(str(column) for column in frame.columns),
        )
        if registry is None:
            return incoming
        existing = registry.metadata
        merged_columns: dict[str, object] = {}
        existing_columns = existing.get("columns", {})
        if isinstance(existing_columns, Mapping):
            merged_columns.update({str(column): dict(value) for column, value in existing_columns.items() if isinstance(value, Mapping)})
        incoming_columns = incoming.get("columns", {})
        if isinstance(incoming_columns, Mapping):
            for column, value in incoming_columns.items():
                prior = merged_columns.get(str(column), {})
                merged = dict(prior) if isinstance(prior, Mapping) else {}
                if isinstance(value, Mapping):
                    merged.update(value)
                merged_columns[str(column)] = merged
        merged: dict[str, object] = {"columns": merged_columns}
        existing_dataset = {
            key: existing[key]
            for key in ("weight", "split", "group")
            if key in existing
        }
        for key in ("weight", "split", "group"):
            if key in incoming:
                existing_dataset[key] = incoming[key]
        merged.update(existing_dataset)
        return merged
    except (MetadataProvenanceError, TypeError, ValueError) as exc:
        raise DataColumnCastValidationError(str(exc)) from exc


def preview_metadata_mutation(
    project_root: Path | str,
    spec: MetadataMutationSpecV1,
) -> MetadataMutationPreviewV1:
    run_root, _graph, node, artifact, source_path = _resolve_source(
        project_root,
        _transform_source_spec(
            spec.source_run_id,
            spec.source_node_id,
            spec.source_artifact_id,
        ),
    )
    frame = _read_frame(source_path)
    registry = _metadata_registry_for_source(run_root, node, spec.source_artifact_id)
    if registry is None:
        raise DataMetadataUnavailableError(
            "metadata mutation requires a confirmed server-owned metadata registry"
        )
    canonical = _metadata_mutation_canonical(frame, spec, registry)
    source_sha = str(artifact.get("sha256") or sha256_file(source_path))
    schema_revision = registry.schema_revision if registry is not None else _schema_revision_for_frame(frame)
    metadata_revision = metadata_revision_digest(canonical, schema_revision=schema_revision)
    metadata_fingerprint = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    changed_columns = set(canonical.get("columns", {}))
    for declaration_name in ("weight", "split", "group"):
        declaration = canonical.get(declaration_name)
        if isinstance(declaration, Mapping):
            if declaration_name == "weight":
                changed_columns.add(str(declaration["column"]))
            else:
                changed_columns.update(str(column) for column in declaration["columns"])
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "metadata_fingerprint": metadata_fingerprint,
        "metadata": canonical,
        "schema_revision": schema_revision,
        "metadata_revision": metadata_revision,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return MetadataMutationPreviewV1(
        spec=spec,
        source_sha256=source_sha,
        metadata_fingerprint=metadata_fingerprint,
        changed_columns=tuple(sorted(changed_columns)),
        fingerprint=fingerprint,
        canonical_metadata=canonical,
        schema_revision=schema_revision,
        metadata_revision=metadata_revision,
    )


@_data_operation_transaction
def apply_metadata_mutation(
    project_root: Path | str,
    spec: MetadataMutationSpecV1,
    preview: MetadataMutationPreviewV1,
    *,
    execution_key_value: str | None = None,
) -> MetadataMutationEffectV1:
    if preview.spec != spec:
        raise DataColumnCastValidationError("metadata mutation preview spec does not match")
    fresh = preview_metadata_mutation(project_root, spec)
    if fresh.fingerprint != preview.fingerprint:
        raise DataColumnCastValidationError("metadata mutation preview is stale")
    run_root, _graph, source_node, source_artifact, source_path = _resolve_source(
        project_root,
        _transform_source_spec(
            spec.source_run_id,
            spec.source_node_id,
            spec.source_artifact_id,
        ),
    )
    execution = execution_key_value or f"exec_{fresh.fingerprint[:32]}"
    suffix = execution.removeprefix("exec_")
    record_id = f"metadata_update:{spec.source_run_id}:{suffix}"
    metadata_artifact_id = f"metadata_update_{suffix}"
    relative_dir = Path("derived") / "data_operations" / "metadata_update" / suffix
    metadata_rel = (relative_dir / "metadata.json").as_posix()
    record_rel = (relative_dir / "operation.json").as_posix()
    metadata_path = run_root / metadata_rel
    record_path = run_root / record_rel
    child_node_id = f"metadata-update:{suffix}"
    source_sha = str(source_artifact.get("sha256") or "")
    metadata_payload = {
        "payload_schema": "workbench.data-metadata",
        "schema_version": 1,
        "operation_id": spec.operation_id,
        "operation_version": spec.operation_version,
        "record_id": record_id,
        "execution_key": execution,
        "source": {
            "run_id": spec.source_run_id,
            "node_id": child_node_id,
            "artifact_id": spec.source_artifact_id,
            "sha256": source_sha,
        },
        "confirmed": True,
        "schema_revision": fresh.schema_revision,
        "metadata_revision": fresh.metadata_revision,
        "metadata_fingerprint": fresh.metadata_fingerprint,
        "metadata": fresh.canonical_metadata,
        "child_node_id": child_node_id,
        "provenance": {
            "operation_id": spec.operation_id,
            "preview_fingerprint": fresh.fingerprint,
            "parent_metadata_revision": None,
        },
    }
    _preflight_json_path(
        metadata_path,
        metadata_payload,
        "deterministic metadata artifact path is occupied",
    )
    _preflight_record_path(record_path, record_id=record_id, execution_key=execution)
    _preflight_artifact_binding(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="metadata",
        step="data.metadata.update",
        inputs=[spec.source_artifact_id],
    )
    _preflight_node_index_entry(
        run_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(metadata_path) if metadata_path.exists() else None,
        artifact_rel=str(source_artifact.get("path")),
        producing_stage="data.metadata.update",
        create_if_missing=True,
    )
    _preflight_graph_child(
        _graph,
        child_node_id=child_node_id,
        artifact_path=metadata_path,
        artifact_rel=str(source_artifact.get("path")),
        operation_id=spec.operation_id,
    )
    if not metadata_path.exists():
        write_json(metadata_path, metadata_payload)
    _ensure_registered_artifact(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="metadata",
        step="data.metadata.update",
        inputs=[spec.source_artifact_id],
    )
    record_payload = {
        "record_id": record_id,
        "operation_id": spec.operation_id,
        "operation_version": spec.operation_version,
        "status": "completed",
        "execution_key": execution,
        "source": metadata_payload["source"],
        "metadata_fingerprint": fresh.metadata_fingerprint,
        "metadata": fresh.canonical_metadata,
        "metadata_artifact": {
            "artifact_id": metadata_artifact_id,
            "path": metadata_rel,
            "sha256": sha256_file(metadata_path),
        },
        "child_node_id": child_node_id,
        "preview": fresh.to_dict(),
    }
    if record_path.exists() and read_json(record_path) != record_payload:
        raise DataColumnCastValidationError("deterministic metadata record path is occupied")
    if not record_path.exists():
        write_json(record_path, record_payload)
    _graph_store_for(run_root).mutate(
        spec.source_run_id,
        lambda current: current
        if child_node_id in current.nodes
        else _commit_metadata_graph_child(
            current,
            spec=spec,
            preview=fresh,
            metadata_rel=metadata_rel,
            data_artifact_rel=str(source_artifact.get("path")),
            metadata_artifact_id=metadata_artifact_id,
            child_node_id=child_node_id,
            execution_key=execution,
            node_hash=sha256_file(metadata_path),
        ),
    )
    _ensure_node_index_entry(
        run_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(metadata_path),
        artifact_rel=str(source_artifact.get("path")),
        producing_stage="data.metadata.update",
        create_if_missing=True,
    )
    return MetadataMutationEffectV1(
        record_id=record_id,
        execution_key=execution,
        metadata_artifact_id=metadata_artifact_id,
        metadata_artifact_path=metadata_rel,
        child_node_id=child_node_id,
        schema_revision=fresh.schema_revision,
        metadata_revision=fresh.metadata_revision,
    )


def read_metadata_mutation_record(project_root: Path | str, record_id: str) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    runs_root = root / "runs"
    if not runs_root.is_dir():
        raise FileNotFoundError("project runs root was not found")
    for run_root in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        base = run_root / "derived" / "data_operations" / "metadata_update"
        if not base.is_dir():
            continue
        for record_path in sorted(base.glob("*/operation.json")):
            try:
                payload = read_json(record_path)
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("record_id") == record_id:
                return payload
    raise FileNotFoundError("metadata mutation record was not found")


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
    metadata_artifact_id: str | None = None
    metadata_artifact_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
            "metadata_artifact_id": self.metadata_artifact_id,
            "metadata_artifact_path": self.metadata_artifact_path,
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


@_data_operation_transaction
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
    run_root, graph, source_node, source_artifact, source_path = _resolve_source(project_root, source_spec)
    metadata_registry = _metadata_registry_for_source(
        run_root, source_node, spec.source_artifact_id
    )
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
    child_node_id = f"feature-recipe:{suffix}"
    metadata_artifact_id = f"{artifact_id}_metadata"
    metadata_rel = (relative_dir / "metadata.json").as_posix()
    output_metadata = _metadata_for_output(
        metadata_registry, spec=spec, output_columns=output.columns
    )
    metadata_payload = _metadata_sidecar_payload(
        registry=metadata_registry,
        metadata=output_metadata,
        output_frame=output,
        run_id=spec.source_run_id,
        child_node_id=child_node_id,
        artifact_id=artifact_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(source_artifact.get("sha256") or sha256_file(source_path)),
        operation_id="data.feature_recipe",
        preview_fingerprint=fresh.fingerprint,
    )
    recipe_payload = {
        **spec.recipe.to_dict(),
        "execution_key": execution,
        "source_sha256": str(source_artifact.get("sha256") or sha256_file(source_path)),
        "result": {"artifact_id": artifact_id, "path": artifact_rel},
    }
    _preflight_frame_artifact(artifact_path, output)
    _preflight_json_path(run_root / metadata_rel, metadata_payload, "deterministic metadata sidecar path is occupied")
    _preflight_json_path(recipe_path, recipe_payload, "deterministic feature recipe path is occupied")
    _preflight_artifact_binding(run_root, artifact_id=artifact_id, path=artifact_path, artifact_type="derived_data", step=spec.recipe.operation_id, inputs=[spec.source_artifact_id])
    _preflight_artifact_binding(run_root, artifact_id=metadata_artifact_id, path=run_root / metadata_rel, artifact_type="metadata", step="data.feature_recipe", inputs=[spec.source_artifact_id, artifact_id])
    _preflight_artifact_binding(run_root, artifact_id=recipe_artifact_id, path=recipe_path, artifact_type="metadata", step=spec.recipe.operation_id, inputs=[spec.source_artifact_id, artifact_id])
    _preflight_graph_child(graph, child_node_id=child_node_id, artifact_path=artifact_path, artifact_rel=artifact_rel, operation_id=spec.recipe.operation_id)
    _preflight_node_index_entry(run_root, child_node_id=child_node_id, node_hash=sha256_file(artifact_path) if artifact_path.exists() else None, artifact_rel=artifact_rel, producing_stage=spec.recipe.operation_id, create_if_missing=True)
    _write_frame_artifact(artifact_path, output, "csv")
    metadata_artifact_id, metadata_rel, _metadata_payload = _write_metadata_sidecar(
        run_root,
        relative_dir=relative_dir,
        artifact_id=artifact_id,
        output_frame=output,
        child_node_id=child_node_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(source_artifact.get("sha256") or sha256_file(source_path)),
        operation_id="data.feature_recipe",
        preview_fingerprint=fresh.fingerprint,
        registry=metadata_registry,
        metadata=_metadata_for_output(metadata_registry, spec=spec, output_columns=output.columns),
    )
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
            metadata_artifact_id=metadata_artifact_id,
            metadata_rel=metadata_rel,
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
        metadata_artifact_id=metadata_artifact_id,
        metadata_artifact_path=metadata_rel,
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


@_data_operation_transaction
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
    metadata_registry = _metadata_registry_for_source(
        run_root, source_node, spec.source_artifact_id
    )
    execution = execution_key_value or data_column_cast_execution_key(spec, fresh)
    artifact_id = f"data_cast_{execution.removeprefix('exec_')}"
    recipe_artifact_id = f"data_cast_recipe_{execution.removeprefix('exec_')}"
    relative_dir = Path("derived") / "data_column_cast" / execution.removeprefix("exec_")
    artifact_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = run_root / artifact_rel
    recipe_path = run_root / recipe_rel
    child_node_id = f"data-cast:{execution.removeprefix('exec_')}"

    frame = _read_frame(source_path)
    converted, failures = _convert_strict(frame[spec.column], spec.target_dtype)
    if bool(failures.any()):
        raise DataColumnCastValidationError("cast preview is blocked")
    output_frame = frame.copy()
    output_frame[spec.column] = converted
    metadata_artifact_id = f"{artifact_id}_metadata"
    metadata_rel = (relative_dir / "metadata.json").as_posix()
    metadata_payload = _metadata_sidecar_payload(
        registry=metadata_registry,
        metadata=_metadata_for_output(metadata_registry, spec=spec, output_columns=output_frame.columns),
        output_frame=output_frame,
        run_id=spec.source_run_id,
        child_node_id=child_node_id,
        artifact_id=artifact_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(source_artifact.get("sha256") or sha256_file(source_path)),
        operation_id=spec.operation_id,
        preview_fingerprint=fresh.fingerprint,
    )
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
    _preflight_frame_artifact(artifact_path, output_frame)
    _preflight_json_path(run_root / metadata_rel, metadata_payload, "deterministic metadata sidecar path is occupied")
    _preflight_json_path(recipe_path, recipe, "deterministic cast recipe path is occupied")
    _preflight_artifact_binding(run_root, artifact_id=artifact_id, path=artifact_path, artifact_type="derived_data", step="data.column.cast", inputs=[spec.source_artifact_id])
    _preflight_artifact_binding(run_root, artifact_id=metadata_artifact_id, path=run_root / metadata_rel, artifact_type="metadata", step=spec.operation_id, inputs=[spec.source_artifact_id, artifact_id])
    _preflight_artifact_binding(run_root, artifact_id=recipe_artifact_id, path=recipe_path, artifact_type="metadata", step="data.column.cast", inputs=[spec.source_artifact_id, artifact_id])
    _preflight_graph_child(graph, child_node_id=child_node_id, artifact_path=artifact_path, artifact_rel=artifact_rel, operation_id=spec.operation_id)
    _preflight_node_index_entry(run_root, child_node_id=child_node_id, node_hash=sha256_file(artifact_path) if artifact_path.exists() else None, artifact_rel=artifact_rel, producing_stage="data.column.cast", create_if_missing=True)
    _write_frame_artifact(artifact_path, output_frame, "csv")
    metadata_artifact_id, metadata_rel, _metadata_payload = _write_metadata_sidecar(
        run_root,
        relative_dir=relative_dir,
        artifact_id=artifact_id,
        output_frame=output_frame,
        child_node_id=child_node_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(source_artifact.get("sha256") or sha256_file(source_path)),
        operation_id=spec.operation_id,
        preview_fingerprint=fresh.fingerprint,
        registry=metadata_registry,
        metadata=_metadata_for_output(metadata_registry, spec=spec, output_columns=output_frame.columns),
    )

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
                metadata_artifact_id=metadata_artifact_id,
                metadata_rel=metadata_rel,
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
        metadata_artifact_id=metadata_artifact_id,
        metadata_artifact_path=metadata_rel,
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
    metadata_artifact_id: str | None = None
    metadata_artifact_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
            "metadata_artifact_id": self.metadata_artifact_id,
            "metadata_artifact_path": self.metadata_artifact_path,
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


@_data_operation_transaction
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
    metadata_registry = _metadata_registry_for_source(
        run_root, source_node, spec.source_artifact_id
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
    child_node_id = f"data-casts:{key}"

    frame = _read_frame(source_path)
    output_frame = frame.copy()
    for item in spec.casts:
        converted, failures = _convert_strict(frame[item.column], item.target_dtype)
        if bool(failures.any()):
            raise DataColumnCastValidationError("cast preview is blocked")
        output_frame[item.column] = converted
    metadata_artifact_id = f"{artifact_id}_metadata"
    metadata_rel = (relative_dir / "metadata.json").as_posix()
    metadata_payload = _metadata_sidecar_payload(
        registry=metadata_registry,
        metadata=_metadata_for_output(metadata_registry, spec=spec, output_columns=output_frame.columns),
        output_frame=output_frame,
        run_id=spec.source_run_id,
        child_node_id=child_node_id,
        artifact_id=artifact_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(source_artifact.get("sha256") or sha256_file(source_path)),
        operation_id=spec.operation_id,
        preview_fingerprint=fresh.fingerprint,
    )
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
    _preflight_frame_artifact(artifact_path, output_frame)
    _preflight_json_path(run_root / metadata_rel, metadata_payload, "deterministic metadata sidecar path is occupied")
    _preflight_json_path(recipe_path, recipe, "deterministic cast recipe path is occupied")
    _preflight_artifact_binding(run_root, artifact_id=artifact_id, path=artifact_path, artifact_type="derived_data", step=spec.operation_id, inputs=[spec.source_artifact_id])
    _preflight_artifact_binding(run_root, artifact_id=metadata_artifact_id, path=run_root / metadata_rel, artifact_type="metadata", step=spec.operation_id, inputs=[spec.source_artifact_id, artifact_id])
    _preflight_artifact_binding(run_root, artifact_id=recipe_artifact_id, path=recipe_path, artifact_type="metadata", step=spec.operation_id, inputs=[spec.source_artifact_id, artifact_id])
    _preflight_graph_child(graph, child_node_id=child_node_id, artifact_path=artifact_path, artifact_rel=artifact_rel, operation_id=spec.operation_id)
    _preflight_node_index_entry(run_root, child_node_id=child_node_id, node_hash=sha256_file(artifact_path) if artifact_path.exists() else None, artifact_rel=artifact_rel, producing_stage=spec.operation_id, create_if_missing=True)
    _write_frame_artifact(artifact_path, output_frame, spec.output_format)
    metadata_artifact_id, metadata_rel, _metadata_payload = _write_metadata_sidecar(
        run_root,
        relative_dir=relative_dir,
        artifact_id=artifact_id,
        output_frame=output_frame,
        child_node_id=child_node_id,
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        source_sha256=str(source_artifact.get("sha256") or sha256_file(source_path)),
        operation_id=spec.operation_id,
        preview_fingerprint=fresh.fingerprint,
        registry=metadata_registry,
        metadata=_metadata_for_output(metadata_registry, spec=spec, output_columns=output_frame.columns),
    )

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
                metadata_artifact_id=metadata_artifact_id,
                metadata_rel=metadata_rel,
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
        metadata_artifact_id=metadata_artifact_id,
        metadata_artifact_path=metadata_rel,
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
    metadata_artifact_id: str | None = None,
    metadata_rel: str | None = None,
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
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_artifact_path": metadata_rel,
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


def _node_annotation_value(node: Any, key: str) -> object | None:
    for annotation in getattr(node, "annotations", ()):
        if isinstance(annotation, Mapping) and key in annotation:
            return annotation[key]
    return None


def _metadata_registry_for_source(
    run_root: Path,
    node: Any,
    source_artifact_id: str,
) -> MetadataRegistryV1 | None:
    """Resolve only a confirmed metadata artifact bound to the selected data."""

    index = read_json(run_root / "artifacts_index.json")
    records = index.get("artifacts", [])
    if not isinstance(records, list):
        raise DataMetadataUnavailableError("metadata artifact index is malformed")
    by_id = {
        item.get("artifact_id"): item
        for item in records
        if isinstance(item, Mapping) and isinstance(item.get("artifact_id"), str)
    }
    candidate_ids: list[str] = []
    annotated_id = _node_annotation_value(node, "metadata_artifact_id")
    if isinstance(annotated_id, str) and annotated_id:
        candidate_ids.append(annotated_id)
    annotated_path = _node_annotation_value(node, "metadata_artifact_path")
    candidates: list[Mapping[str, object]] = []
    for artifact_id in candidate_ids:
        candidate = by_id.get(artifact_id)
        if isinstance(candidate, Mapping):
            candidates.append(candidate)
        else:
            raise DataMetadataUnavailableError(
                f"metadata artifact {artifact_id!r} is not registered"
            )
    for item in records:
        if not isinstance(item, Mapping) or item in candidates:
            continue
        inputs = item.get("inputs")
        if item.get("artifact_type") == "metadata" and isinstance(inputs, list) and source_artifact_id in inputs:
            candidates.append(item)
            continue
        if isinstance(annotated_path, str) and item.get("path") == annotated_path:
            candidates.append(item)
    for artifact in candidates:
        relative = artifact.get("path")
        if not isinstance(relative, str) or not relative:
            raise DataMetadataUnavailableError("metadata artifact has no safe path")
        metadata_path = (run_root / relative).resolve()
        try:
            metadata_path.relative_to(run_root.resolve())
        except ValueError as exc:
            raise DataMetadataUnavailableError("metadata artifact escapes the run root") from exc
        if not metadata_path.is_file():
            raise DataMetadataUnavailableError("metadata artifact file is missing")
        expected_sha = artifact.get("sha256")
        if expected_sha and expected_sha != sha256_file(metadata_path):
            raise DataMetadataUnavailableError("metadata artifact fingerprint changed")
        try:
            payload = read_json(metadata_path)
            if not isinstance(payload, Mapping):
                raise ValueError("metadata artifact must be an object")
            if payload.get("payload_schema") != "workbench.data-metadata":
                continue
            payload_source = payload.get("source")
            if isinstance(payload_source, Mapping) and (
                payload_source.get("run_id") != run_root.name
                or payload_source.get("node_id") != getattr(node, "id", None)
                or payload_source.get("artifact_id") != source_artifact_id
            ):
                if artifact.get("artifact_id") in candidate_ids:
                    raise DataMetadataUnavailableError(
                        "metadata artifact source does not match the selected dataset"
                    )
                continue
            return MetadataRegistryV1.from_payload(
                payload,
                source_run_id=run_root.name,
                source_node_id=str(getattr(node, "id", "")),
                source_artifact_id=source_artifact_id,
            )
        except MetadataProvenanceError:
            # Derived transforms always retain a provenance sidecar, even
            # when their source had no confirmed registry.  That sidecar
            # remains useful evidence but must never become a metadata
            # consumer registry.  Skip only the explicit unconfirmed
            # projection; malformed/confirmed artifacts still fail closed.
            if payload.get("confirmed") is False:
                continue
            raise DataMetadataUnavailableError(
                f"metadata artifact {relative!r} is not a confirmed registry"
            ) from None
        except (OSError, TypeError, ValueError) as exc:
            raise DataMetadataUnavailableError(
                f"metadata artifact {relative!r} is unreadable: {exc}"
            ) from exc
    return None


def resolve_metadata_registry(
    project_root: Path | str,
    *,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> MetadataRegistryV1 | None:
    probe = _transform_source_spec(source_run_id, source_node_id, source_artifact_id)
    run_root, _graph, node, _artifact, _path = _resolve_source(project_root, probe)
    return _metadata_registry_for_source(run_root, node, source_artifact_id)


def _schema_revision_for_frame(frame: pd.DataFrame) -> str:
    payload = {
        "columns": [
            {"name": str(column), "dtype": str(frame[column].dtype)}
            for column in frame.columns
        ]
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"schema:{digest}"


def _metadata_for_output(
    registry: MetadataRegistryV1 | None,
    *,
    spec: DataTransformSpecV1 | DataColumnCastSpecV1 | DataColumnsCastSpecV1 | FeatureRecipeOperationSpecV1,
    output_columns: Iterable[str],
) -> dict[str, object]:
    if registry is None:
        return {"columns": {}}
    output_names = tuple(str(column) for column in output_columns)
    output_name_set = set(output_names)
    parameters = getattr(spec, "parameters", {})
    rename_mapping: dict[str, str] = {}
    if isinstance(parameters, Mapping) and spec.__class__ is DataTransformSpecV1:
        if spec.operation == "rename" and isinstance(parameters.get("mapping"), Mapping):
            rename_mapping = {
                str(old): str(new)
                for old, new in parameters["mapping"].items()
            }

    source_metadata = registry.metadata
    raw_columns = source_metadata.get("columns", {})
    if not isinstance(raw_columns, Mapping):
        return {"columns": {}}
    columns: dict[str, dict[str, object]] = {}
    for source_column, declaration in raw_columns.items():
        if not isinstance(declaration, Mapping):
            continue
        output_name = rename_mapping.get(str(source_column), str(source_column))
        if output_name in output_name_set:
            # A rename changes identity, not the meaning of a confirmed
            # declaration.  Copy the complete expressible declaration so
            # labels, value labels, and user-missing values survive reload.
            columns[output_name] = dict(declaration)
    result: dict[str, object] = {"columns": columns}
    dataset_copy = {
        key: source_metadata[key]
        for key in ("weight", "split", "group")
        if key in source_metadata
    }
    if dataset_copy:
        weight = dataset_copy.get("weight")
        if isinstance(weight, Mapping):
            weight_copy = dict(weight)
            weight_column = weight_copy.get("column")
            mapped_weight_column = rename_mapping.get(str(weight_column), weight_column)
            if mapped_weight_column not in output_name_set:
                dataset_copy.pop("weight", None)
            else:
                weight_copy["column"] = mapped_weight_column
                dataset_copy["weight"] = weight_copy
        for name in ("split", "group"):
            declaration = dataset_copy.get(name)
            if isinstance(declaration, Mapping):
                declaration_copy = dict(declaration)
                declared_columns = declaration_copy.get("columns")
                mapped_columns = [
                    rename_mapping.get(str(column), str(column))
                    for column in declared_columns
                ] if isinstance(declared_columns, list) else None
                if mapped_columns is not None and not set(mapped_columns) <= output_name_set:
                    dataset_copy.pop(name, None)
                elif mapped_columns is not None:
                    declaration_copy["columns"] = mapped_columns
                    dataset_copy[name] = declaration_copy
        result.update(dataset_copy)
    return result


def _metadata_column_aliases(spec: object) -> dict[str, str]:
    parameters = getattr(spec, "parameters", {})
    if (
        isinstance(parameters, Mapping)
        and spec.__class__ is DataTransformSpecV1
        and spec.operation == "rename"
        and isinstance(parameters.get("mapping"), Mapping)
    ):
        return {str(old): str(new) for old, new in parameters["mapping"].items()}
    return {}


def _metadata_sidecar_payload(
    *,
    registry: MetadataRegistryV1 | None,
    metadata: Mapping[str, object],
    output_frame: pd.DataFrame,
    run_id: str,
    child_node_id: str,
    artifact_id: str,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
    source_sha256: str,
    operation_id: str,
    preview_fingerprint: str,
    column_aliases: Mapping[str, str] | None = None,
) -> dict[str, object]:
    schema_revision = _schema_revision_for_frame(output_frame)
    metadata_loss: list[dict[str, str]] = []
    if registry is not None:
        source_metadata = registry.metadata
        source_columns = source_metadata.get("columns", {})
        aliases = {str(key): str(value) for key, value in (column_aliases or {}).items()}
        if isinstance(source_columns, Mapping):
            for column, declaration in source_columns.items():
                output_column = aliases.get(str(column), str(column))
                if output_column not in output_frame.columns and isinstance(declaration, Mapping):
                    for field_name in declaration:
                        metadata_loss.append(
                            {
                                "field": f"{column}.{field_name}",
                                "status": "dropped",
                                "reason": "transform output does not contain the source column",
                            }
                        )
        for dataset_name in ("weight", "split", "group"):
            declaration = source_metadata.get(dataset_name)
            if not isinstance(declaration, Mapping):
                continue
            declared_columns = declaration.get("columns")
            if dataset_name == "weight":
                declared_columns = [aliases.get(str(declaration.get("column")), declaration.get("column"))]
            elif isinstance(declared_columns, list):
                declared_columns = [aliases.get(str(column), str(column)) for column in declared_columns]
            if isinstance(declared_columns, list) and not set(declared_columns) <= set(output_frame.columns):
                metadata_loss.append(
                    {
                        "field": dataset_name,
                        "status": "dropped",
                        "reason": "transform output cannot express a declaration for missing columns",
                    }
                )
    return {
        "payload_schema": "workbench.data-metadata",
        "schema_version": 1,
        "confirmed": registry is not None,
        "schema_revision": schema_revision,
        "metadata_revision": metadata_revision_digest(metadata, schema_revision=schema_revision),
        "source": {
            "run_id": run_id,
            "node_id": child_node_id,
            "artifact_id": artifact_id,
        },
        "metadata": dict(metadata),
        "metadata_loss": metadata_loss,
        "provenance": {
            "source_run_id": source_run_id,
            "source_node_id": source_node_id,
            "source_artifact_id": source_artifact_id,
            "source_sha256": source_sha256,
            "operation_id": operation_id,
            "preview_fingerprint": preview_fingerprint,
            "parent_metadata_revision": None if registry is None else registry.metadata_revision,
            "metadata_confirmation": "server-owned" if registry is not None else "unavailable",
        },
    }


def _write_metadata_sidecar(
    run_root: Path,
    *,
    relative_dir: Path,
    metadata_filename: str = "metadata.json",
    artifact_id: str,
    output_frame: pd.DataFrame,
    child_node_id: str,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
    source_sha256: str,
    operation_id: str,
    preview_fingerprint: str,
    registry: MetadataRegistryV1 | None,
    metadata: Mapping[str, object],
    column_aliases: Mapping[str, str] | None = None,
) -> tuple[str, str, dict[str, object]]:
    metadata_artifact_id = f"{artifact_id}_metadata"
    metadata_rel = (relative_dir / metadata_filename).as_posix()
    metadata_path = run_root / metadata_rel
    payload = _metadata_sidecar_payload(
        registry=registry,
        metadata=metadata,
        output_frame=output_frame,
        run_id=source_run_id,
        child_node_id=child_node_id,
        artifact_id=artifact_id,
        source_run_id=source_run_id,
        source_node_id=source_node_id,
        source_artifact_id=source_artifact_id,
        source_sha256=source_sha256,
        operation_id=operation_id,
        preview_fingerprint=preview_fingerprint,
        column_aliases=column_aliases,
    )
    if metadata_path.exists() and read_json(metadata_path) != payload:
        raise DataColumnCastValidationError("deterministic metadata sidecar path is occupied")
    if not metadata_path.exists():
        write_json(metadata_path, payload)
    _ensure_registered_artifact(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="metadata",
        step=operation_id,
        inputs=[source_artifact_id, artifact_id],
    )
    return metadata_artifact_id, metadata_rel, payload


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


def _preflight_json_path(path: Path, payload: Mapping[str, object], error: str) -> None:
    """Reject a conflicting deterministic JSON path before any operation write."""

    if path.exists() and read_json(path) != dict(payload):
        raise DataColumnCastValidationError(error)


def _preflight_record_path(path: Path, *, record_id: str, execution_key: str) -> None:
    """Reject an occupied operation-record path before any artifact write."""

    if not path.exists():
        return
    payload = read_json(path)
    if not isinstance(payload, Mapping) or (
        payload.get("record_id") != record_id
        or payload.get("execution_key") != execution_key
    ):
        raise DataColumnCastValidationError("deterministic metadata record path is occupied")


def _preflight_graph_child(
    graph: Graph,
    *,
    child_node_id: str,
    artifact_path: Path,
    artifact_rel: str,
    operation_id: str,
) -> None:
    """Validate an existing graph child and edge before persistent writes."""

    child = graph.nodes.get(child_node_id)
    edge = graph.edges.get(f"edge:{child_node_id}")
    if child is None:
        if edge is not None:
            raise DataColumnCastValidationError("deterministic graph edge has no child")
        return
    if child.payload_ref != artifact_rel:
        raise DataColumnCastValidationError("deterministic graph child payload is occupied")
    if not artifact_path.is_file():
        raise DataColumnCastValidationError("deterministic graph child artifact is missing")
    if child.node_hash and child.node_hash != sha256_file(artifact_path):
        raise DataColumnCastValidationError("deterministic graph child hash is occupied")
    if edge is None or edge.target_id != child_node_id or edge.op != operation_id:
        raise DataColumnCastValidationError("deterministic graph edge is occupied")


def _preflight_artifact_binding(
    run_root: Path,
    *,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> None:
    """Validate an existing artifact-index row without mutating the index."""

    index = read_json(run_root / "artifacts_index.json")
    existing = [
        item
        for item in index.get("artifacts", [])
        if isinstance(item, Mapping) and item.get("artifact_id") == artifact_id
    ]
    if not existing:
        return
    if len(existing) != 1:
        raise DataColumnCastValidationError("artifact binding is duplicated")
    row = existing[0]
    expected_path = path.resolve().relative_to(run_root.resolve()).as_posix()
    if (
        row.get("path") != expected_path
        or row.get("artifact_type") != artifact_type
        or row.get("step") != step
        or row.get("inputs") != inputs
        or not path.is_file()
        or row.get("sha256") != sha256_file(path)
    ):
        raise DataColumnCastValidationError("artifact binding is not deterministic")


def _preflight_node_index_entry(
    run_root: Path,
    *,
    child_node_id: str,
    node_hash: str | None,
    artifact_rel: str,
    producing_stage: str,
    create_if_missing: bool,
) -> None:
    """Validate a deterministic child index entry before output materialization."""

    from .lineage.node_index import NODE_INDEX_FILENAME

    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return
    index = read_json(index_path)
    existing = index.get(child_node_id)
    if existing is None:
        return
    if node_hash is None:
        raise DataColumnCastValidationError("node index entry has no matching artifact")
    expected = {
        "node_hash": node_hash,
        "producing_stage": producing_stage,
        "cas_ref": {"node_hash": node_hash, "artifact": artifact_rel},
    }
    if existing != expected:
        raise DataColumnCastValidationError("node index entry is not deterministic")


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
    metadata_artifact_id: str | None = None,
    metadata_rel: str | None = None,
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
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_artifact_path": metadata_rel,
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
    metadata_artifact_id: str | None = None,
    metadata_rel: str | None = None,
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
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_artifact_path": metadata_rel,
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
    metadata_artifact_id: str | None = None,
    metadata_rel: str | None = None,
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
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_artifact_path": metadata_rel,
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


def _commit_metadata_graph_child(
    graph: Graph,
    *,
    spec: MetadataMutationSpecV1,
    preview: MetadataMutationPreviewV1,
    metadata_rel: str,
    data_artifact_rel: str,
    metadata_artifact_id: str,
    child_node_id: str,
    execution_key: str,
    node_hash: str,
) -> Graph:
    branch_id = f"metadata-update:{execution_key.removeprefix('exec_')[:20]}"
    child = Node(
        id=child_node_id,
        kind=NodeKind.DATASET_STAGE,
        display_label="Metadata update",
        created_at=datetime.now(timezone.utc).isoformat(),
        parent_stage_id=spec.source_node_id,
        branch_id=branch_id,
        trust=Trust.OK,
        payload_ref=data_artifact_rel,
        summary=(
            f"metadata for {len(preview.changed_columns)} columns; "
            "source rows unchanged; downstream profile reload required"
        ),
        annotations=(
            {
                "type": "metadata_operation",
                "operation_id": spec.operation_id,
                "execution_key": execution_key,
                "metadata_artifact_path": metadata_rel,
                "metadata_artifact_id": metadata_artifact_id,
                "metadata_fingerprint": preview.metadata_fingerprint,
                "schema_revision": preview.schema_revision,
                "metadata_revision": preview.metadata_revision,
                "source_node_id": spec.source_node_id,
            },
        ),
        stage=Stage.TRANSFORM,
        node_hash=node_hash,
    )
    nodes = _mark_downstream_invalidation(
        {**graph.nodes, child_node_id: child},
        reason="data_metadata_update",
        source_node_id=spec.source_node_id,
        child_node_id=child_node_id,
    )
    edges = dict(graph.edges)
    edges[f"edge:{child_node_id}"] = Edge(
        id=f"edge:{child_node_id}",
        source_id=spec.source_node_id,
        target_id=child_node_id,
        op=spec.operation_id,
        params={
            "execution_key": execution_key,
            "metadata_artifact_path": metadata_rel,
            "metadata_artifact_id": metadata_artifact_id,
            "metadata_fingerprint": preview.metadata_fingerprint,
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


def _preflight_frame_artifact(data_path: Path, frame: pd.DataFrame) -> None:
    """Validate a data file and dtype sidecar before either can be written."""

    schema_path = _schema_sidecar_path(data_path)
    data_exists = data_path.exists()
    schema_exists = schema_path.exists()
    if data_exists != schema_exists:
        raise DataColumnCastValidationError(
            "deterministic data artifact has an incomplete data/schema pair"
        )
    if schema_exists and read_json(schema_path) != {"dtypes": _frame_dtypes(frame)}:
        raise DataColumnCastValidationError("deterministic data schema path is occupied")
    if data_exists and not _read_frame(data_path).equals(frame):
        raise DataColumnCastValidationError("deterministic data artifact path is occupied")


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
