"""Lineage-graph read routes.

``GET /graph`` (project forest) · ``GET /runs/{id}/graph`` (per-run graph or
head-set family view). Also owns the response-time editable-node annotation
(never persisted to graph.json).

Extracted from ``api.py`` in v1.6.10 (D1 decomposition, Phase 4).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import flags
from ..api_errors import WorkbenchAPIError
from ..graph_store import GraphDeserializationError, GraphStore, graph_to_json
from ..lineage.family import scan_family
from ..lineage.headset import build_headset
from ..lineage.node_index import NODE_INDEX_FILENAME
from ..lineage.op_contract import resolve_operation_contract
from ..lineage.project_forest import build_project_forest
from ..repository.run_repository import (
    _read_manifest,
    _resolve_project_runs_dir,
    _resolve_run_root,
)
from ._deps import _backfill_schema_values

router = APIRouter()


def _annotate_editable_node(node: dict, manifest: dict, form: dict | None = None) -> None:
    """Guardrail #7: RESPONSE-TIME decoration only — never persisted to graph.json.
    If `form` is given (head-set view), backfill each control's current value from the
    run's run_inputs.form; otherwise keep capabilities defaults (legacy per-run shape)."""
    contract = resolve_operation_contract(stage=node.get("stage"), manifest=manifest)
    if contract is None:
        return
    node["editable"] = True
    node["op_type"] = contract.op_type
    node["schema_id"] = contract.schema_id
    if form:
        node["editable_schema"] = _backfill_schema_values(contract.editable_schema, form)
        node["editable_schema_source"] = "run_inputs"
    else:
        node["editable_schema"] = contract.editable_schema
        node["editable_schema_source"] = "capabilities"


def _annotate_editable_nodes(body: dict, manifest: dict) -> None:
    for node in body.get("nodes", {}).values():
        _annotate_editable_node(node, manifest)


@router.get("/graph")
def get_project_graph(project_root: str) -> dict[str, Any]:
    """v1.6.8 F1 — project-keyed forest (union of all family head-sets).

    A zero-run project returns an EMPTY forest so the canvas can render as the
    genesis starting point. Same body shape as the per-run headset view."""
    runs_root = _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND
    return build_project_forest(runs_root, annotate=_annotate_editable_node)


@router.get("/runs/{run_id}/graph")
def get_run_graph(run_id: str, project_root: str, view: str | None = None):
    runs_root = _resolve_project_runs_dir(project_root)
    run_root = _resolve_run_root(project_root, run_id)  # 404 if run dir missing
    store = GraphStore(runs_root=runs_root)
    try:
        graph = store.read(run_id)
    except GraphDeserializationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="GRAPH_CORRUPT",
            message=f"graph.json for run {run_id} is corrupt or unreadable: {exc}",
            details={"run_id": run_id},
        ) from exc

    # 2B.2 — head-set family view (flag- or query-gated, non-breaking by default).
    headset_requested = view == "headset" or flags.graph_headset()
    target_legacy = not (run_root / NODE_INDEX_FILENAME).is_file()
    if headset_requested and not target_legacy:
        family = scan_family(runs_root, run_id)
        body = build_headset(runs_root, family, annotate=_annotate_editable_node)
        return body

    body = graph_to_json(graph)
    try:
        _annotate_editable_nodes(body, _read_manifest(run_root))
    except Exception:
        pass  # legacy / manifest-less runs stay non-editable (defensive)
    if headset_requested and target_legacy:
        body["legacy"] = True  # R5: opaque/legacy head, degrade to per-run shape
    sources = {edge.source_id for edge in graph.edges.values()}
    body["stats"] = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "leaf_count": sum(1 for node_id in graph.nodes if node_id not in sources),
        "has_dp_count": sum(1 for node in graph.nodes.values() if node.decision_points),
    }
    return body
