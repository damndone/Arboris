"""Append-only mutable validity/control state for CF1."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ..custom_capability.canonical import domain_digest
from .contracts import _text


class OptimisticConcurrencyError(RuntimeError):
    """Raised when a control writer uses an old sequence."""


def _freeze(value: Any, *, depth: int = 0) -> Any:
    if depth > 16:
        raise ValueError("control value exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("control values must be finite")
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({_text(key, "control key"): _freeze(item, depth=depth + 1) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        if len(value) > 1024:
            raise ValueError("control sequence is too long")
        return tuple(_freeze(item, depth=depth + 1) for item in value)
    raise ValueError(f"unsupported control value: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ControlRecord:
    namespace: str
    sequence: int
    value: Mapping[str, Any]
    value_digest: str


class AppendOnlyControlStore:
    """Serializes writes while retaining every state revision."""

    def __init__(self) -> None:
        self._history: dict[str, list[ControlRecord]] = {}
        self._lock = RLock()

    def append(self, *, namespace: str, value: Mapping[str, Any], expected_sequence: int) -> ControlRecord:
        namespace = _text(namespace, "namespace")
        if not isinstance(expected_sequence, int) or isinstance(expected_sequence, bool) or expected_sequence < 0:
            raise ValueError("expected_sequence must be a non-negative integer")
        frozen = _freeze(value)
        if not isinstance(frozen, Mapping):
            raise ValueError("control value must be an object")
        with self._lock:
            history = self._history.setdefault(namespace, [])
            current_sequence = history[-1].sequence if history else 0
            if expected_sequence != current_sequence:
                raise OptimisticConcurrencyError(
                    f"namespace {namespace!r} is at sequence {current_sequence}, expected {expected_sequence}"
                )
            sequence = current_sequence + 1
            digest = domain_digest(
                "workbench.capability_factory.control/v1",
                {"namespace": namespace, "sequence": sequence, "value": _plain(frozen)},
            )
            record = ControlRecord(namespace, sequence, frozen, digest)
            history.append(record)
            return record

    def history(self, namespace: str) -> tuple[ControlRecord, ...]:
        return tuple(self._history.get(namespace, ()))

    def latest(self, namespace: str) -> ControlRecord | None:
        history = self._history.get(namespace)
        return history[-1] if history else None


class ExecutionControlError(ValueError):
    """Base class for fail-closed execution-control errors."""


class ControlCursorConflict(ExecutionControlError):
    """The caller supplied a cursor revision that is no longer current."""


class ControlSubjectRejected(ExecutionControlError):
    """The current subject cannot satisfy a control fence."""


class ControlSubjectExpired(ControlSubjectRejected):
    """The current subject was expired at the trusted comparison time."""


class ControlReplayMismatch(ExecutionControlError):
    """An idempotency key or record identity was reused with another request."""


def _control_identifier(value: Any, field: str, *, maximum: int = 512) -> str:
    text = _text(value, field)
    if len(text) > maximum or text in {".", ".."} or "/" in text or "\\" in text:
        raise ExecutionControlError(f"{field} must be a bounded path-safe identifier")
    return text


def _control_revision(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ExecutionControlError(f"{field} must be a positive integer")
    return value


def _control_sequence(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExecutionControlError(f"{field} must be a non-negative integer")
    return value


def _control_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ExecutionControlError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _control_time(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExecutionControlError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _control_time_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ControlSubjectCursor:
    """The trusted execution-control projection for one validity subject."""

    subject_kind: str
    subject_ref: str
    validity_revision: int
    status: str
    effective_at: datetime
    expires_at: datetime | None
    authority: str
    reason: str
    source_record_ref: str
    control_sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_kind", _control_identifier(self.subject_kind, "subject_kind"))
        object.__setattr__(self, "subject_ref", _control_identifier(self.subject_ref, "subject_ref"))
        object.__setattr__(self, "validity_revision", _control_revision(self.validity_revision, "validity_revision"))
        object.__setattr__(self, "status", _control_identifier(self.status, "status"))
        object.__setattr__(self, "effective_at", _control_time(self.effective_at, "effective_at"))
        if self.expires_at is not None:
            expires_at = _control_time(self.expires_at, "expires_at")
            if expires_at <= self.effective_at:
                raise ExecutionControlError("expires_at must be after effective_at")
            object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "authority", _control_identifier(self.authority, "authority"))
        object.__setattr__(self, "reason", _control_identifier(self.reason, "reason"))
        object.__setattr__(self, "source_record_ref", _control_identifier(self.source_record_ref, "source_record_ref"))
        object.__setattr__(self, "control_sequence", _control_sequence(self.control_sequence, "control_sequence"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "validity_revision": self.validity_revision,
            "status": self.status,
            "effective_at": _control_time_text(self.effective_at),
            "expires_at": _control_time_text(self.expires_at),
            "authority": self.authority,
            "reason": self.reason,
            "source_record_ref": self.source_record_ref,
            "control_sequence": self.control_sequence,
        }

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.control.subject_cursor/v1", self.to_dict())


@dataclass(frozen=True, slots=True)
class ControlCursorExpectation:
    """The exact current cursor a serialized control operation requires."""

    subject_kind: str
    subject_ref: str
    validity_revision: int
    expected_status: str
    require_unexpired: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_kind", _control_identifier(self.subject_kind, "subject_kind"))
        object.__setattr__(self, "subject_ref", _control_identifier(self.subject_ref, "subject_ref"))
        object.__setattr__(self, "validity_revision", _control_revision(self.validity_revision, "validity_revision"))
        object.__setattr__(self, "expected_status", _control_identifier(self.expected_status, "expected_status"))
        if not isinstance(self.require_unexpired, bool):
            raise ExecutionControlError("require_unexpired must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "validity_revision": self.validity_revision,
            "expected_status": self.expected_status,
            "require_unexpired": self.require_unexpired,
        }


@dataclass(frozen=True, slots=True)
class ControlAppendRequest:
    """Caller-provided immutable record payload; the store supplies its sequence."""

    record_id: str
    record_type: str
    value: Mapping[str, Any]
    idempotency_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _control_identifier(self.record_id, "record_id"))
        object.__setattr__(self, "record_type", _control_identifier(self.record_type, "record_type"))
        object.__setattr__(self, "idempotency_key", _control_identifier(self.idempotency_key, "idempotency_key"))
        frozen = _freeze(self.value)
        if not isinstance(frozen, Mapping):
            raise ExecutionControlError("control append value must be an object")
        object.__setattr__(self, "value", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "value": _plain(self.value),
            "idempotency_key": self.idempotency_key,
        }

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.control.append_request/v1", self.to_dict())


@dataclass(frozen=True, slots=True)
class ExecutionControlRecord:
    """One immutable record and the cursor snapshot that authorized it."""

    control_sequence: int
    request: ControlAppendRequest
    subject_snapshot: tuple[ControlSubjectCursor, ...]
    request_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "control_sequence", _control_sequence(self.control_sequence, "control_sequence"))
        if self.control_sequence < 1:
            raise ExecutionControlError("execution control records start at sequence one")
        if not isinstance(self.request, ControlAppendRequest):
            raise ExecutionControlError("request must be a ControlAppendRequest")
        if not self.subject_snapshot:
            raise ExecutionControlError("subject_snapshot must not be empty")
        object.__setattr__(self, "request_digest", _control_digest(self.request_digest, "request_digest"))

    @property
    def record_digest(self) -> str:
        return self.request.content_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_sequence": self.control_sequence,
            "request": self.request.to_dict(),
            "subject_snapshot": [cursor.to_dict() for cursor in self.subject_snapshot],
            "request_digest": self.request_digest,
            "record_digest": self.record_digest,
        }


class ExecutionControlStore:
    """In-memory serializable control stream used by CF1 and future dispatch consumers.

    Subject publication and compare-plus-append share one lock and one global
    sequence. A successful append therefore has a linearization point that can
    be ordered against revocation or expiry publication without a read-then-
    write gap. This class intentionally has no Run, process, or network code.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._control_sequence = 0
        self._subject_history: dict[tuple[str, str], list[ControlSubjectCursor]] = {}
        self._records: list[ExecutionControlRecord] = []
        self._records_by_id: dict[str, ExecutionControlRecord] = {}
        self._records_by_idempotency: dict[str, ExecutionControlRecord] = {}

    @property
    def control_sequence(self) -> int:
        with self._lock:
            return self._control_sequence

    def publish_subject(
        self,
        cursor: ControlSubjectCursor,
        *,
        expected_validity_revision: int | None = None,
    ) -> ControlSubjectCursor:
        if not isinstance(cursor, ControlSubjectCursor):
            raise ExecutionControlError("cursor must be a ControlSubjectCursor")
        if cursor.control_sequence != 0:
            raise ExecutionControlError("caller cannot provide control_sequence")
        key = (cursor.subject_kind, cursor.subject_ref)
        with self._lock:
            history = self._subject_history.setdefault(key, [])
            current = history[-1] if history else None
            current_revision = current.validity_revision if current is not None else 0
            if expected_validity_revision is not None:
                if not isinstance(expected_validity_revision, int) or isinstance(expected_validity_revision, bool):
                    raise ExecutionControlError("expected_validity_revision must be an integer")
                if expected_validity_revision != current_revision:
                    raise ControlCursorConflict(
                        f"{key!r} is at validity revision {current_revision}, expected {expected_validity_revision}"
                    )
            if cursor.validity_revision < current_revision:
                raise ControlCursorConflict(f"{key!r} cannot move to an older validity revision")
            if current is not None and cursor.validity_revision == current.validity_revision:
                if cursor.to_dict() == {**current.to_dict(), "control_sequence": 0}:
                    return current
                raise ControlCursorConflict(f"{key!r} already has another record at this validity revision")
            self._control_sequence += 1
            stored = replace(cursor, control_sequence=self._control_sequence)
            history.append(stored)
            return stored

    def latest_subject(self, subject_kind: str, subject_ref: str) -> ControlSubjectCursor | None:
        key = (
            _control_identifier(subject_kind, "subject_kind"),
            _control_identifier(subject_ref, "subject_ref"),
        )
        with self._lock:
            history = self._subject_history.get(key)
            return history[-1] if history else None

    def subject_history(self, subject_kind: str, subject_ref: str) -> tuple[ControlSubjectCursor, ...]:
        key = (
            _control_identifier(subject_kind, "subject_kind"),
            _control_identifier(subject_ref, "subject_ref"),
        )
        with self._lock:
            return tuple(self._subject_history.get(key, ()))

    def compare_cursors_and_append(
        self,
        *,
        expectations: tuple[ControlCursorExpectation, ...] | list[ControlCursorExpectation],
        record: ControlAppendRequest,
        now: datetime | None = None,
    ) -> ExecutionControlRecord:
        if not isinstance(record, ControlAppendRequest):
            raise ExecutionControlError("record must be a ControlAppendRequest")
        expected = tuple(expectations)
        if not expected:
            raise ExecutionControlError("at least one subject expectation is required")
        if any(not isinstance(item, ControlCursorExpectation) for item in expected):
            raise ExecutionControlError("expectations must contain ControlCursorExpectation values")
        keys = [(item.subject_kind, item.subject_ref) for item in expected]
        if len(set(keys)) != len(keys):
            raise ExecutionControlError("subject expectations must be unique")
        comparison_time = _control_time(now if now is not None else self._clock(), "now")
        request_digest = domain_digest(
            "workbench.capability_factory.control.compare_append/v1",
            {"record": record.to_dict(), "expectations": [item.to_dict() for item in expected]},
        )
        with self._lock:
            existing_by_key = self._records_by_idempotency.get(record.idempotency_key)
            if existing_by_key is not None:
                if existing_by_key.request_digest != request_digest:
                    raise ControlReplayMismatch("idempotency key is already bound to another request")
                return existing_by_key
            existing_by_id = self._records_by_id.get(record.record_id)
            if existing_by_id is not None:
                if existing_by_id.request_digest != request_digest:
                    raise ControlReplayMismatch("record_id is already bound to another request")
                return existing_by_id

            snapshots: list[ControlSubjectCursor] = []
            for item in expected:
                current = self._subject_history.get((item.subject_kind, item.subject_ref), ())
                cursor = current[-1] if current else None
                if cursor is None:
                    raise ControlSubjectRejected(f"subject {item.subject_kind}:{item.subject_ref} is unavailable")
                if cursor.validity_revision != item.validity_revision:
                    raise ControlCursorConflict(
                        f"subject {item.subject_kind}:{item.subject_ref} is at revision "
                        f"{cursor.validity_revision}, expected {item.validity_revision}"
                    )
                if cursor.status != item.expected_status:
                    raise ControlSubjectRejected(
                        f"subject {item.subject_kind}:{item.subject_ref} has status {cursor.status!r}"
                    )
                if cursor.effective_at > comparison_time:
                    raise ControlSubjectRejected(
                        f"subject {item.subject_kind}:{item.subject_ref} is not effective yet"
                    )
                if item.require_unexpired and cursor.expires_at is not None and cursor.expires_at <= comparison_time:
                    raise ControlSubjectExpired(
                        f"subject {item.subject_kind}:{item.subject_ref} expired before compare"
                    )
                snapshots.append(cursor)

            self._control_sequence += 1
            result = ExecutionControlRecord(
                control_sequence=self._control_sequence,
                request=record,
                subject_snapshot=tuple(snapshots),
                request_digest=request_digest,
            )
            self._records.append(result)
            self._records_by_id[record.record_id] = result
            self._records_by_idempotency[record.idempotency_key] = result
            return result

    def records(self) -> tuple[ExecutionControlRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def latest_record(self) -> ExecutionControlRecord | None:
        with self._lock:
            return self._records[-1] if self._records else None


__all__ = [
    "AppendOnlyControlStore",
    "ControlAppendRequest",
    "ControlCursorExpectation",
    "ControlCursorConflict",
    "ControlRecord",
    "ControlSubjectCursor",
    "ControlSubjectExpired",
    "ControlSubjectRejected",
    "ControlReplayMismatch",
    "ExecutionControlError",
    "ExecutionControlRecord",
    "ExecutionControlStore",
    "OptimisticConcurrencyError",
]
