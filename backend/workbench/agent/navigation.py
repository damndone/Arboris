"""Read-only navigation projections across Agent and Workbench records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .chains import ChainStore, ForkStore
from .events import AgentEventStream
from .operations import OperationRecord, OperationRecordStore
from .proposals import ProposalStore
from .session import JsonlSessionRepository


@dataclass(frozen=True)
class AgentNavigationRef:
    kind: str
    id: str
    label: str
    relation: str
    available: bool
    href: dict[str, str]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "relation": self.relation,
            "available": self.available,
            "href": dict(self.href),
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class AgentNavigationProjection:
    subject: AgentNavigationRef
    links: tuple[AgentNavigationRef, ...]
    last_event_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "links": [link.to_dict() for link in self.links],
            "last_event_seq": self.last_event_seq,
        }


class AgentNavigationProjector:
    """Resolve verified navigation links from the current project root.

    The constructor deliberately receives the project root, not the
    ``workbench/`` storage root: Agent records live below ``workbench/`` while
    run/node validation lives below ``runs/``.
    """

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.workbench_root = self.project_root / "workbench"
        self.repository = JsonlSessionRepository(self.workbench_root)
        self.events = AgentEventStream(self.workbench_root)
        self.chains = ChainStore(self.workbench_root)
        self.forks = ForkStore(self.workbench_root)
        self.proposals = ProposalStore(self.workbench_root)
        self.operations = OperationRecordStore(self.workbench_root)

    def session(self, session_id: str) -> AgentNavigationProjection:
        metadata = self.repository.get_metadata(session_id)
        subject = self._session_ref(session_id, relation="context")
        links: list[AgentNavigationRef] = []
        self._append_unique(links, self._main_ref(relation="parent"))

        chain_id = metadata.get("chain_id")
        if isinstance(chain_id, str) and chain_id:
            chain = self._try_get_chain(chain_id)
            if chain is not None:
                self._append_unique(
                    links,
                    self._chain_ref(chain, relation="parent"),
                )

        for record in self.operations.list_records():
            if not self._record_touches_session(record, session_id):
                continue
            self._append_record_links(links, record)

        return AgentNavigationProjection(
            subject=subject,
            links=tuple(links),
            last_event_seq=self._last_event_seq(session_id),
        )

    def operation(self, record_id: str) -> AgentNavigationProjection:
        record = self.operations.get(record_id)
        subject = self._operation_ref(record, relation="audit")
        links: list[AgentNavigationRef] = []
        self._append_unique(
            links,
            self._session_ref(record.agent_session_id, relation="context"),
        )
        self._append_unique(links, self._main_ref(relation="parent"))
        self._append_record_links(links, record)
        return AgentNavigationProjection(
            subject=subject,
            links=tuple(links),
            last_event_seq=self._last_event_seq(record.agent_session_id),
        )

    def graph(
        self,
        *,
        run_id: str,
        node_ref: str | None,
        forest_node_key: str | None,
    ) -> AgentNavigationProjection:
        node_hash = self._node_hash(run_id, node_ref, forest_node_key)
        available = node_hash is not None
        subject = AgentNavigationRef(
            kind="graph_node",
            id=forest_node_key or node_ref or run_id,
            label=node_ref or forest_node_key or run_id,
            relation="context",
            available=available,
            href=self._graph_href(run_id, node_ref, forest_node_key),
            reason=None if available else "graph node is not present in this project",
        )
        links: list[AgentNavigationRef] = []
        for record in self.operations.list_records():
            if not self._record_matches_node(
                record,
                run_id=run_id,
                node_ref=node_ref,
                forest_node_key=forest_node_key,
                node_hash=node_hash,
            ):
                continue
            self._append_record_links(links, record)
        return AgentNavigationProjection(
            subject=subject,
            links=tuple(links),
            last_event_seq=0,
        )

    def _append_record_links(
        self,
        links: list[AgentNavigationRef],
        record: OperationRecord,
    ) -> None:
        proposal_available = self._try_proposal(record.proposal_id) is not None
        self._append_unique(
            links,
            self._ref(
                kind="proposal",
                identifier=record.proposal_id,
                label=f"Proposal {record.proposal_id}",
                relation="audit",
                available=proposal_available,
                href={
                    "view": "agent",
                    "session_id": record.agent_session_id,
                    "proposal_id": record.proposal_id,
                },
                reason=None if proposal_available else "proposal record is missing",
            ),
        )

        target = record.target
        source_run_id = str(target.get("run_id", ""))
        source_node_ref = _optional_str(target.get("node_ref"))
        source_forest_key = _optional_str(target.get("forest_node_key"))
        source_hash = _optional_str(target.get("node_hash"))
        source_available = self._node_hash(
            source_run_id,
            source_node_ref,
            source_forest_key,
        ) is not None
        if source_run_id and source_node_ref:
            self._append_unique(
                links,
                self._ref(
                    kind="graph_node",
                    identifier=source_forest_key or source_node_ref,
                    label=f"Source {source_node_ref}",
                    relation="source",
                    available=source_available,
                    href=self._graph_href(
                        source_run_id,
                        source_node_ref,
                        source_forest_key,
                        node_hash=source_hash,
                    ),
                    reason=(
                        None
                        if source_available
                        else "source graph node is not present in this project"
                    ),
                ),
            )

        execution = record.execution
        child_run_id = _optional_str(record.outputs.get("target_run_id"))
        if child_run_id:
            child_available = self._run_exists(child_run_id)
            self._append_unique(
                links,
                self._ref(
                    kind="run",
                    identifier=child_run_id,
                    label=f"Child run {child_run_id}",
                    relation="child",
                    available=child_available,
                    href={"view": "graph", "run_id": child_run_id},
                    reason=None if child_available else "child run is not present in this project",
                ),
            )

        fork_id = _optional_str(execution.get("fork_id"))
        if fork_id:
            fork = self._try_get_fork(fork_id)
            self._append_unique(
                links,
                self._ref(
                    kind="fork",
                    identifier=fork_id,
                    label=f"Fork {fork_id}",
                    relation="child",
                    available=fork is not None,
                    href={
                        "view": "graph",
                        "fork_id": fork_id,
                        "run_id": child_run_id or "",
                    },
                    reason=None if fork is not None else "fork record is missing",
                ),
            )

        child_chain_id = _optional_str(execution.get("child_chain_id"))
        if child_chain_id:
            chain = self._try_get_chain(child_chain_id)
            self._append_unique(
                links,
                self._chain_ref(chain, relation="child", identifier=child_chain_id),
            )

        child_session_id = _optional_str(execution.get("child_session_id"))
        if child_session_id:
            self._append_unique(
                links,
                self._session_ref(child_session_id, relation="child"),
            )

        self._append_unique(
            links,
            self._operation_ref(record, relation="audit"),
        )

    def _record_matches_node(
        self,
        record: OperationRecord,
        *,
        run_id: str,
        node_ref: str | None,
        forest_node_key: str | None,
        node_hash: str | None,
    ) -> bool:
        target = record.target
        if str(target.get("run_id", "")) != run_id:
            return False
        if node_ref is not None and target.get("node_ref") != node_ref:
            return False
        if forest_node_key is not None and target.get("forest_node_key") != forest_node_key:
            return False
        target_hash = _optional_str(target.get("node_hash"))
        return node_hash is None or target_hash == node_hash

    def _record_touches_session(self, record: OperationRecord, session_id: str) -> bool:
        return record.agent_session_id == session_id or record.execution.get(
            "child_session_id"
        ) == session_id

    def _session_ref(self, session_id: str, *, relation: str) -> AgentNavigationRef:
        available = self._session_exists(session_id)
        return self._ref(
            kind="agent_session",
            identifier=session_id,
            label=f"Agent {session_id}",
            relation=relation,
            available=available,
            href={"view": "agent", "session_id": session_id},
            reason=None if available else "Agent session is missing",
        )

    def _main_ref(self, *, relation: str) -> AgentNavigationRef:
        return self._session_ref("agent_main", relation=relation)

    def _operation_ref(self, record: OperationRecord, *, relation: str) -> AgentNavigationRef:
        return self._ref(
            kind="operation",
            identifier=record.record_id,
            label=f"{record.operation_id} · {record.status}",
            relation=relation,
            available=True,
            href={
                "view": "agent",
                "session_id": record.agent_session_id,
                "operation_record_id": record.record_id,
            },
        )

    def _chain_ref(
        self,
        chain: dict[str, Any] | None,
        *,
        relation: str,
        identifier: str | None = None,
    ) -> AgentNavigationRef:
        chain_id = identifier or (str(chain.get("chain_id")) if chain else "")
        available = chain is not None
        child_session_id = _optional_str(chain.get("child_session_id")) if chain else None
        href = {"view": "agent", "chain_id": chain_id}
        if child_session_id:
            href["session_id"] = child_session_id
        return self._ref(
            kind="chain",
            identifier=chain_id,
            label=f"Chain {chain_id}",
            relation=relation,
            available=available,
            href=href,
            reason=None if available else "chain record is missing",
        )

    def _ref(
        self,
        *,
        kind: str,
        identifier: str,
        label: str,
        relation: str,
        available: bool,
        href: dict[str, str],
        reason: str | None = None,
    ) -> AgentNavigationRef:
        return AgentNavigationRef(
            kind=kind,
            id=identifier,
            label=label,
            relation=relation,
            available=available,
            href={key: value for key, value in href.items() if value},
            reason=reason,
        )

    def _node_hash(
        self,
        run_id: str,
        node_ref: str | None,
        forest_node_key: str | None,
    ) -> str | None:
        if not self._run_exists(run_id):
            return None
        path = self.project_root / "runs" / run_id / "node_index.json"
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        candidates = [node_ref]
        if forest_node_key and "::" not in forest_node_key:
            candidates.append(forest_node_key)
        for candidate in candidates:
            if candidate and isinstance(index, dict) and candidate in index:
                value = index[candidate]
                if isinstance(value, dict) and value.get("node_hash"):
                    return str(value["node_hash"])
        return None

    def _graph_href(
        self,
        run_id: str,
        node_ref: str | None,
        forest_node_key: str | None,
        *,
        node_hash: str | None = None,
    ) -> dict[str, str]:
        href = {
            "view": "graph",
            "run_id": run_id,
            "node_ref": node_ref or "",
            "forest_node_key": forest_node_key or "",
        }
        if node_hash:
            href["node_hash"] = node_hash
        return href

    def _run_exists(self, run_id: str) -> bool:
        return bool(run_id) and (self.project_root / "runs" / run_id).is_dir()

    def _session_exists(self, session_id: str) -> bool:
        return bool(session_id) and (
            self.workbench_root / "agent-sessions" / f"{session_id}.meta.json"
        ).is_file()

    def _try_get_chain(self, chain_id: str) -> dict[str, Any] | None:
        try:
            return self.chains.get(chain_id)
        except (KeyError, ValueError):
            return None

    def _try_get_fork(self, fork_id: str) -> dict[str, Any] | None:
        try:
            return self.forks.get(fork_id)
        except (KeyError, ValueError):
            return None

    def _try_proposal(self, proposal_id: str):
        try:
            return self.proposals.latest_revision(proposal_id)
        except (KeyError, ValueError):
            return None

    def _last_event_seq(self, session_id: str) -> int:
        events = self.events.replay(session_id)
        return events[-1].seq if events else 0

    @staticmethod
    def _append_unique(
        links: list[AgentNavigationRef],
        candidate: AgentNavigationRef,
    ) -> None:
        key = (candidate.kind, candidate.id, candidate.relation)
        if any((item.kind, item.id, item.relation) == key for item in links):
            return
        links.append(candidate)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value or None
