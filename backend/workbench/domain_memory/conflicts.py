"""Deterministic duplicate/conflict records for explicit review."""

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
from .contracts import DomainMemoryContentRevision, DomainMemoryContractError, MemoryCandidate
from .scope import MemoryScope


class ConflictStoreError(DomainMemoryContractError):
    """The conflict ledger cannot be safely read or written."""


class ConflictStoreConflict(ConflictStoreError):
    """A conflict identity or lifecycle transition was reused incorrectly."""


_STATES = frozenset({"open", "resolved", "ignored"})
_RELATIONS = frozenset({"duplicate", "supersedes", "conflict", "scope_overlap"})
_JOURNAL = "domain-memory-conflicts.jsonl"
_LOCK = ".domain-memory-conflicts.lock"
_MAX_BYTES = 4 * 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or "/" in value or "\\" in value:
        raise ConflictStoreError(f"{field} must be an opaque bounded ref")
    return value


def _refs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or len(value) > 16:
        raise ConflictStoreError("evidence_refs exceed their bound")
    result = tuple(_id(item, "evidence_ref") for item in value)
    if len(set(result)) != len(result):
        raise ConflictStoreError("evidence_refs must be unique")
    return result


@dataclass(frozen=True, slots=True)
class MemoryConflictRecord:
    conflict_ref: str
    revision: int
    scope: MemoryScope
    left_ref: str
    right_ref: str
    relation: str
    detected_at: str
    status: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "conflict_ref", _id(self.conflict_ref, "conflict_ref"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ConflictStoreError("conflict revision must be positive")
        if not isinstance(self.scope, MemoryScope):
            raise ConflictStoreError("conflict scope is required")
        object.__setattr__(self, "left_ref", _id(self.left_ref, "left_ref"))
        object.__setattr__(self, "right_ref", _id(self.right_ref, "right_ref"))
        if self.left_ref == self.right_ref:
            raise ConflictStoreError("conflict endpoints must differ")
        if self.relation not in _RELATIONS:
            raise ConflictStoreError("conflict relation is not registered")
        if not isinstance(self.detected_at, str) or not self.detected_at or len(self.detected_at) > 64:
            raise ConflictStoreError("detected_at is invalid")
        if self.status not in _STATES:
            raise ConflictStoreError("conflict status is not registered")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": "memory-conflict/v1", "conflict_ref": self.conflict_ref, "revision": self.revision,
                "scope": self.scope.to_dict(), "left_ref": self.left_ref, "right_ref": self.right_ref,
                "relation": self.relation, "detected_at": self.detected_at, "status": self.status,
                "evidence_refs": list(self.evidence_refs)}

    @classmethod
    def from_dict(cls, value: Any) -> "MemoryConflictRecord":
        expected = {"contract_version", "conflict_ref", "revision", "scope", "left_ref", "right_ref", "relation", "detected_at", "status", "evidence_refs"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != "memory-conflict/v1":
            raise ConflictStoreError("conflict fields are invalid")
        data = dict(value); data.pop("contract_version")
        data["scope"] = MemoryScope.from_dict(data["scope"])
        return cls(**data)


class ConflictDetector:
    @staticmethod
    def detect(candidate: MemoryCandidate, official: tuple[DomainMemoryContentRevision, ...]) -> tuple[MemoryConflictRecord, ...]:
        if not isinstance(candidate, MemoryCandidate):
            raise ConflictStoreError("candidate is required")
        records: list[MemoryConflictRecord] = []
        candidate_predicates = domain_digest(
            "workbench.domain-memory.conflict-predicates/v1",
            [item.to_dict() for item in candidate.applicability_predicates],
        )
        for content in official:
            if not isinstance(content, DomainMemoryContentRevision) or not content.scope.exact_match(candidate.scope):
                continue
            if content.memory_kind != candidate.memory_kind or set(content.domain_tags) != set(candidate.domain_tags):
                continue
            if domain_digest(
                "workbench.domain-memory.conflict-predicates/v1",
                [item.to_dict() for item in content.applicability_predicates],
            ) != candidate_predicates:
                continue
            relation = "duplicate" if content.compact_lesson == candidate.compact_lesson else "conflict"
            left, right = sorted((candidate.candidate_id, f"{content.memory_id}@{content.revision}"))
            conflict_ref = "conflict-" + domain_digest("workbench.domain-memory.conflict/v1", {"left": left, "right": right, "relation": relation})[:40]
            records.append(MemoryConflictRecord(conflict_ref, 1, candidate.scope, left, right, relation, candidate.created_at, "open", (candidate.created_from_manifest_ref,)))
        return tuple(records)


class ConflictStore:
    def __init__(self, root: Path | str, scope: MemoryScope, *, create: bool = True) -> None:
        if not _O_NOFOLLOW or not _O_DIRECTORY:
            raise ConflictStoreError("safe directory descriptors are unavailable")
        if not isinstance(scope, MemoryScope):
            raise ConflictStoreError("conflict scope is required")
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            raise ConflictStoreError("conflict store root must be absolute")
        if not self.root.exists():
            if not create:
                raise ConflictStoreError("conflict store root is unavailable")
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ConflictStoreError("conflict store root must be a real directory")
        self.scope = scope
        self.journal_path = self.root / _JOURNAL
        self._lock = RLock()

    def append(self, record: MemoryConflictRecord) -> MemoryConflictRecord:
        if not record.scope.exact_match(self.scope):
            raise ConflictStoreError("conflict scope does not match store")
        with self._locked() as fd:
            history = [item for item in self._read_locked(fd) if item.conflict_ref == record.conflict_ref]
            if history:
                current = max(history, key=lambda item: item.revision)
                if current.revision == record.revision:
                    if current != record:
                        raise ConflictStoreConflict("conflict revision was reused")
                    return current
                if record.revision != current.revision + 1 or current.status != "open" or record.status == "open":
                    raise ConflictStoreConflict("conflict lifecycle transition is invalid")
            elif record.revision != 1:
                raise ConflictStoreConflict("conflict stream must start at revision one")
            self._append_locked(fd, record)
            return record

    def transition(self, conflict_ref: str, *, expected_revision: int, status: str) -> MemoryConflictRecord:
        if status not in _STATES:
            raise ConflictStoreConflict("conflict status is not registered")
        history = [item for item in self._read() if item.conflict_ref == conflict_ref]
        if not history:
            raise KeyError(conflict_ref)
        current = max(history, key=lambda item: item.revision)
        if current.revision != expected_revision or current.status != "open":
            raise ConflictStoreConflict("conflict revision is stale or closed")
        return self.append(replace(current, revision=current.revision + 1, status=status))

    def _read(self) -> list[MemoryConflictRecord]:
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

    def _read_locked(self, directory_fd: int) -> list[MemoryConflictRecord]:
        try:
            fd = os.open(_JOURNAL, os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise ConflictStoreError("conflict journal could not be opened") from error
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES or (raw and not raw.endswith(b"\n")):
            raise ConflictStoreError("conflict journal is truncated or too large")
        result: list[MemoryConflictRecord] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=self._pairs)
                if not isinstance(event, dict) or set(event) != {"record_type", "record"} or event["record_type"] != "memory_conflict":
                    raise ValueError("invalid conflict event")
                record = MemoryConflictRecord.from_dict(event["record"])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ConflictStoreError, TypeError) as error:
                raise ConflictStoreError(f"conflict journal line {number} is invalid") from error
            if not record.scope.exact_match(self.scope):
                raise ConflictStoreError("conflict journal scope mismatch")
            result.append(record)
        return result

    @staticmethod
    def _append_locked(directory_fd: int, record: MemoryConflictRecord) -> None:
        line = (json.dumps({"record_type": "memory_conflict", "record": record.to_dict()}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            fd = os.open(_JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "ab") as handle:
                handle.write(line); handle.flush(); os.fsync(handle.fileno())
            os.fsync(directory_fd)
        except OSError as error:
            raise ConflictStoreError("conflict journal append failed") from error

    @contextmanager
    def _locked(self) -> Iterator[int]:
        with self._lock:
            try:
                directory_fd = os.open(os.fspath(self.root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
            except OSError as error:
                raise ConflictStoreError("conflict root could not be safely opened") from error
            lock_fd: int | None = None
            try:
                lock_fd = os.open(_LOCK, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield directory_fd
            except OSError as error:
                raise ConflictStoreError("conflict lock or I/O failed") from error
            finally:
                if lock_fd is not None:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    finally:
                        os.close(lock_fd)
                os.close(directory_fd)


__all__ = ["ConflictDetector", "ConflictStore", "ConflictStoreConflict", "ConflictStoreError", "MemoryConflictRecord"]
