"""Typed, preview-first data operations for the V11 vertical slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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

DataCastTarget = Literal["numeric", "string", "datetime"]
ALLOWED_CAST_TARGETS = frozenset({"numeric", "string", "datetime"})

DataCastOutputFormat = Literal["csv", "xlsx"]
ALLOWED_OUTPUT_FORMATS = frozenset({"csv", "xlsx"})
_SCHEMA_SIDECAR_SUFFIX = ".schema.json"


class DataColumnCastValidationError(ValueError):
    """Raised when a typed cast cannot be resolved or safely previewed."""


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
) -> None:
    """Give the derived child node a Merkle identity in node_index.json.

    The derived artifact's content hash is the child's natural identity (same
    convention as stage:raw using the upload hash). Legacy runs without a
    node_index stay opaque, so a missing file is left absent, and the write is
    idempotent for one execution key.
    """

    from .lineage.node_index import NODE_INDEX_FILENAME

    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return
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
