"""Opt-in, scoped journals of business IDs and timestamps, never tool results.

Owners bind each allocation to its slot and the digest of its request/state.
Replay has no value factory fallback. Real lease and timeout clocks do not use
this module. Child tasks inherit the context, but cannot use it after exit.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from threading import RLock
from typing import Any, Callable, Iterator, Literal

from ..identity.root import open_validated_project_root
from ..jsonl_store import jsonl_lines


class BusinessIdentityError(ValueError):
    """A business allocation cannot be recorded or replayed faithfully."""


_HEADER = {"kind": "header", "schema": "workbench.business-identity", "version": 1}
_TOKEN = re.compile(r"[a-z][a-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_active: ContextVar[_IdentityJournal | None] = ContextVar("business_identity", default=None)


def _snapshot(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _snapshot(item) for key, item in value.items()}
    if type(value) is list:
        return [_snapshot(item) for item in value]
    raise BusinessIdentityError("business identity inputs must be finite JSON values")


def _encode(value: Any) -> bytes:
    try:
        return json.dumps(_snapshot(value), sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, TypeError) as error:
        raise BusinessIdentityError("business identity requires finite UTF-8 JSON") from error


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise BusinessIdentityError("duplicate business identity field")
        out[key] = value
    return out


class _IdentityJournal:
    def __init__(self, mode: str, root: Path | str, name: str):
        self.mode = mode
        self.root = Path(root)
        self.name = name
        self.fd = None
        self.closed = False
        self.failed = False
        self.lock = RLock()
        self.size = 0
        self.index = 0
        self.previous = None
        self.cursor = 0
        self.process_id = os.getpid()
        self.values: list[dict[str, Any]] = []
        if (mode not in {"record", "replay"} or not self.root.is_absolute() or ".." in self.root.parts
                or type(name) is not str or not name or name in {".", ".."}
                or any(c in name for c in ("/", "\\", "\0"))):
            raise BusinessIdentityError("invalid business identity journal mode or path")
        try:
            with open_validated_project_root(self.root) as admitted:
                if admitted.validated.path != self.root:
                    raise BusinessIdentityError("business identity directory must not contain symlinks")
                self.binding = admitted.validated.binding_key
                flags = os.O_NOFOLLOW | os.O_NONBLOCK
                flags |= os.O_WRONLY | os.O_CREAT | os.O_EXCL if mode == "record" else os.O_RDONLY
                self.fd = os.open(name, flags, 0o600, dir_fd=admitted.fd)
                observed = os.fstat(self.fd)
                if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                    raise BusinessIdentityError("business identity journal must be one regular file")
                self.identity = observed.st_dev, observed.st_ino
                fcntl.flock(self.fd, (fcntl.LOCK_EX if mode == "record" else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                if mode == "record":
                    os.fsync(admitted.fd)
            if mode == "record":
                self._append(_HEADER)
            else:
                self._load()
        except (OSError, ValueError, UnicodeError, TypeError) as error:
            self.close()
            if isinstance(error, BusinessIdentityError):
                raise
            raise BusinessIdentityError("business identity journal is unsafe, corrupt or unavailable") from error

    @property
    def remaining(self) -> int:
        return len(self.values) - self.cursor if self.mode == "replay" else 0

    def _validate(self, admitted) -> None:
        if admitted.validated.path != self.root or admitted.validated.binding_key != self.binding:
            raise BusinessIdentityError("business identity directory binding changed")
        current = os.stat(self.name, dir_fd=admitted.fd, follow_symlinks=False)
        observed = os.fstat(self.fd)
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or observed.st_nlink != 1
                or (current.st_dev, current.st_ino) != self.identity
                or (observed.st_dev, observed.st_ino) != self.identity):
            raise BusinessIdentityError("business identity file binding changed")

    def _append(self, payload: dict[str, Any]) -> None:
        body = {"index": self.index, "previous_sha256": self.previous, "payload": payload}
        digest = hashlib.sha256(_encode(body)).hexdigest()
        raw = _encode({**body, "sha256": digest}) + b"\n"
        try:
            with open_validated_project_root(self.root) as admitted:
                self._validate(admitted)
                if os.fstat(self.fd).st_size != self.size:
                    raise BusinessIdentityError("business identity journal changed outside its writer")
                view = memoryview(raw)
                while view:
                    written = os.write(self.fd, view)
                    if written <= 0:
                        raise OSError("short identity journal write")
                    view = view[written:]
                os.fsync(self.fd)
                os.fsync(admitted.fd)
        except (OSError, ValueError) as error:
            self.failed = True
            raise BusinessIdentityError("business identity journal write failed") from error
        self.previous = digest
        self.index += 1
        self.size += len(raw)

    def _load(self) -> None:
        with open_validated_project_root(self.root) as admitted:
            self._validate(admitted)
            before = os.fstat(self.fd)
            chunks = []
            while chunk := os.read(self.fd, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(self.fd)
            self._validate(admitted)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise BusinessIdentityError("business identity journal changed while reading")
        raw = b"".join(chunks)
        if not raw.endswith(b"\n"):
            raise BusinessIdentityError("incomplete business identity journal")
        payloads = []
        previous = None
        for index, line in enumerate(jsonl_lines(raw)):
            row = json.loads(line, object_pairs_hook=_object)
            if (type(row) is not dict or set(row) != {"index", "previous_sha256", "payload", "sha256"}
                    or type(row["index"]) is not int or row["index"] != index or row["previous_sha256"] != previous):
                raise BusinessIdentityError("invalid business identity journal sequence")
            body = {k: row[k] for k in ("index", "previous_sha256", "payload")}
            previous = hashlib.sha256(_encode(body)).hexdigest()
            if row["sha256"] != previous:
                raise BusinessIdentityError("corrupt business identity journal digest")
            payloads.append(row["payload"])
        if (len(payloads) < 2 or payloads[0] != _HEADER or type(payloads[0].get("version")) is not int
                or payloads[-1] != {"kind": "end", "count": len(payloads) - 2}
                or type(payloads[-1].get("count")) is not int):
            raise BusinessIdentityError("incomplete business identity journal")
        for row in payloads[1:-1]:
            if (type(row) is not dict or set(row) != {"kind", "owner", "slot", "input_sha256", "value"}
                    or row["kind"] != "value" or not self._token(row["owner"]) or not self._token(row["slot"])
                    or type(row["input_sha256"]) is not str or not _DIGEST.fullmatch(row["input_sha256"])
                    or not self._value(row["value"])):
                raise BusinessIdentityError("invalid business identity allocation")
        self.values = payloads[1:-1]
        self.read_state = after.st_size, after.st_mtime_ns

    @staticmethod
    def _token(value: Any) -> bool:
        return type(value) is str and bool(_TOKEN.fullmatch(value))

    @staticmethod
    def _value(value: Any) -> bool:
        return type(value) is str and 0 < len(value) <= 512

    def allocate(self, owner: str, slot: str, inputs: Any, create: Callable[[], str]) -> str:
        with self.lock:
            if self.closed or self.failed or os.getpid() != self.process_id:
                raise BusinessIdentityError("business identity scope is closed or failed")
            if not self._token(owner) or not self._token(slot):
                raise BusinessIdentityError("business identity owner and slot must be explicit tokens")
            key = {"kind": "value", "owner": owner, "slot": slot,
                   "input_sha256": hashlib.sha256(_encode(inputs)).hexdigest()}
            if self.mode == "replay":
                try:
                    with open_validated_project_root(self.root) as admitted:
                        self._validate(admitted)
                        observed = os.fstat(self.fd)
                        if (observed.st_size, observed.st_mtime_ns) != self.read_state:
                            raise BusinessIdentityError("business identity journal changed after loading")
                except (OSError, ValueError) as error:
                    self.failed = True
                    raise BusinessIdentityError("business identity journal changed after loading") from error
                if not self.remaining:
                    self.failed = True
                    raise BusinessIdentityError("business identity replay exhausted")
                row = self.values[self.cursor]
                if any(row[k] != v for k, v in key.items()):
                    self.failed = True
                    raise BusinessIdentityError(f"business identity mismatch at allocation {self.cursor}: {owner}/{slot}")
                self.cursor += 1
                return row["value"]
            try:
                value = create()
                if not self._value(value):
                    raise BusinessIdentityError("business identity factory must return a bounded string")
                self._append({**key, "value": value})
                self.cursor += 1
                return value
            except BaseException:
                self.failed = True
                raise

    def finish(self) -> None:
        with self.lock:
            if self.closed or self.failed:
                raise BusinessIdentityError("business identity scope is closed or failed")
            if self.mode == "record":
                self._append({"kind": "end", "count": self.cursor})
            elif self.remaining:
                raise BusinessIdentityError(f"business identity replay has {self.remaining} unconsumed allocations")

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None


@contextmanager
def business_identity_scope(*, mode: Literal["record", "replay"], root: Path | str,
                            name: str) -> Iterator[_IdentityJournal]:
    """Use one explicit journal; normal exit requires a complete consumption."""
    if _active.get() is not None:
        raise BusinessIdentityError("business identity scopes cannot be nested")
    journal = _IdentityJournal(mode, root, name)
    token = _active.set(journal)
    try:
        yield journal
        journal.finish()
    finally:
        journal.close()
        _active.reset(token)


def identity_value(*, owner: str, slot: str, inputs: Any, create: Callable[[], str]) -> str:
    """Allocate normally outside a scope; otherwise record/replay this owner slot."""
    journal = _active.get()
    return create() if journal is None else journal.allocate(owner, slot, inputs, create)
