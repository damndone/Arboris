"""A durable two-node comparison, addressable as a node in the lineage forest.

Comparison used to be ephemeral UI state: a conclusion the user reached about
two models vanished on reload and could not be revisited or cited. Here it
becomes a stored record that the forest projects as a node joining its two
endpoints, which is what makes the lineage a DAG rather than a set of chains.

Two properties matter. Identity is symmetric, because comparing A with B is the
same question as comparing B with A, and minting two nodes for one question
would be a lie about the graph. And the record is write-once: the stored packet
is the evidence the user reached a conclusion from, so a divergent rewrite is
refused rather than silently applied.

Nothing here is written into any run's graph.json. Compare nodes live at the
project level and are merged in at response time, so the per-run graphs stay
byte-identical and golden holds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from ..artifacts import read_json
from ..canonical import sha256_canonical


COMPARE_NODE_SCHEMA_ID = "lineage.compare_node.v1"
COMPARE_NODE_DIRNAME = "compare-nodes"

Relation = Literal["ancestor_descendant", "unrelated"]


class CompareNodeError(ValueError):
    """A structured refusal, so a caller can act on the reason."""

    def __init__(
        self, code: str, message: str, *, evidence: dict[str, Any] | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.evidence = dict(evidence or {})
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CompareEndpoint:
    run_id: str
    node_id: str
    node_hash: str
    forest_node_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "node_id": self.node_id,
            "node_hash": self.node_hash,
            "forest_node_key": self.forest_node_key,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CompareEndpoint":
        return cls(
            run_id=str(value["run_id"]),
            node_id=str(value["node_id"]),
            node_hash=str(value["node_hash"]),
            forest_node_key=str(value["forest_node_key"]),
        )


@dataclass(frozen=True)
class CompareNodeRecord:
    compare_id: str
    schema_id: str
    left: CompareEndpoint
    right: CompareEndpoint
    relation: Relation
    created_at: str
    packet: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "compare_id": self.compare_id,
            "schema_id": self.schema_id,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "relation": self.relation,
            "created_at": self.created_at,
            "packet": self.packet,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CompareNodeRecord":
        return cls(
            compare_id=str(value["compare_id"]),
            schema_id=str(value["schema_id"]),
            left=CompareEndpoint.from_dict(value["left"]),
            right=CompareEndpoint.from_dict(value["right"]),
            relation=value["relation"],
            created_at=str(value["created_at"]),
            packet=dict(value.get("packet") or {}),
        )


def compare_node_id(left: CompareEndpoint, right: CompareEndpoint) -> str:
    """Content-address the pair, order-independently."""

    keys = sorted([left.forest_node_key, right.forest_node_key])
    return sha256_canonical({"schema_id": COMPARE_NODE_SCHEMA_ID, "endpoints": keys})


def canonical_endpoint_order(
    left: CompareEndpoint,
    right: CompareEndpoint,
    *,
    ancestor_forest_node_key: str | None = None,
) -> tuple[tuple[CompareEndpoint, CompareEndpoint], Relation]:
    """Order a pair, and say what relation that order expresses.

    The order is not cosmetic: whichever endpoint lands on the left is the
    baseline the packet reads against, so it must be derived from the pair
    itself rather than from the order the user happened to click in. Callers
    that build the packet must order it through here too, or the stored packet
    would read against a different baseline than the record claims.
    """

    for endpoint in (left, right):
        if not endpoint.node_hash or not endpoint.forest_node_key:
            raise CompareNodeError(
                "COMPARE_ENDPOINT_NOT_IDENTIFIED",
                "both endpoints need a node hash and a forest node key",
                evidence={"run_id": endpoint.run_id, "node_id": endpoint.node_id},
            )
    if left.forest_node_key == right.forest_node_key:
        raise CompareNodeError(
            "COMPARE_SELF",
            "a node cannot be compared with itself",
            evidence={"forest_node_key": left.forest_node_key},
        )
    if ancestor_forest_node_key is None:
        ordered = tuple(sorted((left, right), key=lambda item: item.forest_node_key))
        return (ordered[0], ordered[1]), "unrelated"

    endpoints = {left.forest_node_key: left, right.forest_node_key: right}
    if ancestor_forest_node_key not in endpoints:
        raise CompareNodeError(
            "COMPARE_ANCESTOR_NOT_AN_ENDPOINT",
            "the declared ancestor is not one of the two endpoints",
            evidence={"ancestor_forest_node_key": ancestor_forest_node_key},
        )
    ancestor = endpoints.pop(ancestor_forest_node_key)
    (descendant,) = endpoints.values()
    return (ancestor, descendant), "ancestor_descendant"


def build_compare_node(
    *,
    left: CompareEndpoint,
    right: CompareEndpoint,
    packet: dict[str, Any],
    created_at: str,
    ancestor_forest_node_key: str | None = None,
) -> CompareNodeRecord:
    """Validate a pair and store it in its canonical order."""

    ordered, relation = canonical_endpoint_order(
        left, right, ancestor_forest_node_key=ancestor_forest_node_key
    )

    return CompareNodeRecord(
        compare_id=compare_node_id(left, right),
        schema_id=COMPARE_NODE_SCHEMA_ID,
        left=ordered[0],
        right=ordered[1],
        relation=relation,
        created_at=created_at,
        packet=dict(packet),
    )


def compare_forest_projection(
    forest_nodes: Mapping[str, Any],
    records: Iterable[CompareNodeRecord],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return the compare nodes and join edges drawable on this forest.

    A record whose endpoint is absent -- its run deleted, or simply outside the
    forest being drawn -- is skipped. Emitting it anyway would put an edge on
    the canvas whose other end does not exist, which reads as a broken graph
    rather than as a missing run.
    """

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for record in records:
        if record.left.forest_node_key not in forest_nodes:
            continue
        if record.right.forest_node_key not in forest_nodes:
            continue
        runs = [record.left.run_id]
        if record.right.run_id not in runs:
            runs.append(record.right.run_id)
        nodes[record.compare_id] = {
            "id": record.compare_id,
            "kind": "compare",
            "display_label": "Comparison",
            "summary": _compare_summary(record),
            "created_at": record.created_at,
            "parent_stage_id": None,
            "branch_id": "main",
            "stage": "compare",
            "node_hash": record.compare_id,
            "runs": runs,
            "compare": {
                "compare_id": record.compare_id,
                "schema_id": record.schema_id,
                "relation": record.relation,
                "left": record.left.to_dict(),
                "right": record.right.to_dict(),
                "packet": record.packet,
            },
        }
        for endpoint in (record.left, record.right):
            edges.append(
                {
                    "source": endpoint.forest_node_key,
                    "target": record.compare_id,
                    "op": "compare",
                    "params": None,
                }
            )
    return nodes, edges


