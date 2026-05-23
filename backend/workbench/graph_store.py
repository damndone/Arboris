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
import time
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from filelock import FileLock, Timeout

from .graph_model import (
    AutoChosenReason,
    BranchRef,
    Contestability,
    DecisionPoint,
    Edge,
    Graph,
    Node,
    NodeKind,
    SCHEMA_VERSION,
    Stage,
    Trust,
)


class GraphSerializationError(ValueError):
    """Raised when a graph cannot be JSON-serialized."""


class GraphDeserializationError(ValueError):
    """Raised when a persisted graph cannot be deserialized."""


class GraphLockTimeout(RuntimeError):
    """Raised when the per-run graph lock cannot be acquired within the timeout."""


def graph_to_json(graph: Graph) -> dict[str, Any]:
    """Serialize a Graph to a JSON-compatible dict. Raises on non-JSON-safe values."""
    try:
        data = _to_jsonable(graph)
    except TypeError as exc:
        raise GraphSerializationError(f"Graph is not JSON-serializable: {exc}") from exc
    data["schema_version"] = SCHEMA_VERSION
    if __debug__:
        # Validate JSON-safety in dev/test; skipped with `python -O` in production
        try:
            json.dumps(data)
        except (TypeError, ValueError) as exc:
            raise GraphSerializationError(f"Graph is not JSON-serializable: {exc}") from exc
    return data


def graph_from_json(data: dict[str, Any]) -> Graph:
    """Deserialize a Graph from a JSON-compatible dict.

    Raises GraphDeserializationError if required keys are missing, values have
    wrong types, or an unknown enum value is encountered (e.g. future NodeKind).
    """
    try:
        schema_version = data["schema_version"]
        return Graph(
            schema_version=schema_version,
            run_id=data["run_id"],
            nodes={
                k: _node_from_json(v, schema_version=schema_version)
                for k, v in data.get("nodes", {}).items()
            },
            edges={k: _edge_from_json(v) for k, v in data.get("edges", {}).items()},
            branches={k: _branch_from_json(v) for k, v in data.get("branches", {}).items()},
            legacy=data.get("legacy", False),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise GraphDeserializationError(
            f"Cannot deserialize graph for run {data.get('run_id', '?')}: {exc}"
        ) from exc


class GraphStore:
    """Persistence boundary for lineage graphs.

    One JSON file per run at `{runs_root}/{run_id}/graph.json`. Writes are atomic
    (temp file + os.replace) and serialized through a per-run lock.
    """

    def __init__(self, runs_root: Path) -> None:
        self._runs_root = runs_root

    MAX_GRAPH_BYTES = 32 * 1024 * 1024  # 32 MiB hard cap; protects against
    # JSON-bombs and runaway graph growth. A real run produces ~10s of KiB.

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
        size = path.stat().st_size
        if size > self.MAX_GRAPH_BYTES:
            raise GraphDeserializationError(
                f"graph.json for run {run_id} is {size} bytes, exceeds "
                f"MAX_GRAPH_BYTES={self.MAX_GRAPH_BYTES}"
            )
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return graph_from_json(data)
        except GraphDeserializationError:
            raise
        except json.JSONDecodeError as exc:
            raise GraphDeserializationError(
                f"Corrupt graph.json for run {run_id}: {exc}"
            ) from exc

    def write(self, graph: Graph) -> None:
        path = self._graph_path(graph.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = graph_to_json(graph)
        with self._acquire(graph.run_id):
            self._atomic_write_json(path, data)

    def mutate(self, run_id: str, fn: Callable[[Graph], Graph]) -> Graph:
        """Read-modify-write under a per-run lock.

        The `fn` callback receives the current Graph and must return the
        updated Graph. The returned Graph's run_id is validated against
        the lock's run_id — a mismatch raises ValueError to prevent
        accidentally writing one run's graph into another's directory.
        """
        with self._acquire(run_id):
            current = self.read(run_id)
            updated = fn(current)
            if updated.run_id != run_id:
                raise ValueError(
                    f"Mutation callback changed run_id from {run_id!r} to "
                    f"{updated.run_id!r}. The graph's run_id must be preserved."
                )
            data = graph_to_json(updated)
            self._atomic_write_json(self._graph_path(run_id), data)
            return graph_from_json(data)

    # -- internals -------------------------------------------------------------

    LOCK_TIMEOUT_SECONDS = 30.0

    def _graph_path(self, run_id: str) -> Path:
        return self._runs_root / run_id / "graph.json"

    def _lock(self, run_id: str) -> FileLock:
        lock_dir = self._runs_root / run_id
        lock_dir.mkdir(parents=True, exist_ok=True)
        return FileLock(str(lock_dir / "graph.lock"))

    def _acquire(self, run_id: str) -> FileLock:
        lock = self._lock(run_id)
        try:
            lock.acquire(timeout=self.LOCK_TIMEOUT_SECONDS)
        except Timeout as exc:
            raise GraphLockTimeout(
                f"Could not acquire graph lock for run {run_id!r} within "
                f"{self.LOCK_TIMEOUT_SECONDS}s"
            ) from exc
        return lock

    _TMP_STALE_SECONDS = 300

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        # Sweep stale .graph.*.tmp siblings left by SIGKILL'd writes.
        self._cleanup_stale_tmp(path.parent)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".graph.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @classmethod
    def _cleanup_stale_tmp(cls, run_dir: Path) -> None:
        now = time.time()
        try:
            entries = list(run_dir.glob(".graph.*.tmp"))
        except OSError:
            return
        for entry in entries:
            try:
                if now - entry.stat().st_mtime > cls._TMP_STALE_SECONDS:
                    entry.unlink()
            except OSError:
                pass


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


def _node_from_json(d: dict[str, Any], *, schema_version: int) -> Node:
    dps_field = d.get("decision_points")
    if dps_field is not None:
        if not isinstance(dps_field, list):
            raise TypeError("decision_points must be a list")
        decision_points = tuple(_decision_point_from_json(x) for x in dps_field)
    elif d.get("decision_point") is not None:
        decision_points = (_decision_point_from_json(d["decision_point"]),)
    else:
        decision_points = ()
    stage = None
    if schema_version >= 3 and d.get("stage") is not None:
        stage = Stage(d["stage"])
    return Node(
        id=d["id"],
        kind=NodeKind(d["kind"]),
        display_label=d["display_label"],
        created_at=d["created_at"],
        parent_stage_id=d.get("parent_stage_id"),
        branch_id=d.get("branch_id", "main"),
        trust=Trust(d.get("trust", "ok")),
        trust_reason=d.get("trust_reason"),
        archived=d.get("archived", False),
        payload_ref=d.get("payload_ref"),
        decision_points=decision_points,
        summary=d.get("summary"),
        annotations=tuple(d.get("annotations", ())),
        stage=stage,
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
    # Use .derive() so legacy JSON without review_status gets it derived.
    return Contestability.derive(
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
