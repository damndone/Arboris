"""The single server-owned producer for local profile identity.

All persistence is reached through an admission that owns trusted directory
descriptors.  Store methods never reopen a record through a caller-controlled
path.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised through the capability test
    fcntl = None  # type: ignore[assignment]

from ..canonical import canonical_json_v1
from .contracts import (
    LocalProfileIdentity,
    LocalProfileIdentityRevision,
)


_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_RECORD_NAME = re.compile(r"^[0-9a-f]{64}\.json\Z")
_ADMISSION_ISSUER = object()


class IdentityStoreError(ValueError):
    """Base error for an identity authority store failure."""


class IdentityCollisionError(IdentityStoreError):
    """An immutable identity address or scope contains conflicting content."""

    code = "IDENTITY_COLLISION"


class IdentityRecordCorruptError(IdentityStoreError):
    """A persisted identity object or pointer is malformed or tampered with."""

    code = "IDENTITY_RECORD_CORRUPT"


class IdentityClientClaimError(IdentityStoreError):
    """Client supplied identity fields are not accepted by the authority."""

    code = "IDENTITY_CLIENT_CLAIM_REJECTED"


_LOCKS: dict[Path, RLock] = {}
_LOCKS_GUARD = RLock()


def _process_lock(key: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, RLock())


def _close(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _validate_component(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise IdentityStoreError("identity storage component is unsafe")
    return value


def _require_fd_primitives() -> None:
    if (
        fcntl is None
        or not hasattr(fcntl, "flock")
        or not _O_DIRECTORY
        or not _O_NOFOLLOW
        or not _O_NONBLOCK
        or os.open not in os.supports_dir_fd
        or os.mkdir not in os.supports_dir_fd
        or os.unlink not in os.supports_dir_fd
        or os.lstat not in os.supports_dir_fd
    ):
        raise IdentityStoreError("identity FD admission is unsupported on this host")


def _open_directory(parent_fd: int, name: str) -> int:
    _validate_component(name)
    try:
        fd = os.open(
            name,
            os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except (OSError, ValueError) as exc:
        raise IdentityRecordCorruptError(
            "identity storage directory is missing or unsafe"
        ) from exc
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise IdentityRecordCorruptError("identity storage component is not a directory")
        return fd
    except BaseException:
        _close(fd)
        raise


def _open_or_create_directory(
    parent_fd: int, name: str, *, create: bool = True
) -> int | None:
    _validate_component(name)
    try:
        return _open_directory(parent_fd, name)
    except IdentityRecordCorruptError as exc:
        if not isinstance(exc.__cause__, FileNotFoundError):
            raise
        if not create:
            return None
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except (OSError, ValueError) as exc:
        raise IdentityStoreError("cannot create identity storage directory") from exc
    return _open_directory(parent_fd, name)


def _open_absolute_directory(path: Path, *, create: bool = True) -> int | None:
    _require_fd_primitives()
    if not path.is_absolute():
        raise IdentityStoreError("identity authority root must be absolute")
    try:
        path = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise IdentityStoreError("identity authority root cannot be canonicalized") from exc
    parts = tuple(part for part in path.parts if part not in {"", os.path.sep})
    current = os.open(os.path.sep, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        for part in parts:
            try:
                next_fd = os.open(
                    _validate_component(part),
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                    dir_fd=current,
                )
            except FileNotFoundError:
                if not create:
                    _close(current)
                    return None
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                except (OSError, ValueError) as exc:
                    raise IdentityStoreError(
                        "cannot create identity authority directory"
                    ) from exc
                next_fd = os.open(
                    part,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                    dir_fd=current,
                )
            except (OSError, ValueError) as exc:
                raise IdentityRecordCorruptError(
                    "identity authority root contains an unsafe component"
                ) from exc
            _close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise IdentityStoreError("identity authority root is not a directory")
        return current
    except BaseException:
        _close(current)
        raise


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(fd, content[offset:])
        except OSError as exc:
            raise IdentityStoreError("identity persistence write failed") from exc
        if written <= 0:
            raise IdentityStoreError("identity persistence write made no progress")
        offset += written


def _snapshot_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_fd_snapshot(fd: int, *, max_bytes: int = 1024 * 1024) -> bytes:
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 0 or before.st_size > max_bytes:
            raise IdentityRecordCorruptError("identity record is not a bounded regular file")
        os.lseek(fd, 0, os.SEEK_SET)
        content = bytearray()
        while len(content) <= before.st_size:
            chunk = os.read(fd, before.st_size + 1 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(fd)
    except (OSError, ValueError) as exc:
        raise IdentityRecordCorruptError("identity record cannot be read by FD") from exc
    if len(content) != before.st_size or _snapshot_identity(before) != _snapshot_identity(after):
        raise IdentityRecordCorruptError("identity record changed during FD read")
    return bytes(content)


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON is not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_json_object(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise IdentityRecordCorruptError("identity JSON is invalid") from exc
    if not isinstance(value, dict):
        raise IdentityRecordCorruptError("identity JSON must be an object")
    return value


def _parse_local_profile_record(value: dict[str, Any]) -> LocalProfileIdentity:
    try:
        return LocalProfileIdentity.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise IdentityRecordCorruptError("local profile record is invalid") from exc


def _parse_jsonl(content: bytes) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    complete_bytes = 0
    for line in content.splitlines(keepends=True):
        if not line.strip():
            raise IdentityRecordCorruptError("identity log line is not canonical")
        complete = line.endswith(b"\n")
        if not complete:
            break
        line_content = line[:-1]
        parsed = _parse_json_object(line_content)
        if line_content != _canonical_bytes(parsed).rstrip(b"\n"):
            raise IdentityRecordCorruptError("identity log line is not canonical")
        records.append(parsed)
        complete_bytes += len(line)
    if complete_bytes != len(content) and content[complete_bytes:].strip():
        return records, complete_bytes
    return records, len(content)


def _open_child_file(
    parent_fd: int,
    name: str,
    *,
    flags: int,
    mode: int = 0o600,
) -> int:
    _validate_component(name)
    for attempt in range(4):
        try:
            return os.open(
                name,
                flags | _O_NOFOLLOW | _O_NONBLOCK,
                mode,
                dir_fd=parent_fd,
            )
        except FileNotFoundError as exc:
            if attempt == 3:
                raise IdentityRecordCorruptError(
                    "identity file is missing or unsafe"
                ) from exc
            time.sleep(0.001)
        except (OSError, ValueError) as exc:
            raise IdentityRecordCorruptError("identity file is missing or unsafe") from exc


def _read_child(
    parent_fd: int,
    name: str,
    *,
    missing_is_none: bool = False,
) -> bytes | None:
    _validate_component(name)
    try:
        fd = os.open(
            name,
            os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        if missing_is_none:
            return None
        raise IdentityRecordCorruptError("identity file is missing")
    except (OSError, ValueError) as exc:
        raise IdentityRecordCorruptError("identity file is unsafe") from exc
    try:
        return _read_fd_snapshot(fd)
    finally:
        _close(fd)


def _unlink_child(parent_fd: int, name: str) -> None:
    _validate_component(name)
    try:
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except (OSError, ValueError) as exc:
        raise IdentityRecordCorruptError("identity derived file cannot be recovered") from exc


def _canonical_bytes(value: dict[str, object]) -> bytes:
    return (canonical_json_v1(value) + "\n").encode("utf-8")


def _create_content_addressed(
    admission: "_IdentityStoreAdmission", record_name: str, value: dict[str, object]
) -> None:
    admission.require()
    expected = _canonical_bytes(value)
    try:
        fd = os.open(
            _validate_component(record_name),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
            0o600,
            dir_fd=admission.records_fd,
        )
    except FileExistsError:
        actual = _read_child(admission.records_fd, record_name)
        if actual != expected:
            raise IdentityCollisionError(
                f"content-addressed record collision at {record_name}"
            )
        return
    except (OSError, ValueError) as exc:
        raise IdentityStoreError("cannot create content-addressed identity record") from exc
    try:
        _write_all(fd, expected)
        os.fsync(fd)
        os.fsync(admission.records_fd)
    except BaseException:
        _close(fd)
        raise
    else:
        _close(fd)


def _create_pointer(
    admission: "_IdentityStoreAdmission", value: dict[str, object]
) -> bool:
    admission.require()
    expected = _canonical_bytes(value)
    try:
        fd = os.open(
            "current.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
            0o600,
            dir_fd=admission.scope_fd,
        )
    except FileExistsError:
        actual = _read_child(admission.scope_fd, "current.json")
        if actual != expected:
            raise IdentityCollisionError("local profile pointer collision")
        return False
    except (OSError, ValueError) as exc:
        raise IdentityStoreError("cannot create local profile pointer") from exc
    try:
        _write_all(fd, expected)
        os.fsync(fd)
        os.fsync(admission.scope_fd)
    except BaseException:
        _close(fd)
        raise
    else:
        _close(fd)
        return True


def _append_jsonl(
    admission: "_IdentityStoreAdmission", value: dict[str, object]
) -> None:
    admission.require()
    line = _canonical_bytes(value)
    try:
        fd = os.open(
            "records.jsonl",
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | _O_NOFOLLOW | _O_NONBLOCK,
            0o600,
            dir_fd=admission.scope_fd,
        )
    except (OSError, ValueError) as exc:
        raise IdentityStoreError("cannot open identity journal") from exc
    try:
        _write_all(fd, line)
        os.fsync(fd)
        os.fsync(admission.scope_fd)
    finally:
        _close(fd)


def _truncate_jsonl(
    admission: "_IdentityStoreAdmission", complete_bytes: int
) -> None:
    admission.require()
    try:
        fd = os.open(
            "records.jsonl",
            os.O_WRONLY | _O_NOFOLLOW | _O_NONBLOCK,
            dir_fd=admission.scope_fd,
        )
        os.ftruncate(fd, complete_bytes)
        os.fsync(fd)
        os.fsync(admission.scope_fd)
    except (OSError, ValueError) as exc:
        raise IdentityStoreError("cannot recover identity journal") from exc
    finally:
        _close(locals().get("fd"))


def _list_record_names(admission: "_IdentityStoreAdmission") -> tuple[str, ...]:
    admission.require()
    try:
        names = os.listdir(admission.records_fd)
    except OSError as exc:
        raise IdentityRecordCorruptError("cannot enumerate identity records") from exc
    unsafe = [name for name in names if _RECORD_NAME.fullmatch(name) is None]
    if unsafe:
        raise IdentityRecordCorruptError("identity records directory contains unsafe names")
    return tuple(sorted(names))


def _reject_record_special(admission: "_IdentityStoreAdmission", name: str) -> None:
    try:
        record_stat = os.lstat(name, dir_fd=admission.records_fd)
    except (OSError, ValueError) as exc:
        raise IdentityRecordCorruptError("identity record cannot be inspected safely") from exc
    if not stat.S_ISREG(record_stat.st_mode):
        raise IdentityRecordCorruptError("identity records must be regular files")


@dataclass
class _IdentityStoreAdmission:
    token: object
    authority_binding: tuple[int, int]
    scope_fd: int
    records_fd: int

    def require(self) -> None:
        if self.token is not _ADMISSION_ISSUER:
            raise IdentityStoreError("identity FD admission is missing")


@contextmanager
def _open_store_admission(
    authority_root: Path,
    scope_name: str,
    process_lock: RLock,
    *,
    create: bool = True,
) -> Iterator[_IdentityStoreAdmission | None]:
    _require_fd_primitives()
    authority_fd: int | None = None
    identity_fd: int | None = None
    scope_fd: int | None = None
    lock_fd: int | None = None
    records_fd: int | None = None
    with process_lock:
        try:
            authority_fd = _open_absolute_directory(authority_root, create=create)
            if authority_fd is None:
                yield None
                return
            identity_fd = _open_or_create_directory(
                authority_fd, "identity", create=create
            )
            if identity_fd is None:
                yield None
                return
            scope_fd = _open_or_create_directory(
                identity_fd, scope_name, create=create
            )
            if scope_fd is None:
                yield None
                return
            try:
                lock_fd = _open_child_file(
                    scope_fd,
                    ".lock",
                    flags=os.O_RDWR | (os.O_CREAT if create else 0),
                )
            except IdentityRecordCorruptError as exc:
                if not create and isinstance(exc.__cause__, FileNotFoundError):
                    yield None
                    return
                raise
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise IdentityRecordCorruptError("identity lock is not a regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            records_fd = _open_or_create_directory(
                scope_fd, "records", create=create
            )
            if records_fd is None:
                yield None
                return
            authority_stat = os.fstat(authority_fd)
            admission = _IdentityStoreAdmission(
                _ADMISSION_ISSUER,
                (authority_stat.st_dev, authority_stat.st_ino),
                scope_fd,
                records_fd,
            )
            try:
                yield admission
            finally:
                _close(records_fd)
                records_fd = None
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            _close(lock_fd)
            _close(scope_fd)
            _close(identity_fd)
            _close(authority_fd)


def _read_record_objects(
    admission: _IdentityStoreAdmission,
    parser: Callable[[dict[str, Any]], object],
    referenced_hashes: set[str],
    *,
    recover_invalid_orphans: bool = True,
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for name in _list_record_names(admission):
        _reject_record_special(admission, name)
        try:
            raw = _read_child(admission.records_fd, name)
            assert raw is not None
            value = parser(_parse_json_object(raw))
            to_dict = getattr(value, "to_dict", None)
            if not callable(to_dict) or raw != _canonical_bytes(to_dict()):
                raise IdentityRecordCorruptError(
                    "identity record is not canonical"
                )
        except (IdentityRecordCorruptError, AssertionError):
            record_hash = name[:-5]
            if record_hash in referenced_hashes or not recover_invalid_orphans:
                raise
            try:
                os.unlink(name, dir_fd=admission.records_fd)
                os.fsync(admission.records_fd)
            except OSError as exc:
                raise IdentityRecordCorruptError(
                    "cannot remove an uncommitted identity record"
                ) from exc
            continue
        records.append({"name": name, "value": value})
    return tuple(records)


class LocalProfileIdentityStore:
    """Issue exactly one stable local profile identity for one authority root."""

    def __init__(self, authority_root: Path | str) -> None:
        self.authority_root = Path(authority_root).expanduser()
        if not self.authority_root.is_absolute():
            raise IdentityStoreError("identity authority root must be absolute")
        self._lock = _process_lock(Path(os.path.normpath(os.fspath(self.authority_root))))

    def _authority_binding(self) -> tuple[int, int]:
        with self._lock:
            authority_fd = _open_absolute_directory(self.authority_root)
            try:
                authority_stat = os.fstat(authority_fd)
                return authority_stat.st_dev, authority_stat.st_ino
            finally:
                _close(authority_fd)

    def get_or_create(
        self,
        *,
        profile_id: str | None = None,
        client_profile_id: str | None = None,
    ) -> LocalProfileIdentity:
        if profile_id is not None or client_profile_id is not None:
            raise IdentityClientClaimError(
                "local profile identity is issued by the server and cannot be claimed"
            )
        with _open_store_admission(self.authority_root, "local_profile", self._lock) as admission:
            return self._load_or_recover(admission)

    ensure = get_or_create

    def get_current(self, *, recover: bool = False) -> LocalProfileIdentity | None:
        with _open_store_admission(
            self.authority_root,
            "local_profile",
            self._lock,
            create=recover,
        ) as admission:
            if admission is None:
                return None
            return self._load_or_recover(admission, create=False, recover=recover)

    current = get_current

    def record_name(self, identity: LocalProfileIdentity) -> str:
        return f"{identity.content_hash}.json"

    def read_record_bytes(self, identity: LocalProfileIdentity) -> bytes:
        with _open_store_admission(
            self.authority_root, "local_profile", self._lock, create=False
        ) as admission:
            if admission is None:
                raise IdentityCollisionError(
                    "local profile record is outside the current scope"
                )
            current = self._load_or_recover(
                admission,
                create=False,
                recover=False,
                recover_invalid_orphans=False,
            )
            if not isinstance(identity, LocalProfileIdentity):
                raise IdentityRecordCorruptError("local profile identity is invalid")
            if current is None or current.content_hash != identity.content_hash:
                raise IdentityCollisionError("local profile record is outside the current scope")
            raw = _read_child(admission.records_fd, self.record_name(identity))
            if raw is None:
                raise IdentityRecordCorruptError("local profile record is missing")
            parsed = _parse_local_profile_record(_parse_json_object(raw))
            if parsed != current or raw != _canonical_bytes(parsed.to_dict()):
                raise IdentityRecordCorruptError("local profile record is not canonical")
            return raw

    def read_records_log_bytes(self) -> bytes:
        with _open_store_admission(
            self.authority_root, "local_profile", self._lock, create=False
        ) as admission:
            if admission is None:
                return b""
            self._load_or_recover(
                admission,
                create=False,
                recover=False,
                recover_invalid_orphans=False,
            )
            raw = _read_child(admission.scope_fd, "records.jsonl", missing_is_none=True)
            return raw or b""

    def content_addressed_record_names(self) -> tuple[str, ...]:
        with _open_store_admission(
            self.authority_root, "local_profile", self._lock, create=False
        ) as admission:
            if admission is None:
                return ()
            self._load_or_recover(
                admission,
                create=False,
                recover=False,
                recover_invalid_orphans=False,
            )
            return _list_record_names(admission)

    def _load_or_recover(
        self,
        admission: _IdentityStoreAdmission,
        *,
        create: bool = True,
        recover: bool = True,
        recover_invalid_orphans: bool = True,
    ) -> LocalProfileIdentity | None:
        if not recover:
            recover_invalid_orphans = False
        log_raw = _read_child(admission.scope_fd, "records.jsonl", missing_is_none=True)
        lifecycle: list[LocalProfileIdentityRevision] = []
        if log_raw is not None:
            parsed, complete_bytes = _parse_jsonl(log_raw)
            if complete_bytes != len(log_raw):
                if not recover:
                    raise IdentityRecordCorruptError(
                        "local profile lifecycle log is incomplete"
                    )
                _truncate_jsonl(admission, complete_bytes)
            try:
                lifecycle = [LocalProfileIdentityRevision.from_dict(item) for item in parsed]
            except (IdentityRecordCorruptError, TypeError, ValueError) as exc:
                raise IdentityRecordCorruptError("local profile lifecycle is invalid") from exc
            self._validate_lifecycle(lifecycle)
        referenced = {item.identity_hash for item in lifecycle}
        objects = _read_record_objects(
            admission,
            _parse_local_profile_record,
            referenced,
            recover_invalid_orphans=recover_invalid_orphans,
        )
        identities = [item["value"] for item in objects]
        for item in objects:
            name = str(item["name"])
            identity = item["value"]
            if name[:-5] != identity.content_hash:
                raise IdentityCollisionError(
                    f"local profile record does not match its content address: {name}"
                )
        if len({identity.content_hash for identity in identities}) > 1:
            raise IdentityCollisionError("local profile scope has multiple identities")
        identity = identities[0] if identities else None
        if lifecycle:
            current_hash = lifecycle[-1].identity_hash
            matching = [item for item in identities if item.content_hash == current_hash]
            if len(matching) != 1:
                raise IdentityRecordCorruptError("local profile lifecycle points to missing identity")
            candidate = matching[0]
            if any(item.profile_id != candidate.profile_id for item in lifecycle):
                raise IdentityCollisionError("local profile lifecycle scope is inconsistent")
            identity = candidate
            if any(item.identity_hash != identity.content_hash for item in lifecycle):
                raise IdentityCollisionError("local profile lifecycle changes stable identity")
        if identity is None:
            if not create:
                orphan_pointer = _read_child(
                    admission.scope_fd, "current.json", missing_is_none=True
                )
                if orphan_pointer is not None:
                    raise IdentityRecordCorruptError(
                        "local profile pointer exists without an identity record"
                    )
                return None
            identity = LocalProfileIdentity(profile_id=f"profile_{uuid4().hex}")
            _create_content_addressed(admission, self.record_name(identity), identity.to_dict())
        if not lifecycle:
            if not recover:
                raise IdentityRecordCorruptError(
                    "local profile lifecycle is missing"
                )
            lifecycle_record = LocalProfileIdentityRevision(
                profile_id=identity.profile_id,
                revision=1,
                identity_hash=identity.content_hash,
            )
            _append_jsonl(admission, lifecycle_record.to_dict())
            lifecycle = [lifecycle_record]
        pointer = _read_child(admission.scope_fd, "current.json", missing_is_none=True)
        expected_pointer = {
            "identity_hash": identity.content_hash,
            "revision": lifecycle[-1].revision,
            "revision_record_hash": lifecycle[-1].content_hash,
        }
        if pointer is None:
            if not recover:
                raise IdentityRecordCorruptError("local profile pointer is missing")
            _create_pointer(admission, expected_pointer)
        else:
            if pointer != _canonical_bytes(expected_pointer):
                raise IdentityRecordCorruptError(
                    "local profile pointer is not canonical"
                )
            actual_pointer = _parse_json_object(pointer)
            if actual_pointer != expected_pointer:
                raise IdentityCollisionError(
                    "local profile pointer conflicts with lifecycle"
                )
        return identity

    @staticmethod
    def _validate_lifecycle(records: list[LocalProfileIdentityRevision]) -> None:
        if not records:
            return
        for expected, record in enumerate(records, start=1):
            if record.revision != expected:
                raise IdentityCollisionError("local profile lifecycle has a revision gap or fork")
            if expected > 1 and record.previous_revision != expected - 1:
                raise IdentityCollisionError("local profile lifecycle chain is broken")


LocalProfileStore = LocalProfileIdentityStore


__all__ = [
    "IdentityClientClaimError",
    "IdentityCollisionError",
    "IdentityRecordCorruptError",
    "IdentityStoreError",
    "LocalProfileIdentityStore",
    "LocalProfileStore",
]
