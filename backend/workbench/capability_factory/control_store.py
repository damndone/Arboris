"""Durable backing for the generic Capability Factory control fence."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from ..agent.storage import read_jsonl
from .control import (
    ControlAppendRequest,
    ControlCursorExpectation,
    ControlSubjectCursor,
    ExecutionControlRecord,
    ExecutionControlStore,
)


_JOURNAL_NAME = "control-stream.jsonl"
_SUBJECT_EVENT = "subject_cursor"
_RECORD_EVENT = "execution_control"


class DurableControlStoreError(ValueError):
    """Raised when the durable control journal cannot be trusted."""


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise DurableControlStoreError(f"{field} must be an ISO-8601 timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DurableControlStoreError(f"{field} must be an ISO-8601 timestamp") from error


class DurableExecutionControlStore(ExecutionControlStore):
    """File-backed control stream with lock-covered replay and append.

    Every state-changing call takes the journal lock, rehydrates the entire
    append-only stream, performs the inherited serialized operation, and only
    then writes one event. This keeps the compare/read/append interval atomic
    across independent processes and makes restart recovery deterministic.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        create: bool = True,
    ) -> None:
        super().__init__(clock=clock)
        self.root = Path(root)
        self.directory = self.root / "execution-control"
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = self.directory / _JOURNAL_NAME
        with self._lock, self._journal_lock(create=False):
            self._load_locked()

    @property
    def control_sequence(self) -> int:
        with self._lock, self._journal_lock(create=False):
            self._load_locked()
            return super().control_sequence

    def publish_subject(
        self,
        cursor: ControlSubjectCursor,
        *,
        expected_validity_revision: int | None = None,
    ) -> ControlSubjectCursor:
        with self._lock, self._journal_lock():
            self._load_locked()
            previous_sequence = self._control_sequence
            result = super().publish_subject(
                cursor,
                expected_validity_revision=expected_validity_revision,
            )
            if self._control_sequence != previous_sequence:
                self._append_event_locked({"record_type": _SUBJECT_EVENT, "cursor": result.to_dict()})
            return result

    def compare_cursors_and_append(
        self,
        *,
        expectations: tuple[ControlCursorExpectation, ...] | list[ControlCursorExpectation],
        record: ControlAppendRequest,
        now: datetime | None = None,
    ) -> ExecutionControlRecord:
        with self._lock, self._journal_lock():
            self._load_locked()
            previous_sequence = self._control_sequence
            result = super().compare_cursors_and_append(
                expectations=expectations,
                record=record,
                now=now,
            )
            if self._control_sequence != previous_sequence:
                self._append_event_locked({"record_type": _RECORD_EVENT, "record": result.to_dict()})
            return result

    def latest_subject(self, subject_kind: str, subject_ref: str) -> ControlSubjectCursor | None:
        with self._lock, self._journal_lock(create=False):
            self._load_locked()
            return super().latest_subject(subject_kind, subject_ref)

    def subject_history(self, subject_kind: str, subject_ref: str) -> tuple[ControlSubjectCursor, ...]:
        with self._lock, self._journal_lock(create=False):
            self._load_locked()
            return super().subject_history(subject_kind, subject_ref)

    def records(self) -> tuple[ExecutionControlRecord, ...]:
        with self._lock, self._journal_lock(create=False):
            self._load_locked()
            return super().records()

    def latest_record(self) -> ExecutionControlRecord | None:
        with self._lock, self._journal_lock(create=False):
            self._load_locked()
            return super().latest_record()

    def _load_locked(self) -> None:
        self._control_sequence = 0
        self._subject_history = {}
        self._records = []
        self._records_by_id = {}
        self._records_by_idempotency = {}
        try:
            events = read_jsonl(self.journal)
        except (OSError, ValueError) as error:
            raise DurableControlStoreError("control journal cannot be read") from error

        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict) or "record_type" not in event:
                raise DurableControlStoreError(f"control journal event {index} has invalid shape")
            record_type = event["record_type"]
            if record_type == _SUBJECT_EVENT:
                if set(event) != {"record_type", "cursor"}:
                    raise DurableControlStoreError(f"subject event {index} has invalid fields")
                cursor = self._cursor_from_dict(event["cursor"])
                if cursor.control_sequence != self._control_sequence + 1:
                    raise DurableControlStoreError("control sequence is not strictly monotonic")
                key = (cursor.subject_kind, cursor.subject_ref)
                history = self._subject_history.setdefault(key, [])
                if history:
                    previous = history[-1]
                    if cursor.validity_revision <= previous.validity_revision:
                        raise DurableControlStoreError("subject validity revisions are not strictly increasing")
                history.append(cursor)
                self._control_sequence = cursor.control_sequence
                continue
            if record_type == _RECORD_EVENT:
                if set(event) != {"record_type", "record"}:
                    raise DurableControlStoreError(f"execution event {index} has invalid fields")
                record = self._record_from_dict(event["record"])
                if record.control_sequence != self._control_sequence + 1:
                    raise DurableControlStoreError("control sequence is not strictly monotonic")
                if record.request.record_id in self._records_by_id:
                    raise DurableControlStoreError("duplicate control record id")
                if record.request.idempotency_key in self._records_by_idempotency:
                    raise DurableControlStoreError("duplicate control idempotency key")
                self._records.append(record)
                self._records_by_id[record.request.record_id] = record
                self._records_by_idempotency[record.request.idempotency_key] = record
                self._control_sequence = record.control_sequence
                continue
            raise DurableControlStoreError(f"unsupported control journal event: {record_type!r}")

    @staticmethod
    def _cursor_from_dict(value: Any) -> ControlSubjectCursor:
        if not isinstance(value, dict):
            raise DurableControlStoreError("subject cursor is not an object")
        expected = {
            "subject_kind",
            "subject_ref",
            "validity_revision",
            "status",
            "effective_at",
            "expires_at",
            "authority",
            "reason",
            "source_record_ref",
            "control_sequence",
        }
        if set(value) != expected:
            raise DurableControlStoreError("subject cursor fields are invalid")
        try:
            return ControlSubjectCursor(
                subject_kind=value["subject_kind"],
                subject_ref=value["subject_ref"],
                validity_revision=value["validity_revision"],
                status=value["status"],
                effective_at=_parse_time(value["effective_at"], "effective_at"),
                expires_at=(
                    None
                    if value["expires_at"] is None
                    else _parse_time(value["expires_at"], "expires_at")
                ),
                authority=value["authority"],
                reason=value["reason"],
                source_record_ref=value["source_record_ref"],
                control_sequence=value["control_sequence"],
            )
        except Exception as error:
            if isinstance(error, DurableControlStoreError):
                raise
            raise DurableControlStoreError("subject cursor is invalid") from error

    @classmethod
    def _record_from_dict(cls, value: Any) -> ExecutionControlRecord:
        if not isinstance(value, dict):
            raise DurableControlStoreError("control record is not an object")
        expected = {"control_sequence", "request", "subject_snapshot", "request_digest", "record_digest"}
        if set(value) != expected or not isinstance(value["request"], dict):
            raise DurableControlStoreError("control record fields are invalid")
        request_value = value["request"]
        if set(request_value) != {"record_id", "record_type", "value", "idempotency_key"}:
            raise DurableControlStoreError("control request fields are invalid")
        try:
            request = ControlAppendRequest(
                record_id=request_value["record_id"],
                record_type=request_value["record_type"],
                value=request_value["value"],
                idempotency_key=request_value["idempotency_key"],
            )
            if value["record_digest"] != request.content_digest:
                raise DurableControlStoreError("control record digest mismatch")
            snapshot_value = value["subject_snapshot"]
            if not isinstance(snapshot_value, list) or not snapshot_value:
                raise DurableControlStoreError("control subject snapshot is invalid")
            snapshot = tuple(cls._cursor_from_dict(item) for item in snapshot_value)
            return ExecutionControlRecord(
                control_sequence=value["control_sequence"],
                request=request,
                subject_snapshot=snapshot,
                request_digest=value["request_digest"],
            )
        except DurableControlStoreError:
            raise
        except Exception as error:
            raise DurableControlStoreError("control record is invalid") from error

    def _append_event_locked(self, event: dict[str, Any]) -> None:
        existing = self.journal.read_bytes() if self.journal.exists() else b""
        line = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.journal)
        except OSError as error:
            raise DurableControlStoreError("control journal append failed") from error
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @contextmanager
    def _journal_lock(self, *, create: bool = True) -> Iterator[None]:
        if not self.directory.exists():
            if not create:
                yield
                return
            self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / f".{_JOURNAL_NAME}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["DurableControlStoreError", "DurableExecutionControlStore"]
