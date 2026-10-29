"""Shared execution identity and durable claim primitives for Agent operations."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock
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
    WorkbenchOrchestrator instance. A live holder retains its OS file lock
    until release; the JSON deadline governs recovery only after that lock is
    free, never takeover from a worker that is still running.
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
        self._lock = RLock()
        self._handle = None
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
        with self._lock:
            if self._handle is not None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._path.open("a+", encoding="utf-8")
            try:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise OperationClaimConflict(
                        "another operation is executing against the same Chain active head"
                    ) from exc
                handle.seek(0)
                raw = handle.read().strip()
                current = json.loads(raw) if raw else {}
                now = _now().timestamp()
                expires_at = float(current.get("expires_at", 0) or 0)
                if current.get("status") == "active" and expires_at > now:
                    if current.get("execution_key") == self.execution_key:
                        self._handle = handle
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
                self._handle = handle
            except BaseException:
                handle.close()
                raise

    def release(self) -> None:
        with self._lock:
            handle = self._handle
            if handle is None:
                return
            try:
                handle.seek(0)
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
                self._handle = None
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()


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
        project_root: Path | None = None,
    ) -> None:
        self.operation_store = operation_store
        self.project_root = project_root
        self.operation_registry = operation_registry
        self.handlers = handlers
        self.lease_owner = lease_owner
        self.failpoint = failpoint or NoopFailpoint()
        self.risk_authorization_store = risk_authorization_store

    async def execute(self, record_id: str) -> OperationRecord:
        record = self.operation_store.get(record_id)
        has_ar = record.operation_id == 'operation.multi_step' and any(
            step.get('operation_id') == 'iv.ar_confidence' for step in record.changes.get('steps', []))
        if has_ar:
            # Reuse this operation's caller cancellation and owned lifetime.
            # The math layer only receives a check; it imports no Agent state.
            from ..checks.ar_cancellation import cancellation_scope
            requested = Event()
            reason = []

            def request_cancel(error):
                if not requested.is_set():
                    reason.append(error)
                    requested.set()

            def check_cancel():
                if requested.is_set():
                    raise reason[0]

            with cancellation_scope(check_cancel):
                return await self._execute_draining(record_id, request_cancel=request_cancel)
        return await self._execute_draining(record_id)

    async def _execute_draining(self, record_id, *, request_cancel=None):
        # Cancelling an await on to_thread does not stop its native worker.
        # Keep the whole effect/commit/lease lifetime owned until it drains,
        # rather than cancelling the handler and releasing a still-live lease.
        # Exact AR additionally observes the same cancellation in its native
        # and root-certification loops. Other effects retain drain semantics.
        owned = asyncio.create_task(self._execute_owned(record_id))
        try:
            return await asyncio.shield(owned)
        except asyncio.CancelledError as error:
            if request_cancel is not None:
                request_cancel(error)
            while not owned.done():
                try:
                    await asyncio.shield(owned)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            # Retrieve a drained failure even when cancellation wins the
            # caller-facing outcome; no task exception should be abandoned.
            if not owned.cancelled():
                owned.exception()
            raise

    async def _execute_owned(self, record_id: str) -> OperationRecord:
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
        from ..operation_approvals import OperationApprovalStore

        OperationApprovalStore(self.operation_store.root).require_binding(
            record.execution.get("approval_id"), proposal_id=record.proposal_id,
            fingerprint=record.proposal_fingerprint, execution_key=key,
            reconcile=bool(record.execution.get("bindings")) or record.effect_status == "committed")
        first_dispatch = record.status == "pending" and not record.execution.get("execution_key")
        record = self.operation_store.claim_execution(
            record_id,
            execution_key=key,
            lease_owner=self.lease_owner,
        )
        self.failpoint.hit("after_claim", record)
        domain_lease: Any = None
        try:
            acquire_domain_lease = getattr(handler, "acquire_domain_lease", None)
            if acquire_domain_lease is not None:
                domain_lease = acquire_domain_lease(
                    record,
                    execution_key=key,
                )
                if inspect.isawaitable(domain_lease):
                    domain_lease = await domain_lease
            # Common to native operations and the CF4 handler. Check after
            # acquiring the domain lease so an undo cannot race dispatch.
            validate_session = getattr(handler, "validate_session", None)
            if validate_session is not None:
                validate_session(record)
            from .extension_runtime import dispatch_hooks
            hook_facts = {"operation_ids": sorted({record.operation_id, *(
                item["operation_id"] for item in record.changes.get("steps", []))}),
                "record_id": record.record_id}
            if self.project_root is not None and not record.execution.get("bindings") and record.effect_status != "committed":
                dispatch_hooks(self.project_root, "before_operation", hook_facts, key=key)
            admit_research = getattr(handler, "admit_research", None)
            if admit_research is not None:
                proof = admit_research(record, first_dispatch=first_dispatch)
                record = self.operation_store.append_status(record.record_id, record.status,
                    execution=merge_execution(record.execution, {"research_specification": proof}))
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
                OperationApprovalStore(self.operation_store.root).start(record.execution["approval_id"], execution_key=key)
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
            if effect.status not in {"completed", "failed"}:
                # Submission is a durable, non-terminal lifecycle state.  A
                # child run may still be queued/running after the effect ids
                # have been bound; recording that as a failed effect and a
                # complete projection makes the UI lie and prevents the
                # terminal observer from running during reconcile.
                nonterminal = self.operation_store.append_status(
                    record.record_id,
                    effect.status,
                    execution=record.execution,
                    outputs=effect.outputs,
                    diff_ref=effect.diff_ref,
                    verification=effect.verification,
                    error=effect.error,
                    effect_status="pending",
                    projection_status="pending",
                )
                return nonterminal
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
            return self._after_operation(terminal, key=key)
        except asyncio.CancelledError as exc:
            cancelled = self.operation_store.append_status(
                record.record_id, 'cancelled', execution=record.execution,
                error={'type': type(exc).__name__, 'message': str(exc)},
                effect_status='failed', projection_status='complete')
            publish_state = getattr(handler, 'publish_state', None)
            if publish_state is not None:
                published = publish_state(cancelled, phase='cancelled')
                if inspect.isawaitable(published):
                    await published
            raise
        except (InjectedOperationCrash, OperationClaimConflict):
            raise
        except Exception as exc:
            failure = OperationEffect(
                execution=record.execution,
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
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
                error=failure.error or {"type": type(exc).__name__, "message": str(exc)},
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
            return self._after_operation(failed, key=key)
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

    def _after_operation(self, record, *, key):
        if self.project_root is None:
            return record
        from .extension_runtime import dispatch_hooks
        from .extensions import ExtensionError
        try:
            dispatch_hooks(self.project_root, "after_operation",
                {"operation_ids": sorted({record.operation_id, *(
                    item["operation_id"] for item in record.changes.get("steps", []))}),
                 "record_id": record.record_id, "status": record.status}, key=key)
        except (ExtensionError, OSError):
            # An observer cannot change a committed success or the original failure.
            return self.operation_store.append_status(record.record_id, record.status,
                execution=merge_execution(record.execution, {"extension_hook_error": "after_operation"}))
        return record
