"""Private, append-safe local settings for opt-in domain memory.

This is deliberately separate from memory content journals.  A preference only
answers whether a scope may participate in future retrieval or candidate
generation; it never stores a raw project path or memory content.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from .scope import MemoryScope


class LocalMemoryPreferenceError(ValueError):
    """Local memory settings are absent, corrupt, stale, or unsafe."""


@dataclass(frozen=True, slots=True)
class GlobalMemorySettings:
    revision: int = 0
    library_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 0:
            raise LocalMemoryPreferenceError("global preference revision is invalid")
        if type(self.library_enabled) is not bool:
            raise LocalMemoryPreferenceError("global library setting must be boolean")


@dataclass(frozen=True, slots=True)
class ProjectMemorySettings:
    scope_ref: str
    revision: int = 0
    library_enabled: bool = False
    inherit_global: bool = False
    candidate_generation_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope_ref, str) or not self.scope_ref or len(self.scope_ref) > 256:
            raise LocalMemoryPreferenceError("project preference scope is invalid")
        if type(self.revision) is not int or self.revision < 0:
            raise LocalMemoryPreferenceError("project preference revision is invalid")
        for value in (self.library_enabled, self.inherit_global, self.candidate_generation_enabled):
            if type(value) is not bool:
                raise LocalMemoryPreferenceError("project library settings must be booleans")


_PREFERENCES_FILE = ".domain-memory-preferences-v1.json"
_LOCK_FILE = ".domain-memory-preferences-v1.lock"
_SCHEMA_VERSION = 1
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class LocalMemoryPreferenceStore:
    """CAS-updated, private settings keyed only by opaque ``scope_ref`` values."""

    def __init__(self, base_dir: Path | str) -> None:
        if not _O_DIRECTORY or not _O_NOFOLLOW:
            raise LocalMemoryPreferenceError("safe directory descriptors are unavailable")
        self.base_dir = Path(base_dir).expanduser()
        if (
            not self.base_dir.is_absolute()
            or not self.base_dir.is_dir()
            or any(path.is_symlink() for path in (self.base_dir, *self.base_dir.parents))
        ):
            raise LocalMemoryPreferenceError("local preference root is unavailable")
        self._lock = RLock()

    def global_settings(self) -> GlobalMemorySettings:
        document = self._read()
        return self._global_from(document["global"])

    def project_settings(self, scope: MemoryScope) -> ProjectMemorySettings:
        scope_ref = self._project_scope_ref(scope)
        document = self._read()
        value = document["projects"].get(scope_ref)
        if value is None:
            return ProjectMemorySettings(scope_ref=scope_ref)
        return self._project_from(scope_ref, value)

    def update_global(self, *, expected_revision: int, library_enabled: bool) -> GlobalMemorySettings:
        if type(expected_revision) is not int or expected_revision < 0 or type(library_enabled) is not bool:
            raise LocalMemoryPreferenceError("global preference update is invalid")
        with self._locked_directory() as directory_fd:
            document = self._read_locked(directory_fd)
            current = self._global_from(document["global"])
            if current.revision != expected_revision:
                raise LocalMemoryPreferenceError("global preference revision is stale")
            updated = GlobalMemorySettings(revision=current.revision + 1, library_enabled=library_enabled)
            document["global"] = self._global_dict(updated)
            self._write_locked(directory_fd, document)
            return updated

    def update_project(
        self,
        scope: MemoryScope,
        *,
        expected_revision: int,
        library_enabled: bool,
        inherit_global: bool,
        candidate_generation_enabled: bool,
    ) -> ProjectMemorySettings:
        scope_ref = self._project_scope_ref(scope)
        if type(expected_revision) is not int or expected_revision < 0:
            raise LocalMemoryPreferenceError("project preference revision is invalid")
        with self._locked_directory() as directory_fd:
            document = self._read_locked(directory_fd)
            current = self._project_from(scope_ref, document["projects"].get(scope_ref, {}))
            if current.revision != expected_revision:
                raise LocalMemoryPreferenceError("project preference revision is stale")
            updated = ProjectMemorySettings(
                scope_ref=scope_ref,
                revision=current.revision + 1,
                library_enabled=library_enabled,
                inherit_global=inherit_global,
                candidate_generation_enabled=candidate_generation_enabled,
            )
            document["projects"][scope_ref] = self._project_dict(updated)
            self._write_locked(directory_fd, document)
            return updated

    @staticmethod
    def _project_scope_ref(scope: MemoryScope) -> str:
        if not isinstance(scope, MemoryScope) or scope.visibility_scope != "private":
            raise LocalMemoryPreferenceError("a private project scope is required")
        return scope.scope_ref

    @staticmethod
    def _global_from(value: Any) -> GlobalMemorySettings:
        if not isinstance(value, dict) or set(value) != {"revision", "library_enabled"}:
            raise LocalMemoryPreferenceError("global preference document is invalid")
        return GlobalMemorySettings(**value)

    @staticmethod
    def _project_from(scope_ref: str, value: Any) -> ProjectMemorySettings:
        if value == {}:
            return ProjectMemorySettings(scope_ref=scope_ref)
        if not isinstance(value, dict) or set(value) != {
            "revision", "library_enabled", "inherit_global", "candidate_generation_enabled"
        }:
            raise LocalMemoryPreferenceError("project preference document is invalid")
        return ProjectMemorySettings(scope_ref=scope_ref, **value)

    @staticmethod
    def _global_dict(value: GlobalMemorySettings) -> dict[str, Any]:
        return {"revision": value.revision, "library_enabled": value.library_enabled}

    @staticmethod
    def _project_dict(value: ProjectMemorySettings) -> dict[str, Any]:
        return {
            "revision": value.revision,
            "library_enabled": value.library_enabled,
            "inherit_global": value.inherit_global,
            "candidate_generation_enabled": value.candidate_generation_enabled,
        }

    @staticmethod
    def _default_document() -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "global": {"revision": 0, "library_enabled": False},
            "projects": {},
        }

    def _read(self) -> dict[str, Any]:
        with self._locked_directory() as directory_fd:
            return self._read_locked(directory_fd)

    def _read_locked(self, directory_fd: int) -> dict[str, Any]:
        try:
            file_fd = os.open(_PREFERENCES_FILE, os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError:
            return self._default_document()
        except OSError as error:
            raise LocalMemoryPreferenceError("preference document could not be safely opened") from error
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) > 1024 * 1024:
                    raise LocalMemoryPreferenceError("preference document is too large")
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LocalMemoryPreferenceError("preference document is corrupt") from error
        finally:
            os.close(file_fd)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "global", "projects"}
            or value.get("schema_version") != _SCHEMA_VERSION
            or not isinstance(value.get("projects"), dict)
        ):
            raise LocalMemoryPreferenceError("preference document is invalid")
        self._global_from(value["global"])
        for scope_ref, item in value["projects"].items():
            self._project_from(scope_ref, item)
        return value

    def _write_locked(self, directory_fd: int, document: dict[str, Any]) -> None:
        encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = f".{_PREFERENCES_FILE}.{os.getpid()}.tmp"
        try:
            temp_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                offset = 0
                while offset < len(encoded):
                    written = os.write(temp_fd, encoded[offset:])
                    if written <= 0:
                        raise OSError("preference document write made no progress")
                    offset += written
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
            os.replace(temporary, _PREFERENCES_FILE, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError as error:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            raise LocalMemoryPreferenceError("preference document could not be written") from error

    def _locked_directory(self):
        return _PreferenceDirectoryLock(self.base_dir, self._lock)


class _PreferenceDirectoryLock:
    def __init__(self, directory: Path, lock: RLock) -> None:
        self.directory = directory
        self.lock = lock
        self.directory_fd: int | None = None
        self.lock_fd: int | None = None

    def __enter__(self) -> int:
        self.lock.acquire()
        try:
            self.directory_fd = os.open(os.fspath(self.directory), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
            self.lock_fd = os.open(_LOCK_FILE, os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600, dir_fd=self.directory_fd)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX)
            return self.directory_fd
        except OSError as error:
            self.__exit__(None, None, None)
            raise LocalMemoryPreferenceError("preference root could not be safely locked") from error

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if self.lock_fd is not None:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
        finally:
            self.lock_fd = None
            if self.directory_fd is not None:
                os.close(self.directory_fd)
            self.directory_fd = None
            self.lock.release()


__all__ = [
    "GlobalMemorySettings",
    "LocalMemoryPreferenceError",
    "LocalMemoryPreferenceStore",
    "ProjectMemorySettings",
]
