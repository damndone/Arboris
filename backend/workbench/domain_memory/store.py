"""Descriptor-bound append-only store for official domain-memory control records."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import os
from threading import RLock
from typing import Iterator, Any

from .contracts import (
    DomainMemoryApprovalRecord,
    DomainMemoryContentRevision,
    DomainMemoryContractError,
    DomainMemoryValidityRecord,
)
from .scope import MemoryScope
from .source_access import SourceAccessBinding, SourceAccessValidityRecord


class DomainMemoryStoreError(DomainMemoryContractError):
    """The official memory store cannot be safely read or written."""


class DomainMemoryStoreConflict(DomainMemoryStoreError):
    """An append-only identity, CAS, or lifecycle transition was violated."""


_JOURNAL_NAME = "domain-memory.jsonl"
_LOCK_NAME = ".domain-memory.lock"
_MAX_JOURNAL_BYTES = 16 * 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class DomainMemoryStore:
    """A single explicit scope's content, access, approval, and validity journal."""

    def __init__(self, root: Path | str, scope: MemoryScope, *, create: bool = True) -> None:
        if not _O_DIRECTORY or not _O_NOFOLLOW:
            raise DomainMemoryStoreError("safe directory descriptors are unavailable")
        if not isinstance(scope, MemoryScope):
            raise DomainMemoryStoreError("store scope is required")
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            raise DomainMemoryStoreError("store root must be absolute")
        if not self.root.exists():
            if not create:
                raise DomainMemoryStoreError("store root is unavailable")
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise DomainMemoryStoreError("store root must be a real directory")
        self.scope = scope
        self.journal_path = self.root / _JOURNAL_NAME
        self._lock = RLock()

    def append_content(self, content: DomainMemoryContentRevision) -> DomainMemoryContentRevision:
        if not isinstance(content, DomainMemoryContentRevision) or not content.scope.exact_match(self.scope):
            raise DomainMemoryStoreError("content scope does not match the store")
        with self._locked_directory() as directory_fd:
            records = self._read_locked(directory_fd)
            existing = [item for kind, item in records if kind == "memory_content" and item.memory_id == content.memory_id]
            if existing:
                current = max(existing, key=lambda item: item.revision)
                if current.revision == content.revision:
                    if current.content_hash != content.content_hash:
                        raise DomainMemoryStoreConflict("content revision is bound to another hash")
                    return current
                if content.revision != current.revision + 1 or content.supersedes_revision != current.revision:
                    raise DomainMemoryStoreConflict("content revisions must be contiguous and superseding")
            elif content.revision != 1 or content.supersedes_revision is not None:
                raise DomainMemoryStoreConflict("a new content stream must start at revision one")
            self._append_locked(directory_fd, "memory_content", content.to_dict())
            return content

    def append_binding(self, binding: SourceAccessBinding) -> SourceAccessBinding:
        if not isinstance(binding, SourceAccessBinding) or not binding.scope.exact_match(self.scope):
            raise DomainMemoryStoreError("source binding scope does not match the store")
        with self._locked_directory() as directory_fd:
            records = self._read_locked(directory_fd)
            existing = [item for kind, item in records if kind == "source_access_binding" and item.binding_ref == binding.binding_ref]
            if existing:
                if existing[-1] != binding:
                    raise DomainMemoryStoreConflict("source binding identity was reused")
                return existing[-1]
            self._append_locked(directory_fd, "source_access_binding", binding.to_dict())
            return binding

    def append_source_validity(self, validity: SourceAccessValidityRecord) -> SourceAccessValidityRecord:
        if not isinstance(validity, SourceAccessValidityRecord):
            raise DomainMemoryStoreError("source validity is invalid")
        with self._locked_directory() as directory_fd:
            records = self._read_locked(directory_fd)
            bindings = {item.binding_ref: item for kind, item in records if kind == "source_access_binding"}
            if validity.binding_ref not in bindings:
                raise DomainMemoryStoreConflict("source validity references an unknown binding")
            if bindings[validity.binding_ref].source_tombstone_ref is not None and validity.state == "valid":
                raise DomainMemoryStoreConflict("a tombstoned source cannot become valid")
            history = [item for kind, item in records if kind == "source_access_validity" and item.binding_ref == validity.binding_ref]
            if history:
                current = max(history, key=lambda item: item.validity_revision)
                if current.validity_revision == validity.validity_revision:
                    if current != validity:
                        raise DomainMemoryStoreConflict("source validity revision was reused")
                    return current
                if validity.validity_revision != current.validity_revision + 1 or validity.control_sequence <= current.control_sequence:
                    raise DomainMemoryStoreConflict("source validity revisions must be contiguous and monotonic")
                if current.state != "valid" or validity.state == "valid":
                    raise DomainMemoryStoreConflict("source access cannot be silently restored")
            elif validity.validity_revision != 1 or validity.control_sequence != 1 or validity.state != "valid":
                raise DomainMemoryStoreConflict("source access must begin with a valid grant")
            self._append_locked(directory_fd, "source_access_validity", validity.to_dict())
            return validity

    def append_approval(self, approval: DomainMemoryApprovalRecord) -> DomainMemoryApprovalRecord:
        if not isinstance(approval, DomainMemoryApprovalRecord) or not approval.scope.exact_match(self.scope):
            raise DomainMemoryStoreError("approval scope does not match the store")
        with self._locked_directory() as directory_fd:
            records = self._read_locked(directory_fd)
            contents = {
                (item.memory_id, item.revision): item
                for kind, item in records if kind == "memory_content"
            }
            content = contents.get((approval.memory_id, approval.content_revision))
            if content is None or content.content_hash != approval.content_hash or not content.scope.exact_match(approval.scope):
                raise DomainMemoryStoreConflict("approval is not bound to the exact content revision")
            existing_by_ref = [item for kind, item in records if kind == "memory_approval" and item.approval_ref == approval.approval_ref]
            if existing_by_ref:
                if existing_by_ref[-1] != approval:
                    raise DomainMemoryStoreConflict("approval identity was reused")
                return existing_by_ref[-1]
            history = [item for kind, item in records if kind == "memory_approval" and item.memory_id == approval.memory_id]
            current = max(history, key=lambda item: item.grant_control_sequence) if history else None
            expected = current.approval_ref if current else None
            sequence = current.grant_control_sequence + 1 if current else 1
            if approval.expected_current_approval_ref != expected or approval.supersedes_approval_ref != expected or approval.grant_control_sequence != sequence:
                raise DomainMemoryStoreConflict("approval CAS or grant sequence failed")
            self._append_locked(directory_fd, "memory_approval", approval.to_dict())
            return approval

    def append_validity(self, validity: DomainMemoryValidityRecord) -> DomainMemoryValidityRecord:
        if not isinstance(validity, DomainMemoryValidityRecord):
            raise DomainMemoryStoreError("memory validity is invalid")
        with self._locked_directory() as directory_fd:
            records = self._read_locked(directory_fd)
            approvals = {item.approval_ref: item for kind, item in records if kind == "memory_approval"}
            approval = approvals.get(validity.approval_ref)
            if approval is None or approval.memory_id != validity.memory_id or approval.content_revision != validity.content_revision:
                raise DomainMemoryStoreConflict("validity is not bound to its approval")
            if validity.control_sequence != approval.grant_control_sequence:
                raise DomainMemoryStoreConflict("validity control sequence does not match approval")
            current_approval = self._current_approval(records, validity.memory_id)
            history = [item for kind, item in records if kind == "memory_validity" and item.approval_ref == validity.approval_ref]
            if history:
                current = max(history, key=lambda item: item.validity_revision)
                if current.validity_revision == validity.validity_revision:
                    if current != validity:
                        raise DomainMemoryStoreConflict("validity revision was reused")
                    return current
                if validity.validity_revision != current.validity_revision + 1:
                    raise DomainMemoryStoreConflict("validity revisions must be contiguous")
                if current.state != "active" or validity.state == "active":
                    raise DomainMemoryStoreConflict("validity cannot be restored in place")
            elif validity.validity_revision != 1:
                raise DomainMemoryStoreConflict("a validity stream must start at revision one")
            if validity.state == "active" and (current_approval is None or current_approval.approval_ref != approval.approval_ref):
                raise DomainMemoryStoreConflict("only the current approval may become active")
            self._append_locked(directory_fd, "memory_validity", validity.to_dict())
            return validity

    def get_content(self, memory_id: str, revision: int) -> DomainMemoryContentRevision:
        records = self._read()
        for kind, item in reversed(records):
            if kind == "memory_content" and item.memory_id == memory_id and item.revision == revision:
                return item
        raise KeyError((memory_id, revision))

    def list_content(self) -> tuple[DomainMemoryContentRevision, ...]:
        records = self._read()
        return tuple(item for kind, item in records if kind == "memory_content")

    def list_bindings(self) -> tuple[SourceAccessBinding, ...]:
        return tuple(item for kind, item in self._read() if kind == "source_access_binding")

    def current_source_validity(self, binding_ref: str) -> SourceAccessValidityRecord | None:
        history = [item for kind, item in self._read() if kind == "source_access_validity" and item.binding_ref == binding_ref]
        return max(history, key=lambda item: item.validity_revision) if history else None

    def current_approval(self, memory_id: str) -> DomainMemoryApprovalRecord | None:
        return self._current_approval(self._read(), memory_id)

    def current_validity(self, memory_id: str) -> DomainMemoryValidityRecord | None:
        records = self._read()
        approval = self._current_approval(records, memory_id)
        if approval is None:
            return None
        history = [item for kind, item in records if kind == "memory_validity" and item.approval_ref == approval.approval_ref]
        if not history:
            return None
        latest = max(history, key=lambda item: item.validity_revision)
        return latest if latest.state == "active" else None

    def active_contents(self) -> tuple[DomainMemoryContentRevision, ...]:
        records = self._read()
        current_approvals: dict[str, DomainMemoryApprovalRecord] = {}
        for kind, item in records:
            if kind == "memory_approval" and (item.memory_id not in current_approvals or item.grant_control_sequence > current_approvals[item.memory_id].grant_control_sequence):
                current_approvals[item.memory_id] = item
        active: list[DomainMemoryContentRevision] = []
        for memory_id, approval in current_approvals.items():
            validity = self.current_validity(memory_id)
            if validity is None:
                continue
            content = next((item for kind, item in records if kind == "memory_content" and item.memory_id == memory_id and item.revision == approval.content_revision), None)
            if content is not None:
                active.append(content)
        return tuple(sorted(active, key=lambda item: (item.memory_id, item.revision)))

    def _read(self) -> list[tuple[str, Any]]:
        with self._locked_directory() as directory_fd:
            return self._read_locked(directory_fd)

    @staticmethod
    def _current_approval(records: list[tuple[str, Any]], memory_id: str) -> DomainMemoryApprovalRecord | None:
        approvals = [item for kind, item in records if kind == "memory_approval" and item.memory_id == memory_id]
        return max(approvals, key=lambda item: item.grant_control_sequence) if approvals else None

    @contextmanager
    def _locked_directory(self) -> Iterator[int]:
        with self._lock:
            try:
                directory_fd = os.open(os.fspath(self.root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
            except OSError as error:
                raise DomainMemoryStoreError("memory store root could not be safely opened") from error
            lock_fd: int | None = None
            try:
                lock_fd = os.open(_LOCK_NAME, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield directory_fd
            except OSError as error:
                raise DomainMemoryStoreError("memory store lock or I/O failed") from error
            finally:
                if lock_fd is not None:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    finally:
                        os.close(lock_fd)
                os.close(directory_fd)

    def _read_locked(self, directory_fd: int) -> list[tuple[str, Any]]:
        try:
            journal_fd = os.open(_JOURNAL_NAME, os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise DomainMemoryStoreError("memory journal could not be opened") from error
        try:
            with os.fdopen(journal_fd, "rb") as handle:
                raw = handle.read(_MAX_JOURNAL_BYTES + 1)
        except OSError as error:
            raise DomainMemoryStoreError("memory journal could not be read") from error
        if len(raw) > _MAX_JOURNAL_BYTES or (raw and not raw.endswith(b"\n")):
            raise DomainMemoryStoreError("memory journal is truncated or too large")
        decoders = {
            "memory_content": DomainMemoryContentRevision.from_dict,
            "source_access_binding": SourceAccessBinding.from_dict,
            "source_access_validity": SourceAccessValidityRecord.from_dict,
            "memory_approval": DomainMemoryApprovalRecord.from_dict,
            "memory_validity": DomainMemoryValidityRecord.from_dict,
        }
        records: list[tuple[str, Any]] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=_strict_pairs)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                raise DomainMemoryStoreError(f"memory journal line {line_number} is invalid") from error
            if not isinstance(event, dict) or set(event) != {"record_type", "record"} or event["record_type"] not in decoders:
                raise DomainMemoryStoreError(f"memory journal line {line_number} has invalid fields")
            try:
                record = decoders[event["record_type"]](event["record"])
            except (DomainMemoryContractError, TypeError, KeyError, ValueError) as error:
                raise DomainMemoryStoreError(f"memory journal line {line_number} is invalid") from error
            if hasattr(record, "scope") and not record.scope.exact_match(self.scope):
                raise DomainMemoryStoreError("memory journal contains an invalid scope")
            records.append((event["record_type"], record))
        return records

    @staticmethod
    def _append_locked(directory_fd: int, record_type: str, record: dict[str, Any]) -> None:
        line = (json.dumps({"record_type": record_type, "record": record}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            journal_fd = os.open(_JOURNAL_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(journal_fd, "ab") as handle:
                handle.write(line); handle.flush(); os.fsync(handle.fileno())
            os.fsync(directory_fd)
        except OSError as error:
            raise DomainMemoryStoreError("memory journal append failed") from error


__all__ = ["DomainMemoryStore", "DomainMemoryStoreConflict", "DomainMemoryStoreError"]
