"""The single server-owned producer for local profile identity."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator
from uuid import uuid4

from ..canonical import canonical_json_v1
from .contracts import LocalProfileIdentity

try:  # pragma: no cover - the supported Workbench host is POSIX.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class IdentityStoreError(ValueError):
    """Base error for an identity authority store failure."""


class IdentityCollisionError(IdentityStoreError):
    """An immutable identity address already contains different content."""

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


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _canonical_bytes(value: dict[str, object]) -> bytes:
    return (canonical_json_v1(value) + "\n").encode("utf-8")


def _create_content_addressed(path: Path, value: dict[str, object]) -> None:
    expected = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise IdentityRecordCorruptError(
                f"cannot read content-addressed record: {path}"
            ) from exc
        if actual != expected:
            raise IdentityCollisionError(
                f"content-addressed record collision at {path.name}"
            )
        return
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _create_pointer(path: Path, value: dict[str, object]) -> bool:
    expected = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise IdentityRecordCorruptError(f"cannot read identity pointer: {path}") from exc
        if actual != expected:
            raise IdentityCollisionError(f"identity pointer collision at {path}")
        return False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _append_jsonl(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _canonical_bytes(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalProfileIdentityStore:
    """Issue exactly one local profile identity for one authority root."""

    def __init__(self, authority_root: Path | str) -> None:
        self.authority_root = Path(authority_root).expanduser().resolve()
        self.root = self.authority_root / "identity" / "local_profile"
        self.records_dir = self.root / "records"
        self.records_log_path = self.root / "records.jsonl"
        self.anchor_path = self.root / "current.json"
        self.lock_path = self.root / ".lock"
        self._lock = _process_lock(self.authority_root)

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
        with self._lock:
            with _file_lock(self.lock_path):
                current = self._read_current()
                if current is not None:
                    return current
                identity = LocalProfileIdentity(profile_id=f"profile_{uuid4().hex}")
                _create_content_addressed(
                    self.record_path(identity), identity.to_dict()
                )
                _create_pointer(self.anchor_path, {"record_hash": identity.content_hash})
                _append_jsonl(
                    self.records_log_path,
                    {
                        "contract_version": identity.contract_version,
                        "record_hash": identity.content_hash,
                    },
                )
                return identity

    ensure = get_or_create

    def get_current(self) -> LocalProfileIdentity | None:
        with self._lock:
            with _file_lock(self.lock_path):
                return self._read_current()

    current = get_current

    def record_path(self, identity: LocalProfileIdentity) -> Path:
        return self.records_dir / f"{identity.content_hash}.json"

    def _read_current(self) -> LocalProfileIdentity | None:
        if not self.anchor_path.exists():
            return None
        try:
            pointer = json.loads(self.anchor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IdentityRecordCorruptError(
                f"invalid local profile pointer: {self.anchor_path}"
            ) from exc
        if not isinstance(pointer, dict) or set(pointer) != {"record_hash"}:
            raise IdentityRecordCorruptError("local profile pointer has invalid fields")
        record_hash = pointer["record_hash"]
        if type(record_hash) is not str or len(record_hash) != 64:
            raise IdentityRecordCorruptError("local profile pointer has invalid hash")
        record_path = self.records_dir / f"{record_hash}.json"
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            identity = LocalProfileIdentity.from_dict(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IdentityRecordCorruptError(
                f"invalid local profile record: {record_path}"
            ) from exc
        if identity.content_hash != record_hash:
            raise IdentityCollisionError(
                f"local profile record does not match its content address: {record_hash}"
            )
        return identity


LocalProfileStore = LocalProfileIdentityStore


__all__ = [
    "IdentityClientClaimError",
    "IdentityCollisionError",
    "IdentityRecordCorruptError",
    "IdentityStoreError",
    "LocalProfileIdentityStore",
    "LocalProfileStore",
]
