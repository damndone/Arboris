"""Typed specs, previews and effects of data operations, and their shared vocabulary."""

from __future__ import annotations

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
    status: PreviewStatus = "ready"
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


PreviewStatus = Literal["ready", "blocked"]
"""A preview is ready to confirm, or blocked with its reason."""


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
    "recode",
]


# Operations implemented before the declaration registry. Everything newer is
# declared in data_operation_registry and admitted from there.
def allowed_data_transform_operations() -> frozenset[str]:
    from ..data_operation_registry import data_operation_declarations

    return frozenset(declaration.operation for declaration in data_operation_declarations())


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
        allowed = allowed_data_transform_operations()
        if self.operation not in allowed:
            raise DataColumnCastValidationError(
                "operation must be one of: " + ", ".join(sorted(allowed))
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
    status: PreviewStatus = "ready"
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
    status: PreviewStatus = "ready"

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


# Batch cast (data.columns.cast): N columns -> one immutable child. Same typed
# lifecycle as the singular data.column.cast, but the operation grain
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
    status: PreviewStatus

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
    status: PreviewStatus = "ready"

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
