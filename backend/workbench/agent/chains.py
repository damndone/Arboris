"""Durable chain/fork provenance and the request-independent rerun seam."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Awaitable, Callable
from uuid import uuid4

from ..artifacts import read_json, write_json
from ..lineage.family import scan_family


class ChainHeadConflict(ValueError):
    """The caller supplied a head that differs from the durable chain head."""


class ChainHeadUnavailable(ValueError):
    """A managed chain does not currently have a usable active head."""


def legacy_family_anchor(runs_root: Path | str, run_id: str) -> str:
    """Return the deterministic family id used when adopting a legacy run."""

    family = scan_family(Path(runs_root), run_id)
    root_run_id = family.ancestors[-1] if family.ancestors else run_id
    return f"legacy-family:{root_run_id}"


def ensure_chain_root(
    workbench_root: Path | str,
    *,
    runs_root: Path | str,
    chain_id: str,
    active_head_run_id: str,
    agent_session_id: str,
) -> dict[str, Any]:
    """Create or validate the managed record for a Chain Agent session."""

    store = ChainStore(workbench_root)
    try:
        store.resolve_active_head(
            chain_id,
            requested_active_head_run_id=active_head_run_id,
        )
        return store.get(chain_id)
    except KeyError:
        return store.create_root(
            chain_id=chain_id,
            run_family_id=legacy_family_anchor(runs_root, active_head_run_id),
            active_head_run_id=active_head_run_id,
            agent_session_id=agent_session_id,
        )


@dataclass(frozen=True)
class RerunExecutionRequest:
    operation_id: str
    operation_version: str
    operation_record_id: str
    proposal_id: str
    source_chain_id: str
    source_session_id: str
    source_run_id: str
    source_node_ref: str
    context_version: str
    context_fingerprint: str
    owner_run_id: str
    op_node_id: str
    node_hash: str
    forest_node_key: str
    owner_resolution: str
    active_head_run_id: str
    changes: dict[str, Any]
    fork_id: str
    child_chain_id: str
    child_session_id: str
    execution_key: str = ""
    confirmed_payload_hash: str = ""
    executed_proposal_payload_hash: str = ""
    plan_hash: str = ""
    canonical_patch_hash: str = ""


@dataclass(frozen=True)
class RerunExecutionResult:
    target_run_id: str
    outputs: dict[str, Any] = field(default_factory=dict)
    diff_ref: dict[str, Any] | None = None
    verification: dict[str, Any] = field(default_factory=dict)


RerunExecutor = Callable[
    [RerunExecutionRequest],
    RerunExecutionResult | Awaitable[RerunExecutionResult],
]


class _JsonRecordStore:
    def __init__(self, root: Path | str, directory: str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.directory = self.root / directory
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, record_id: str) -> Path:
        if not record_id or Path(record_id).name != record_id:
            raise ValueError("record id must be a non-empty path-safe identifier")
        return self.directory / f"{record_id}.json"

    def get(self, record_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                value = read_json(self._path(record_id))
            except FileNotFoundError as exc:
                raise KeyError(f"unknown record: {record_id}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"record is not an object: {record_id}")
            return dict(value)

    def list_records(self) -> list[dict[str, Any]]:
        """Return stored records without creating the backing directory."""

        with self._lock:
            if not self.directory.exists():
                return []
            records: list[dict[str, Any]] = []
            for path in sorted(self.directory.glob("*.json")):
                value = read_json(path)
                if not isinstance(value, dict):
                    raise ValueError(f"record is not an object: {path.name}")
                records.append(dict(value))
            return records

    def _create(self, record_id: str, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            path = self._path(record_id)
            if path.exists():
                raise ValueError(f"record already exists: {record_id}")
            write_json(path, value)
            return dict(value)

    def _update(self, record_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            value = self.get(record_id)
            value.update(changes)
            write_json(self._path(record_id), value)
            return dict(value)


class ChainStore(_JsonRecordStore):
    """Project-local authoritative records for managed analysis chains."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        super().__init__(root, "chains", create=create)

    def create_root(
        self,
        *,
        chain_id: str,
        run_family_id: str,
        active_head_run_id: str,
        agent_session_id: str,
    ) -> dict[str, Any]:
        """Create the first managed record for a legacy-backed Chain session."""

        return self._create(
            chain_id,
            {
                "schema_version": "chain.v1",
                "chain_id": chain_id,
                "run_family_id": run_family_id,
                "parent_chain_id": None,
                "source_run_id": active_head_run_id,
                "source_node_ref": None,
                "fork_id": None,
                "agent_session_id": agent_session_id,
                "active_head_run_id": active_head_run_id,
                "status": "active",
            },
        )

    def resolve_active_head(
        self,
        chain_id: str,
        *,
        requested_active_head_run_id: str | None = None,
    ) -> str:
        """Read the durable head and optionally compare a caller's expectation."""

        record = self.get(chain_id)
        active_head = record.get("active_head_run_id")
        if not isinstance(active_head, str) or not active_head:
            raise ChainHeadUnavailable(f"chain has no active head: {chain_id}")
        if (
            requested_active_head_run_id is not None
            and requested_active_head_run_id != active_head
        ):
            raise ChainHeadConflict(
                f"active head mismatch for {chain_id}: "
                f"expected {active_head}, received {requested_active_head_run_id}"
            )
        return active_head

    def create_child(
        self,
        *,
        child_chain_id: str,
        source_chain_id: str,
        run_family_id: str,
        source_run_id: str,
        source_node_ref: str,
        fork_id: str,
        child_session_id: str,
    ) -> dict[str, Any]:
        return self._create(
            child_chain_id,
            {
                "schema_version": "chain.v1",
                "chain_id": child_chain_id,
                "run_family_id": run_family_id,
                "parent_chain_id": source_chain_id,
                "source_run_id": source_run_id,
                "source_node_ref": source_node_ref,
                "fork_id": fork_id,
                "child_session_id": child_session_id,
                "active_head_run_id": None,
                "status": "pending",
            },
        )

    def activate(self, chain_id: str, *, active_head_run_id: str) -> dict[str, Any]:
        return self._update(
            chain_id,
            active_head_run_id=active_head_run_id,
            status="active",
        )

    def fail(self, chain_id: str, *, error: dict[str, Any]) -> dict[str, Any]:
        return self._update(chain_id, status="failed", error=dict(error))