def _compare_summary(record: CompareNodeRecord) -> str:
    if record.relation == "ancestor_descendant":
        return f"{record.left.run_id} → {record.right.run_id}"
    return f"{record.left.run_id} vs {record.right.run_id}"


def _substantive(record: CompareNodeRecord) -> dict[str, Any]:
    """The record minus the fact of when it was first made."""

    return {
        key: value for key, value in record.to_dict().items() if key != "created_at"
    }


class CompareNodeStore:
    """Write-once records under the project's workbench directory."""

    def __init__(self, project_root: Path | str, *, create: bool = True) -> None:
        supplied = Path(project_root)
        workbench_root = (
            supplied if supplied.name == "workbench" else supplied / "workbench"
        )
        self.root = workbench_root / COMPARE_NODE_DIRNAME
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, compare_id: str) -> Path:
        return self.root / f"{compare_id}.json"

    def create(self, record: CompareNodeRecord) -> CompareNodeRecord:
        with self._lock:
            existing = self.get(record.compare_id)
            if existing is not None:
                # `created_at` is when this pair was first compared, so a later
                # request for the same comparison reuses it rather than looking
                # like a conflicting rewrite. Anything else differing means the
                # evidence itself moved, which is worth refusing.
                if _substantive(existing) != _substantive(record):
                    raise CompareNodeError(
                        "COMPARE_NODE_CONFLICT",
                        "a different comparison is already stored for this pair",
                        evidence={"compare_id": record.compare_id},
                    )
                return existing
            path = self._path(record.compare_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
            # O_EXCL so a concurrent creator loses the race loudly rather than
            # half-writing over an existing record.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            try:
                os.write(fd, payload.encode("utf-8"))
            finally:
                os.close(fd)
            return record

    def get(self, compare_id: str) -> CompareNodeRecord | None:
        try:
            return CompareNodeRecord.from_dict(read_json(self._path(compare_id)))
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError):
            return None

    def list(self) -> list[CompareNodeRecord]:
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError:
            return []
        records: list[CompareNodeRecord] = []
        for path in paths:
            try:
                records.append(CompareNodeRecord.from_dict(read_json(path)))
            except (OSError, KeyError, TypeError, ValueError):
                # One corrupt record must not hide every other comparison.
                continue
        return records

    def delete(self, compare_id: str) -> bool:
        with self._lock:
            try:
                self._path(compare_id).unlink()
            except (FileNotFoundError, OSError):
                return False
            return True


__all__ = [
    "COMPARE_NODE_DIRNAME",
    "COMPARE_NODE_SCHEMA_ID",
    "CompareEndpoint",
    "CompareNodeError",
    "CompareNodeRecord",
    "CompareNodeStore",
    "build_compare_node",
    "canonical_endpoint_order",
    "compare_forest_projection",
    "compare_node_id",
]
