"""Separate append-only pending candidate store."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import fcntl
import json
import os
from threading import RLock
from typing import Any, Iterator

from .contracts import CANDIDATE_STATES, DomainMemoryContractError, MemoryCandidate
from .scope import MemoryScope


class MemoryCandidateStoreError(DomainMemoryContractError):
    """The candidate journal cannot be safely read or changed."""


class MemoryCandidateStoreConflict(MemoryCandidateStoreError):
    """Candidate revision or state transition failed."""


_JOURNAL_NAME = "domain-memory-candidates.jsonl"
_LOCK_NAME = ".domain-memory-candidates.lock"
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_TRANSITIONS = {
    "proposed": {"needs_review", "expired", "rejected"},
    "needs_review": {"approved", "rejected", "expired"},
    "approved": set(),
    "rejected": set(),
    "expired": set(),
}


class MemoryCandidateStore:
    def __init__(self, root: Path | str, scope: MemoryScope, *, create: bool = True) -> None:
        if not _O_DIRECTORY or not _O_NOFOLLOW:
            raise MemoryCandidateStoreError("safe directory descriptors are unavailable")
        if not isinstance(scope, MemoryScope):
            raise MemoryCandidateStoreError("candidate store scope is required")
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            raise MemoryCandidateStoreError("candidate store root must be absolute")
        if not self.root.exists():
            if not create:
                raise MemoryCandidateStoreError("candidate store root is unavailable")
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise MemoryCandidateStoreError("candidate store root must be a real directory")
        self.scope = scope
        self.journal_path = self.root / _JOURNAL_NAME
        self._lock = RLock()

    def append(self, candidate: MemoryCandidate) -> MemoryCandidate:
        if not isinstance(candidate, MemoryCandidate) or not candidate.scope.exact_match(self.scope):
            raise MemoryCandidateStoreError("candidate scope does not match the store")
        with self._locked() as directory_fd:
            history = [item for item in self._read_locked(directory_fd) if item.candidate_id == candidate.candidate_id]
            if history:
                current = max(history, key=lambda item: item.revision)
                if current.revision == candidate.revision:
                    if current != candidate:
                        raise MemoryCandidateStoreConflict("candidate revision was reused")
                    return current
                if candidate.revision != current.revision + 1:
                    raise MemoryCandidateStoreConflict("candidate revisions must be contiguous")
                if candidate.status not in _TRANSITIONS[current.status]:
                    raise MemoryCandidateStoreConflict("candidate state transition is not registered")
            elif candidate.revision != 1 or candidate.status not in {"proposed", "needs_review"}:
                raise MemoryCandidateStoreConflict("a candidate stream must start pending")
            self._append_locked(directory_fd, candidate)
            return candidate

    def transition(self, candidate_id: str, *, expected_revision: int, status: str) -> MemoryCandidate:
        if status not in CANDIDATE_STATES:
            raise MemoryCandidateStoreConflict("candidate status is not registered")
        history = [item for item in self._read() if item.candidate_id == candidate_id]
        if not history:
            raise KeyError(candidate_id)
        current = max(history, key=lambda item: item.revision)
        if current.revision != expected_revision:
            raise MemoryCandidateStoreConflict("candidate revision is stale")
        if status not in _TRANSITIONS[current.status]:
            raise MemoryCandidateStoreConflict("candidate state transition is not registered")
        return self.append(replace(current, revision=current.revision + 1, status=status))

    def pending(self, requester: MemoryScope) -> tuple[MemoryCandidate, ...]:
        if not isinstance(requester, MemoryScope) or not self.scope.can_read(requester):
            raise MemoryCandidateStoreError("candidate scope mismatch")
        latest: dict[str, MemoryCandidate] = {}
        for item in self._read():
            if item.candidate_id not in latest or item.revision > latest[item.candidate_id].revision:
                latest[item.candidate_id] = item
        return tuple(sorted((item for item in latest.values() if item.status in {"proposed", "needs_review"}), key=lambda item: item.candidate_id))

    def _read(self) -> list[MemoryCandidate]:
        with self._locked() as directory_fd:
            return self._read_locked(directory_fd)

    @staticmethod
    def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def _read_locked(self, directory_fd: int) -> list[MemoryCandidate]:
        try:
            journal_fd = os.open(_JOURNAL_NAME, os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise MemoryCandidateStoreError("candidate journal could not be opened") from error
        with os.fdopen(journal_fd, "rb") as handle:
            raw = handle.read(_MAX_JOURNAL_BYTES + 1)
        if len(raw) > _MAX_JOURNAL_BYTES or (raw and not raw.endswith(b"\n")):
            raise MemoryCandidateStoreError("candidate journal is truncated or too large")
        result: list[MemoryCandidate] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=self._strict_pairs)
                if not isinstance(event, dict) or set(event) != {"record_type", "candidate"} or event["record_type"] != "memory_candidate":
                    raise ValueError("invalid candidate event")
                candidate = MemoryCandidate.from_dict(event["candidate"])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, DomainMemoryContractError, TypeError) as error:
                raise MemoryCandidateStoreError(f"candidate journal line {number} is invalid") from error
            if not candidate.scope.exact_match(self.scope):
                raise MemoryCandidateStoreError("candidate journal scope mismatch")
            result.append(candidate)
        return result

    @staticmethod
    def _append_locked(directory_fd: int, candidate: MemoryCandidate) -> None:
        line = (json.dumps({"record_type": "memory_candidate", "candidate": candidate.to_dict()}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            journal_fd = os.open(_JOURNAL_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(journal_fd, "ab") as handle:
                handle.write(line); handle.flush(); os.fsync(handle.fileno())
            os.fsync(directory_fd)
        except OSError as error:
            raise MemoryCandidateStoreError("candidate journal append failed") from error

    @contextmanager
    def _locked(self) -> Iterator[int]:
        with self._lock:
            try:
                directory_fd = os.open(os.fspath(self.root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
            except OSError as error:
                raise MemoryCandidateStoreError("candidate root could not be safely opened") from error
            lock_fd: int | None = None
            try:
                lock_fd = os.open(_LOCK_NAME, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield directory_fd
            except OSError as error:
                raise MemoryCandidateStoreError("candidate lock or I/O failed") from error
            finally:
                if lock_fd is not None:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    finally:
                        os.close(lock_fd)
                os.close(directory_fd)


__all__ = ["MemoryCandidateStore", "MemoryCandidateStoreConflict", "MemoryCandidateStoreError"]
