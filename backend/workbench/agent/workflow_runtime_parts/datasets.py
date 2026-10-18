"""Datasets service for workflow execution."""

from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import pandas as pd
from ...artifacts import read_json, sha256_file, write_json, write_text_durable
from ...graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from ...graph_store import GraphStore
from ...statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    exploration_fingerprint,
    persist_exploration,
)
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult
from .artifacts import _ensure_runtime_artifact
from .inputs import _apply_numeric_recipes
from .constants import _NUMERIC_DERIVATION_SCHEMA, _PRODUCED_DATASET_SCHEMA


def _persist_numeric_derivation(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    frame: pd.DataFrame,
    step: Any,
) -> WorkflowStepResult:
    """Persist a derived dataset + recipe and add one visible graph child."""

    derived, summaries = _apply_numeric_recipes(frame, step.spec["recipes"])
    # The output is written into the workflow's target run regardless of which
    # dataset it derives from; only the lineage references follow the real
    # source. `_lineage_source` refuses a binding from any other run, so the
    # parent node named below always exists in the graph mutated here.
    source_run_id = str(draft.target["run_id"])
    run_root = root / "runs" / source_run_id
    result_fingerprint = str(step.fingerprint)
    fingerprint = result_fingerprint.replace(":", "_")
    relative_dir = Path("derived") / "workflow_numeric" / fingerprint
    data_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    data_path = run_root / data_rel
    recipe_path = run_root / recipe_rel
    data_path.parent.mkdir(parents=True, exist_ok=True)
    recipe = {
        "schema_version": _NUMERIC_DERIVATION_SCHEMA,
        "workflow_id": draft.workflow_id,
        "workflow_step_id": str(step.step_id),
        "workflow_step_fingerprint": result_fingerprint,
        "source": {
            "artifact_id": lineage["artifact_id"],
            "sha256": lineage["sha256"],
        },
        "recipes": [dict(recipe) for recipe in step.spec["recipes"]],
        "result": {"path": data_rel, "output_columns": summaries},
    }
    if recipe_path.exists():
        if read_json(recipe_path) != recipe:
            raise WorkflowExecutionError("numeric derivation recipe path is occupied")
    else:
        write_json(recipe_path, recipe)
    serialized_data = derived.to_csv(index=False)
    if data_path.exists():
        if data_path.read_text(encoding="utf-8") != serialized_data:
            raise WorkflowExecutionError("numeric derivation data path is occupied")
    else:
        write_text_durable(data_path, serialized_data)
    data_artifact_id = f"workflow_derived_numeric_{fingerprint[:24]}"
    recipe_artifact_id = f"workflow_derived_numeric_recipe_{fingerprint[:24]}"
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type="derived_data",
        step="workflow.derive_numeric",
        inputs=[lineage["artifact_id"]],
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="workflow.derive_numeric",
        inputs=[lineage["artifact_id"], data_artifact_id],
    )
    child_node_id = f"data-derive-numeric:{fingerprint[:24]}"
    branch_id = f"workflow-numeric:{fingerprint[:20]}"
    source_node_id = lineage["node_ref"]

    def add_child(graph: Graph) -> Graph:
        if child_node_id in graph.nodes:
            return graph
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label="Derived numeric columns",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=source_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=(
                f"{len(summaries)} declared numeric transform(s); "
                f"{len(derived)} rows"
            ),
            annotations=(
                {
                    "type": "workflow_numeric_derivation",
                    "workflow_id": draft.workflow_id,
                    "workflow_step_id": str(step.step_id),
                    "recipe_path": recipe_rel,
                },
            ),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=source_node_id,
                    target_id=child_node_id,
                    op="workflow.derive_numeric",
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=source_node_id,
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(source_run_id, add_child)
    data_sha256 = sha256_file(data_path)
    node_index_path = run_root / "node_index.json"
    if node_index_path.is_file():
        node_index = read_json(node_index_path)
        entry = {
            "node_hash": data_sha256,
            "producing_stage": "workflow.derive_numeric",
            "cas_ref": {"node_hash": data_sha256, "artifact": data_rel},
        }
        existing = node_index.get(child_node_id)
        if existing is not None and existing != entry:
            raise WorkflowExecutionError("numeric derivation node identity is not deterministic")
        if existing is None:
            write_json(node_index_path, {**node_index, child_node_id: entry})
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, recipe_artifact_id],
        row_counts={item["output_name"]: item["nonmissing_count"] for item in summaries},
        result_fingerprint=fingerprint,
        payload={
            "output_columns": summaries,
            # The standard binding a later step commits to consuming. Every
            # dataset-producing step publishes this exact shape, so resolution
            # never branches on which operation produced the input.
            "produced_dataset": {
                "schema_version": _PRODUCED_DATASET_SCHEMA,
                "run_id": source_run_id,
                "node_ref": child_node_id,
                "artifact_id": data_artifact_id,
                # The two hashes are not interchangeable. content_sha256 digests
                # the bytes on disk, so a consumer comparing it against what it
                # actually read detects a binding that points at the wrong
                # artifact, or a run directory rewritten between resumes.
                # result_fingerprint is the producing step's own fingerprint and
                # is provenance only: a consumer that re-derives it from the same
                # step record is comparing a value against itself, which no input
                # can falsify. Verify with content_sha256, attribute with this.
                "content_sha256": data_sha256,
                "dataset_kind": "derived_data",
                "result_fingerprint": fingerprint,
            },
        },
    )



