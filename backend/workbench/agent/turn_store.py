"""Compact durable turn checkpoints; this module never runs or replays a turn.

Session entries own all prompt, queue and result content. Per-turn files retain
only references and recovery state. Mutations use a project directory lock,
version CAS and expiring, fenced ownership. Filesystem operations follow the
descriptor-anchored O_NOFOLLOW/atomic-replace pattern in local_preferences.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

TERMINAL = frozenset({"completed", "failed", "cancelled"})
TRANSITIONS = {
    "accepted": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"awaiting_approval", "interrupted", *TERMINAL}),
    "awaiting_approval": frozenset({"running", "failed", "cancelled"}),
    "interrupted": frozenset({"running", "completed", "failed", "cancelled"}),
    **{status: frozenset() for status in TERMINAL},
}
_MAX_BYTES = 128 * 1024
_MAX_ITEMS = 256


class TurnStoreError(ValueError):
    """Invalid, unsafe, stale, unowned or unreconciled durable turn state."""


class TurnStoreWriteError(TurnStoreError):
    """A failed write; reload after a visible replacement, never replay input.

    replacement_visible=True means rename succeeded but durability could not be
    confirmed. It does not mean the directory fsync succeeded.
    """

    def __init__(self, *, replacement_visible: bool) -> None:
        self.replacement_visible = replacement_visible
        super().__init__("turn write failed; reload durable state before retrying")


@dataclass(eq=False)
class TurnExecutionGuard:
    """Opaque live local-process ownership, issued only by execution_guard."""

    _store: Any
    session_id: str
    _directory_identity: tuple[int, int]
    _pid: int
    _fd: int
    _directory_fd: int
    _file_identity: tuple[int, int]
    _filename: str
    _active: bool = True


def _identifier(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 200
            or value in {".", ".."} or any(char in value for char in ("/", "\\", "\x00"))):
        raise TurnStoreError("turn/session identifier is unsafe")
    return value


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise TurnStoreError("reference or owner is invalid")
    return value


def _number(value: Any, *, integer: bool = False, positive: bool = False) -> None:
    if type(value) not in ({int} if integer else {int, float}):
        raise TurnStoreError("budget, version or lease value is invalid")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        raise TurnStoreError("budget, version or lease value is invalid")


def _references(value: dict[str, str]) -> None:
    if not isinstance(value, dict) or len(value) > 16:
        raise TurnStoreError("checkpoint/evidence must be compact references")
    for key, reference in value.items():
        _text(key)
        _text(reference)


def _reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TurnStoreError("duplicate turn document key")
        result[key] = value
    return result


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    command_id: str
    session_id: str
    input_entry_id: str
    execution_mode: str
    budget: dict[str, int | float]
    version: int = 1
    status: str = "accepted"
    steps_used: int = 0
    wall_s_used: float = 0.0
    checkpoint: dict[str, str] | None = None
    reconciliation: dict[str, str] | None = None
    tool_calls: dict[str, dict[str, Any]] | None = None
    queue: list[dict[str, Any]] | None = None
    cancel_requested: bool = False
    requires_reconcile: bool = False
    lease_owner: str | None = None
    lease_epoch: int = 0
    lease_expires_at: float | None = None
    schema_version: str = "agent.turn.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _record(value: Any) -> TurnRecord:
    if not isinstance(value, dict) or set(value) != {field.name for field in fields(TurnRecord)}:
        raise TurnStoreError("turn document has an invalid shape")
    record = TurnRecord(**value)
    for identifier in (record.turn_id, record.command_id, record.session_id):
        _identifier(identifier)
    _text(record.input_entry_id)
    if (record.schema_version != "agent.turn.v1" or record.status not in TRANSITIONS
            or record.execution_mode not in {"ask", "auto"}):
        raise TurnStoreError("turn document has an invalid lifecycle")
    _number(record.version, integer=True, positive=True)
    _number(record.lease_epoch, integer=True)
    _number(record.steps_used, integer=True)
    _number(record.wall_s_used)
    if not isinstance(record.budget, dict) or set(record.budget) != {"max_steps", "timeout_s"}:
        raise TurnStoreError("budget must declare max_steps and timeout_s")
    _number(record.budget["max_steps"], integer=True, positive=True)
    _number(record.budget["timeout_s"], positive=True)
    if type(record.cancel_requested) is not bool or type(record.requires_reconcile) is not bool:
        raise TurnStoreError("turn flags are invalid")
    if record.requires_reconcile and record.status != "interrupted":
        raise TurnStoreError("reconciliation state is invalid")
    if record.lease_owner is None:
        if record.lease_expires_at is not None:
            raise TurnStoreError("unowned lease has an expiry")
    else:
        _text(record.lease_owner)
        _number(record.lease_expires_at, positive=True)
        if record.status in TERMINAL or record.lease_epoch < 1:
            raise TurnStoreError("terminal or unfenced lease is invalid")
    _references(record.checkpoint)
    _references(record.reconciliation)
    if not isinstance(record.tool_calls, dict) or len(record.tool_calls) > _MAX_ITEMS:
        raise TurnStoreError("tool references are invalid or full")
    for call_id, call in record.tool_calls.items():
        _text(call_id)
        if not isinstance(call, dict) or set(call) != {"operation_key", "status", "checkpoint", "evidence"}:
            raise TurnStoreError("tool checkpoint is invalid")
        if call["operation_key"] is not None:
            _text(call["operation_key"])
        _references(call["checkpoint"])
        _references(call["evidence"])
        if call["status"] not in {"pending", "resolved"}:
            raise TurnStoreError("tool state is invalid")
        if call["status"] == "resolved" and (call["operation_key"] is None or not call["evidence"]):
            raise TurnStoreError("resolved tool lacks reconciliation evidence")
    if not isinstance(record.queue, list) or len(record.queue) > _MAX_ITEMS:
        raise TurnStoreError("queue references are invalid or full")
    ids = set()
    for item in record.queue:
        if not isinstance(item, dict) or set(item) != {"message_id", "kind", "entry_id", "consumed"}:
            raise TurnStoreError("queue item is invalid")
        _text(item["message_id"])
        _text(item["entry_id"])
        if item["message_id"] in ids or item["kind"] not in {"steer", "follow_up"} or type(item["consumed"]) is not bool:
            raise TurnStoreError("queue identity or consumption marker is invalid")
        ids.add(item["message_id"])
    if record.status == "running" and record.lease_owner is None:
        raise TurnStoreError("running turn has no owner")
    if record.status in {*TERMINAL, "awaiting_approval"} and any(
            call["status"] == "pending" for call in record.tool_calls.values()):
        raise TurnStoreError("paused or terminal turn has unresolved execution")
    return record


class TurnStore:
    """Persist references under ``project/workbench/agent-turns/<turn_id>.json``.

    A claim grants storage ownership only; approval, execution, session-entry
    admission and operation reconciliation remain the caller's responsibility.
    """

    def __init__(self, project_root: Path | str, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(project_root).expanduser()
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise TurnStoreError("turn store requires an absolute safe project directory")
        self._clock = clock
        self._lock = RLock()
        self._identity: tuple[int, int] | None = None
        self._execution_guards: dict[str, TurnExecutionGuard] = {}
        with self._locked():
            pass

    @contextmanager
    def _locked(self) -> Iterator[int]:
        """Walk every ancestor without following links; never reopen raw paths."""
        directory_fd = lock_fd = None
        with self._lock:
            try:
                directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                for index, part in enumerate((*self.root.parts[1:], "workbench", "agent-turns")):
                    try:
                        child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    except FileNotFoundError:
                        if index < len(self.root.parts) - 1:
                            raise
                        try:
                            os.mkdir(part, 0o700, dir_fd=directory_fd)
                            os.fsync(directory_fd)
                        except FileExistsError:
                            pass  # Another opener created it; the no-follow open still admits it.
                        child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = child_fd
                info = os.fstat(directory_fd)
                identity = (info.st_dev, info.st_ino)
                if self._identity is not None and identity != self._identity:
                    raise TurnStoreError("turn directory was replaced")
                self._identity = identity
                flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
                try:
                    lock_fd = os.open(".state.lock", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
                except FileExistsError:
                    lock_fd = os.open(".state.lock", flags, dir_fd=directory_fd)
                self._regular(lock_fd)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield directory_fd
            except (OSError, UnicodeError) as exc:
                raise TurnStoreError("turn storage could not be safely accessed") from exc
            finally:
                if lock_fd is not None:
                    os.close(lock_fd)
                if directory_fd is not None:
                    os.close(directory_fd)

    @staticmethod
    def _regular(fd: int) -> None:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TurnStoreError("turn storage requires a single-link regular file")

    @contextmanager
    def execution_guard(self, session_id: str) -> Iterator[TurnExecutionGuard]:
        """Hold a nonblocking per-session OS lock, independently of JSON leases.

        Only acquisition uses the short state lock. The stable lock file is
        never unlinked, and retained descriptors anchor the guard to its inode.
        This is local execution ownership, not a distributed authority boundary.
        """
        session_id = _identifier(session_id)
        filename = f".execution.{hashlib.sha256(session_id.encode('utf-8')).hexdigest()}.lock"
        lock_fd = directory_copy = None
        guard = None
        try:
            try:
                with self._locked() as directory_fd:
                    if session_id in self._execution_guards:
                        raise TurnStoreError("session execution is already owned")
                    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
                    try:
                        lock_fd = os.open(filename, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
                        os.fsync(directory_fd)
                    except FileExistsError:
                        lock_fd = os.open(filename, flags, dir_fd=directory_fd)
                    self._regular(lock_fd)
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as exc:
                        raise TurnStoreError("session execution is already owned") from exc
                    directory_copy = os.dup(directory_fd)
                    info = os.fstat(lock_fd)
                    guard = TurnExecutionGuard(self, session_id, self._identity, os.getpid(), lock_fd,
                                               directory_copy, (info.st_dev, info.st_ino), filename)
                    self._execution_guards[session_id] = guard
            except (OSError, UnicodeError) as exc:
                raise TurnStoreError("session execution guard could not be safely acquired") from exc
            yield guard
        finally:
            with self._lock:
                if guard is not None:
                    guard._active = False
                    if self._execution_guards.get(session_id) is guard:
                        self._execution_guards.pop(session_id)
                # Closing, rather than explicitly unlocking, cannot unlock the
                # parent's shared open-file description from a forked child.
                for fd in (lock_fd, directory_copy):
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass

    def _validate_execution_guard(self, guard: TurnExecutionGuard, session_id: str) -> None:
        """Caller holds _locked, which has revalidated the current directory."""
        if (type(guard) is not TurnExecutionGuard or guard._store is not self
                or guard.session_id != session_id or guard._pid != os.getpid() or not guard._active
                or self._execution_guards.get(session_id) is not guard
                or guard._directory_identity != self._identity):
            raise TurnStoreError("invalid or inactive session execution guard")
        try:
            directory = os.fstat(guard._directory_fd)
            self._regular(guard._fd)
            info = os.fstat(guard._fd)
            linked = os.stat(guard._filename, dir_fd=guard._directory_fd, follow_symlinks=False)
            if ((directory.st_dev, directory.st_ino) != guard._directory_identity
                    or (info.st_dev, info.st_ino) != guard._file_identity
                    or (linked.st_dev, linked.st_ino) != guard._file_identity):
                raise TurnStoreError("session execution guard inode changed")
            fcntl.flock(guard._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TurnStoreError("session execution guard descriptor is invalid") from exc

    def _read(self, directory_fd: int, turn_id: str) -> TurnRecord:
        name = f"{_identifier(turn_id)}.json"
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            self._regular(fd)
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise TurnStoreError("turn document is too large")
            value = json.loads(raw, object_pairs_hook=_reject_duplicate)
            record = _record(value)
            if record.turn_id != turn_id:
                raise TurnStoreError("turn filename and identity differ")
            return record
        except (json.JSONDecodeError, TypeError) as exc:
            raise TurnStoreError("turn document is corrupt") from exc
        finally:
            os.close(fd)

    def _write(self, directory_fd: int, record: TurnRecord) -> None:
        _record(record.to_dict())
        raw = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(raw) > _MAX_BYTES:
            raise TurnStoreError("turn document is too large")
        temporary = f".{record.turn_id}.{uuid4().hex}.tmp"
        fd = None
        replaced = False
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    raise OSError("turn write made no progress")
                offset += written
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(temporary, f"{record.turn_id}.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            replaced = True
            os.fsync(directory_fd)
        except OSError as exc:
            raise TurnStoreWriteError(replacement_visible=replaced) from exc
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass

    def _records(self, directory_fd: int) -> list[TurnRecord]:
        return [self._read(directory_fd, name[:-5]) for name in sorted(os.listdir(directory_fd)) if name.endswith(".json")]

    def get(self, turn_id: str) -> TurnRecord:
        with self._locked() as directory_fd:
            return self._read(directory_fd, turn_id)

    def list_active(self) -> list[TurnRecord]:
        with self._locked() as directory_fd:
            return [record for record in self._records(directory_fd) if record.status not in TERMINAL]

    def create(self, session_id: str, input_entry_id: str, *, budget: dict[str, int | float],
               execution_mode: str = "ask", turn_id: str | None = None,
               command_id: str | None = None) -> TurnRecord:
        record = _record(TurnRecord(turn_id=_identifier(f"turn_{uuid4().hex}" if turn_id is None else turn_id),
                                    command_id=_identifier(f"command_{uuid4().hex}" if command_id is None else command_id),
                                    session_id=_identifier(session_id),
                                    input_entry_id=input_entry_id, execution_mode=execution_mode,
                                    budget=dict(budget), checkpoint={}, reconciliation={}, tool_calls={}, queue=[]).to_dict())
        with self._locked() as directory_fd:
            records = self._records(directory_fd)
            for previous in records:
                if previous.turn_id == record.turn_id:
                    if ((previous.session_id, previous.input_entry_id, previous.budget, previous.execution_mode) != (
                            record.session_id, record.input_entry_id, record.budget, record.execution_mode)
                            or command_id is not None and previous.command_id != record.command_id):
                        raise TurnStoreError("turn identity is already bound to another input")
                    return previous
            if any(item.session_id == session_id and item.status not in TERMINAL for item in records):
                raise TurnStoreError("session already has a nonterminal turn")
            self._write(directory_fd, record)
        return record

    def _edit(self, turn_id: str, expected_version: int, change: Callable[[dict[str, Any]], None],
              *, owner: str | None = None, fence: int | None = None, owned: bool = False) -> TurnRecord:
        _number(expected_version, integer=True, positive=True)
        if owned:
            _text(owner)
            _number(fence, integer=True, positive=True)
        with self._locked() as directory_fd:
            current = self._read(directory_fd, turn_id)
            if current.version != expected_version:
                raise TurnStoreError("turn version is stale")
            if current.status in TERMINAL:
                raise TurnStoreError("terminal turns are immutable")
            if owned and (current.lease_owner != owner or owner is None or current.lease_epoch != fence
                          or current.lease_expires_at is None or current.lease_expires_at <= self._now()):
                raise TurnStoreError("turn lease is expired, unowned or fenced")
            document = current.to_dict()
            change(document)
            document["version"] += 1
            updated = _record(document)
            self._write(directory_fd, updated)
            return updated

    def _now(self) -> float:
        now = self._clock()
        _number(now)
        return now

    def claim(self, turn_id: str, *, expected_version: int, owner: str, lease_seconds: float) -> TurnRecord:
        _text(owner)
        _number(lease_seconds, positive=True)
        def change(value):
            if value["status"] == "running":
                raise TurnStoreError("recover running as interrupted before claiming")
            if value["lease_owner"] is not None and value["lease_expires_at"] > self._now():
                raise TurnStoreError("turn already has a live owner")
            value.update(lease_owner=owner, lease_epoch=value["lease_epoch"] + 1,
                         lease_expires_at=self._now() + lease_seconds)
        return self._edit(turn_id, expected_version, change)

    def renew(self, turn_id: str, *, expected_version: int, owner: str, fence: int, lease_seconds: float) -> TurnRecord:
        _number(lease_seconds, positive=True)
        def change(value):
            value["lease_expires_at"] = max(value["lease_expires_at"], self._now() + lease_seconds)
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    @staticmethod
    def _pending(value: dict[str, Any]) -> bool:
        return any(call["status"] == "pending" for call in value["tool_calls"].values())

    @staticmethod
    def _release(value: dict[str, Any]) -> None:
        value.update(lease_owner=None, lease_expires_at=None, lease_epoch=value["lease_epoch"] + 1)

    def transition(self, turn_id: str, status: str, *, expected_version: int, owner: str, fence: int) -> TurnRecord:
        def change(value):
            if status not in TRANSITIONS[value["status"]]:
                raise TurnStoreError("turn status transition is invalid")
            if status == "completed" and value["requires_reconcile"]:
                raise TurnStoreError("reconcile interrupted execution before completing")
            if status == "running":
                if value["requires_reconcile"] or self._pending(value):
                    raise TurnStoreError("reconcile pending execution before resuming")
                if value["cancel_requested"]:
                    raise TurnStoreError("turn has a cancellation intent")
                if value["steps_used"] >= value["budget"]["max_steps"] or value["wall_s_used"] >= value["budget"]["timeout_s"]:
                    raise TurnStoreError("turn budget is exhausted")
            elif status != "interrupted" and self._pending(value):
                raise TurnStoreError("pending execution cannot be discarded")
            value["status"] = status
            if status == "interrupted":
                value["requires_reconcile"] = True
            if status != "running":
                self._release(value)
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    def interrupt_expired(self, turn_id: str, *, expected_version: int) -> TurnRecord:
        def change(value):
            if value["status"] != "running" or value["lease_expires_at"] > self._now():
                raise TurnStoreError("only expired running turns can be recovered")
            value.update(status="interrupted", requires_reconcile=True)
            self._release(value)
        return self._edit(turn_id, expected_version, change)

    def interrupt_orphaned(self, turn_id: str, *, expected_version: int,
                          guard: TurnExecutionGuard) -> TurnRecord:
        """Interrupt a running local orphan after acquiring its execution lock.

        The guard proves exclusion only for runtimes using this local lock;
        legacy APIs and arbitrary external writers are not fenced by it.
        """
        def change(value):
            self._validate_execution_guard(guard, value["session_id"])
            if value["status"] != "running":
                raise TurnStoreError("only running turns can be recovered as local orphans")
            value.update(status="interrupted", requires_reconcile=True)
            self._release(value)
        return self._edit(turn_id, expected_version, change)

    def release_orphaned_claim(self, turn_id: str, *, expected_version: int,
                               guard: TurnExecutionGuard) -> TurnRecord:
        """Release a local orphan's nonrunning claim without discarding recovery state."""
        def change(value):
            self._validate_execution_guard(guard, value["session_id"])
            if value["status"] in {"running", *TERMINAL} or value["lease_owner"] is None:
                raise TurnStoreError("only claimed nonrunning turns can release an orphaned claim")
            self._release(value)
        return self._edit(turn_id, expected_version, change)

    def mark_reconciled(self, turn_id: str, *, evidence: dict[str, str], expected_version: int,
                        owner: str, fence: int) -> TurnRecord:
        _references(evidence)
        if not evidence:
            raise TurnStoreError("reconciliation requires evidence references")
        def change(value):
            if value["status"] != "interrupted" or not value["requires_reconcile"] or self._pending(value):
                raise TurnStoreError("pending execution must be reconciled first")
            value.update(requires_reconcile=False, reconciliation=dict(evidence))
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    def checkpoint(self, turn_id: str, *, steps_used: int, wall_s_used: float, checkpoint: dict[str, str],
                   expected_version: int, owner: str, fence: int) -> TurnRecord:
        _number(steps_used, integer=True)
        _number(wall_s_used)
        _references(checkpoint)
        def change(value):
            if steps_used < value["steps_used"] or wall_s_used < value["wall_s_used"]:
                raise TurnStoreError("cumulative budget usage cannot decrease")
            value.update(steps_used=steps_used, wall_s_used=wall_s_used, checkpoint=dict(checkpoint))
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    def record_tool_call(self, turn_id: str, tool_call_id: str, *, operation_key: str | None,
                         checkpoint: dict[str, str], expected_version: int, owner: str, fence: int) -> TurnRecord:
        _text(tool_call_id)
        _references(checkpoint)
        if operation_key is not None:
            _text(operation_key)
        def change(value):
            if value["status"] != "running" or tool_call_id in value["tool_calls"]:
                raise TurnStoreError("tool call must be new and belong to a running turn")
            value["tool_calls"][tool_call_id] = {"operation_key": operation_key, "status": "pending",
                                                  "checkpoint": dict(checkpoint), "evidence": {}}
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    def bind_tool_operation(self, turn_id: str, tool_call_id: str, *, operation_key: str,
                            expected_version: int, owner: str, fence: int) -> TurnRecord:
        _text(operation_key)
        def change(value):
            call = value["tool_calls"].get(tool_call_id)
            if call is None or call["status"] != "pending" or call["operation_key"] is not None:
                raise TurnStoreError("tool operation binding is missing or already fixed")
            call["operation_key"] = operation_key
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    def resolve_tool_call(self, turn_id: str, tool_call_id: str, *, operation_key: str, evidence: dict[str, str],
                          expected_version: int, owner: str, fence: int) -> TurnRecord:
        _text(operation_key)
        _references(evidence)
        if not evidence:
            raise TurnStoreError("tool resolution requires evidence references")
        def change(value):
            call = value["tool_calls"].get(tool_call_id)
            if call is None or call["status"] != "pending" or call["operation_key"] != operation_key:
                raise TurnStoreError("unknown pending execution cannot be resolved")
            call.update(status="resolved", evidence=dict(evidence))
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)

    def request_cancel(self, turn_id: str, *, expected_version: int) -> TurnRecord:
        return self._edit(turn_id, expected_version, lambda value: value.update(cancel_requested=True))

    def enqueue(self, turn_id: str, kind: str, entry_id: str, *, expected_version: int,
                message_id: str | None = None) -> TurnRecord:
        _text(entry_id)
        message_id = _text(message_id or f"queue_{uuid4().hex}")
        if kind not in {"steer", "follow_up"}:
            raise TurnStoreError("queue kind is invalid")
        def change(value):
            if any(item["message_id"] == message_id for item in value["queue"]):
                raise TurnStoreError("queue message is already recorded")
            value["queue"].append({"message_id": message_id, "kind": kind, "entry_id": entry_id, "consumed": False})
        return self._edit(turn_id, expected_version, change)

    def consume_queue(self, turn_id: str, message_id: str, *, expected_version: int, owner: str, fence: int) -> TurnRecord:
        def change(value):
            item = next((item for item in value["queue"] if item["message_id"] == message_id), None)
            if item is None or item["consumed"]:
                raise TurnStoreError("queue message is unknown or already consumed")
            item["consumed"] = True
        return self._edit(turn_id, expected_version, change, owner=owner, fence=fence, owned=True)