class ForkStore(_JsonRecordStore):
    """Project-local graph/session fork identity records."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        super().__init__(root, "forks", create=create)

    def create(
        self,
        *,
        fork_id: str | None = None,
        source_chain_id: str,
        source_node_ref: str,
        source_session_id: str,
        source_session_entry_id: str,
        inherited_context_fingerprint: str,
        child_chain_id: str,
        child_session_id: str,
    ) -> dict[str, Any]:
        fork_id = fork_id or f"fork_{uuid4().hex}"
        return self._create(
            fork_id,
            {
                "schema_version": "fork.v1",
                "fork_id": fork_id,
                "source_chain_id": source_chain_id,
                "source_node_ref": source_node_ref,
                "source_session_id": source_session_id,
                "source_session_entry_id": source_session_entry_id,
                "inherited_context_fingerprint": inherited_context_fingerprint,
                "child_chain_id": child_chain_id,
                "child_agent_id": child_session_id,
                "child_session_id": child_session_id,
                "graph_fork_node_id": f"fork:{fork_id}",
                "status": "planning",
            },
        )

    def activate(self, fork_id: str) -> dict[str, Any]:
        return self._update(fork_id, status="active")

    def fail(self, fork_id: str, *, error: dict[str, Any]) -> dict[str, Any]:
        return self._update(fork_id, status="failed", error=dict(error))
