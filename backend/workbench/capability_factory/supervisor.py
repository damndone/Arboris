"""Execution-free supervisor contracts for one reserved capability attempt.

This module is the boundary between a future trusted executor and the CF4
control plane.  It records identity and lifecycle facts, but it deliberately
does not start a process, inspect a host, open a socket, or persist anything.
The later supervisor may consume these contracts only after it supplies an
independently attested handle or quiescence proof.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl
from pathlib import Path
from typing import Any, ClassVar, Mapping

from ..agent.storage import append_jsonl_atomic, read_jsonl
from ..custom_capability.canonical import domain_digest
from .dispatch import DispatchReservation


EXECUTION_ATTEMPT_CONTRACT_VERSION = "ExecutionAttemptRecord@1.0"
QUIESCENCE_PROOF_CONTRACT_VERSION = "AttemptQuiescenceProof@1.0"
QUIESCENCE_ASSESSMENT_CONTRACT_VERSION = "QuiescenceAssessment@1.0"
_HEX = frozenset("0123456789abcdef")
_STATUSES = frozenset(
    {
        "reserved",
        "spawn_requested",
        "spawn_acknowledged",
        "running",
        "terminated",
        "dispatch_unknown",
        "failed",
        "consumed",
    }
)
_TRANSITIONS = {
    "reserved": frozenset({"spawn_requested", "dispatch_unknown", "failed"}),
    "spawn_requested": frozenset({"spawn_acknowledged", "dispatch_unknown", "failed"}),
    "spawn_acknowledged": frozenset({"running", "dispatch_unknown", "failed"}),
    "running": frozenset({"terminated", "dispatch_unknown", "failed"}),
    "terminated": frozenset({"consumed", "failed"}),
    "dispatch_unknown": frozenset(),
    "failed": frozenset(),
    "consumed": frozenset(),
}
_HANDLE_REQUIRED = frozenset({"spawn_acknowledged", "running", "terminated", "consumed"})
_PROOF_KINDS = frozenset({"not_spawned", "terminated_clean"})
_PROOF_ISSUER_ROLES = frozenset({"trusted_supervisor", "trusted_containment"})


class SupervisorStateError(ValueError):
    """Raised whenever a supervisor contract cannot be trusted."""


class DurableSupervisorError(SupervisorStateError):
    """Raised when the supervisor journal cannot be replayed safely."""


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SupervisorStateError(f"{field} must be a bounded non-empty string")
    if any(ord(char) < 0x20 for char in value):
        raise SupervisorStateError(f"{field} contains a control character")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise SupervisorStateError(f"{field} must be path-safe")
    return text


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise SupervisorStateError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _epoch(value: Any, field: str = "lease_epoch") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SupervisorStateError(f"{field} must be a positive integer")
    return value


def _revision(value: Any, field: str = "state_revision") -> int:
    return _epoch(value, field)


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SupervisorStateError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return _time(value, "timestamp").isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SupervisorStateError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SupervisorStateError(f"{field} must be an ISO-8601 timestamp") from error
    return _time(parsed, field)


def _optional_identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


@dataclass(frozen=True, slots=True)
class ExecutionAttemptRecord:
    """Content-addressed state for exactly one reserved execution attempt."""

    attempt_id: str
    reservation_id: str
    authorization_id: str
    authorization_payload_digest: str
    intent_id: str
    intent_digest: str
    run_id: str
    executor_idempotency_key: str
    lease_epoch: int
    status: str
    process_handle_ref: str | None
    state_revision: int
    lease_owner_id: str | None
    transition_id: str
    prior_state_digest: str
    transition_reason: str

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "attempt_id",
        "reservation_id",
        "authorization_id",
        "authorization_payload_digest",
        "intent_id",
        "intent_digest",
        "run_id",
        "executor_idempotency_key",
        "lease_epoch",
        "status",
        "process_handle_ref",
        "state_revision",
        "lease_owner_id",
        "transition_id",
        "prior_state_digest",
        "transition_reason",
    )

    def __post_init__(self) -> None:
        for field in (
            "attempt_id",
            "reservation_id",
            "authorization_id",
            "intent_id",
            "run_id",
            "executor_idempotency_key",
            "transition_id",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        for field in ("authorization_payload_digest", "intent_digest", "prior_state_digest"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(self, "lease_epoch", _epoch(self.lease_epoch))
        object.__setattr__(self, "state_revision", _revision(self.state_revision))
        object.__setattr__(self, "status", _identifier(self.status, "status"))
        if self.status not in _STATUSES:
            raise SupervisorStateError("status is unsupported")
        object.__setattr__(self, "process_handle_ref", _optional_identifier(self.process_handle_ref, "process_handle_ref"))
        object.__setattr__(self, "lease_owner_id", _optional_identifier(self.lease_owner_id, "lease_owner_id"))
        object.__setattr__(self, "transition_reason", _text(self.transition_reason, "transition_reason", maximum=256))
        if self.status in _HANDLE_REQUIRED and self.process_handle_ref is None:
            raise SupervisorStateError(f"{self.status} requires a process/job handle identity")
        if self.status in {"reserved", "spawn_requested"} and self.process_handle_ref is not None:
            raise SupervisorStateError(f"{self.status} cannot carry a process/job handle identity")
        if self.status == "reserved" and self.state_revision < 1:
            raise SupervisorStateError("reserved attempt must have a positive state revision")

    @classmethod
    def from_reservation(cls, reservation: DispatchReservation) -> "ExecutionAttemptRecord":
        if not isinstance(reservation, DispatchReservation):
            raise SupervisorStateError("reservation must be a DispatchReservation")
        return cls(
            attempt_id=reservation.attempt_id,
            reservation_id=reservation.reservation_id,
            authorization_id=reservation.authorization_id,
            authorization_payload_digest=reservation.authorization_payload_digest,
            intent_id=reservation.intent_id,
            intent_digest=reservation.intent_digest,
            run_id=reservation.run_id,
            executor_idempotency_key=reservation.executor_idempotency_key,
            lease_epoch=reservation.lease_epoch,
            status="reserved",
            process_handle_ref=None,
            state_revision=1,
            lease_owner_id=None,
            transition_id="reserved",
            prior_state_digest=reservation.content_digest,
            transition_reason="reservation recorded",
        )

    def _payload(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.execution_attempt/v1",
            {"contract_version": EXECUTION_ATTEMPT_CONTRACT_VERSION, **self._payload()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": EXECUTION_ATTEMPT_CONTRACT_VERSION,
            **self._payload(),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionAttemptRecord":
        if not isinstance(value, Mapping):
            raise SupervisorStateError("execution attempt must be an object")
        expected = {"contract_version", *cls._FIELDS, "content_digest"}
        if set(value) != expected or value["contract_version"] != EXECUTION_ATTEMPT_CONTRACT_VERSION:
            raise SupervisorStateError("execution attempt fields or version are invalid")
        try:
            result = cls(**{field: value[field] for field in cls._FIELDS})
        except (TypeError, ValueError) as error:
            if isinstance(error, SupervisorStateError):
                raise
            raise SupervisorStateError("execution attempt fields are invalid") from error
        if value["content_digest"] != result.content_digest:
            raise SupervisorStateError("execution attempt content digest mismatch")
        return result

    def transition(
        self,
        *,
        target_status: str,
        transition_id: str,
        owner_id: str,
        lease_epoch: int,
        reason: str,
        process_handle_ref: str | None = None,
    ) -> "ExecutionAttemptRecord":
        target = _identifier(target_status, "target_status")
        transition = _identifier(transition_id, "transition_id")
        owner = _identifier(owner_id, "owner_id")
        epoch = _epoch(lease_epoch)
        transition_reason = _text(reason, "reason", maximum=256)
        handle = _optional_identifier(process_handle_ref, "process_handle_ref")

        if epoch != self.lease_epoch:
            raise SupervisorStateError("lease epoch is stale")
        if self.lease_owner_id is not None and owner != self.lease_owner_id:
            raise SupervisorStateError("lease owner does not match current attempt")
        if transition == self.transition_id:
            if (
                target == self.status
                and owner == self.lease_owner_id
                and transition_reason == self.transition_reason
                and (handle is None or handle == self.process_handle_ref)
            ):
                return self
            raise SupervisorStateError("transition replay has a different payload")
        if target not in _STATUSES:
            raise SupervisorStateError("target status is unsupported")
        if target not in _TRANSITIONS[self.status]:
            raise SupervisorStateError(f"transition from {self.status} is terminal or invalid")
        if self.process_handle_ref is not None and handle not in {None, self.process_handle_ref}:
            raise SupervisorStateError("process/job handle identity cannot be replaced")
        if target in _HANDLE_REQUIRED and handle is None and self.process_handle_ref is None:
            raise SupervisorStateError(f"{target} requires a process/job handle identity")
        if target in {"reserved", "spawn_requested"} and handle is not None:
            raise SupervisorStateError(f"{target} cannot carry a process/job handle identity")
        return replace(
            self,
            status=target,
            process_handle_ref=self.process_handle_ref if self.process_handle_ref is not None else handle,
            state_revision=self.state_revision + 1,
            lease_owner_id=owner,
            transition_id=transition,
            prior_state_digest=self.content_digest,
            transition_reason=transition_reason,
        )

    def assess_quiescence(self, proof: "AttemptQuiescenceProof") -> "QuiescenceAssessment":
        if not isinstance(proof, AttemptQuiescenceProof):
            raise SupervisorStateError("quiescence proof is required")
        if self.status != "dispatch_unknown":
            raise SupervisorStateError("quiescence proof applies only to dispatch_unknown")
        if proof.attempt_id != self.attempt_id or proof.reservation_id != self.reservation_id:
            raise SupervisorStateError("quiescence proof does not match attempt identity")
        if proof.authorization_id != self.authorization_id:
            raise SupervisorStateError("quiescence proof does not match authorization")
        if proof.lease_epoch != self.lease_epoch:
            raise SupervisorStateError("quiescence proof has a stale lease epoch")
        if self.process_handle_ref is not None and proof.process_handle_ref != self.process_handle_ref:
            raise SupervisorStateError("quiescence proof handle does not match attempt")
        return QuiescenceAssessment(
            attempt_id=self.attempt_id,
            source_attempt_status=self.status,
            source_attempt_digest=self.content_digest,
            proof_digest=proof.content_digest,
            outcome="quiescent",
            release_isolation=True,
            requires_new_user_authorization=True,
            execution_allowed=False,
        )


@dataclass(frozen=True, slots=True)
class AttemptQuiescenceProof:
    """Independent supervisor/containment attestation for an unknown attempt."""

    proof_id: str
    attempt_id: str
    reservation_id: str
    authorization_id: str
    lease_epoch: int
    proof_kind: str
    process_handle_ref: str | None
    process_tree_digest: str
    resource_cleanup_digest: str
    output_cleanup_digest: str
    issued_by: str
    issuer_role: str
    issued_at: datetime
    authority_attestation_digest: str

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "proof_id",
        "attempt_id",
        "reservation_id",
        "authorization_id",
        "lease_epoch",
        "proof_kind",
        "process_handle_ref",
        "process_tree_digest",
        "resource_cleanup_digest",
        "output_cleanup_digest",
        "issued_by",
        "issuer_role",
        "issued_at",
        "authority_attestation_digest",
    )

    def __post_init__(self) -> None:
        for field in ("proof_id", "attempt_id", "reservation_id", "authorization_id", "issued_by"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, "lease_epoch", _epoch(self.lease_epoch))
        object.__setattr__(self, "proof_kind", _identifier(self.proof_kind, "proof_kind"))
        if self.proof_kind not in _PROOF_KINDS:
            raise SupervisorStateError("quiescence proof kind is unsupported")
        object.__setattr__(self, "issuer_role", _identifier(self.issuer_role, "issuer_role"))
        if self.issuer_role not in _PROOF_ISSUER_ROLES:
            raise SupervisorStateError("quiescence proof issuer role is not trusted")
        object.__setattr__(self, "process_handle_ref", _optional_identifier(self.process_handle_ref, "process_handle_ref"))
        if self.proof_kind == "terminated_clean" and self.process_handle_ref is None:
            raise SupervisorStateError("terminated_clean proof requires a process/job handle identity")
        if self.proof_kind == "not_spawned" and self.process_handle_ref is not None:
            raise SupervisorStateError("not_spawned proof cannot carry a process/job handle identity")
        for field in ("process_tree_digest", "resource_cleanup_digest", "output_cleanup_digest", "authority_attestation_digest"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(self, "issued_at", _time(self.issued_at, "issued_at"))

    def _payload(self) -> dict[str, Any]:
        payload = {field: getattr(self, field) for field in self._FIELDS}
        payload["issued_at"] = _time_text(self.issued_at)
        return payload

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.quiescence_proof/v1",
            {"contract_version": QUIESCENCE_PROOF_CONTRACT_VERSION, **self._payload()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": QUIESCENCE_PROOF_CONTRACT_VERSION,
            **self._payload(),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttemptQuiescenceProof":
        if not isinstance(value, Mapping):
            raise SupervisorStateError("quiescence proof must be an object")
        expected = {"contract_version", *cls._FIELDS, "content_digest"}
        if set(value) != expected or value["contract_version"] != QUIESCENCE_PROOF_CONTRACT_VERSION:
            raise SupervisorStateError("quiescence proof fields or version are invalid")
        try:
            result = cls(
                **{
                    **{field: value[field] for field in cls._FIELDS if field != "issued_at"},
                    "issued_at": _parse_time(value["issued_at"], "issued_at"),
                }
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, SupervisorStateError):
                raise
            raise SupervisorStateError("quiescence proof fields are invalid") from error
        if value["content_digest"] != result.content_digest:
            raise SupervisorStateError("quiescence proof content digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class QuiescenceAssessment:
    """Non-executing result of reconciling an unknown attempt."""

    attempt_id: str
    source_attempt_status: str
    source_attempt_digest: str
    proof_digest: str
    outcome: str
    release_isolation: bool
    requires_new_user_authorization: bool
    execution_allowed: bool

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "attempt_id",
        "source_attempt_status",
        "source_attempt_digest",
        "proof_digest",
        "outcome",
        "release_isolation",
        "requires_new_user_authorization",
        "execution_allowed",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _identifier(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "source_attempt_status", _identifier(self.source_attempt_status, "source_attempt_status"))
        object.__setattr__(self, "source_attempt_digest", _digest(self.source_attempt_digest, "source_attempt_digest"))
        object.__setattr__(self, "proof_digest", _digest(self.proof_digest, "proof_digest"))
        object.__setattr__(self, "outcome", _identifier(self.outcome, "outcome"))
        if self.source_attempt_status != "dispatch_unknown" or self.outcome != "quiescent":
            raise SupervisorStateError("assessment must reconcile a dispatch_unknown attempt")
        if self.release_isolation is not True or self.requires_new_user_authorization is not True:
            raise SupervisorStateError("quiescent assessment must require a fresh user authorization")
        if self.execution_allowed is not False:
            raise SupervisorStateError("quiescence assessment cannot authorize execution")
        for field in ("release_isolation", "requires_new_user_authorization", "execution_allowed"):
            if not isinstance(getattr(self, field), bool):
                raise SupervisorStateError(f"{field} must be boolean")

    def _payload(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.quiescence_assessment/v1",
            {"contract_version": QUIESCENCE_ASSESSMENT_CONTRACT_VERSION, **self._payload()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": QUIESCENCE_ASSESSMENT_CONTRACT_VERSION,
            **self._payload(),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuiescenceAssessment":
        if not isinstance(value, Mapping):
            raise SupervisorStateError("quiescence assessment must be an object")
        expected = {"contract_version", *cls._FIELDS, "content_digest"}
        if set(value) != expected or value["contract_version"] != QUIESCENCE_ASSESSMENT_CONTRACT_VERSION:
            raise SupervisorStateError("quiescence assessment fields or version are invalid")
        try:
            result = cls(**{field: value[field] for field in cls._FIELDS})
        except (TypeError, ValueError) as error:
            if isinstance(error, SupervisorStateError):
                raise
            raise SupervisorStateError("quiescence assessment fields are invalid") from error
        if value["content_digest"] != result.content_digest:
            raise SupervisorStateError("quiescence assessment content digest mismatch")
        return result


class DurableSupervisorStore:
    """Append-only supervisor state with deterministic crash recovery.

    The store persists complete immutable attempt revisions.  A restart loads
    the same attempt and handle identity; it never derives a new spawn key.
    This is a control-plane journal only: it does not start processes or
    inspect the host.  A trusted B1 executor remains the only component that
    can provide a handle or quiescence proof.
    """

    _RECORD_TYPE = "capability_execution_attempt"
    _JOURNAL_NAME = "supervisor-attempts.jsonl"

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.directory = self.root / "capability-supervisor"
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = self.directory / self._JOURNAL_NAME
        self._history: dict[str, list[ExecutionAttemptRecord]] = {}
        self._reload()

    def create(self, reservation: DispatchReservation) -> ExecutionAttemptRecord:
        if not isinstance(reservation, DispatchReservation):
            raise DurableSupervisorError("reservation must be a DispatchReservation")
        with self._locked():
            self._reload()
            history = self._history.get(reservation.attempt_id, [])
            if history:
                current = history[-1]
                if current.reservation_id != reservation.reservation_id:
                    raise DurableSupervisorError("attempt identity is already bound to another reservation")
                return current
            record = ExecutionAttemptRecord.from_reservation(reservation)
            self._append(record)
            self._history[record.attempt_id] = [record]
            return record

    def read(self, attempt_id: str) -> ExecutionAttemptRecord:
        history = self.history(attempt_id)
        if not history:
            raise DurableSupervisorError("execution attempt was not found")
        return history[-1]

    def history(self, attempt_id: str) -> tuple[ExecutionAttemptRecord, ...]:
        self._reload()
        return tuple(self._history.get(attempt_id, ()))

    def transition(
        self,
        attempt_id: str,
        *,
        target_status: str,
        transition_id: str,
        owner_id: str,
        lease_epoch: int,
        reason: str,
        process_handle_ref: str | None = None,
    ) -> ExecutionAttemptRecord:
        with self._locked():
            self._reload()
            current = self.read(attempt_id)
            next_record = current.transition(
                target_status=target_status,
                transition_id=transition_id,
                owner_id=owner_id,
                lease_epoch=lease_epoch,
                reason=reason,
                process_handle_ref=process_handle_ref,
            )
            if next_record == current:
                return current
            self._append(next_record)
            self._history.setdefault(attempt_id, []).append(next_record)
            return next_record

    def take_over_lease(
        self,
        attempt_id: str,
        *,
        owner_id: str,
        transition_id: str,
        reason: str = "lease takeover after supervisor recovery",
    ) -> ExecutionAttemptRecord:
        """Fence the previous worker while retaining the same attempt/handle."""

        with self._locked():
            self._reload()
            current = self.read(attempt_id)
            if current.status in {"dispatch_unknown", "failed", "consumed", "terminated"}:
                raise DurableSupervisorError("lease takeover is not valid for this attempt state")
            owner = _identifier(owner_id, "owner_id")
            transition = _identifier(transition_id, "transition_id")
            if transition == current.transition_id:
                if current.lease_owner_id == owner:
                    return current
                raise DurableSupervisorError("lease takeover replay has a different owner")
            next_record = replace(
                current,
                lease_epoch=current.lease_epoch + 1,
                state_revision=current.state_revision + 1,
                lease_owner_id=owner,
                transition_id=transition,
                prior_state_digest=current.content_digest,
                transition_reason=_text(reason, "reason", maximum=256),
            )
            self._append(next_record)
            self._history.setdefault(attempt_id, []).append(next_record)
            return next_record

    def assess_quiescence(
        self, attempt_id: str, proof: AttemptQuiescenceProof
    ) -> QuiescenceAssessment:
        return self.read(attempt_id).assess_quiescence(proof)

    def _reload(self) -> None:
        self._history = {}
        try:
            events = read_jsonl(self.journal)
        except (OSError, ValueError) as error:
            raise DurableSupervisorError("supervisor journal cannot be read") from error
        for index, event in enumerate(events, start=1):
            if set(event) != {"record_type", "attempt"} or event["record_type"] != self._RECORD_TYPE:
                raise DurableSupervisorError(f"supervisor journal event {index} has invalid fields")
            try:
                record = ExecutionAttemptRecord.from_dict(event["attempt"])
            except SupervisorStateError as error:
                raise DurableSupervisorError(f"supervisor attempt event {index} is invalid") from error
            history = self._history.setdefault(record.attempt_id, [])
            if not history:
                if record.status != "reserved" or record.state_revision != 1:
                    raise DurableSupervisorError("supervisor attempt history must start at reserved revision one")
            else:
                previous = history[-1]
                if record.prior_state_digest != previous.content_digest:
                    raise DurableSupervisorError("supervisor attempt history has a broken digest chain")
                if record.state_revision != previous.state_revision + 1:
                    raise DurableSupervisorError("supervisor attempt revisions are not contiguous")
                if record.reservation_id != previous.reservation_id or record.intent_digest != previous.intent_digest:
                    raise DurableSupervisorError("supervisor attempt identity changed across a revision")
            history.append(record)

    def _append(self, record: ExecutionAttemptRecord) -> None:
        append_jsonl_atomic(
            self.journal,
            {"record_type": self._RECORD_TYPE, "attempt": record.to_dict()},
        )

    @contextmanager
    def _locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / ".supervisor.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "AttemptQuiescenceProof",
    "EXECUTION_ATTEMPT_CONTRACT_VERSION",
    "ExecutionAttemptRecord",
    "DurableSupervisorError",
    "DurableSupervisorStore",
    "QUIESCENCE_ASSESSMENT_CONTRACT_VERSION",
    "QUIESCENCE_PROOF_CONTRACT_VERSION",
    "QuiescenceAssessment",
    "SupervisorStateError",
]
