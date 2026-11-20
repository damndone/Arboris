"""Column type casts, single and batch: preview, resolve, apply."""

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
from .specs import DataColumnCastEffect, DataColumnCastItemResult, DataColumnCastPreview, DataColumnCastSpecV1, DataColumnCastValidationError, DataColumnsCastEffect, DataColumnsCastPreview, DataColumnsCastSpecV1
from .frames import _convert_strict, _read_frame, _schema_fingerprint, _schema_sidecar_path, _write_frame_artifact
from .source_cache import load_verified_frame
from .graph import _commit_batch_graph_child, _commit_graph_child, _ensure_node_index_entry, _ensure_registered_artifact, _graph_store_for, _resolve_source


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

    context, _frame = _resolve_data_column_cast_source(
        project_root, source_run_id=source_run_id, source_node_id=source_node_id
    )
    return context


def _node_artifact(records: list[dict[str, Any]], node: Any, node_id: str) -> dict[str, Any]:
    """The registered artifact a dataset node's payload is: by its payload path, or the one raw snapshot."""

    if node.payload_ref:
        try:
            return next(item for item in records if item.get("path") == node.payload_ref)
        except StopIteration as exc:
            raise DataColumnCastValidationError("source node artifact was not found") from exc
    if node_id in {"stage:raw", "stage:source"}:
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
        return raw_artifacts[0]
    raise DataColumnCastValidationError("source dataset node has no materialized artifact")


def dataset_node_artifact_id(project_root: Path | str, run_id: str, node_id: str) -> str | None:
    """The artifact id of a dataset node's registered payload, without reading the data; None if none."""

    runs_root = Path(project_root).expanduser().resolve() / "runs"
    run_root = (runs_root / run_id).resolve()
    if not run_root.is_relative_to(runs_root) or not run_root.is_dir():
        return None
    from ..graph_store import GraphStore

    try:
        node = GraphStore(runs_root).read(run_id).nodes[node_id]
        if node.kind != NodeKind.DATASET_STAGE:
            return None
        artifact = _node_artifact(read_json(run_root / "artifacts_index.json").get("artifacts", []), node, node_id)
    except (KeyError, OSError, ValueError, DataColumnCastValidationError):
        return None
    artifact_id = artifact.get("artifact_id")
    return artifact_id if isinstance(artifact_id, str) and artifact_id else None


def _resolve_data_column_cast_source(
    project_root: Path | str,
    *,
    source_run_id: str,
    source_node_id: str,
    cached: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Resolve the validated source and its context once within one call.

    Hash and decode the same open file. The Data view sets ``cached`` to reuse the digest
    and frame within a byte budget. Other callers keep nothing between requests.
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

    from ..graph_store import GraphStore

    graph = GraphStore(runs_root).read(source_run_id)
    try:
        node = graph.nodes[source_node_id]
    except KeyError as exc:
        raise DataColumnCastValidationError("source graph node was not found") from exc
    if node.kind != NodeKind.DATASET_STAGE:
        raise DataColumnCastValidationError("source node must be a dataset_stage node")
    index = read_json(run_root / "artifacts_index.json")
    artifact = _node_artifact(index.get("artifacts", []), node, source_node_id)

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
    actual_sha, frame = load_verified_frame(
        source_path,
        _schema_sidecar_path(source_path),
        artifact.get("sha256"),
        lambda stream: _read_frame(source_path, stream=stream),
        cached=cached,
    )

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
    }, frame


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
