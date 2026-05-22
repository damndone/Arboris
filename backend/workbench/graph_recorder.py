"""Orchestrator-facing helper to accumulate lineage graph entries during a run.

Usage pattern (in orchestrator):

    recorder = GraphRecorder(run_id=manifest["run_id"], store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw data",
                          payload_ref="raw_snapshot.csv")
    recorder.record_stage(node_id="stage:cleaned", display_label="Cleaned",
                          payload_ref="cleaned.csv")
    recorder.record_edge(edge_id="e1", source_id="stage:raw",
                         target_id="stage:cleaned", op="drop_na")
    ...
    recorder.flush()  # persists accumulated graph

The recorder operates on an in-memory Graph and persists once at flush(). This
avoids per-record file I/O during a run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .graph_model import (
    BranchRef,
    DecisionPoint,
    Edge,
    Graph,
    Node,
    NodeKind,
    Trust,
)
from .graph_store import GraphStore

_MAIN_BRANCH = "main"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GraphRecorder:
    """Accumulates graph entries during a single run; persists on flush."""

    def __init__(self, run_id: str, store: GraphStore) -> None:
        self._run_id = run_id
        self._store = store
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}

    # -- record helpers (called by orchestrator) -------------------------------

    def record_stage(
        self,
        node_id: str,
        display_label: str,
        *,
        payload_ref: str | None = None,
        trust: Trust = Trust.OK,
        trust_reason: str | None = None,
        decision_points: tuple[DecisionPoint, ...] = (),
        summary: str | None = None,
    ) -> None:
        self._add_node(
            id=node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=display_label,
            parent_stage_id=None,
            payload_ref=payload_ref,
            trust=trust,
            trust_reason=trust_reason,
            decision_points=decision_points,
            summary=summary,
            created_at=_now_iso(),
        )

    def record_variable(
        self,
        node_id: str,
        display_label: str,
        parent_stage_id: str,
        *,
        payload_ref: str | None = None,
        trust: Trust = Trust.OK,
        trust_reason: str | None = None,
        decision_points: tuple[DecisionPoint, ...] = (),
        summary: str | None = None,
    ) -> None:
        self._add_node(
            id=node_id,
            kind=NodeKind.VARIABLE,
            display_label=display_label,
            parent_stage_id=parent_stage_id,
            payload_ref=payload_ref,
            trust=trust,
            trust_reason=trust_reason,
            decision_points=decision_points,
            summary=summary,
            created_at=_now_iso(),
        )

    def record_model(
        self,
        node_id: str,
        display_label: str,
        *,
        payload_ref: str | None = None,
        trust: Trust = Trust.OK,
        trust_reason: str | None = None,
        decision_points: tuple[DecisionPoint, ...] = (),
        summary: str | None = None,
    ) -> None:
        self._add_node(
            id=node_id,
            kind=NodeKind.MODEL,
            display_label=display_label,
            parent_stage_id=None,
            payload_ref=payload_ref,
            trust=trust,
            trust_reason=trust_reason,
            decision_points=decision_points,
            summary=summary,
            created_at=_now_iso(),
        )

    def record_report(
        self,
        node_id: str,
        display_label: str,
        *,
        payload_ref: str | None = None,
        trust: Trust = Trust.OK,
        trust_reason: str | None = None,
        summary: str | None = None,
    ) -> None:
        self._add_node(
            id=node_id,
            kind=NodeKind.REPORT,
            display_label=display_label,
            parent_stage_id=None,
            payload_ref=payload_ref,
            trust=trust,
            trust_reason=trust_reason,
            decision_points=(),
            summary=summary,
            created_at=_now_iso(),
        )

    def record_edge(
        self,
        edge_id: str,
        source_id: str,
        target_id: str,
        op: str,
        params: dict[str, Any] | None = None,
        reversible: bool = False,
        inverse_op: str | None = None,
    ) -> None:
        if source_id not in self._nodes:
            raise ValueError(f"source_id {source_id!r} not in graph")
        if target_id not in self._nodes:
            raise ValueError(f"target_id {target_id!r} not in graph")
        self._edges[edge_id] = Edge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            op=op,
            params=dict(params or {}),
            reversible=reversible,
            inverse_op=inverse_op,
        )

    # -- persistence -----------------------------------------------------------

    def flush(self) -> None:
        """Persist the accumulated graph.

        Branch head = MODEL/REPORT nodes if any exist; otherwise the topological
        leaves (nodes with no outgoing edges). Avoids relying on dict insertion
        order, which gave misleading heads on blocked-path early-return flushes.
        """
        head_candidates = tuple(
            n.id for n in self._nodes.values()
            if n.kind in (NodeKind.MODEL, NodeKind.REPORT)
        )
        if head_candidates:
            head_node_ids = head_candidates
        else:
            sources = {e.source_id for e in self._edges.values()}
            head_node_ids = tuple(nid for nid in self._nodes if nid not in sources)
        graph = Graph(
            schema_version=2,
            run_id=self._run_id,
            nodes=dict(self._nodes),
            edges=dict(self._edges),
            branches={
                _MAIN_BRANCH: BranchRef(
                    id=_MAIN_BRANCH,
                    forked_from_node_id=None,
                    head_node_ids=head_node_ids,
                ),
            },
        )
        self._store.write(graph)

    # -- internals -------------------------------------------------------------

    def _add_node(
        self,
        *,
        id: str,
        kind: NodeKind,
        display_label: str,
        parent_stage_id: str | None,
        payload_ref: str | None,
        trust: Trust,
        trust_reason: str | None,
        decision_points: tuple[DecisionPoint, ...],
        summary: str | None,
        created_at: str,
    ) -> None:
        if id in self._nodes:
            raise ValueError(f"duplicate node id {id!r}")
        self._nodes[id] = Node(
            id=id,
            kind=kind,
            display_label=display_label,
            created_at=created_at,
            parent_stage_id=parent_stage_id,
            branch_id=_MAIN_BRANCH,
            trust=trust,
            trust_reason=trust_reason,
            archived=False,
            payload_ref=payload_ref,
            decision_points=decision_points,
            summary=summary,
        )
