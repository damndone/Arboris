"""2B.2 — head-set graph response (the family union DAG).

Builds a cross-run lineage forest view from a `Family` (see `family.py`). Every run in
the family contributes its per-run graph (graph.json) + node↔hash bridge (node_index.json,
2A.7). Nodes are re-keyed by `node_hash` and the family is collapsed into a single union
DAG: shared-prefix nodes (same hash across runs) appear exactly once, divergence (e.g. a
re-estimated model) shows as sibling branches, and each member run contributes one `head`.

Decorate-only (v1.6.0 discipline): this is computed at response time from graph.json +
node_index.json and is NEVER written back. graph.json stays byte-identical, so golden holds.

Dedup key per node:
- node_hash when the node is in node_index.json (cacheable stage-output);
- else the bare node_id (deterministic across the family — e.g. the raw upload node),
  so genuinely-shared non-cacheable prefix nodes still collapse to one.

Legacy degrade (R5): a run with no node_index.json (flag-off / pre-v1.6.1) has no node
identity. If the *target* run is legacy the caller returns the old per-run graph shape
with `legacy: true`; legacy *members* inside a new family are skipped from the union.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from ..artifacts import read_json
from ..graph_store import GraphStore, graph_to_json
from .family import Family
from .node_index import NODE_INDEX_FILENAME

HEADSET_SCHEMA_VERSION = 4


def _read_node_index(runs_dir: Path, run_id: str) -> dict[str, dict]:
    path = runs_dir / run_id / NODE_INDEX_FILENAME
    try:
        return read_json(path)
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _read_manifest(runs_dir: Path, run_id: str) -> dict:
    try:
        return read_json(runs_dir / run_id / "run_manifest.json")
    except (FileNotFoundError, OSError, ValueError):
        return {}


# v1.6.11 A2 — dataset-aware Ask AI context. Serve-time decoration only (graph.json
# untouched, same philosophy as editable_schema): dataset nodes get an `artifacts`
# list with a compact schema/profile preview so the LLM can actually describe the
# data (rows/cols, dtypes, missingness) instead of disclosing an empty packet.
_PROFILE_CORRELATION_MAX_COLS = 12


def _dataset_artifacts(runs_dir: Path, run_id: str, node_id: str) -> list[dict] | None:
    if node_id == "stage:raw":
        try:
            profile = read_json(runs_dir / run_id / "staged" / "data_profile.json")
        except (FileNotFoundError, OSError, ValueError):
            return None
        preview: dict[str, Any] = {
            "row_count": profile.get("row_count"),
            "column_count": profile.get("column_count"),
            "columns": profile.get("columns"),
        }
        columns = profile.get("columns") or {}
        if len(columns) <= _PROFILE_CORRELATION_MAX_COLS and profile.get("correlations"):
            preview["correlations"] = profile["correlations"]
        return [{
            "name": "data_profile.json",
            "mime": "application/json",
            "summary": {
                "row_count": profile.get("row_count"),
                "column_count": profile.get("column_count"),
            },
            "preview": preview,
        }]
    if node_id == "stage:cleaned":
        try:
            actions = read_json(runs_dir / run_id / "processed" / "cleaning_actions.json")
        except (FileNotFoundError, OSError, ValueError):
            return None
        return [{
            "name": "cleaning_actions.json",
            "mime": "application/json",
            "preview": actions,
        }]
    return None


def _node_key(node_id: str, node_index: dict[str, dict]) -> str:
    """Cross-run dedup key. Two nodes merge iff they are the SAME node_id with the SAME
    node_hash — so the shared prefix (raw/cleaned/variables) collapses across reruns, a
    re-estimated model forks (same id, new hash → distinct), and distinct graph nodes that
    happen to share a stage-output hash (e.g. the cleaned dataset and its per-variable
    nodes) stay SEPARATE (different id → kept, so variables remain visible)."""
    entry = node_index.get(node_id)
    if entry and entry.get("node_hash"):
        return f"{entry['node_hash']}::{node_id}"
    return node_id


def build_headset(
    runs_dir: Path,
    family: Family,
    *,
    annotate: Optional[Callable[..., None]] = None,
) -> dict[str, Any]:
    """Build the head-set union DAG for `family`. `annotate` (optional) is applied to
    each NodeView as `annotate(view, manifest, form)` with the manifest + run_inputs.form
    of the run that produced it (editable decoration + 2B.4 value backfill)."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_seen: set[tuple[str, str]] = set()
    heads: list[dict] = []
    produced_markers: list[tuple[str, str, str]] = []

    members = [family.self_id, *family.ancestors, *family.descendants, *family.siblings]
    seen_members: set[str] = set()
    store = GraphStore(runs_root=runs_dir)

    for run_id in members:
        if run_id in seen_members:
            continue
        seen_members.add(run_id)
        member = family.members.get(run_id)
        if member is not None and member.legacy:
            continue  # legacy member: no node identity, excluded from the union
        try:
            graph = graph_to_json(store.read(run_id))
        except Exception:
            continue
        node_index = _read_node_index(runs_dir, run_id)
        manifest = _read_manifest(runs_dir, run_id)
        try:
            inputs = read_json(runs_dir / run_id / "run_inputs.json")
        except (FileNotFoundError, OSError, ValueError):
            inputs = {}
        form = inputs.get("form") or {}

        # id -> dedup key for this run's nodes
        keymap = {nid: _node_key(nid, node_index) for nid in graph.get("nodes", {})}
        rerun_from = inputs.get("rerun_from")
        from_node = inputs.get("from_node")
        if (
            isinstance(rerun_from, dict)
            and isinstance(from_node, str)
            and rerun_from.get("op_node_id") == from_node
            and from_node in keymap
        ):
            request_id = rerun_from.get("rerun_request_id")
            if request_id:
                produced_markers.append((run_id, keymap[from_node], str(request_id)))

        for nid, node in graph.get("nodes", {}).items():
            key = keymap[nid]
            entry = node_index.get(nid) or {}
            if key not in nodes:
                view = dict(node)
                # Remap parent_stage_id to the parent's dedup KEY so the FE (whose node
                # ids ARE the keys) can attach children (e.g. variable nodes) to their
                # parent for folding / layout. The node's own `id` stays the per-run id
                # (the adapter reuses it as opNodeId / rerun from_node).
                parent = node.get("parent_stage_id")
                if parent is not None:
                    view["parent_stage_id"] = keymap.get(parent, parent)
                view["node_hash"] = entry.get("node_hash")
                view["producing_stage"] = entry.get("producing_stage")
                view["cas_ref"] = entry.get("cas_ref")
                view["runs"] = [run_id]
                dataset_artifacts = _dataset_artifacts(runs_dir, run_id, nid)
                if dataset_artifacts:
                    view["artifacts"] = dataset_artifacts
                if annotate is not None:
                    try:
                        annotate(view, manifest, form)
                    except Exception:
                        pass
                nodes[key] = view
            elif run_id not in nodes[key]["runs"]:
                nodes[key]["runs"].append(run_id)

        for edge in graph.get("edges", {}).values():
            src = keymap.get(edge["source_id"])
            dst = keymap.get(edge["target_id"])
            op = edge.get("op")
            # v1.6.5: carry op + params into the forest projection so the
            # canvas can render variable roles (role lives on the edge). Dedup
            # on (src, dst, op) so a column holding two roles (e.g. Unit +
            # Cluster) keeps both role edges instead of collapsing to one.
            if src is None or dst is None or (src, dst, op) in edge_seen:
                continue
            edge_seen.add((src, dst, op))
            edges.append(
                {"source": src, "target": dst, "op": op, "params": edge.get("params")}
            )

        # Head = leaf node of this run's graph (not a source of any edge).
        run_edges = graph.get("edges", {}).values()
        sources = {e["source_id"] for e in run_edges}
        leaves = [nid for nid in graph.get("nodes", {}) if nid not in sources]
        head_id = leaves[-1] if leaves else None
        head_key = keymap.get(head_id) if head_id else None
        heads.append({
            "run_id": run_id,
            "head_node_hash": nodes[head_key]["node_hash"] if head_key in nodes else None,
            "from_node": inputs.get("from_node"),
            "rerun_of": inputs.get("rerun_of"),
            "rerun_from": rerun_from,
            "rerun_reason": inputs.get("rerun_reason"),
            "status": manifest.get("status"),
            "created_at": manifest.get("started_at") or manifest.get("created_at"),
        })

    for run_id, produced_key, request_id in produced_markers:
        node = nodes.get(produced_key)
        if node is not None and node.get("runs") == [run_id]:
            node["produced_by_rerun_request_id"] = request_id

    return {
        "nodes": nodes,
        "edges": edges,
        "heads": heads,
        "schema_version": HEADSET_SCHEMA_VERSION,
        "legacy": False,
    }
