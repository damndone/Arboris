"""Committing an operation's output as a child node in the run's lineage graph."""

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
from .specs import DataColumnCastPreview, DataColumnCastSpecV1, DataColumnCastValidationError, DataColumnsCastPreview, DataColumnsCastSpecV1, DataTransformPreview, DataTransformSpecV1, FeatureRecipeOperationSpecV1, FeatureRecipePreview


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
    from ..graph_store import GraphStore

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

    from ..lineage.node_index import NODE_INDEX_FILENAME

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
    from ..graph_store import GraphStore

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
