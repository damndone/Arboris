"""FD-bound append-only storage for rebuildable MEM1 index revisions."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import os
from threading import RLock
from typing import Iterator

from .project_index_contract import ProjectContextIndex, ProjectIndexError


_JOURNAL_NAME = "project-context-index.jsonl"
_LOCK_NAME = ".project-context-index.lock"
_RECORD_TYPE = "project_context_index"
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class ProjectIndexStoreError(ProjectIndexError):
    """The index store cannot safely be opened or parsed."""


class ProjectIndexStoreConflict(ProjectIndexStoreError):
    """An index revision or content-addressed identity was reused incorrectly."""


def _query_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ProjectIndexStoreError(f"{field} must be a path-safe id")
    return value


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class ProjectContextIndexStore:
    """Persist indexes under an already scoped directory using descriptor I/O.

    The writer never follows a journal or lock symlink. A future CORE-backed
    service can pass the same trusted directory boundary; this cache itself
    does not resolve project paths or create an identity authority.
    """

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        if not _O_DIRECTORY or not _O_NOFOLLOW:
            raise ProjectIndexStoreError("safe directory descriptors are unavailable")
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            raise ProjectIndexStoreError("index store root must be absolute")
        if not self.root.exists():
            if not create:
                raise ProjectIndexStoreError("index store root is unavailable")
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ProjectIndexStoreError("index store root must be a real directory")
        self.journal_path = self.root / _JOURNAL_NAME
        self._lock = RLock()

    def append(self, index: ProjectContextIndex) -> ProjectContextIndex:
        if not isinstance(index, ProjectContextIndex):
            raise ProjectIndexStoreError("index must be a ProjectContextIndex")
        with self._locked_directory() as directory_fd:
            records = self._read_locked(directory_fd)
            same_id = [record for record in records if record.index_id == index.index_id]
            if same_id:
                current = max(same_id, key=lambda item: item.revision)
                if current.revision == index.revision:
                    if current.content_hash != index.content_hash:
                        raise ProjectIndexStoreConflict("index revision is bound to another content hash")
                    return current
                if index.revision != current.revision + 1:
                    raise ProjectIndexStoreConflict("index revisions must be contiguous")
                if index.previous_index_hash != current.content_hash:
                    raise ProjectIndexStoreConflict("previous_index_hash does not match the current revision")
            elif index.revision != 1:
                raise ProjectIndexStoreConflict("a new index id must start at revision one")
            self._append_locked(directory_fd, index)
            return index

    def read(self, index_id: str) -> ProjectContextIndex:
        identifier = _query_id(index_id, "index_id")
        history = self.history(identifier)
        if not history:
            raise KeyError(f"unknown project context index: {identifier}")
        return history[-1]

    def history(self, index_id: str) -> tuple[ProjectContextIndex, ...]:
        identifier = _query_id(index_id, "index_id")
        with self._locked_directory() as directory_fd:
            return tuple(record for record in self._read_locked(directory_fd) if record.index_id == identifier)

    def latest(self, *, project_id: str, run_family_id: str) -> ProjectContextIndex | None:
        project = _query_id(project_id, "project_id")
        family = _query_id(run_family_id, "run_family_id")
        with self._locked_directory() as directory_fd:
            matching = [
                record
                for record in self._read_locked(directory_fd)
                if record.project_id == project and record.run_family_id == family
            ]
        if not matching:
            return None
        return max(matching, key=lambda item: (item.revision, item.content_hash))

    def clear(self) -> None:
        """Delete this derived cache journal; canonical facts remain untouched."""
        with self._locked_directory() as directory_fd:
            try:
                os.unlink(_JOURNAL_NAME, dir_fd=directory_fd)
            except FileNotFoundError:
                return
            os.fsync(directory_fd)

    @contextmanager
    def _locked_directory(self) -> Iterator[int]:
        with self._lock:
            try:
                directory_fd = os.open(
                    os.fspath(self.root),
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                )
            except OSError as error:
                raise ProjectIndexStoreError("index store root could not be safely opened") from error
            lock_fd: int | None = None
            try:
                lock_fd = os.open(
                    _LOCK_NAME,
                    os.O_RDWR | os.O_CREAT | _O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield directory_fd
            except OSError as error:
                raise ProjectIndexStoreError("index store lock or I/O failed") from error
            finally:
                if lock_fd is not None:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    finally:
                        os.close(lock_fd)
                os.close(directory_fd)

    @staticmethod
    def _read_locked(directory_fd: int) -> list[ProjectContextIndex]:
        try:
            journal_fd = os.open(_JOURNAL_NAME, os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise ProjectIndexStoreError("index journal could not be opened") from error
        try:
            with os.fdopen(journal_fd, "rb") as handle:
                raw = handle.read(_MAX_JOURNAL_BYTES + 1)
        except OSError as error:
            raise ProjectIndexStoreError("index journal could not be read") from error
        if len(raw) > _MAX_JOURNAL_BYTES or (raw and not raw.endswith(b"\n")):
            raise ProjectIndexStoreError("index journal is truncated or too large")
        records: list[ProjectContextIndex] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=_strict_object_pairs)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                raise ProjectIndexStoreError(f"index journal line {line_number} is invalid") from error
            if not isinstance(event, dict) or set(event) != {"record_type", "index"}:
                raise ProjectIndexStoreError(f"index journal line {line_number} has invalid fields")
            if event["record_type"] != _RECORD_TYPE:
                raise ProjectIndexStoreError("index journal has an unsupported record type")
            try:
                records.append(ProjectContextIndex.from_dict(event["index"]))
            except (ProjectIndexError, TypeError) as error:
                raise ProjectIndexStoreError(f"index journal line {line_number} is invalid") from error
        return records

    @staticmethod
    def _append_locked(directory_fd: int, index: ProjectContextIndex) -> None:
        value = {"record_type": _RECORD_TYPE, "index": index.to_dict()}
        line = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            journal_fd = os.open(
                _JOURNAL_NAME,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(journal_fd, "ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(directory_fd)
        except OSError as error:
            raise ProjectIndexStoreError("index journal append failed") from error


__all__ = [
    "ProjectContextIndexStore",
    "ProjectIndexStoreConflict",
    "ProjectIndexStoreError",
]
