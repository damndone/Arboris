"""V1.4 lineage graph persistence.

Each run gets one JSON file at `runs/{run_id}/graph.json`. Writes go through
`GraphStore.write()` (atomic temp + rename) or `GraphStore.mutate(run_id, fn)`
(read-modify-write under a per-run file lock).

A non-JSON-serializable value anywhere in the graph raises GraphSerializationError
at write time. Silent fallback would break audit trail integrity.

Pre-V1.4 runs (graph.json missing) surface as legacy=True empty Graph.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from filelock import FileLock

from .graph_model import (
    AutoChosenReason,
    BranchRef,
    Contestability,
    DecisionPoint,
    Edge,
    Graph,
    Node,
    NodeKind,
    Trust,
)


class GraphSerializationError(ValueError):
    """Raised when a graph cannot be JSON-serialized."""


def graph_to_json(graph: Graph) -> dict[str, Any]:
    """Serialize a Graph to a JSON-compatible dict. Raises on non-JSON-safe values."""
    try:
        data = _to_jsonable(graph)
        # Round-trip through json to surface any latent issues
        json.dumps(data)
    except (TypeError, ValueError) as exc:
        raise GraphSerializationError(f"Graph is not JSON-serializable: {exc}") from exc
    return data


def graph_from_json(data: dict[str, Any]) -> Graph:
    """Deserialize a Graph from a JSON-compatible dict."""
    return Graph(
        schema_version=data["schema_version"],
        run_id=data["run_id"],
        nodes={k: _node_from_json(v) for k, v in data.get("nodes", {}).items()},
        edges={k: _edge_from_json(v) for k, v in data.get("edges", {}).items()},
        branches={k: _branch_from_json(v) for k, v in data.get("branches", {}).items()},
        legacy=data.get("legacy", False),
    )


class GraphStore:
    """Persistence boundary for lineage graphs.

    One JSON file per run at `{runs_root}/{run_id}/graph.json`. Writes are atomic
    (temp file + os.replace) and serialized through a per-run lock.
    """

    def __init__(self, runs_root: Path) -> None:
        self._runs_root = runs_root

    def read(self, run_id: str) -> Graph:
        path = self._graph_path(run_id)
        if not path.is_file():
            return Graph(
                schema_version=1,
                run_id=run_id,
                nodes={},
                edges={},
                branches={},
                legacy=True,
            )
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return graph_from_json(data)

    def write(self, graph: Graph) -> None:
        path = self._graph_path(graph.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = graph_to_json(graph)
        with self._lock(graph.run_id):
            self._atomic_write_json(path, data)

    def mutate(self, run_id: str, fn: Callable[[Graph], Graph]) -> Graph:
        """Read-modify-write under a per-run lock."""
        with self._lock(run_id):
            current = self.read(run_id)
            updated = fn(current)
            data = graph_to_json(updated)
            self._atomic_write_json(self._graph_path(run_id), data)
            return updated

    # -- internals -------------------------------------------------------------

    def _graph_path(self, run_id: str) -> Path:
        return self._runs_root / run_id / "graph.json"

    def _lock(self, run_id: str) -> FileLock:
        lock_dir = self._runs_root / run_id
        lock_dir.mkdir(parents=True, exist_ok=True)
        return FileLock(str(lock_dir / "graph.lock"))

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        # Write to a temp file in the same directory, then atomic rename.
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".graph.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file if rename failed
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise


# -- to_jsonable: walk dataclass tree, convert to plain dict/list/scalars ----


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if is_dataclass(value):
        return {k: _to_jsonable(v) for k, v in asdict(value).items()}
    raise TypeError(f"Value of type {type(value).__name__} is not JSON-safe")


# -- from_jsonable: rebuild dataclasses from plain dicts ---------------------


def _node_from_json(d: dict[str, Any]) -> Node:
    return Node(
        id=d["id"],
        kind=NodeKind(d["kind"]),
        display_label=d["display_label"],
        created_at=d["created_at"],
        parent_stage_id=d.get("parent_stage_id"),
        branch_id=d["branch_id"],
        trust=Trust(d.get("trust", "ok")),
        trust_reason=d.get("trust_reason"),
        archived=d.get("archived", False),
        payload_ref=d.get("payload_ref"),
        decision_point=_decision_point_from_json(d["decision_point"]) if d.get("decision_point") else None,
        annotations=tuple(d.get("annotations", ())),
    )


def _edge_from_json(d: dict[str, Any]) -> Edge:
    return Edge(
        id=d["id"],
        source_id=d["source_id"],
        target_id=d["target_id"],
        op=d["op"],
        params=dict(d.get("params", {})),
        reversible=d.get("reversible", False),
        inverse_op=d.get("inverse_op"),
    )


def _branch_from_json(d: dict[str, Any]) -> BranchRef:
    return BranchRef(
        id=d["id"],
        forked_from_node_id=d.get("forked_from_node_id"),
        head_node_ids=tuple(d.get("head_node_ids", ())),
        archived=d.get("archived", False),
    )


def _decision_point_from_json(d: dict[str, Any]) -> DecisionPoint:
    return DecisionPoint(
        decision_id=d["decision_id"],
        decision_id_alias=tuple(d.get("decision_id_alias", ())),
        selected=d.get("selected"),
        candidates=tuple(d.get("candidates", ())),
        source=d.get("source", "system_default"),
        contestability=_contestability_from_json(d.get("contestability", {})),
        reason=_reason_from_json(d["reason"]) if d.get("reason") else None,
    )


def _contestability_from_json(d: dict[str, Any]) -> Contestability:
    return Contestability(
        is_contestable=d.get("is_contestable", True),
        assumption_checks_needed=tuple(d.get("assumption_checks_needed", ())),
        warnings=tuple(d.get("warnings", ())),
        review_status=d.get("review_status"),
    )


def _reason_from_json(d: dict[str, Any]) -> AutoChosenReason:
    return AutoChosenReason(
        reason_type=d["reason_type"],
        explanation=d.get("explanation"),
        chosen_params_schema=d.get("chosen_params_schema"),
        chosen_params=dict(d.get("chosen_params", {})),
    )
