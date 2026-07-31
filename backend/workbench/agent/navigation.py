"""Read-only navigation projections across Agent and Workbench records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .chains import ChainStore, ForkStore
from .events import AgentEvent, AgentEventStream
from .operations import OperationRecord, OperationRecordStore
from .proposals import ProposalStore
from .session import EntryRef, JsonlSessionRepository


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
class AgentHierarchyNode:
    ref: AgentNavigationRef
    status: str | None
    children: tuple["AgentHierarchyNode", ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref.to_dict(),
            "status": self.status,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass(frozen=True)
class AgentActivityItem:
    """Read-only AI Activity projection of one durable operation record."""

    activity_id: str
    at: str
    main: AgentNavigationRef
    chain: AgentNavigationRef
    operation: AgentNavigationRef
    diff: AgentNavigationRef | None
    status: str
    links: tuple[AgentNavigationRef, ...]
    diff_ref: dict[str, Any] | None
    verification: dict[str, Any]
    effect_status: str
    projection_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "operation",
            "activity_id": self.activity_id,
            "at": self.at,
            "main": self.main.to_dict(),
            "chain": self.chain.to_dict(),
            "operation": self.operation.to_dict(),
            "diff": self.diff.to_dict() if self.diff is not None else None,
            "status": self.status,
            "links": [link.to_dict() for link in self.links],
            "diff_ref": dict(self.diff_ref) if self.diff_ref is not None else None,
            "verification": dict(self.verification),
            "effect_status": self.effect_status,
            "projection_status": self.projection_status,
        }


@dataclass(frozen=True)
class AgentActivityEventItem:
    """Read-only AI Activity projection of one durable Agent event.

    Event payloads are deliberately reduced to a bounded, structured detail
    object. Navigation links are resolved from durable operation/proposal
    records and verified graph/session stores rather than from model prose.
    """

    activity_id: str
    at: str
    seq: int
    event_type: str
    session: AgentNavigationRef
    main: AgentNavigationRef
    chain: AgentNavigationRef
    command_id: str | None
    details: dict[str, Any]
    links: tuple[AgentNavigationRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "event",
            "activity_id": self.activity_id,
            "at": self.at,
            "seq": self.seq,
            "event_type": self.event_type,
            "session": self.session.to_dict(),
            "main": self.main.to_dict(),
            "chain": self.chain.to_dict(),
            "command_id": self.command_id,
            "details": dict(self.details),
            "links": [link.to_dict() for link in self.links],
        }


@dataclass(frozen=True)
class AgentNavigationProjection:
    subject: AgentNavigationRef
    links: tuple[AgentNavigationRef, ...]
    last_event_seq: int
    hierarchy: AgentHierarchyNode | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "subject": self.subject.to_dict(),
            "links": [link.to_dict() for link in self.links],
            "last_event_seq": self.last_event_seq,
        }
        if self.hierarchy is not None:
            result["hierarchy"] = self.hierarchy.to_dict()
        return result


class AgentNavigationProjector:
    """Resolve verified navigation links from the current project root.

    The constructor deliberately receives the project root, not the
    ``workbench/`` storage root: Agent records live below ``workbench/`` while
    run/node validation lives below ``runs/``.
    """

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.workbench_root = self.project_root / "workbench"
        self.repository = JsonlSessionRepository(self.workbench_root, create=False)
        self.events = AgentEventStream(self.workbench_root, create=False)
        self.chains = ChainStore(self.workbench_root, create=False)
        self.forks = ForkStore(self.workbench_root, create=False)
        self.proposals = ProposalStore(self.workbench_root, create=False)
        self.operations = OperationRecordStore(self.workbench_root, create=False)

    def session(self, session_id: str) -> AgentNavigationProjection:
        metadata = self.repository.get_metadata(session_id)
        subject = self._session_ref(session_id, relation="context")
        links: list[AgentNavigationRef] = []
        self._append_unique(links, self._main_ref(relation="parent"))

        chain_id = metadata.get("chain_id")
        if isinstance(chain_id, str) and chain_id:
            chain = self._try_get_chain(chain_id)
            self._append_unique(
                links,
                self._chain_ref(chain, relation="parent", identifier=chain_id),
            )

        for record in self.operations.list_records():
            if not self._record_touches_session(record, session_id):
                continue
            self._append_record_links(links, record)

        return AgentNavigationProjection(
            subject=subject,
            links=tuple(links),
            last_event_seq=self._last_event_seq(session_id),
            hierarchy=self._build_hierarchy(session_id),
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

    def activity(self) -> tuple[AgentActivityItem, ...]:
        """Project all durable operations for the project into AI Activity."""

        records = sorted(
            self.operations.list_records(),
            key=lambda record: (record.updated_at or record.created_at, record.record_id),
            reverse=True,
        )
        activities: list[AgentActivityItem] = []
        for record in records:
            links: list[AgentNavigationRef] = []
            self._append_record_links(links, record)
            activities.append(
                AgentActivityItem(
                    activity_id=record.record_id,
                    at=record.updated_at or record.created_at,
                    main=self._main_ref(relation="parent"),
                    chain=self._chain_ref(
                        self._try_get_chain(record.chain_id),
                        relation="parent",
                        identifier=record.chain_id,
                    ),
                    operation=self._operation_ref(record, relation="audit"),
                    diff=self._diff_ref(record),
                    status=record.status,
                    links=tuple(link for link in links if link.kind != "operation"),
                    diff_ref=dict(record.diff_ref) if record.diff_ref is not None else None,
                    verification=dict(record.verification),
                    effect_status=record.effect_status,
                    projection_status=record.projection_status,
                )
            )
        return tuple(activities)

    def activity_events(self) -> tuple[AgentActivityEventItem, ...]:
        """Project the replayable Agent lifecycle into granular activity rows."""

        metadata = self.repository.list_metadata()
        events: list[tuple[dict[str, Any], AgentEvent]] = []
        for value in metadata:
            session_id = _optional_str(value.get("session_id"))
            if not session_id:
                continue
            for event in self.events.replay(session_id):
                events.append((value, event))

        projected: list[AgentActivityEventItem] = []
        for metadata_value, event in sorted(
            events,
            key=lambda item: (
                item[1].created_at,
                item[1].session_id,
                item[1].seq,
                item[1].event_id,
            ),
        ):
            session_id = event.session_id
            chain_id = _optional_str(metadata_value.get("chain_id"))
            links: list[AgentNavigationRef] = []
            record_id = _optional_str(
                event.payload.get("record_id")
                or event.payload.get("operation_record_id")
            )
            record = self._try_get_operation(record_id) if record_id else None
            if record is not None:
                self._append_record_links(links, record)
            proposal_id = _optional_str(
                event.payload.get("proposal_id")
                or (event.payload.get("proposal") or {}).get("proposal_id")
            )
            if proposal_id:
                self._append_unique(links, self._proposal_ref(proposal_id, session_id))
            self._append_event_target_link(links, event)
            self._append_event_entity_links(links, event)
            projected.append(
                AgentActivityEventItem(
                    activity_id=event.event_id,
                    at=event.created_at,
                    seq=event.seq,
                    event_type=event.event_type,
                    session=self._session_ref(session_id, relation="context"),
                    main=self._main_ref(relation="parent"),
                    chain=self._chain_ref(
                        self._try_get_chain(chain_id) if chain_id else None,
                        relation="parent",
                        identifier=chain_id,
                    ),
                    command_id=event.command_id,
                    details=self._event_details(event),
                    links=tuple(links),
                )
            )
        return tuple(projected)

    def activity_hierarchy(self) -> AgentHierarchyNode | None:
        """Project the durable Main/Chain tree for the AI Activity surface."""

        metadata = self.repository.list_metadata()
        main_id = self._main_session_id(metadata)
        if not any(str(value.get("session_id")) == main_id for value in metadata):
            return None
        return self._build_hierarchy(main_id)

    def entry(self, session_id: str, entry_id: str) -> AgentNavigationProjection:
        """Project one durable Agent message entry without parsing its prose."""

        self.repository.get_metadata(session_id)
        entry = self.repository.get_entry(EntryRef(session_id, entry_id))
        subject = self._ref(
            kind="agent_entry",
            identifier=entry.entry_id,
            label=f"Agent entry {entry.entry_id}",
            relation="context",
            available=True,
            href={
                "view": "agent",
                "session_id": session_id,
                "entry_id": entry.entry_id,
            },
        )
        # Session/Main scope is rendered once in the panel projection. Keep
        # message-level refs focused on relationships caused by this entry so
        # a long transcript does not repeat the same parent chips on every
        # line.
        links: list[AgentNavigationRef] = []
        command_id = _optional_str(entry.payload.get("command_id"))
        for record in self.operations.list_records():
            if record.agent_session_id != session_id:
                continue
            if command_id is None or record.command_id != command_id:
                continue
            self._append_record_links(links, record)
        return AgentNavigationProjection(
            subject=subject,
            links=tuple(links),
            last_event_seq=self._last_event_seq(session_id),
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
        if not available:
            return AgentNavigationProjection(
                subject=subject,
                links=(),
                last_event_seq=0,
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
            # Graph navigation starts from the source-side Chain session. Keep
            # this relation graph-scoped so operation/session projections do
            # not redundantly link to their own Agent session.
            self._append_unique(
                links,
                self._session_ref(record.agent_session_id, relation="source"),
            )
            self._append_record_links(links, record)
        # A fork is a durable graph relationship in its own right. It may be
        # created before an operation record exists (or remain after a failed
        # operation), so graph -> Agent navigation must not depend solely on
        # operation records.
        for fork in self._fork_records():
            if self._fork_matches_node(
                fork,
                run_id=run_id,
                node_ref=node_ref,
                forest_node_key=forest_node_key,
            ):
                self._append_fork_links(links, fork)
        return AgentNavigationProjection(
            subject=subject,
            links=tuple(links),
            last_event_seq=0,
        )

    def _build_hierarchy(self, session_id: str) -> AgentHierarchyNode:
        """Build a read-only Main → Chain → operation/child Chain tree."""

        metadata = self.repository.list_metadata()
        by_session = {
            str(value.get("session_id")): value
            for value in metadata
            if value.get("session_id")
        }
        current = by_session.get(session_id)
        if current is None:
            raise KeyError(f"unknown session: {session_id}")

        main_id = self._main_session_id(metadata)
        main_ref = self._session_ref(main_id, relation="context")
        main_status = (by_session.get(main_id) or {}).get("status")

        chain_sessions: dict[str, list[dict[str, Any]]] = {}
        for value in by_session.values():
            if value.get("role") != "chain":
                continue
            chain_id = _optional_str(value.get("chain_id"))
            if chain_id:
                chain_sessions.setdefault(chain_id, []).append(value)

        chain_records = {
            str(value.get("chain_id")): value
            for value in self.chains.list_records()
            if value.get("chain_id")
        }
        chain_ids = set(chain_sessions) | set(chain_records)
        for record in chain_records.values():
            parent_chain_id = _optional_str(record.get("parent_chain_id"))
            if parent_chain_id:
                chain_ids.add(parent_chain_id)

        children_by_parent: dict[str, list[str]] = {}
        root_chain_ids: list[str] = []
        for chain_id in sorted(chain_ids):
            record = chain_records.get(chain_id)
            parent_chain_id = _optional_str(record.get("parent_chain_id")) if record else None
            if parent_chain_id and parent_chain_id in chain_ids:
                children_by_parent.setdefault(parent_chain_id, []).append(chain_id)
            else:
                root_chain_ids.append(chain_id)

        records = sorted(self.operations.list_records(), key=lambda value: value.record_id)

        def chain_node(chain_id: str, visiting: frozenset[str] = frozenset()) -> AgentHierarchyNode:
            record = chain_records.get(chain_id)
            sessions = sorted(chain_sessions.get(chain_id, []), key=lambda value: str(value.get("session_id")))
            if record is not None:
                ref = self._chain_ref(record, relation="child", identifier=chain_id)
            else:
                session_for_href = _optional_str(sessions[0].get("session_id")) if sessions else None
                ref = self._ref(
                    kind="chain",
                    identifier=chain_id,
                    label=f"Chain {chain_id}",
                    relation="child",
                    available=bool(sessions),
                    href={
                        "view": "agent",
                        "chain_id": chain_id,
                        "session_id": session_for_href or "",
                    },
                    reason=None if sessions else "chain session is missing",
                )
            status = _optional_str(record.get("status")) if record else None
            if status is None and sessions:
                status = _optional_str(sessions[0].get("status"))

            child_nodes: list[AgentHierarchyNode] = [
                AgentHierarchyNode(
                    ref=self._session_ref(str(value["session_id"]), relation="child"),
                    status=_optional_str(value.get("status")),
                )
                for value in sessions
                if value.get("session_id")
            ]
            for operation in records:
                if operation.chain_id == chain_id:
                    child_nodes.append(self._operation_hierarchy(operation))

            if chain_id not in visiting:
                next_visiting = visiting | {chain_id}
                child_nodes.extend(
                    chain_node(child_id, next_visiting)
                    for child_id in children_by_parent.get(chain_id, [])
                    if child_id not in next_visiting
                )
            return AgentHierarchyNode(ref=ref, status=status, children=tuple(child_nodes))

        return AgentHierarchyNode(
            ref=main_ref,
            status=main_status,
            children=tuple(chain_node(chain_id) for chain_id in root_chain_ids),
        )

    def _operation_hierarchy(self, record: OperationRecord) -> AgentHierarchyNode:
        links: list[AgentNavigationRef] = []
        self._append_record_links(links, record)
        children = tuple(
            AgentHierarchyNode(ref=link, status=self._link_status(link))
            for link in links
            if link.kind not in {"operation", "chain", "agent_session"}
        )
        return AgentHierarchyNode(
            ref=self._operation_ref(record, relation="audit"),
            status=record.status,
            children=children,
        )

    def _link_status(self, link: AgentNavigationRef) -> str | None:
        if link.kind == "proposal":
            try:
                return self.proposals.latest_status(link.id)
            except (KeyError, ValueError):
                return None
        if link.kind == "fork":
            fork = self._try_get_fork(link.id)
            return _optional_str(fork.get("status")) if fork else None
        if link.kind == "run":
            try:
                manifest = json.loads(
                    (self.project_root / "runs" / link.id / "run_manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
            except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
                return None
            return _optional_str(manifest.get("status")) if isinstance(manifest, dict) else None
        if link.kind == "graph_node" and link.available:
            return "available"
        if link.kind == "diff" and link.available:
            return "available"
        return None

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
        source_navigation_key = self._navigation_forest_key(
            source_forest_key,
            source_hash,
            source_node_ref,
        )
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
                    identifier=source_navigation_key or source_node_ref,
                    label=f"Source {source_node_ref}",
                    relation="source",
                    available=source_available,
                    href=self._graph_href(
                        source_run_id,
                        source_node_ref,
                        source_navigation_key,
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
        # The child session is a server-recorded execution binding, not a
        # client guess.  Keep it on the child-run navigation ref so the UI can
        # retain the output transcript while it moves to that exact run.
        child_session_id = _optional_str(execution.get("child_session_id"))
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
                    href={
                        "view": "graph",
                        "run_id": child_run_id,
                        **(
                            {"session_id": child_session_id}
                            if child_session_id
                            else {}
                        ),
                    },
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

        if child_session_id:
            self._append_unique(
                links,
                self._session_ref(child_session_id, relation="child"),
            )

        self._append_unique(
            links,
            self._operation_ref(record, relation="audit"),
        )
        diff = self._diff_ref(record)
        if diff is not None:
            self._append_unique(links, diff)

    def _append_event_target_link(
        self,
        links: list[AgentNavigationRef],
        event: AgentEvent,
    ) -> None:
        """Resolve a graph target from structured event facts when no record exists."""

        target = event.payload.get("target")
        target = target if isinstance(target, dict) else event.payload
        run_id = _optional_str(target.get("run_id") or target.get("source_run_id"))
        node_ref = _optional_str(target.get("node_ref") or target.get("source_node_ref"))
        forest_node_key = _optional_str(target.get("forest_node_key"))
        node_hash = _optional_str(target.get("node_hash"))
        if not run_id or not node_ref:
            return
        available = self._node_hash(run_id, node_ref, forest_node_key) is not None
        self._append_unique(
            links,
            self._ref(
                kind="graph_node",
                identifier=self._navigation_forest_key(forest_node_key, node_hash, node_ref)
                or node_ref,
                label=f"Source {node_ref}",
                relation="source",
                available=available,
                href=self._graph_href(
                    run_id,
                    node_ref,
                    forest_node_key,
                    node_hash=node_hash,
                ),
                reason=None if available else "source graph node is not present in this project",
            ),
        )

    def _append_event_entity_links(
        self,
        links: list[AgentNavigationRef],
        event: AgentEvent,
    ) -> None:
        payload = event.payload
        fork_id = _optional_str(payload.get("fork_id"))
        if fork_id and self._try_get_fork(fork_id) is not None:
            self._append_unique(
                links,
                self._ref(
                    kind="fork",
                    identifier=fork_id,
                    label=f"Fork {fork_id}",
                    relation="child",
                    available=True,
                    href={"view": "graph", "fork_id": fork_id},
                ),
            )
        child_chain_id = _optional_str(payload.get("child_chain_id"))
        if child_chain_id:
            self._append_unique(
                links,
                self._chain_ref(
                    self._try_get_chain(child_chain_id),
                    relation="child",
                    identifier=child_chain_id,
                ),
            )
        child_session_id = _optional_str(payload.get("child_session_id"))
        if child_session_id:
            self._append_unique(links, self._session_ref(child_session_id, relation="child"))
        child_run_id = _optional_str(payload.get("target_run_id"))
        if child_run_id:
            available = self._run_exists(child_run_id)
            self._append_unique(
                links,
                self._ref(
                    kind="run",
                    identifier=child_run_id,
                    label=f"Child run {child_run_id}",
                    relation="child",
                    available=available,
                    href={"view": "graph", "run_id": child_run_id},
                    reason=None if available else "child run is not present in this project",
                ),
            )

    def _event_details(self, event: AgentEvent) -> dict[str, Any]:
        """Keep event rows useful without projecting unbounded transcript data."""

        payload = event.payload
        details: dict[str, Any] = {}
        scalar_keys = (
            "record_id",
            "operation_record_id",
            "proposal_id",
            "operation_id",
            "operation_version",
            "status",
            "tool_id",
            "tool_call_id",
            "target_run_id",
            "source_run_id",
            "source_node_ref",
            "child_chain_id",
            "child_session_id",
            "fork_id",
            "revision",
            "active_head_run_id",
            "run_family_id",
            "stop_reason",
        )
        for key in scalar_keys:
            if key in payload and isinstance(payload[key], (str, int, float, bool)):
                details[key] = payload[key]
        for parent_key, child_keys in (
            ("target", ("run_id", "node_ref", "node_hash", "forest_node_key")),
            ("preconditions", ("context_version", "active_head_run_id", "owner_resolution")),
            ("execution", scalar_keys),
            ("outputs", ("status", "target_run_id", "fork_id", "child_chain_id", "child_session_id")),
        ):
            nested = payload.get(parent_key)
            if not isinstance(nested, dict):
                continue
            for key in child_keys:
                if key in nested and isinstance(nested[key], (str, int, float, bool)):
                    details.setdefault(key, nested[key])
        error = payload.get("error")
        if isinstance(error, dict):
            bounded_error = {
                key: value
                for key, value in error.items()
                if key in {"type", "phase", "code", "message"}
                and isinstance(value, (str, int, float, bool))
            }
            if bounded_error:
                details["error"] = bounded_error
        return details

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
        target_run_id = str(target.get("run_id", ""))
        if target_run_id == run_id:
            if node_ref is not None and target.get("node_ref") != node_ref:
                return False
            target_hash = _optional_str(target.get("node_hash"))
            if forest_node_key is not None:
                if "::" in forest_node_key:
                    key_prefix, key_node_ref = forest_node_key.split("::", 1)
                    if key_node_ref != str(target.get("node_ref", "")):
                        return False
                    # The UI selector is node_hash::node_ref while durable
                    # operation targets intentionally persist node_hash.
                    # Keep accepting legacy run_id::node_ref selectors.
                    if key_prefix not in {run_id, target_hash}:
                        return False
                elif forest_node_key not in {
                    _optional_str(target.get("forest_node_key")),
                    target_hash,
                }:
                    return False
            return node_hash is None or target_hash == node_hash

        # A child graph node points back through the operation's durable
        # execution output. The child artifact has its own node hash and
        # forest key, so only the stable node ref is compared here; the
        # projector has already verified the child run/node exists locally.
        child_run_id = _optional_str(record.outputs.get("target_run_id"))
        if child_run_id != run_id:
            return False
        return node_ref is None or target.get("node_ref") == node_ref

    def _record_touches_session(self, record: OperationRecord, session_id: str) -> bool:
        return record.agent_session_id == session_id or record.execution.get(
            "child_session_id"
        ) == session_id

    def _fork_matches_node(
        self,
        fork: dict[str, Any],
        *,
        run_id: str,
        node_ref: str | None,
        forest_node_key: str | None,
    ) -> bool:
        chain_id = _optional_str(fork.get("source_chain_id"))
        source_node_ref = _optional_str(fork.get("source_node_ref"))
        child_chain_id = _optional_str(fork.get("child_chain_id"))
        chain = self._try_get_chain(child_chain_id) if child_chain_id else None
        source_chain = self._try_get_chain(chain_id) if chain_id else None
        chain = chain or source_chain
        source_run_id = _optional_str(chain.get("source_run_id")) if chain else None
        if source_run_id != run_id or (node_ref and source_node_ref != node_ref):
            return False
        if forest_node_key and "::" in forest_node_key:
            key_prefix, forest_node_ref = forest_node_key.split("::", 1)
            if forest_node_ref != source_node_ref:
                return False
            if key_prefix != run_id and self._node_hash(
                run_id,
                source_node_ref,
                forest_node_key,
            ) is None:
                return False
        return bool(source_node_ref)

    def _append_fork_links(
        self,
        links: list[AgentNavigationRef],
        fork: dict[str, Any],
    ) -> None:
        fork_id = _optional_str(fork.get("fork_id"))
        if not fork_id:
            return
        child_chain_id = _optional_str(fork.get("child_chain_id"))
        child_session_id = _optional_str(
            fork.get("child_session_id") or fork.get("child_agent_id")
        )
        child_chain = self._try_get_chain(child_chain_id) if child_chain_id else None
        child_run_id = _optional_str(child_chain.get("active_head_run_id")) if child_chain else None
        self._append_unique(
            links,
            self._ref(
                kind="fork",
                identifier=fork_id,
                label=f"Fork {fork_id}",
                relation="child",
                available=True,
                href={
                    "view": "graph",
                    "fork_id": fork_id,
                    "run_id": child_run_id or "",
                },
            ),
        )
        if child_run_id:
            self._append_unique(
                links,
                self._ref(
                    kind="run",
                    identifier=child_run_id,
                    label=f"Child run {child_run_id}",
                    relation="child",
                    available=self._run_exists(child_run_id),
                    href={"view": "graph", "run_id": child_run_id},
                    reason=(
                        None
                        if self._run_exists(child_run_id)
                        else "child run is not present in this project"
                    ),
                ),
            )
        if child_chain_id:
            self._append_unique(
                links,
                self._chain_ref(
                    child_chain,
                    relation="child",
                    identifier=child_chain_id,
                ),
            )
        if child_session_id:
            self._append_unique(
                links,
                self._session_ref(child_session_id, relation="child"),
            )

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

    def _main_session_id(self, metadata: list[dict[str, Any]] | None = None) -> str:
        values = metadata if metadata is not None else self.repository.list_metadata()
        return next(
            (
                str(value["session_id"])
                for value in values
                if value.get("role") == "main" and value.get("session_id")
            ),
            "agent_main",
        )

    def _main_ref(self, *, relation: str) -> AgentNavigationRef:
        return self._session_ref(self._main_session_id(), relation=relation)

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

    def _proposal_ref(self, proposal_id: str, session_id: str) -> AgentNavigationRef:
        available = self._try_proposal(proposal_id) is not None
        return self._ref(
            kind="proposal",
            identifier=proposal_id,
            label=f"Proposal {proposal_id}",
            relation="audit",
            available=available,
            href={
                "view": "agent",
                "session_id": session_id,
                "proposal_id": proposal_id,
            },
            reason=None if available else "proposal record is missing",
        )

    def _diff_ref(self, record: OperationRecord) -> AgentNavigationRef | None:
        if record.diff_ref is None:
            return None
        kind = _optional_str(record.diff_ref.get("kind")) or "operation"
        return self._ref(
            kind="diff",
            identifier=record.record_id,
            label=f"Diff · {kind}",
            relation="result",
            available=True,
            href={
                "view": "agent",
                "session_id": record.agent_session_id,
                "operation_record_id": record.record_id,
                "diff": "1",
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
        key_hash: str | None = None
        if forest_node_key and "::" in forest_node_key:
            key_hash, forest_node_ref = forest_node_key.split("::", 1)
            # Both historical run_id::node_ref and the graph forest's
            # node_hash::node_ref selectors are valid typed references.
            if node_ref and forest_node_ref != node_ref:
                return None
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
                    indexed_hash = str(value["node_hash"])
                    if key_hash and key_hash not in {indexed_hash, run_id}:
                        return None
                    return indexed_hash
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

    @staticmethod
    def _navigation_forest_key(
        forest_node_key: str | None,
        node_hash: str | None,
        node_ref: str | None,
    ) -> str | None:
        """Project canonical durable keys into the browser's selector shape."""

        if forest_node_key and node_hash and node_ref and forest_node_key == node_hash:
            return f"{node_hash}::{node_ref}"
        return forest_node_key

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

    def _try_get_operation(self, record_id: str) -> OperationRecord | None:
        try:
            return self.operations.get(record_id)
        except (KeyError, ValueError):
            return None

    def _try_get_fork(self, fork_id: str) -> dict[str, Any] | None:
        try:
            return self.forks.get(fork_id)
        except (KeyError, ValueError):
            return None

    def _fork_records(self) -> Iterable[dict[str, Any]]:
        for path in sorted((self.workbench_root / "forks").glob("*.json")):
            try:
                record = self.forks.get(path.stem)
            except (KeyError, ValueError):
                continue
            yield record

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
