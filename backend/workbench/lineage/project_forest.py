"""v1.6.8 F1 — project-level forest: union of all family head-sets.

The canvas home is /p/:slug/graph; a zero-run project must render an EMPTY
forest (genesis starts on the empty canvas). Reuses scan_family + build_headset
per family — build_headset internals are untouched.

Shape parity with the per-run headset body (the HARD requirement — the frontend
feeds both through the same adaptHeadSet adapter):
- `nodes`  : dict keyed by the dedup key (node_hash::node_id, or bare node_id),
             exactly as build_headset returns it. First family to contribute a
             key wins the view; `runs` lists are merged across families.
- `edges`  : list of {source, target, op, params}, deduped on (source, target, op)
             — the same triple build_headset dedups on within one family.
- `heads`  : one entry per run, deduped by run_id across overlapping scans.
- `schema_version` / `legacy: False` : carried through unchanged (legacy runs
  have no node identity and are skipped INSIDE build_headset, so a project
  forest never degrades to the legacy per-run shape — it just omits them,
  matching the per-run headset's treatment of legacy family members).

Project-only addition (absent from the per-run body, additive & adapter-safe):
- `families`: [{family_root, members}] — one entry per rerun family, rooted at
  the family's topmost ancestor.

Omitted per-run-only keys (they belong to the LEGACY per-run graph shape that
the run-keyed endpoint returns when view!=headset, never to a headset body):
- `stats` (node/edge/leaf counts of a single run's graph.json).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from .compare_nodes import CompareNodeStore, compare_forest_projection
from .family import scan_family
from .headset import HEADSET_SCHEMA_VERSION, build_headset

RUN_MANIFEST_FILENAME = "run_manifest.json"


def build_project_forest(
    runs_dir: Path,
    *,
    annotate: Optional[Callable[..., None]] = None,
) -> dict[str, Any]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_seen: set[tuple[str, str, Any]] = set()
    heads: list[dict] = []
    head_seen: set[str] = set()
    families: list[dict] = []
    seen: set[str] = set()

    if runs_dir.is_dir():
        run_ids = sorted(
            entry.name
            for entry in runs_dir.iterdir()
            if entry.is_dir() and (entry / RUN_MANIFEST_FILENAME).is_file()
        )
    else:
        run_ids = []

    for run_id in run_ids:
        if run_id in seen:
            continue
        family = scan_family(runs_dir, run_id)
        if family.ancestors:
            # Re-root at the topmost ancestor: the root family's descendants
            # cover the WHOLE tree (a mid-tree family misses cousins, e.g. a
            # sibling's children), so each rerun tree is unioned exactly once.
            family = scan_family(runs_dir, family.ancestors[-1])
        members = {
            family.self_id,
            *family.ancestors,
            *family.descendants,
            *family.siblings,
        }
        seen |= members

        body = build_headset(runs_dir, family, annotate=annotate)
        for key, node in body["nodes"].items():
            existing = nodes.get(key)
            if existing is None:
                nodes[key] = node
            else:  # defensive: merge run membership across overlapping scans
                for rid in node.get("runs", []):
                    if rid not in existing.get("runs", []):
                        existing.setdefault("runs", []).append(rid)
        for edge in body["edges"]:
            k = (edge["source"], edge["target"], edge.get("op"))
            if k not in edge_seen:
                edge_seen.add(k)
                edges.append(edge)
        for head in body["heads"]:
            if head["run_id"] not in head_seen:
                head_seen.add(head["run_id"])
                heads.append(head)
        families.append(
            {"family_root": family.self_id, "members": sorted(members)}
        )

    # Compare nodes are merged last, and only here: a comparison may join two
    # nodes from different families, which a single-family head-set cannot see.
    # They are never written into any run's graph.json, so per-run graphs stay
    # byte-identical.
    compare_nodes, compare_edges = compare_forest_projection(
        nodes, CompareNodeStore(runs_dir.parent, create=False).list()
    )
    nodes.update(compare_nodes)
    for edge in compare_edges:
        key = (edge["source"], edge["target"], edge.get("op"))
        if key not in edge_seen:
            edge_seen.add(key)
            edges.append(edge)

    return {
        "nodes": nodes,
        "edges": edges,
        "heads": heads,
        "families": families,
        "schema_version": HEADSET_SCHEMA_VERSION,
        "legacy": False,
    }
