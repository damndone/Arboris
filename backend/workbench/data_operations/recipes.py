"""Feature recipes: derived columns previewed, then committed as a new data node."""

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
from .specs import DataColumnCastSpecV1, DataColumnCastValidationError, FeatureRecipeEffect, FeatureRecipeOperationSpecV1, FeatureRecipePreview
from .frames import _read_frame, _schema_fingerprint, _write_frame_artifact
from .graph import _commit_feature_recipe_graph_child, _ensure_node_index_entry, _ensure_registered_artifact, _graph_store_for, _resolve_source


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