def _persist_workflow_dataset_frame(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
    dataset_label: str,
    producer_step: str,
    summary: Mapping[str, Any],
) -> WorkflowStepResult:
    """Persist one prepared frame and publish the standard source binding."""

    source_run_id = str(draft.target["run_id"])
    run_root = root / "runs" / source_run_id
    result_fingerprint = str(step.fingerprint)
    fingerprint = result_fingerprint.replace(":", "_")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", dataset_label)
    relative_dir = Path("derived") / "workflow_datasets" / fingerprint[:24]
    data_rel = (relative_dir / f"{safe_label}.parquet").as_posix()
    metadata_rel = (relative_dir / f"{safe_label}.json").as_posix()
    data_path = run_root / data_rel
    metadata_path = run_root / metadata_rel
    data_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = frame.to_parquet(index=False)
    if data_path.exists():
        if data_path.read_bytes() != serialized:
            raise WorkflowExecutionError(
                f"{producer_step} dataset path is occupied by different content"
            )
    else:
        data_path.write_bytes(serialized)
    metadata = {
        "schema_version": "workflow-prepared-dataset.v1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": str(step.step_id),
        "workflow_step_fingerprint": result_fingerprint,
        "producer": producer_step,
        "source": {
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
        },
        "summary": dict(summary),
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "data_path": data_rel,
    }
    if metadata_path.exists():
        if read_json(metadata_path) != metadata:
            raise WorkflowExecutionError(
                f"{producer_step} metadata path is occupied by different content"
            )
    else:
        write_json(metadata_path, metadata)
    data_artifact_id = f"workflow_{safe_label}_{fingerprint[:24]}"
    metadata_artifact_id = f"workflow_{safe_label}_metadata_{fingerprint[:24]}"
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type="derived_data",
        step=producer_step,
        inputs=[str(lineage["artifact_id"])],
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="metadata",
        step=producer_step,
        inputs=[str(lineage["artifact_id"]), data_artifact_id],
    )
    child_node_id = f"data-{safe_label}:{fingerprint[:24]}"
    branch_id = f"workflow-{safe_label}:{fingerprint[:20]}"
    source_node_id = str(lineage["node_ref"])

    def add_child(graph: Graph) -> Graph:
        existing = graph.nodes.get(child_node_id)
        if existing is not None:
            if existing.payload_ref != data_rel or existing.parent_stage_id != source_node_id:
                raise WorkflowExecutionError(
                    f"{producer_step} graph child identity is not deterministic"
                )
            return graph
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=f"{dataset_label.title()} dataset",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=source_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=f"{producer_step}: {len(frame)} rows",
            annotations=(
                {
                    "type": "workflow_prepared_dataset",
                    "producer": producer_step,
                    "workflow_id": draft.workflow_id,
                    "workflow_step_id": str(step.step_id),
                    "metadata_path": metadata_rel,
                },
            ),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=source_node_id,
                    target_id=child_node_id,
                    op=producer_step,
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=source_node_id,
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(source_run_id, add_child)
    data_sha256 = sha256_file(data_path)
    node_index_path = run_root / "node_index.json"
    if node_index_path.is_file():
        node_index = read_json(node_index_path)
        entry = {
            "node_hash": data_sha256,
            "producing_stage": producer_step,
            "cas_ref": {"node_hash": data_sha256, "artifact": data_rel},
        }
        existing = node_index.get(child_node_id)
        if existing is not None and existing != entry:
            raise WorkflowExecutionError(
                f"{producer_step} node identity is not deterministic"
            )
        if existing is None:
            write_json(node_index_path, {**node_index, child_node_id: entry})
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, metadata_artifact_id],
        row_counts={"source": int(len(frame))},
        result_fingerprint=result_fingerprint,
        payload={
            "summary": dict(summary),
            "produced_dataset": {
                "schema_version": _PRODUCED_DATASET_SCHEMA,
                "run_id": source_run_id,
                "node_ref": child_node_id,
                "artifact_id": data_artifact_id,
                "content_sha256": data_sha256,
                "dataset_kind": "derived_data",
                "result_fingerprint": result_fingerprint,
            },
        },
    )



def _exploration_spec(spec: Mapping[str, Any]) -> ExplorationSpec:
    return ExplorationSpec(
        operation=str(spec["operation"]),
        selected_columns=tuple(str(item) for item in spec.get("selected_columns", [])),
        filters=tuple(
            FilterSpec(
                column=str(item["column"]),
                operator=str(item["operator"]),
                value=item.get("value"),
            )
            for item in spec.get("filters", [])
        ),
        options=dict(spec.get("options") or {}),
        derived_definitions=tuple(spec.get("derived_definitions") or []),
    )



def _persist_workflow_exploration(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    *,
    spec: ExplorationSpec,
    result: Mapping[str, Any],
    frame: pd.DataFrame,
) -> tuple[dict[str, Any], str]:
    """The single place a workflow exploration record names its source.

    Four dispatch branches persist exploration records -- the plain explore,
    the plots explore, derive_boolean and derived_group_summarize -- and each
    used to spell out `draft.target` for itself. Four copies of a source
    reference is four chances to write the wrong one, and the numbers stay
    right when it happens, so nothing complains.

    The fingerprint is derived from the same digest, which is not decoration:
    it is the record's identity on disk. Keying it on the target while
    computing from a derived dataset makes two different explorations collide
    on one artifact path.
    """

    fingerprint = exploration_fingerprint(str(lineage["sha256"]), spec)
    record = persist_exploration(
        root,
        source_run_id=str(draft.target["run_id"]),
        source_node_id=str(lineage["node_ref"]),
        source_artifact_id=str(lineage["artifact_id"]),
        source_sha256=str(lineage["sha256"]),
        spec=spec,
        result=dict(result),
        fingerprint=fingerprint,
        source_frame=frame,
    )
    return record, fingerprint
