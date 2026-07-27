"""CF4 execution authorization control-plane primitives.

This module records a server-created, one-time authorization for the narrow
``confirm_and_execute`` option mode.  It deliberately stops before Draft, Run,
Graph, Artifact, process, or network handling.  Those consumers must claim
the durable receipt before they create any external side effect.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator, Mapping

from ..agent.storage import read_jsonl
from ..custom_capability.canonical import domain_digest


OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION = "OptionExecutionAuthorization@1.0"
_RECORD_TYPE = "option_execution_authorization"
_JOURNAL_NAME = "option-execution-authorizations.jsonl"
_MAX_TEXT = 512
_MAX_REASON = 256
_HEX = frozenset("0123456789abcdef")
_STATUSES = frozenset({"issued", "rejected", "claimed", "invalidated"})


class ExecutionAuthorizationError(ValueError):
    """Base class for fail-closed authorization errors."""

    code = "CAPABILITY_OPTION_EXECUTION_RECEIPT_INVALID"


class ExecutionAuthorizationReplay(ExecutionAuthorizationError):
    """The authorization or idempotency key was reused with another payload."""

    code = "CAPABILITY_OPTION_EXECUTION_REPLAY_MISMATCH"


class ExecutionAuthorizationRejected(ExecutionAuthorizationError):
    """The authorization could not be claimed and was durably rejected."""

    code = "CAPABILITY_OPTION_EXECUTION_REJECTED"


class ExecutionAuthorizationInvalidated(ExecutionAuthorizationRejected):
    """A claimed authorization lost its binding before dispatch reservation."""

    code = "CAPABILITY_OPTION_EXECUTION_INVALIDATED"


def _text(value: Any, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ExecutionAuthorizationError(f"{field} must be a bounded non-empty string")
    if any(ord(char) < 0x20 for char in value):
        raise ExecutionAuthorizationError(f"{field} contains a control character")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if (
        Path(text).name != text
        or text in {".", ".."}
        or "/" in text
        or "\\" in text
    ):
        raise ExecutionAuthorizationError(f"{field} must be path-safe")
    return text


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ExecutionAuthorizationError(f"{field} must be a positive integer")
    return value


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ExecutionAuthorizationError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _draft_hash(value: Any) -> str:
    text = _text(value, "draft_hash", maximum=71)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ExecutionAuthorizationError("draft_hash must be a sha256-prefixed digest")
    if any(char not in _HEX for char in text[7:]):
        raise ExecutionAuthorizationError("draft_hash must be a lowercase SHA-256 digest")
    return text


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExecutionAuthorizationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ExecutionAuthorizationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ExecutionAuthorizationError(f"{field} must be an ISO-8601 timestamp") from error
    return _utc(parsed, field)


@dataclass(frozen=True, slots=True)
class OptionExecutionAuthorization:
    """Immutable snapshot of an authorization and its current journal state."""

    authorization_id: str
    notebook_id: str
    option_id: str
    option_revision: int
    binding_revision: int
    capability_resolution_binding_ref: str
    materialization_id: str
    draft_id: str
    draft_hash: str
    run_intent_id: str
    capability_ref: str
    bundle_ref: str
    evidence_ref: str
    admission_ref: str
    runtime_policy_ref: str
    freshness_cursor_ref: str
    input_graph_fingerprint: str
    freshness_dependency_fingerprint: str
    operation_id: str
    execution_mode: str
    risk_level: str
    artifact_contract_ref: str
    consumer_projection_ref: str
    idempotency_key: str
    issued_at: datetime
    expires_at: datetime
    status: str = "issued"
    claim_owner_id: str | None = None
    lease_epoch: int | None = None
    lease_expires_at: datetime | None = None
    rejection_reason: str | None = None

    _KEYS = frozenset(
        {
            "contract_version",
            "authorization_id",
            "notebook_id",
            "option_id",
            "option_revision",
            "binding_revision",
            "capability_resolution_binding_ref",
            "materialization_id",
            "draft_id",
            "draft_hash",
            "run_intent_id",
            "capability_ref",
            "bundle_ref",
            "evidence_ref",
            "admission_ref",
            "runtime_policy_ref",
            "freshness_cursor_ref",
            "input_graph_fingerprint",
            "freshness_dependency_fingerprint",
            "operation_id",
            "execution_mode",
            "risk_level",
            "artifact_contract_ref",
            "consumer_projection_ref",
            "idempotency_key",
            "issued_at",
            "expires_at",
            "status",
            "claim_owner_id",
            "lease_epoch",
            "lease_expires_at",
            "rejection_reason",
            "payload_digest",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorization_id", _identifier(self.authorization_id, "authorization_id"))
        for field in (
            "notebook_id",
            "option_id",
            "materialization_id",
            "draft_id",
            "run_intent_id",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, "option_revision", _positive_int(self.option_revision, "option_revision"))
        object.__setattr__(self, "binding_revision", _positive_int(self.binding_revision, "binding_revision"))
        for field in (
            "capability_resolution_binding_ref",
            "capability_ref",
            "bundle_ref",
            "evidence_ref",
            "admission_ref",
            "runtime_policy_ref",
            "freshness_cursor_ref",
            "artifact_contract_ref",
            "consumer_projection_ref",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(self, "draft_hash", _draft_hash(self.draft_hash))
        object.__setattr__(self, "input_graph_fingerprint", _text(self.input_graph_fingerprint, "input_graph_fingerprint"))
        object.__setattr__(self, "freshness_dependency_fingerprint", _text(self.freshness_dependency_fingerprint, "freshness_dependency_fingerprint"))
        object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id"))
        if self.execution_mode != "confirm_and_execute":
            raise ExecutionAuthorizationError(
                "execution_mode must be confirm_and_execute for this authorization"
            )
        if self.risk_level != "low":
            raise ExecutionAuthorizationError("only low-risk options may use confirm_and_execute")
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        issued_at = _utc(self.issued_at, "issued_at")
        expires_at = _utc(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise ExecutionAuthorizationError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        if self.status not in _STATUSES:
            raise ExecutionAuthorizationError(f"unsupported authorization status: {self.status}")
        if self.claim_owner_id is not None:
            object.__setattr__(self, "claim_owner_id", _identifier(self.claim_owner_id, "claim_owner_id"))
        if self.lease_epoch is not None:
            object.__setattr__(self, "lease_epoch", _positive_int(self.lease_epoch, "lease_epoch"))
        if self.lease_expires_at is not None:
            object.__setattr__(self, "lease_expires_at", _utc(self.lease_expires_at, "lease_expires_at"))
        if self.rejection_reason is not None:
            object.__setattr__(self, "rejection_reason", _text(self.rejection_reason, "rejection_reason", maximum=_MAX_REASON))
        if self.status == "issued" and any(
            value is not None
            for value in (self.claim_owner_id, self.lease_epoch, self.lease_expires_at, self.rejection_reason)
        ):
            raise ExecutionAuthorizationError("issued authorization cannot carry transition metadata")
        if self.status == "claimed":
            if self.claim_owner_id is None or self.lease_epoch is None or self.lease_expires_at is None:
                raise ExecutionAuthorizationError("claimed authorization requires lease metadata")
            if self.rejection_reason is not None:
                raise ExecutionAuthorizationError("claimed authorization cannot carry rejection_reason")
        if self.status == "rejected":
            if self.rejection_reason is None:
                raise ExecutionAuthorizationError("rejected authorization requires rejection_reason")
            if any(value is not None for value in (self.claim_owner_id, self.lease_epoch, self.lease_expires_at)):
                raise ExecutionAuthorizationError("rejected authorization cannot carry lease metadata")
        if self.status == "invalidated":
            if self.rejection_reason is None:
                raise ExecutionAuthorizationError("invalidated authorization requires rejection_reason")
            if self.claim_owner_id is None or self.lease_epoch is None or self.lease_expires_at is None:
                raise ExecutionAuthorizationError("invalidated authorization requires claim metadata")

    @property
    def contract_version(self) -> str:
        return OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "notebook_id": self.notebook_id,
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "binding_revision": self.binding_revision,
            "capability_resolution_binding_ref": self.capability_resolution_binding_ref,
            "materialization_id": self.materialization_id,
            "draft_id": self.draft_id,
            "draft_hash": self.draft_hash,
            "run_intent_id": self.run_intent_id,
            "capability_ref": self.capability_ref,
            "bundle_ref": self.bundle_ref,
            "evidence_ref": self.evidence_ref,
            "admission_ref": self.admission_ref,
            "runtime_policy_ref": self.runtime_policy_ref,
            "freshness_cursor_ref": self.freshness_cursor_ref,
            "input_graph_fingerprint": self.input_graph_fingerprint,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "operation_id": self.operation_id,
            "execution_mode": self.execution_mode,
            "risk_level": self.risk_level,
            "artifact_contract_ref": self.artifact_contract_ref,
            "consumer_projection_ref": self.consumer_projection_ref,
            "idempotency_key": self.idempotency_key,
            "issued_at": _time_text(self.issued_at),
            "expires_at": _time_text(self.expires_at),
        }

    @property
    def payload_digest(self) -> str:
        return domain_digest("workbench.capability_factory.option_execution_authorization/v1", self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "authorization_id": self.authorization_id,
            "status": self.status,
            "claim_owner_id": self.claim_owner_id,
            "lease_epoch": self.lease_epoch,
            "lease_expires_at": None if self.lease_expires_at is None else _time_text(self.lease_expires_at),
            "rejection_reason": self.rejection_reason,
            "payload_digest": self.payload_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptionExecutionAuthorization":
        if not isinstance(value, Mapping) or set(value) != cls._KEYS:
            raise ExecutionAuthorizationError("option execution authorization has an unknown or missing field")
        if value["contract_version"] != OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION:
            raise ExecutionAuthorizationError("contract_version is unsupported")
        result = cls(
            authorization_id=value["authorization_id"],
            notebook_id=value["notebook_id"],
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            binding_revision=value["binding_revision"],
            capability_resolution_binding_ref=value["capability_resolution_binding_ref"],
            materialization_id=value["materialization_id"],
            draft_id=value["draft_id"],
            draft_hash=value["draft_hash"],
            run_intent_id=value["run_intent_id"],
            capability_ref=value["capability_ref"],
            bundle_ref=value["bundle_ref"],
            evidence_ref=value["evidence_ref"],
            admission_ref=value["admission_ref"],
            runtime_policy_ref=value["runtime_policy_ref"],
            freshness_cursor_ref=value["freshness_cursor_ref"],
            input_graph_fingerprint=value["input_graph_fingerprint"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            operation_id=value["operation_id"],
            execution_mode=value["execution_mode"],
            risk_level=value["risk_level"],
            artifact_contract_ref=value["artifact_contract_ref"],
            consumer_projection_ref=value["consumer_projection_ref"],
            idempotency_key=value["idempotency_key"],
            issued_at=_parse_time(value["issued_at"], "issued_at"),
            expires_at=_parse_time(value["expires_at"], "expires_at"),
            status=value["status"],
            claim_owner_id=value["claim_owner_id"],
            lease_epoch=value["lease_epoch"],
            lease_expires_at=(
                None
                if value["lease_expires_at"] is None
                else _parse_time(value["lease_expires_at"], "lease_expires_at")
            ),
            rejection_reason=value["rejection_reason"],
        )
        if value["payload_digest"] != result.payload_digest:
            raise ExecutionAuthorizationError("option execution authorization payload digest mismatch")
        return result


class OptionExecutionAuthorizationStore:
    """Append-only journal with atomic idempotent issue and claim operations."""

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        create: bool = True,
    ) -> None:
        self.root = Path(root)
        self.directory = self.root / "option-execution-authorizations"
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = self.directory / _JOURNAL_NAME
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    def issue(self, authorization: OptionExecutionAuthorization) -> OptionExecutionAuthorization:
        if not isinstance(authorization, OptionExecutionAuthorization):
            raise ExecutionAuthorizationError("authorization must be OptionExecutionAuthorization")
        if authorization.status != "issued":
            raise ExecutionAuthorizationError("only issued authorizations can be stored")
        with self._lock, self._journal_lock():
            now = _utc(self._clock(), "clock")
            if authorization.issued_at > now or authorization.expires_at <= now:
                raise ExecutionAuthorizationRejected("authorization is outside its validity window")
            records = self._records()
            current_by_id = self._latest_by_id(records)
            existing_for_key = next(
                (
                    current
                    for current in current_by_id.values()
                    if current.idempotency_key == authorization.idempotency_key
                ),
                None,
            )
            if existing_for_key is not None:
                if existing_for_key.payload_digest != authorization.payload_digest:
                    raise ExecutionAuthorizationReplay(
                        "idempotency key is already bound to another payload"
                    )
                return existing_for_key
            existing = current_by_id.get(authorization.authorization_id)
            if existing is not None:
                if existing.payload_digest != authorization.payload_digest:
                    raise ExecutionAuthorizationReplay(
                        "authorization id is already bound to another payload"
                    )
                return existing
            self._append_locked(authorization)
            return authorization

    def read(self, authorization_id: str) -> OptionExecutionAuthorization:
        identifier = _identifier(authorization_id, "authorization_id")
        with self._lock:
            current = self._latest_by_id(self._records()).get(identifier)
        if current is None:
            raise KeyError(f"unknown option execution authorization: {identifier}")
        return current

    def history(self, authorization_id: str) -> tuple[OptionExecutionAuthorization, ...]:
        identifier = _identifier(authorization_id, "authorization_id")
        with self._lock:
            return tuple(
                record
                for record in self._records()
                if record.authorization_id == identifier
            )

    def claim(
        self,
        authorization_id: str,
        *,
        idempotency_key: str,
        current_binding_ref: str,
        current_freshness_cursor_ref: str,
        owner_id: str,
        lease_seconds: int,
    ) -> OptionExecutionAuthorization:
        identifier = _identifier(authorization_id, "authorization_id")
        key = _text(idempotency_key, "idempotency_key")
        binding = _digest(current_binding_ref, "current_binding_ref")
        freshness = _digest(current_freshness_cursor_ref, "current_freshness_cursor_ref")
        owner = _identifier(owner_id, "owner_id")
        lease = _positive_int(lease_seconds, "lease_seconds")

        with self._lock, self._journal_lock():
            current = self._latest_by_id(self._records()).get(identifier)
            if current is None:
                raise ExecutionAuthorizationRejected("authorization was not found")
            if current.idempotency_key != key:
                raise ExecutionAuthorizationReplay("idempotency key does not match authorization")
            if current.status == "claimed":
                if binding != current.capability_resolution_binding_ref:
                    invalidated = replace(current, status="invalidated", rejection_reason="binding")
                    self._append_locked(invalidated)
                    raise ExecutionAuthorizationInvalidated(
                        "authorization claim invalidated: binding"
                    )
                if freshness != current.freshness_cursor_ref:
                    invalidated = replace(current, status="invalidated", rejection_reason="freshness")
                    self._append_locked(invalidated)
                    raise ExecutionAuthorizationInvalidated(
                        "authorization claim invalidated: freshness"
                    )
                return current
            if current.status == "rejected":
                raise ExecutionAuthorizationRejected(
                    f"authorization was rejected: {current.rejection_reason}"
                )
            if current.status == "invalidated":
                raise ExecutionAuthorizationInvalidated(
                    f"authorization was invalidated: {current.rejection_reason}"
                )
            now = _utc(self._clock(), "clock")
            reason = None
            if now >= current.expires_at:
                reason = "expired"
            elif binding != current.capability_resolution_binding_ref:
                reason = "binding"
            elif freshness != current.freshness_cursor_ref:
                reason = "freshness"
            if reason is not None:
                rejected = replace(current, status="rejected", rejection_reason=reason)
                self._append_locked(rejected)
                raise ExecutionAuthorizationRejected(
                    f"authorization claim rejected: {reason}"
                )
            claimed = replace(
                current,
                status="claimed",
                claim_owner_id=owner,
                lease_epoch=1,
                lease_expires_at=now + timedelta(seconds=lease),
            )
            self._append_locked(claimed)
            return claimed

    def _records(self) -> list[OptionExecutionAuthorization]:
        if not self.journal.exists():
            return []
        values = read_jsonl(self.journal)
        records: list[OptionExecutionAuthorization] = []
        for value in values:
            if set(value) != {"record_type", "authorization"}:
                raise ExecutionAuthorizationError("authorization journal record shape is invalid")
            if value["record_type"] != _RECORD_TYPE:
                raise ExecutionAuthorizationError("authorization journal record type is invalid")
            records.append(OptionExecutionAuthorization.from_dict(value["authorization"]))
        return records

    @staticmethod
    def _latest_by_id(
        records: list[OptionExecutionAuthorization],
    ) -> dict[str, OptionExecutionAuthorization]:
        latest: dict[str, OptionExecutionAuthorization] = {}
        for record in records:
            latest[record.authorization_id] = record
        return latest

    def _append_locked(self, authorization: OptionExecutionAuthorization) -> None:
        existing = self.journal.read_bytes() if self.journal.exists() else b""
        value = {"record_type": _RECORD_TYPE, "authorization": authorization.to_dict()}
        line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.journal)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @contextmanager
    def _journal_lock(self) -> Iterator[None]:
        lock_path = self.directory / f".{_JOURNAL_NAME}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "ExecutionAuthorizationError",
    "ExecutionAuthorizationInvalidated",
    "ExecutionAuthorizationReplay",
    "ExecutionAuthorizationRejected",
    "OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION",
    "OptionExecutionAuthorization",
    "OptionExecutionAuthorizationStore",
]
