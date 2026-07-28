"""Bounded provenance graphs for CF3 evidence independence checks.

This module stores references and lineage only.  It never reads fixtures,
imports implementations, or evaluates author output.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import _content_digest, _digest, _text


_NODE_KINDS = frozenset({"author", "oracle", "holdout", "review"})
_MAX_NODES = 256


class ProvenanceError(ValueError):
    """Raised when evidence provenance cannot establish an independent source."""


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    node_id: str
    kind: str
    artifact_ref: str
    parent_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "node_id", _text(self.node_id, "node_id"))
            if self.kind not in _NODE_KINDS:
                raise ProvenanceError("unsupported provenance node kind")
            object.__setattr__(self, "kind", self.kind)
            object.__setattr__(self, "artifact_ref", _digest(self.artifact_ref, "artifact_ref"))
            parents = tuple(self.parent_refs)
            if len(parents) > _MAX_NODES or any(not isinstance(item, str) or not item for item in parents):
                raise ProvenanceError("parent_refs must be bounded identifiers")
            if len(set(parents)) != len(parents):
                raise ProvenanceError("parent_refs must be unique")
            object.__setattr__(self, "parent_refs", parents)
        except ValueError as error:
            if isinstance(error, ProvenanceError):
                raise
            raise ProvenanceError(str(error)) from error


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    evidence_ref: str
    author_root: str
    oracle_root: str | None
    nodes: tuple[ProvenanceNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ref", _digest(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "author_root", _text(self.author_root, "author_root"))
        if self.oracle_root is not None:
            object.__setattr__(self, "oracle_root", _text(self.oracle_root, "oracle_root"))
        nodes = tuple(self.nodes)
        if not nodes or len(nodes) > _MAX_NODES or any(not isinstance(item, ProvenanceNode) for item in nodes):
            raise ProvenanceError("nodes must be a bounded non-empty ProvenanceNode sequence")
        by_id = {item.node_id: item for item in nodes}
        if len(by_id) != len(nodes) or self.author_root not in by_id:
            raise ProvenanceError("provenance roots must reference known nodes")
        if self.oracle_root is not None and self.oracle_root not in by_id:
            raise ProvenanceError("oracle_root must reference a known node")
        for node in nodes:
            if any(parent not in by_id for parent in node.parent_refs):
                raise ProvenanceError("provenance node references an unknown parent")
        self._assert_acyclic(by_id)
        if by_id[self.author_root].kind != "author":
            raise ProvenanceError("author_root must be an author node")
        if self.oracle_root is not None and by_id[self.oracle_root].kind not in {"oracle", "holdout", "review"}:
            raise ProvenanceError("oracle_root must be an independent evidence node")
        if self.oracle_root is not None and not self._has_disjoint_lineage(by_id):
            raise ProvenanceError("oracle lineage is not independent from author lineage")
        object.__setattr__(self, "nodes", nodes)

    @staticmethod
    def _assert_acyclic(nodes: dict[str, ProvenanceNode]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ProvenanceError("provenance graph contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for parent in nodes[node_id].parent_refs:
                visit(parent)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in nodes:
            visit(node_id)

    @staticmethod
    def _ancestors(nodes: dict[str, ProvenanceNode], root: str) -> set[str]:
        found: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in found:
                return
            found.add(node_id)
            for parent in nodes[node_id].parent_refs:
                visit(parent)

        visit(root)
        return found

    def _has_disjoint_lineage(self, nodes: dict[str, ProvenanceNode]) -> bool:
        author_lineage = self._ancestors(nodes, self.author_root)
        oracle_lineage = self._ancestors(nodes, self.oracle_root)  # type: ignore[arg-type]
        return author_lineage.isdisjoint(oracle_lineage)

    @property
    def independent_oracle(self) -> bool:
        return self.oracle_root is not None

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = ["EvidenceProvenance", "ProvenanceError", "ProvenanceNode"]
