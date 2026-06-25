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
            if src is None or dst is None or (src, dst) in edge_seen:
                continue
            edge_seen.add((src, dst))
            edges.append({"source": src, "target": dst})

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
            "rerun_reason": inputs.get("rerun_reason"),
            "status": manifest.get("status"),
            "created_at": manifest.get("started_at") or manifest.get("created_at"),
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "heads": heads,
        "schema_version": HEADSET_SCHEMA_VERSION,
        "legacy": False,
    }
