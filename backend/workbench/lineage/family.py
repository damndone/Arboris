"""2B.1 — serve-layer family scanner over the rerun forest.

A "family" is the set of runs connected to a target run through the `rerun_of`
lineage links recorded in each run's `run_inputs.json`. This is read-only serve-layer
code: it scans the project's runs directory and never mutates graph.json.

Classification (relative to the target run):
- ancestors   : the rerun_of chain walking up from the target (nearest parent first).
- descendants : every run that transitively reruns the target.
- siblings    : runs sharing the target's direct `rerun_of` parent (excluding self).

A run is `legacy` when it carries no `node_index.json` (flag-off / pre-v1.6.1 runs, or
runs whose run_inputs.json is missing/unreadable). The scanner must tolerate a mixed
legacy/new family without crashing: legacy members simply lack node-hash identity and
are treated as opaque heads downstream (2B.2 dedup).

Scanning is O(runs-in-project); indexing is a Slice-3 concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..artifacts import read_json
from .node_index import NODE_INDEX_FILENAME
from .run_inputs import RUN_INPUTS_FILENAME


@dataclass(frozen=True)
class FamilyMember:
    run_id: str
    rerun_of: str | None
    legacy: bool


@dataclass(frozen=True)
class Family:
    self_id: str
    ancestors: list[str] = field(default_factory=list)
    descendants: list[str] = field(default_factory=list)
    siblings: list[str] = field(default_factory=list)
    members: dict[str, FamilyMember] = field(default_factory=dict)


def _scan_runs(runs_dir: Path) -> dict[str, FamilyMember]:
    """Read every run dir's lineage metadata. Unreadable/legacy runs degrade to an
    opaque root (rerun_of=None, legacy=True) rather than raising."""
    members: dict[str, FamilyMember] = {}
    if not runs_dir.is_dir():
        return members
    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        run_id = entry.name
        rerun_of: str | None = None
        try:
            inputs = read_json(entry / RUN_INPUTS_FILENAME)
            rerun_of = inputs.get("rerun_of")
        except (FileNotFoundError, OSError, ValueError):
            rerun_of = None  # legacy / opaque root
        legacy = not (entry / NODE_INDEX_FILENAME).is_file()
        members[run_id] = FamilyMember(run_id=run_id, rerun_of=rerun_of, legacy=legacy)
    return members


def scan_family(runs_dir: Path, run_id: str) -> Family:
    """Build the rerun family for `run_id`. The target is always present in `members`,
    even if its run dir is absent (singleton opaque fallback), so callers never KeyError."""
    members = _scan_runs(runs_dir)
    if run_id not in members:
        # Unknown / missing target: singleton opaque family (defensive fallback).
        members = {**members, run_id: FamilyMember(run_id=run_id, rerun_of=None, legacy=True)}

    # child -> parent (only edges where the parent run actually exists in the project)
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = {}
    for rid, member in members.items():
        parent = member.rerun_of
        if parent is not None and parent in members:
            parent_of[rid] = parent
            children_of.setdefault(parent, []).append(rid)

    # Ancestors: walk up, nearest parent first; guard against cycles.
    ancestors: list[str] = []
    seen: set[str] = {run_id}
    cursor = parent_of.get(run_id)
    while cursor is not None and cursor not in seen:
        ancestors.append(cursor)
        seen.add(cursor)
        cursor = parent_of.get(cursor)

    # Descendants: BFS down the children graph (excludes self), deterministic order.
    descendants: list[str] = []
    visited: set[str] = {run_id}
    frontier = sorted(children_of.get(run_id, []))
    while frontier:
        nxt: list[str] = []
        for child in frontier:
            if child in visited:
                continue
            visited.add(child)
            descendants.append(child)
            nxt.extend(sorted(children_of.get(child, [])))
        frontier = nxt

    # Siblings: same direct parent, excluding self. (Roots have no siblings here.)
    direct_parent = parent_of.get(run_id)
    siblings = (
        sorted(c for c in children_of.get(direct_parent, []) if c != run_id)
        if direct_parent is not None
        else []
    )

    return Family(
        self_id=run_id,
        ancestors=ancestors,
        descendants=descendants,
        siblings=siblings,
        members=members,
    )
