"""Explicit, crash-recoverable review job records without a hidden worker."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
import fcntl
import json
import os
from threading import RLock
from typing import Any, Iterator

from ..custom_capability.canonical import domain_digest
from .scope import MemoryScope


class ReviewJobError(ValueError):
    """A review job is malformed or its explicit lifecycle operation is stale."""


_STATES = frozenset({"queued", "running", "completed", "failed"})
_KINDS = frozenset({"candidate", "memory", "conflict"})
_JOURNAL = "domain-memory-review-jobs.jsonl"
_LOCK = ".domain-memory-review-jobs.lock"
_MAX_BYTES = 4 * 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or "/" in value or "\\" in value:
        raise ReviewJobError(f"{field} must be an opaque bounded ref")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ReviewJobError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ReviewJobRecord:
    job_id: str
    revision: int
    scope: MemoryScope
    target_kind: str
    target_ref: str
    idempotency_key: str
    state: str
    attempt: int
    scheduled_at: str
    lease_until: str | None
    last_error: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _id(self.job_id, "job_id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ReviewJobError("job revision must be positive")
        if not isinstance(self.scope, MemoryScope):
            raise ReviewJobError("job scope is required")
        if self.target_kind not in _KINDS:
            raise ReviewJobError("target_kind is not registered")
        object.__setattr__(self, "target_ref", _id(self.target_ref, "target_ref"))
        object.__setattr__(self, "idempotency_key", _digest(self.idempotency_key, "idempotency_key"))
        if self.state not in _STATES:
            raise ReviewJobError("review job state is not registered")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 0:
            raise ReviewJobError("job attempt must be non-negative")
        if not isinstance(self.scheduled_at, str) or not self.scheduled_at or len(self.scheduled_at) > 64:
            raise ReviewJobError("scheduled_at is invalid")
        if self.lease_until is not None and (not isinstance(self.lease_until, str) or not self.lease_until or len(self.lease_until) > 64):
            raise ReviewJobError("lease_until is invalid")
        if self.last_error is not None:
            object.__setattr__(self, "last_error", _id(self.last_error, "last_error"))

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": "review-job/v1", "job_id": self.job_id, "revision": self.revision,
                "scope": self.scope.to_dict(), "target_kind": self.target_kind, "target_ref": self.target_ref,
                "idempotency_key": self.idempotency_key, "state": self.state, "attempt": self.attempt,
                "scheduled_at": self.scheduled_at, "lease_until": self.lease_until, "last_error": self.last_error}

    @classmethod
    def from_dict(cls, value: Any) -> "ReviewJobRecord":
        expected = {"contract_version", "job_id", "revision", "scope", "target_kind", "target_ref", "idempotency_key", "state", "attempt", "scheduled_at", "lease_until", "last_error"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != "review-job/v1":
            raise ReviewJobError("review job fields are invalid")
        data = dict(value); data.pop("contract_version"); data["scope"] = MemoryScope.from_dict(data["scope"])
        return cls(**data)


class ReviewJobStore:
    def __init__(self, root: Path | str, scope: MemoryScope, *, create: bool = True) -> None:
        if not _O_NOFOLLOW or not _O_DIRECTORY:
            raise ReviewJobError("safe directory descriptors are unavailable")
        if not isinstance(scope, MemoryScope):
            raise ReviewJobError("job scope is required")
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            raise ReviewJobError("job root must be absolute")
        if not self.root.exists():
            if not create:
                raise ReviewJobError("job root is unavailable")
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ReviewJobError("job root must be a real directory")
        self.scope = scope
        self.journal_path = self.root / _JOURNAL
        self._lock = RLock()

    def append(self, record: ReviewJobRecord) -> ReviewJobRecord:
        if not record.scope.exact_match(self.scope):
            raise ReviewJobError("job scope does not match store")
        with self._locked() as fd:
            history = [item for item in self._read_locked(fd) if item.job_id == record.job_id]
            if history:
                current = max(history, key=lambda item: item.revision)
                if current.revision == record.revision:
                    if current != record:
                        raise ReviewJobError("job revision was reused")
                    return current
                if record.revision != current.revision + 1:
                    raise ReviewJobError("job revisions must be contiguous")
            elif record.revision != 1:
                raise ReviewJobError("job stream must start at revision one")
            self._append_locked(fd, record)
            return record

    def latest(self, job_id: str) -> ReviewJobRecord:
        history = [item for item in self._read() if item.job_id == job_id]
        if not history:
            raise KeyError(job_id)
        return max(history, key=lambda item: item.revision)

    def by_idempotency(self, key: str) -> ReviewJobRecord | None:
        _digest(key, "idempotency_key")
        history = [item for item in self._read() if item.idempotency_key == key]
        return max(history, key=lambda item: item.revision) if history else None

    def _read(self) -> list[ReviewJobRecord]:
        with self._locked() as fd:
            return self._read_locked(fd)

    @staticmethod
    def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def _read_locked(self, directory_fd: int) -> list[ReviewJobRecord]:
        try:
            fd = os.open(_JOURNAL, os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise ReviewJobError("job journal could not be opened") from error
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES or (raw and not raw.endswith(b"\n")):
            raise ReviewJobError("job journal is truncated or too large")
        result: list[ReviewJobRecord] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=self._pairs)
                if not isinstance(event, dict) or set(event) != {"record_type", "record"} or event["record_type"] != "review_job":
                    raise ValueError("invalid review job event")
                record = ReviewJobRecord.from_dict(event["record"])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ReviewJobError, TypeError) as error:
                raise ReviewJobError(f"job journal line {number} is invalid") from error
            if not record.scope.exact_match(self.scope):
                raise ReviewJobError("job journal scope mismatch")
            result.append(record)
        return result

    @staticmethod
    def _append_locked(directory_fd: int, record: ReviewJobRecord) -> None:
        line = (json.dumps({"record_type": "review_job", "record": record.to_dict()}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            fd = os.open(_JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "ab") as handle:
                handle.write(line); handle.flush(); os.fsync(handle.fileno())
            os.fsync(directory_fd)
        except OSError as error:
            raise ReviewJobError("job journal append failed") from error

    @contextmanager
    def _locked(self) -> Iterator[int]:
        with self._lock:
            try:
                directory_fd = os.open(os.fspath(self.root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
            except OSError as error:
                raise ReviewJobError("job root could not be safely opened") from error
            lock_fd: int | None = None
            try:
                lock_fd = os.open(_LOCK, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield directory_fd
            except OSError as error:
                raise ReviewJobError("job lock or I/O failed") from error
            finally:
                if lock_fd is not None:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    finally:
                        os.close(lock_fd)
                os.close(directory_fd)


class ReviewScheduler:
    """Only performs explicit caller-invoked state transitions; no worker thread."""

    def __init__(self, store: ReviewJobStore) -> None:
        self.store = store

    def enqueue(self, *, target_kind: str, target_ref: str, idempotency_key: str, scheduled_at: str) -> ReviewJobRecord:
        existing = self.store.by_idempotency(idempotency_key)
        if existing is not None:
            return existing
        job_id = "job-" + domain_digest("workbench.domain-memory.review-job/v1", {"target_kind": target_kind, "target_ref": target_ref, "idempotency_key": idempotency_key})[:40]
        return self.store.append(ReviewJobRecord(job_id, 1, self.store.scope, target_kind, target_ref, idempotency_key, "queued", 0, scheduled_at, None, None))

    def claim(self, job_id: str, *, expected_revision: int, lease_until: str) -> ReviewJobRecord:
        current = self.store.latest(job_id)
        if current.revision != expected_revision or current.state != "queued":
            raise ReviewJobError("job is stale or not queued")
        return self.store.append(replace(current, revision=current.revision + 1, state="running", attempt=current.attempt + 1, lease_until=lease_until, last_error=None))

    def recover(self, job_id: str, *, expected_revision: int) -> ReviewJobRecord:
        current = self.store.latest(job_id)
        if current.revision != expected_revision or current.state != "running":
            raise ReviewJobError("only a running job can be explicitly recovered")
        return self.store.append(replace(current, revision=current.revision + 1, state="queued", lease_until=None, last_error="recovered_after_restart"))

    def complete(self, job_id: str, *, expected_revision: int) -> ReviewJobRecord:
        current = self.store.latest(job_id)
        if current.revision != expected_revision or current.state != "running":
            raise ReviewJobError("only a running job can complete")
        return self.store.append(replace(current, revision=current.revision + 1, state="completed", lease_until=None))


__all__ = ["ReviewJobError", "ReviewJobRecord", "ReviewJobStore", "ReviewScheduler"]
