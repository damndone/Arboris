"""Shared execution identity and durable claim primitives for Agent operations."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import fcntl

from .operations import OperationRecord, OperationRecordStore, OperationRegistry
from .risk import RiskAuthorizationRequired, RiskAuthorizationStore


class OperationClaimConflict(RuntimeError):
    """Raised when an operation cannot safely claim or bind an execution."""


class InjectedOperationCrash(RuntimeError):
    """A test-only failpoint exception that leaves the durable record recoverable."""


class ChainExecutionLease:
    """Project-local compare-and-swap lease for one Chain active head.

    Operation records prevent two executors from claiming the same proposal.
    This second key prevents two different proposals from mutating the same
    Chain head concurrently, even when each HTTP request constructs a fresh
    WorkbenchOrchestrator instance.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        chain_id: str,
        active_head_run_id: str,
        execution_key: str,
        lease_seconds: int = 300,
    ) -> None:
        self.root = Path(root)
        self.chain_id = chain_id
        self.active_head_run_id = active_head_run_id
        self.execution_key = execution_key
        self.lease_seconds = lease_seconds
        identity = json.dumps(
            {"chain_id": chain_id, "active_head_run_id": active_head_run_id},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        self._path = (
            self.root
            / "operation-records"
            / "chain-leases"
            / f"lease_{hashlib.sha256(identity).hexdigest()[:32]}.json"
        )

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                raw = handle.read().strip()
                current = json.loads(raw) if raw else {}
                now = _now().timestamp()
                expires_at = float(current.get("expires_at", 0) or 0)
                if current.get("status") == "active" and expires_at > now:
                    if current.get("execution_key") == self.execution_key:
                        return
                    raise OperationClaimConflict(
                        "another operation is executing against the same Chain active head"
                    )
                payload = {
                    "status": "active",
                    "chain_id": self.chain_id,
                    "active_head_run_id": self.active_head_run_id,
                    "execution_key": self.execution_key,
                    "claimed_at": _now().isoformat(),
                    "expires_at": now + self.lease_seconds,
                }
                handle.seek(0)
                handle.truncate()
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def release(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                raw = handle.read().strip()
                current = json.loads(raw) if raw else {}
                if current.get("execution_key") != self.execution_key:
                    return
                current.update({"status": "released", "released_at": _now().isoformat()})
                handle.seek(0)
                handle.truncate()
                json.dump(current, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def execution_key(*, proposal_id: str, revision: int, fingerprint: str) -> str:
    """Return a stable identity for one immutable proposal revision."""

    payload = json.dumps(
        {
            "proposal_id": proposal_id,
            "revision": revision,
            "fingerprint": fingerprint,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return f"exec_{hashlib.sha256(payload).hexdigest()[:32]}"


class OperationFailpoint(Protocol):
    def hit(self, point: str, record: OperationRecord) -> None:
        """Raise an injected crash at a named lifecycle boundary."""


class NoopFailpoint:
    def hit(self, point: str, record: OperationRecord) -> None:
        return None


@dataclass(frozen=True)
class OperationEffect:
    """Normalized effect binding returned by one operation handler."""

    outputs: dict[str, Any] = field(default_factory=dict)
    diff_ref: dict[str, Any] | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    error: dict[str, Any] | None = None


def merge_execution(
    current: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Merge execution metadata without losing previously bound effects."""

    merged = {**current, **updates}
    bindings = {
        **(current.get("bindings") or {}),
        **(updates.get("bindings") or {}),
    }
    if current.get("bindings") is not None or updates.get("bindings") is not None:
        merged["bindings"] = bindings
    return merged


class OperationHandler(Protocol):
    def acquire_domain_lease(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> Any: ...

    def release_domain_lease(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        lease: Any,
    ) -> None: ...

    async def execute(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        failpoint: OperationFailpoint,
    ) -> OperationEffect: ...

    async def reconcile(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        failpoint: OperationFailpoint,
    ) -> OperationEffect: ...

    async def commit_domain_state(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        effect: OperationEffect,
    ) -> OperationEffect: ...


class WorkbenchOperationLifecycle:
    """Dispatch registered operations through one idempotent lifecycle."""

    def __init__(
        self,
        *,
        operation_store: OperationRecordStore,
        operation_registry: OperationRegistry,
        handlers: dict[str, OperationHandler],
        lease_owner: str,
        failpoint: OperationFailpoint | None = None,
        risk_authorization_store: RiskAuthorizationStore | None = None,
    ) -> None:
        self.operation_store = operation_store
        self.operation_registry = operation_registry
        self.handlers = handlers
        self.lease_owner = lease_owner
        self.failpoint = failpoint or NoopFailpoint()
        self.risk_authorization_store = risk_authorization_store

    async def execute(self, record_id: str) -> OperationRecord:
        record = self.operation_store.get(record_id)
        definition = self.operation_registry.require(
            record.operation_id,
            record.operation_version,
        )
        handler = self.handlers[definition.executor_key]
        validate = getattr(handler, "validate", None)
        if validate is not None:
            validation = validate(record)
            if inspect.isawaitable(validation):
                await validation
        key = execution_key(
            proposal_id=record.proposal_id,
            revision=record.proposal_revision,
            fingerprint=record.proposal_fingerprint,
        )
        record = self.operation_store.claim_execution(
            record_id,
            execution_key=key,
            lease_owner=self.lease_owner,
        )
        self.failpoint.hit("after_claim", record)
        domain_lease: Any = None
        try:
            if definition.requires_risk_authorization:
                authorization_id = record.execution.get("risk_authorization_id")
                if not authorization_id or self.risk_authorization_store is None:
                    raise RiskAuthorizationRequired(
                        "high-risk operation requires a consumed risk authorization"
                    )
                self.risk_authorization_store.require_consumed(
                    str(authorization_id),
                    operation_id=record.operation_id,
                    operation_version=record.operation_version,
                    proposal_id=record.proposal_id,
                    revision=record.proposal_revision,
                    fingerprint=record.proposal_fingerprint,
                    session_id=record.agent_session_id,
                    chain_id=record.chain_id,
                    active_head_run_id=str(
                        record.preconditions.get("active_head_run_id") or ""
                    ),
                    execution_key=key,
                )
            acquire_domain_lease = getattr(handler, "acquire_domain_lease", None)
            if acquire_domain_lease is not None:
                domain_lease = acquire_domain_lease(
                    record,
                    execution_key=key,
                )
                if inspect.isawaitable(domain_lease):
                    domain_lease = await domain_lease
            prepare = getattr(handler, "prepare", None)
            if prepare is not None:
                prepared = prepare(
                    record,
                    execution_key=key,
                    failpoint=self.failpoint,
                )
                if inspect.isawaitable(prepared):
                    prepared = await prepared
                if not isinstance(prepared, OperationEffect):
                    raise TypeError("operation handler returned an invalid prepared effect")
                if prepared.execution:
                    record = self.operation_store.append_status(
                        record.record_id,
                        record.status,
                        execution=merge_execution(record.execution, prepared.execution),
                    )
            if record.execution.get("bindings"):
                effect = handler.reconcile(
                    record,
                    execution_key=key,
                    failpoint=self.failpoint,
                )
            else:
                self.failpoint.hit("before_child_effect", record)
                effect = handler.execute(
                    record,
                    execution_key=key,
                    failpoint=self.failpoint,
                )
            if inspect.isawaitable(effect):
                effect = await effect
            if not isinstance(effect, OperationEffect):
                raise TypeError("operation handler returned an invalid effect")
            if effect.execution:
                record = self.operation_store.append_status(
                    record.record_id,
                    record.status,
                    execution=merge_execution(record.execution, effect.execution),
                )
            if not record.execution.get("bindings"):
                self.failpoint.hit("after_child_effect", record)
                if effect.bindings:
                    record = self.operation_store.bind_effect(
                        record.record_id,
                        execution_key=key,
                        bindings=effect.bindings,
                    )
            self.failpoint.hit("after_effect_binding", record)
            publish_state = getattr(handler, "publish_state", None)
            if publish_state is not None:
                published = publish_state(record, phase="submitted")
                if inspect.isawaitable(published):
                    await published
            commit_domain_state = getattr(handler, "commit_domain_state", None)
            if effect.status in {"completed", "failed"} and commit_domain_state is not None:
                self.failpoint.hit("before_domain_commit", record)
                committed_effect = commit_domain_state(
                    record,
                    execution_key=key,
                    effect=effect,
                )
                if inspect.isawaitable(committed_effect):
                    committed_effect = await committed_effect
                if not isinstance(committed_effect, OperationEffect):
                    raise TypeError(
                        "operation handler returned an invalid committed effect"
                    )
                effect = committed_effect
                if effect.execution:
                    record = self.operation_store.append_status(
                        record.record_id,
                        record.status,
                        execution=merge_execution(record.execution, effect.execution),
                    )
                record = self.operation_store.append_status(
                    record.record_id,
                    record.status,
                    effect_status=(
                        "committed" if effect.status == "completed" else "failed"
                    ),
                    projection_status="pending",
                )
                self.failpoint.hit("after_domain_commit", record)
            self.failpoint.hit("before_terminal_reconcile", record)
            terminal_effect_status = (
                "committed" if effect.status == "completed" else "failed"
            )
            terminal = self.operation_store.append_status(
                record.record_id,
                effect.status,
                execution=record.execution,
                outputs=effect.outputs,
                diff_ref=effect.diff_ref,
                verification=effect.verification,
                error=effect.error,
                effect_status=terminal_effect_status,
                projection_status="complete",
            )
            observe_terminal = getattr(handler, "observe_terminal", None)
            if observe_terminal is not None and terminal.status in {"completed", "failed"}:
                observation = observe_terminal(terminal)
                if inspect.isawaitable(observation):
                    observation = await observation
                if observation:
                    if not isinstance(observation, dict):
                        raise TypeError("terminal observer must return a mapping")
                    terminal = self.operation_store.append_status(
                        terminal.record_id,
                        terminal.status,
                        outputs={**terminal.outputs, **observation},
                        execution=terminal.execution,
                        diff_ref=terminal.diff_ref,
                        verification=terminal.verification,
                        error=terminal.error,
                        effect_status=terminal.effect_status,
                        projection_status=terminal.projection_status,
                    )
            if publish_state is not None:
                published = publish_state(terminal, phase=terminal.status)
                if inspect.isawaitable(published):
                    await published
            return terminal
        except (InjectedOperationCrash, OperationClaimConflict):
            raise
        except Exception as exc:
            failure = OperationEffect(
                execution=record.execution,
                status="failed",
                error={"type": type(exc).__name__},
            )
            commit_domain_state = getattr(handler, "commit_domain_state", None)
            if commit_domain_state is not None:
                committed_failure = commit_domain_state(
                    record,
                    execution_key=key,
                    effect=failure,
                )
                if inspect.isawaitable(committed_failure):
                    committed_failure = await committed_failure
                if not isinstance(committed_failure, OperationEffect):
                    raise TypeError(
                        "operation handler returned an invalid failed effect"
                    )
                failure = committed_failure
                if failure.execution:
                    record = self.operation_store.append_status(
                        record.record_id,
                        record.status,
                        execution=merge_execution(record.execution, failure.execution),
                    )
            failed = self.operation_store.append_status(
                record.record_id,
                "failed",
                execution=record.execution,
                outputs=failure.outputs,
                diff_ref=failure.diff_ref,
                verification=failure.verification,
                error=failure.error or {"type": type(exc).__name__},
                effect_status=(
                    record.effect_status
                    if record.effect_status != "pending"
                    else "failed"
                ),
                projection_status="failed",
            )
            publish_state = getattr(handler, "publish_state", None)
            if publish_state is not None:
                published = publish_state(failed, phase="failed")
                if inspect.isawaitable(published):
                    await published
            return failed
        finally:
            release_domain_lease = getattr(handler, "release_domain_lease", None)
            if domain_lease is not None and release_domain_lease is not None:
                released = release_domain_lease(
                    record,
                    execution_key=key,
                    lease=domain_lease,
                )
                if inspect.isawaitable(released):
                    await released
