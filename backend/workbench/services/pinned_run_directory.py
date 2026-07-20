"""Descriptor-anchored, fail-closed access to one persisted run directory.

This capability deliberately protects only the file-system boundary needed by
the LMM public-result view.  Its before/after ``fstat`` checks make ordinary
replacement races observable; they do not claim to prove immutability against a
same-UID adversary that can restore every observable attribute.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workbench.canonical import canonical_json_v1
from workbench.contracts.common.envelope import ContractError, PacketEnvelope
from workbench.domain import ArtifactRecord


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_RUN_INPUTS_PARTS = ("run_inputs.json",)
_LMM_INDEX_PARTS = ("artifacts_index.json",)
_LMM_TERMINAL_PACKET_PARTS = ("artifacts", "model_results", "linear_mixed_effects_1.result.json")
_SEAL_PARTS = ("artifacts", "execution", "executed_input_v1.json")
_INVALIDATED_INPUT_PREFIX = "invalidated_input_v1."
_TERMINAL_PACKET_PARTS = ("artifacts", "model_results", "linear_mixed_effects_1.result.json")
_INDEX_PART = "artifacts_index.json"
_WRITER_TOKEN_PART = ".lmm_pinned_v1.admission.lock"
_RECEIPT_ISSUER = object()
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class PinnedRunError(RuntimeError):
    """Stable, non-sensitive error from the pinned run boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LmmPersistenceError(PinnedRunError):
    """Stable persistence outcome that intentionally carries no storage detail."""

    _NON_RETRYABLE_CODES = frozenset({
        "LMM_PERSISTENCE_PACKET_INVALID",
        "LMM_PERSISTENCE_RECEIPT_INVALID",
        "LMM_TERMINAL_PERSISTENCE_CONFLICT",
    })

    @property
    def retryable(self) -> bool:
        return self.code not in self._NON_RETRYABLE_CODES


@dataclass(frozen=True)
class SealedExecutionInput:
    """An opaque-ish proof of exact canonical bytes sealed for one run."""

    run_id: str
    canonical_bytes: bytes
    digest: str


@dataclass(frozen=True)
class PinnedJsonSnapshot:
    """Detached duplicate-key-safe JSON read from a single file snapshot."""

    value: dict[str, Any]
    raw_bytes: bytes


def _raise(code: str) -> None:
    if code.startswith("LMM_PERSISTENCE_") or code == "LMM_TERMINAL_PERSISTENCE_CONFLICT":
        raise LmmPersistenceError(code)
    raise PinnedRunError(code)


def _validate_run_id(run_id: object) -> str:
    if type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None:
        _raise("RUN_ID_INVALID")
    return run_id


def _validate_part(part: object) -> str:
    if (
        type(part) is not str
        or not part
        or part in {".", ".."}
        or "/" in part
        or "\\" in part
        or "\x00" in part
    ):
        _raise("PINNED_RUN_PART_INVALID")
    return part


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _close(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON")


def _reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_json_object(snapshot: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            snapshot.decode("utf-8"),
            object_pairs_hook=_reject_duplicate,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        _raise("PINNED_RUN_JSON_INVALID")
    if type(value) is not dict:
        _raise("PINNED_RUN_JSON_INVALID")
    return value


class PinnedRunDirectory:
    """One private child-directory FD with fixed read/seal operations only."""

    def __init__(self, fd: int, run_id: str) -> None:
        self._fd: int | None = fd
        self.run_id = run_id

    def __enter__(self) -> "PinnedRunDirectory":
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        fd, self._fd = self._fd, None
        _close(fd)

    def _require_open(self) -> int:
        if self._fd is None:
            _raise("PINNED_RUN_CLOSED")
        return self._fd

    def _open_child(self, parent_fd: int, part: str, *, directory: bool) -> int:
        _validate_part(part)
        flags = os.O_RDONLY | _O_NOFOLLOW
        if directory:
            flags |= _O_DIRECTORY
        try:
            fd = os.open(part, flags, dir_fd=parent_fd)
        except (OSError, ValueError):
            _raise("PINNED_RUN_SNAPSHOT_INVALID")
        try:
            mode = os.fstat(fd).st_mode
            if directory != stat.S_ISDIR(mode):
                _raise("PINNED_RUN_SNAPSHOT_INVALID")
            return fd
        except BaseException:
            _close(fd)
            raise

    def _read_regular_snapshot(self, parts: tuple[str, ...], max_bytes: int) -> bytes:
        """Read one fixed relative regular file through the pinned directory FD."""

        root_fd = self._require_open()
        if type(max_bytes) is not int or max_bytes < 0:
            _raise("PINNED_RUN_SNAPSHOT_INVALID")
        if not isinstance(parts, (tuple, list)) or not parts:
            _raise("PINNED_RUN_PART_INVALID")
        checked = tuple(_validate_part(part) for part in parts)
        opened: list[int] = []
        current = root_fd
        try:
            for part in checked[:-1]:
                current = self._open_child(current, part, directory=True)
                opened.append(current)
            file_fd = self._open_child(current, checked[-1], directory=False)
            opened.append(file_fd)
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                _raise("PINNED_RUN_SNAPSHOT_INVALID")
            size = before.st_size
            if type(size) is not int or size < 0 or size > max_bytes:
                _raise("PINNED_RUN_SNAPSHOT_INVALID")
            try:
                snapshot = os.read(file_fd, size + 1)
            except OSError:
                _raise("PINNED_RUN_SNAPSHOT_INVALID")
            after = os.fstat(file_fd)
            if len(snapshot) < size:
                _raise("PINNED_SNAPSHOT_SHORT_READ")
            if len(snapshot) > size:
                _raise("PINNED_SNAPSHOT_SIZE_CHANGED")
            if _identity(before) != _identity(after):
                _raise("PINNED_RUN_SNAPSHOT_INVALID")
            return snapshot
        finally:
            for fd in reversed(opened):
                _close(fd)

    def _read_json_snapshot(self, parts: tuple[str, ...], max_bytes: int) -> PinnedJsonSnapshot:
        raw = self._read_regular_snapshot(parts, max_bytes)
        return PinnedJsonSnapshot(value=_parse_json_object(raw), raw_bytes=raw)

    def read_run_inputs_snapshot(self) -> PinnedJsonSnapshot:
        return self._read_json_snapshot(_RUN_INPUTS_PARTS, 1024 * 1024)

    def read_lmm_index(self) -> bytes:
        """Return the one immutable byte snapshot for the LMM artifact index."""

        return self._read_regular_snapshot(_LMM_INDEX_PARTS, 1024 * 1024)

    def read_lmm_terminal_packet(self) -> bytes:
        """Return the one immutable byte snapshot for the fixed LMM terminal packet."""

        return self._read_regular_snapshot(_LMM_TERMINAL_PACKET_PARTS, 1024 * 1024)

    def read_execution_seal(self) -> bytes:
        """Return the one immutable byte snapshot for the fixed execution seal."""

        return self._read_regular_snapshot(_SEAL_PARTS, 1024 * 1024)

    def _open_or_create_directory(self, parent_fd: int, part: str) -> int:
        _validate_part(part)
        try:
            fd = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                os.mkdir(part, 0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except FileExistsError:
                _raise("EXECUTED_INPUT_SEAL_INVALID")
            except (OSError, ValueError):
                _raise("EXECUTED_INPUT_SEAL_INVALID")
            try:
                fd = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=parent_fd)
            except (OSError, ValueError):
                _raise("EXECUTED_INPUT_SEAL_INVALID")
        except (OSError, ValueError):
            _raise("EXECUTED_INPUT_SEAL_INVALID")
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                _raise("EXECUTED_INPUT_SEAL_INVALID")
            return fd
        except BaseException:
            _close(fd)
            raise

    def _seal_parent_fd(self) -> int:
        root_fd = self._require_open()
        artifacts = self._open_or_create_directory(root_fd, _SEAL_PARTS[0])
        try:
            execution = self._open_or_create_directory(artifacts, _SEAL_PARTS[1])
        finally:
            _close(artifacts)
        return execution

    def verify_sealed_execution_input(self, seal: object) -> SealedExecutionInput:
        if not isinstance(seal, SealedExecutionInput) or seal.run_id != self.run_id:
            _raise("LMM_EXECUTION_BINDING_INVALID")
        try:
            current = self._read_regular_snapshot(_SEAL_PARTS, 1024 * 1024)
        except PinnedRunError:
            _raise("LMM_EXECUTION_BINDING_INVALID")
        if current != seal.canonical_bytes or hashlib.sha256(current).hexdigest() != seal.digest:
            _raise("LMM_EXECUTION_BINDING_INVALID")
        return seal


class PinnedArtifactReceipt:
    """Unforgeable process-local receipt; artifact facts stay in its private facade."""

    __slots__ = ("__token",)

    def __init__(self, issuer: object | None = None, token: object | None = None) -> None:
        if issuer is not _RECEIPT_ISSUER or token is None:
            raise TypeError("PinnedArtifactReceipt is facade-issued only")
        self.__token = token

    def __reduce__(self) -> object:
        raise TypeError("PinnedArtifactReceipt is not serializable")


class _LmmRunWriteLease:
    __slots__ = ("nonce",)

    def __init__(self) -> None:
        self.nonce = secrets.token_bytes(32)


@dataclass
class _LmmAdmissionRecord:
    """Scheduler-private state for one exact in-process run/seal admission."""

    admission: "_LmmExecutionAdmission | None"
    blocked: "_LmmInputBlockedAdmission | None"
    state: str


_PROVISIONAL_SEALED = "PROVISIONAL_SEALED"
_COMMITTED_EXECUTION = "COMMITTED_EXECUTION"
_INVALIDATED_INPUT_BLOCKED = "INVALIDATED_INPUT_BLOCKED"
_ADMISSION_LOCK = threading.RLock()
_ADMISSION_RECORDS: dict[tuple[int, int, str, str], _LmmAdmissionRecord] = {}
_BLOCKED_ADMISSION_ISSUER = object()


class _LmmExecutionAdmission:
    """Private sealed capability that is not executable until committed."""

    __slots__ = ("_pinned", "_seal", "_lease", "_facade", "_active", "_state")

    def __init__(self, pinned: PinnedRunDirectory, seal: SealedExecutionInput, active: bool) -> None:
        self._pinned = pinned
        self._seal = seal
        self._lease = _LmmRunWriteLease()
        self._active = active
        self._state = _PROVISIONAL_SEALED
        self._facade = _LmmPinnedPersistenceFacade(self) if active else None

    def __copy__(self) -> object:
        raise TypeError("LmmExecutionAdmission is not copyable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("LmmExecutionAdmission is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("LmmExecutionAdmission is not serializable")

    def _close_for_test(self) -> None:
        with _ADMISSION_LOCK:
            if not self._active:
                return
            self._active = False
            assert self._facade is not None
            self._facade._close()
            key = _admission_key(self._pinned, self._seal)
            record = _ADMISSION_RECORDS.get(key)
            if record is not None and record.admission is self:
                if record.blocked is None:
                    del _ADMISSION_RECORDS[key]
                else:
                    record.admission = None

    def _seal_for_test(self) -> SealedExecutionInput:
        return self._seal

    def _facade_for_test(self) -> "_LmmPinnedPersistenceFacade":
        if self._facade is None:
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        return self._facade


class _LmmInputBlockedAdmission:
    """Private, tombstone-bound diagnostic-only capability.

    The object deliberately carries no execution seal or persistence facade.  A
    later slice may give its dedicated diagnostic facade the one lease it needs;
    this state slice only proves that it cannot be forged or upgraded into a
    full execution admission.
    """

    __slots__ = (
        "_pinned", "_tombstone_part", "_registry_key", "_lease", "_active",
        "_diagnostic_consumed",
    )

    def __init__(
        self, issuer: object, pinned: PinnedRunDirectory, tombstone_part: str,
        registry_key: tuple[int, int, str, str],
    ) -> None:
        if issuer is not _BLOCKED_ADMISSION_ISSUER:
            raise TypeError("LmmInputBlockedAdmission is scheduler-issued only")
        self._pinned = pinned
        self._tombstone_part = tombstone_part
        self._registry_key = registry_key
        self._lease = _LmmRunWriteLease()
        self._active = True
        self._diagnostic_consumed = False

    def __reduce__(self) -> object:
        raise TypeError("LmmInputBlockedAdmission is not serializable")

    def _close_for_test(self) -> None:
        with _ADMISSION_LOCK:
            self._active = False
            record = _ADMISSION_RECORDS.get(self._registry_key)
            if record is not None and record.blocked is self:
                del _ADMISSION_RECORDS[self._registry_key]


def _invalidation_tombstone_parts(seal_digest: object) -> tuple[str, ...]:
    if type(seal_digest) is not str or len(seal_digest) != 64 or any(character not in "0123456789abcdef" for character in seal_digest):
        _raise("LMM_EXECUTION_BINDING_INVALID")
    return (
        "artifacts",
        "execution",
        f"{_INVALIDATED_INPUT_PREFIX}{seal_digest}.json",
    )


def _admission_key(pinned: PinnedRunDirectory, seal: SealedExecutionInput) -> tuple[int, int, str, str]:
    """Keep in-process scheduler state scoped to the exact pinned directory."""

    try:
        identity = os.fstat(pinned._require_open())
    except (OSError, PinnedRunError):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    return (identity.st_dev, identity.st_ino, pinned.run_id, seal.digest)


def _canonical_invalidation_tombstone(*, run_id: str, seal_digest: str, reason_code: object) -> bytes:
    if type(reason_code) is not str or re.fullmatch(r"LMM_[A-Z0-9_]+", reason_code) is None:
        _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
    return canonical_json_v1(
        {
            "schema_version": 1,
            "run_id": run_id,
            "seal_digest": seal_digest,
            "reason_code": reason_code,
        }
    ).encode("utf-8")


def _read_invalidation_tombstone(pinned: PinnedRunDirectory, seal: SealedExecutionInput) -> bytes | None:
    parts = _invalidation_tombstone_parts(seal.digest)
    try:
        raw = pinned._read_regular_snapshot(parts, 16 * 1024)
    except PinnedRunError as exc:
        if exc.code == "PINNED_RUN_SNAPSHOT_INVALID":
            if not _invalidation_path_exists(pinned, parts):
                return None
        _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
    try:
        body = _parse_json_object(raw)
    except PinnedRunError:
        _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
    if (
        set(body) != {"schema_version", "run_id", "seal_digest", "reason_code"}
        or body.get("schema_version") != 1
        or body.get("run_id") != pinned.run_id
        or body.get("seal_digest") != seal.digest
    ):
        _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
    expected = _canonical_invalidation_tombstone(
        run_id=pinned.run_id,
        seal_digest=seal.digest,
        reason_code=body.get("reason_code"),
    )
    if raw != expected:
        _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
    return raw


def _invalidation_path_exists(pinned: PinnedRunDirectory, parts: tuple[str, ...]) -> bool:
    """Distinguish an absent fixed path from a symlinked/corrupt one.

    ``_read_regular_snapshot`` intentionally shares an error code for missing
    and unsafe paths.  Admission may treat only a genuinely absent path as no
    tombstone; an unsafe existing object must block re-admission.
    """

    current = pinned._require_open()
    opened: list[int] = []
    try:
        for part in parts[:-1]:
            try:
                child = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                return False
            except (OSError, ValueError):
                _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
            opened.append(child)
            if not stat.S_ISDIR(os.fstat(child).st_mode):
                _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
            current = child
        try:
            leaf = os.open(parts[-1], os.O_RDONLY | _O_NOFOLLOW, dir_fd=current)
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        opened.append(leaf)
        if not stat.S_ISREG(os.fstat(leaf).st_mode):
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        return True
    finally:
        for fd in reversed(opened):
            _close(fd)


def _sync_existing_regular_leaf(parent_fd: int, part: str, *, error_code: str) -> None:
    """Durably re-prove an equal-name immutable object before reusing it.

    A failed directory fsync after a successful link/create leaves a name that
    may be visible but has not yet earned the right to drive a state change or
    receipt.  The retry path therefore opens the fixed leaf without following
    links, proves it is regular, synchronizes both leaf and parent, and leaves
    canonical content validation to the caller's subsequent fixed-path read.
    """

    _validate_part(part)
    leaf_fd: int | None = None
    try:
        try:
            leaf_fd = os.open(part, os.O_RDONLY | _O_NOFOLLOW, dir_fd=parent_fd)
            if not stat.S_ISREG(os.fstat(leaf_fd).st_mode):
                _raise(error_code)
            os.fsync(leaf_fd)
            os.fsync(parent_fd)
        except (OSError, ValueError):
            _raise(error_code)
    finally:
        _close(leaf_fd)


def _publish_invalidation_tombstone(
    pinned: PinnedRunDirectory, seal: SealedExecutionInput, reason_code: object
) -> str:
    """Create and prove one fixed run/seal tombstone before revocation."""

    content = _canonical_invalidation_tombstone(
        run_id=pinned.run_id,
        seal_digest=seal.digest,
        reason_code=reason_code,
    )
    parts = _invalidation_tombstone_parts(seal.digest)
    parent_fd = pinned._seal_parent_fd()
    final_part = parts[-1]
    fd: int | None = None
    try:
        try:
            fd = os.open(
                final_part,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            _sync_existing_regular_leaf(
                parent_fd, final_part, error_code="LMM_INVALIDATION_TOMBSTONE_INVALID"
            )
            existing = _read_invalidation_tombstone(pinned, seal)
            if existing != content:
                _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
            return final_part
        except (OSError, ValueError):
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        _write_all(fd, content)
        try:
            os.fsync(fd)
        except OSError:
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        _close(fd)
        fd = None
        try:
            os.fsync(parent_fd)
        except OSError:
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        if _read_invalidation_tombstone(pinned, seal) != content:
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        return final_part
    finally:
        _close(fd)
        _close(parent_fd)


def _new_test_lmm_execution_admission(
    pinned_run: PinnedRunDirectory, seal: SealedExecutionInput
) -> _LmmExecutionAdmission:
    """Create the only Task-0A test harness admission, never a production admission path."""

    if not isinstance(pinned_run, PinnedRunDirectory) or not isinstance(seal, SealedExecutionInput):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    pinned_run._require_open()
    pinned_run.verify_sealed_execution_input(seal)
    if _read_invalidation_tombstone(pinned_run, seal) is not None:
        _raise("LMM_EXECUTION_INVALIDATED")
    key = _admission_key(pinned_run, seal)
    with _ADMISSION_LOCK:
        existing = _ADMISSION_RECORDS.get(key)
        if existing is not None:
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        admission = _LmmExecutionAdmission(pinned_run, seal, True)
        _ADMISSION_RECORDS[key] = _LmmAdmissionRecord(
            admission=admission, blocked=None, state=_PROVISIONAL_SEALED
        )
        return admission


def _new_lmm_execution_admission(pinned_run: PinnedRunDirectory, seal: SealedExecutionInput) -> _LmmExecutionAdmission:
    return _new_test_lmm_execution_admission(pinned_run, seal)


def _commit_lmm_execution_admission(admission: object) -> None:
    """Perform the final locked proof and grant the sole fit-capable state."""

    if not isinstance(admission, _LmmExecutionAdmission):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    key = _admission_key(admission._pinned, admission._seal)
    with _ADMISSION_LOCK:
        record = _ADMISSION_RECORDS.get(key)
        if (
            record is None
            or record.admission is not admission
            or record.state != _PROVISIONAL_SEALED
            or not admission._active
        ):
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        admission._pinned._require_open()
        admission._pinned.verify_sealed_execution_input(admission._seal)
        if _read_invalidation_tombstone(admission._pinned, admission._seal) is not None:
            _raise("LMM_EXECUTION_INVALIDATED")
        record.state = _COMMITTED_EXECUTION
        admission._state = _COMMITTED_EXECUTION


def _consume_lmm_provisional_admission_for_preflight(
    admission: object,
) -> tuple[PinnedRunDirectory, SealedExecutionInput]:
    """Expose the live provisional proof to the scheduler's immediate preflight.

    This private helper is intentionally narrower than execution consumption:
    it does not commit, return a writer, or otherwise create a right to fit.
    It first resolves object identity from the private registry, so forged,
    closed, committed, and invalidated objects are rejected before touching a
    pinned descriptor.
    """

    if not isinstance(admission, _LmmExecutionAdmission):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    with _ADMISSION_LOCK:
        matches = [
            record
            for record in _ADMISSION_RECORDS.values()
            if record.admission is admission
        ]
        if (
            len(matches) != 1
            or not admission._active
            or admission._state != _PROVISIONAL_SEALED
            or matches[0].state != _PROVISIONAL_SEALED
        ):
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        admission._pinned._require_open()
        admission._pinned.verify_sealed_execution_input(admission._seal)
        if _read_invalidation_tombstone(admission._pinned, admission._seal) is not None:
            _raise("LMM_EXECUTION_INVALIDATED")
        return admission._pinned, admission._seal


def _invalidate_lmm_execution_admission(admission: object, reason_code: object) -> _LmmInputBlockedAdmission:
    """Durably block one provisional seal, then revoke its full capability."""

    if not isinstance(admission, _LmmExecutionAdmission):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    key = _admission_key(admission._pinned, admission._seal)
    with _ADMISSION_LOCK:
        record = _ADMISSION_RECORDS.get(key)
        if (
            record is None
            or record.admission is not admission
            or record.state != _PROVISIONAL_SEALED
            or not admission._active
        ):
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        admission._pinned._require_open()
        admission._pinned.verify_sealed_execution_input(admission._seal)
        tombstone_part = _publish_invalidation_tombstone(admission._pinned, admission._seal, reason_code)
        # The tombstone is now durable and re-read.  Only now may the full
        # capability disappear and the restricted diagnostic capability exist.
        admission._active = False
        admission._state = _INVALIDATED_INPUT_BLOCKED
        assert admission._facade is not None
        admission._facade._close()
        blocked = _LmmInputBlockedAdmission(
            _BLOCKED_ADMISSION_ISSUER, admission._pinned, tombstone_part, key
        )
        record.admission = None
        record.blocked = blocked
        record.state = _INVALIDATED_INPUT_BLOCKED
        return blocked


def _consume_lmm_execution_admission(admission: object) -> tuple[PinnedRunDirectory, SealedExecutionInput]:
    if not isinstance(admission, _LmmExecutionAdmission):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    key = _admission_key(admission._pinned, admission._seal)
    with _ADMISSION_LOCK:
        record = _ADMISSION_RECORDS.get(key)
        if (
            not admission._active
            or record is None
            or record.admission is not admission
            or record.state != _COMMITTED_EXECUTION
            or admission._state != _COMMITTED_EXECUTION
        ):
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        admission._pinned._require_open()
        admission._pinned.verify_sealed_execution_input(admission._seal)
        if _read_invalidation_tombstone(admission._pinned, admission._seal) is not None:
            _raise("LMM_EXECUTION_INVALIDATED")
        return admission._pinned, admission._seal


def _consume_lmm_input_blocked_admission(admission: object) -> PinnedRunDirectory:
    """Validate only the restricted blocked capability, before any traversal."""

    if not isinstance(admission, _LmmInputBlockedAdmission):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    with _ADMISSION_LOCK:
        if not admission._active:
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        # The only registry lookup before touching the pinned descriptor uses
        # the private tombstone filename; it contains no seal disclosure API.
        matching = [
            record
            for record in _ADMISSION_RECORDS.values()
            if record.blocked is admission and record.state == _INVALIDATED_INPUT_BLOCKED
        ]
        if len(matching) != 1:
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        admission._pinned._require_open()
        seal_digest = admission._registry_key[-1]
        tombstone = _read_invalidation_tombstone(
            admission._pinned,
            SealedExecutionInput(admission._pinned.run_id, b"", seal_digest),
        )
        if tombstone is None or admission._tombstone_part != _invalidation_tombstone_parts(seal_digest)[-1]:
            _raise("LMM_INVALIDATION_TOMBSTONE_INVALID")
        return admission._pinned


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(fd, content[offset:])
        except OSError:
            _raise("LMM_PERSISTENCE_IO_FAILED")
        if written <= 0:
            _raise("LMM_PERSISTENCE_IO_FAILED")
        offset += written


def _read_fd_snapshot(fd: int, *, max_bytes: int) -> bytes:
    try:
        before = os.fstat(fd)
    except OSError:
        _raise("LMM_PERSISTENCE_IO_FAILED")
    if not stat.S_ISREG(before.st_mode) or before.st_size < 0 or before.st_size > max_bytes:
        _raise("LMM_PERSISTENCE_IO_FAILED")
    try:
        snapshot = os.read(fd, before.st_size + 1)
        after = os.fstat(fd)
    except OSError:
        _raise("LMM_PERSISTENCE_IO_FAILED")
    if len(snapshot) != before.st_size or _identity(before) != _identity(after):
        _raise("LMM_PERSISTENCE_IO_FAILED")
    return snapshot


def _read_child_from_fd(parent_fd: int, part: str, *, missing_is_none: bool = False) -> bytes | None:
    _validate_part(part)
    try:
        fd = os.open(part, os.O_RDONLY | _O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        if missing_is_none:
            return None
        _raise("LMM_PERSISTENCE_IO_FAILED")
    except (OSError, ValueError):
        _raise("LMM_PERSISTENCE_IO_FAILED")
    try:
        return _read_fd_snapshot(fd, max_bytes=1024 * 1024)
    finally:
        _close(fd)


def _writer_directory(pinned: PinnedRunDirectory, parts: tuple[str, ...]) -> int:
    current = pinned._require_open()
    opened: list[int] = []
    try:
        for part in parts:
            try:
                child = pinned._open_or_create_directory(current, part)
            except PinnedRunError:
                _raise("LMM_PERSISTENCE_IO_FAILED")
            opened.append(child)
            current = child
        if not opened:
            _raise("LMM_PERSISTENCE_IO_FAILED")
        result = opened.pop()
        return result
    finally:
        for fd in reversed(opened):
            _close(fd)


def _publish_immutable(parent_fd: int, final_part: str, content: bytes) -> None:
    _validate_part(final_part)
    temporary = f".lmm-pinned-{secrets.token_hex(16)}.tmp"
    _validate_part(temporary)
    temp_fd: int | None = None
    try:
        try:
            temp_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except (OSError, ValueError):
            _raise("LMM_PERSISTENCE_IO_FAILED")
        _write_all(temp_fd, content)
        try:
            os.fsync(temp_fd)
        except OSError:
            _raise("LMM_PERSISTENCE_IO_FAILED")
        _close(temp_fd)
        temp_fd = None
        try:
            os.link(
                temporary,
                final_part,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            _sync_existing_regular_leaf(
                parent_fd, final_part, error_code="LMM_PERSISTENCE_IO_FAILED"
            )
            existing = _read_child_from_fd(parent_fd, final_part)
            if existing != content:
                _raise("LMM_TERMINAL_PERSISTENCE_CONFLICT")
        except (OSError, ValueError):
            _raise("LMM_PERSISTENCE_IO_FAILED")
        else:
            try:
                os.fsync(parent_fd)
            except OSError:
                _raise("LMM_PERSISTENCE_IO_FAILED")
            if _read_child_from_fd(parent_fd, final_part) != content:
                _raise("LMM_PERSISTENCE_IO_FAILED")
    finally:
        _close(temp_fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        except OSError:
            _raise("LMM_PERSISTENCE_IO_FAILED")


def _validate_index_record(value: object) -> dict[str, object]:
    required = {"artifact_id", "path", "artifact_type", "step", "sha256", "inputs", "config_hash", "code_version"}
    if not isinstance(value, dict) or set(value) != required:
        _raise("LMM_PERSISTENCE_IO_FAILED")
    for field in ("artifact_id", "path", "artifact_type", "step", "sha256", "config_hash", "code_version"):
        if type(value[field]) is not str or (field != "config_hash" and not value[field]):
            _raise("LMM_PERSISTENCE_IO_FAILED")
    if not isinstance(value["inputs"], list) or any(type(item) is not str or not item for item in value["inputs"]):
        _raise("LMM_PERSISTENCE_IO_FAILED")
    digest = value["sha256"]
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        _raise("LMM_PERSISTENCE_IO_FAILED")
    return dict(value)


def _lmm_packet_bytes(packet: Mapping[str, object], contract: str) -> bytes:
    try:
        envelope = PacketEnvelope.from_dict(packet)
    except (ContractError, TypeError, ValueError):
        _raise("LMM_PERSISTENCE_PACKET_INVALID")
    if (
        envelope.contract != contract
        or envelope.contract_version != "1.0"
        or envelope.producer_version != "linear_mixed_effects@1.0"
    ):
        _raise("LMM_PERSISTENCE_PACKET_INVALID")
    return canonical_json_v1(envelope.to_dict()).encode("utf-8")


def _read_lmm_index(pinned: PinnedRunDirectory) -> dict[str, object]:
    raw = _read_child_from_fd(pinned._require_open(), _INDEX_PART, missing_is_none=True)
    if raw is None:
        return {"schema_version": 1, "artifacts": []}
    try:
        index = _parse_json_object(raw)
    except PinnedRunError:
        _raise("LMM_PERSISTENCE_IO_FAILED")
    if set(index) != {"schema_version", "artifacts"} or index["schema_version"] != 1 or not isinstance(index["artifacts"], list):
        _raise("LMM_PERSISTENCE_IO_FAILED")
    index["artifacts"] = [_validate_index_record(record) for record in index["artifacts"]]
    return index


def _write_lmm_index(pinned: PinnedRunDirectory, index: dict[str, object]) -> None:
    content = canonical_json_v1(index).encode("utf-8")
    root_fd = pinned._require_open()
    temporary = f".lmm-index-{secrets.token_hex(16)}.tmp"
    _validate_part(temporary)
    temp_fd: int | None = None
    try:
        try:
            temp_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600, dir_fd=root_fd)
        except (OSError, ValueError):
            _raise("LMM_PERSISTENCE_IO_FAILED")
        _write_all(temp_fd, content)
        os.fsync(temp_fd)
        _close(temp_fd)
        temp_fd = None
        os.replace(temporary, _INDEX_PART, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        os.fsync(root_fd)
        if _read_child_from_fd(root_fd, _INDEX_PART) != content:
            _raise("LMM_PERSISTENCE_IO_FAILED")
    except (OSError, ValueError):
        _raise("LMM_PERSISTENCE_IO_FAILED")
    finally:
        _close(temp_fd)
        try:
            os.unlink(temporary, dir_fd=root_fd)
        except FileNotFoundError:
            pass
        except OSError:
            _raise("LMM_PERSISTENCE_IO_FAILED")


def _index_lmm_record(pinned: PinnedRunDirectory, record: dict[str, object]) -> None:
    index = _read_lmm_index(pinned)
    artifacts = index["artifacts"]
    assert isinstance(artifacts, list)
    existing = [item for item in artifacts if item["artifact_id"] == record["artifact_id"] or item["path"] == record["path"]]
    if len(existing) > 1 or (existing and any(item != record for item in existing)):
        _raise("LMM_TERMINAL_PERSISTENCE_CONFLICT")
    if record["artifact_type"] == "model_result_packet":
        model_records = [item for item in artifacts if item["artifact_type"] == "model_result_packet"]
        if len(model_records) > 1 or (model_records and any(item != record for item in model_records)):
            _raise("LMM_TERMINAL_PERSISTENCE_CONFLICT")
    if not existing:
        artifacts.append(record)
        _write_lmm_index(pinned, index)


class LmmLifecycleFailureSink:
    """Private descriptor-relative, non-result sink for admitted LMM failures."""

    __slots__ = ("_facade", "_lease")

    def __init__(self, facade: "_LmmPinnedPersistenceFacade") -> None:
        self._facade = facade
        self._lease = facade._lease

    def persist(self, *, admission: object, code: object, retryable: object) -> None:
        admitted = self._facade._require(admission)
        if type(code) is not str or not code.startswith("LMM_") or type(retryable) is not bool:
            _raise("LMM_PERSISTENCE_PACKET_INVALID")
        content = canonical_json_v1({
            "schema_version": 1,
            "state": "PERSISTENCE_INCOMPLETE",
            "run_id": admitted._seal.run_id,
            "code": code,
            "retryable": retryable,
        }).encode("utf-8")
        parent_fd = _writer_directory(admitted._pinned, ("artifacts", "execution"))
        try:
            _publish_immutable(parent_fd, "lmm_lifecycle_failure_v1.json", content)
        finally:
            _close(parent_fd)


class _LmmPinnedPersistenceFacade:
    __slots__ = ("_admission", "_lease", "_receipts", "_receipt_objects", "_lifecycle_failure_sink")

    def __init__(self, admission: _LmmExecutionAdmission) -> None:
        self._admission = admission
        self._lease = admission._lease
        self._receipts: dict[object, dict[str, object]] = {}
        self._receipt_objects: dict[object, PinnedArtifactReceipt] = {}
        self._lifecycle_failure_sink = LmmLifecycleFailureSink(self)

    def _close(self) -> None:
        self._receipts.clear()
        self._receipt_objects.clear()

    def _require(self, admission: object) -> _LmmExecutionAdmission:
        if (
            admission is not self._admission
            or not isinstance(admission, _LmmExecutionAdmission)
            or not admission._active
            or admission._facade is not self
            or admission._lease is not self._lease
        ):
            _raise("LMM_EXECUTION_BINDING_REQUIRED")
        _consume_lmm_execution_admission(admission)
        return admission

    def _receipt_record(self, receipt: object) -> dict[str, object]:
        if not isinstance(receipt, PinnedArtifactReceipt):
            _raise("LMM_PERSISTENCE_RECEIPT_INVALID")
        token = receipt._PinnedArtifactReceipt__token
        record = self._receipts.get(token)
        if record is None:
            _raise("LMM_PERSISTENCE_RECEIPT_INVALID")
        return dict(record)

    def receipt_record(self, receipt: object) -> dict[str, object]:
        """Test-only inspection; the capability itself exposes no such method."""

        if not self._admission._active:
            _raise("LMM_PERSISTENCE_RECEIPT_INVALID")
        self._require(self._admission)
        return self._receipt_record(receipt)

    def _mint_receipt(self, record: dict[str, object]) -> PinnedArtifactReceipt:
        for token, known in self._receipts.items():
            if known == record:
                return self._receipt_objects[token]
        token = object()
        self._receipts[token] = dict(record)
        receipt = PinnedArtifactReceipt(_RECEIPT_ISSUER, token)
        self._receipt_objects[token] = receipt
        return receipt

    def _packet_bytes(self, packet: Mapping[str, object], contract: str) -> bytes:
        try:
            envelope = PacketEnvelope.from_dict(packet)
        except (ContractError, TypeError, ValueError):
            _raise("LMM_PERSISTENCE_PACKET_INVALID")
        if envelope.contract != contract or envelope.contract_version != "1.0" or envelope.producer_version != "linear_mixed_effects@1.0":
            _raise("LMM_PERSISTENCE_PACKET_INVALID")
        return canonical_json_v1(envelope.to_dict()).encode("utf-8")

    def _record(self, *, artifact_id: str, path: str, artifact_type: str, digest: str, inputs: tuple[str, ...]) -> dict[str, object]:
        return ArtifactRecord(
            artifact_id=artifact_id,
            path=path,
            artifact_type=artifact_type,
            step="estimation",
            sha256=digest,
            inputs=inputs,
            config_hash="",
            code_version="linear_mixed_effects@1.0",
        ).to_dict()

    def _acquire_token(self, pinned: PinnedRunDirectory) -> int:
        root_fd = pinned._require_open()
        _validate_part(_WRITER_TOKEN_PART)
        try:
            return os.open(_WRITER_TOKEN_PART, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600, dir_fd=root_fd)
        except FileExistsError:
            _raise("LMM_PERSISTENCE_BUSY")
        except (OSError, ValueError):
            _raise("LMM_PERSISTENCE_IO_FAILED")

    def _release_token(self, pinned: PinnedRunDirectory, token_fd: int) -> None:
        _close(token_fd)
        try:
            os.unlink(_WRITER_TOKEN_PART, dir_fd=pinned._require_open())
            os.fsync(pinned._require_open())
        except (OSError, ValueError):
            _raise("LMM_PERSISTENCE_IO_FAILED")

    def _read_index(self, pinned: PinnedRunDirectory) -> dict[str, object]:
        raw = _read_child_from_fd(pinned._require_open(), _INDEX_PART, missing_is_none=True)
        if raw is None:
            return {"schema_version": 1, "artifacts": []}
        try:
            index = _parse_json_object(raw)
        except PinnedRunError:
            _raise("LMM_PERSISTENCE_IO_FAILED")
        if set(index) != {"schema_version", "artifacts"} or index["schema_version"] != 1 or not isinstance(index["artifacts"], list):
            _raise("LMM_PERSISTENCE_IO_FAILED")
        index["artifacts"] = [_validate_index_record(record) for record in index["artifacts"]]
        return index

    def _write_index(self, pinned: PinnedRunDirectory, index: dict[str, object]) -> None:
        content = canonical_json_v1(index).encode("utf-8")
        root_fd = pinned._require_open()
        temporary = f".lmm-index-{secrets.token_hex(16)}.tmp"
        _validate_part(temporary)
        temp_fd: int | None = None
        try:
            try:
                temp_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW, 0o600, dir_fd=root_fd)
            except (OSError, ValueError):
                _raise("LMM_PERSISTENCE_IO_FAILED")
            _write_all(temp_fd, content)
            os.fsync(temp_fd)
            _close(temp_fd)
            temp_fd = None
            os.replace(temporary, _INDEX_PART, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
            if _read_child_from_fd(root_fd, _INDEX_PART) != content:
                _raise("LMM_PERSISTENCE_IO_FAILED")
        except (OSError, ValueError):
            _raise("LMM_PERSISTENCE_IO_FAILED")
        finally:
            _close(temp_fd)
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except FileNotFoundError:
                pass
            except OSError:
                _raise("LMM_PERSISTENCE_IO_FAILED")

    def _index_record(self, admission: _LmmExecutionAdmission, record: dict[str, object]) -> None:
        pinned = admission._pinned
        index = self._read_index(pinned)
        artifacts = index["artifacts"]
        assert isinstance(artifacts, list)
        existing = [item for item in artifacts if item["artifact_id"] == record["artifact_id"] or item["path"] == record["path"]]
        if len(existing) > 1 or (existing and any(item != record for item in existing)):
            _raise("LMM_TERMINAL_PERSISTENCE_CONFLICT")
        if record["artifact_type"] == "model_result_packet":
            model_records = [item for item in artifacts if item["artifact_type"] == "model_result_packet"]
            if len(model_records) > 1 or (model_records and any(item != record for item in model_records)):
                _raise("LMM_TERMINAL_PERSISTENCE_CONFLICT")
        if not existing:
            artifacts.append(record)
            self._write_index(pinned, index)

    def _persist(
        self,
        *,
        admission: _LmmExecutionAdmission,
        packet: Mapping[str, object],
        contract: str,
        artifact_id: str,
        path: str,
        artifact_type: str,
        directory_parts: tuple[str, ...],
        final_part: str,
        inputs: tuple[str, ...],
        terminal: bool,
    ) -> PinnedArtifactReceipt:
        # Keep the final committed-state/tombstone proof, descriptor traversal,
        # immutable publication, and index mutation in one linearizable
        # scheduler critical section.  A demotion cannot pass this point and
        # subsequently lose to a terminal/recovery write.
        with _ADMISSION_LOCK:
            return self._persist_locked(
                admission=admission,
                packet=packet,
                contract=contract,
                artifact_id=artifact_id,
                path=path,
                artifact_type=artifact_type,
                directory_parts=directory_parts,
                final_part=final_part,
                inputs=inputs,
                terminal=terminal,
            )

    def _persist_locked(
        self,
        *,
        admission: _LmmExecutionAdmission,
        packet: Mapping[str, object],
        contract: str,
        artifact_id: str,
        path: str,
        artifact_type: str,
        directory_parts: tuple[str, ...],
        final_part: str,
        inputs: tuple[str, ...],
        terminal: bool,
    ) -> PinnedArtifactReceipt:
        admitted = self._require(admission)
        if terminal:
            admitted._pinned.verify_sealed_execution_input(admitted._seal)
        content = self._packet_bytes(packet, contract)
        digest = hashlib.sha256(content).hexdigest()
        record = self._record(artifact_id=artifact_id, path=path, artifact_type=artifact_type, digest=digest, inputs=inputs)
        token_fd = self._acquire_token(admitted._pinned)
        try:
            parent_fd = _writer_directory(admitted._pinned, directory_parts)
            try:
                _publish_immutable(parent_fd, final_part, content)
            finally:
                _close(parent_fd)
            self._index_record(admitted, record)
        finally:
            self._release_token(admitted._pinned, token_fd)
        return self._mint_receipt(record)

    def persist_terminal(self, *, admission: _LmmExecutionAdmission, packet: Mapping[str, object]) -> PinnedArtifactReceipt:
        self._require(admission)
        return self._persist(
            admission=admission,
            packet=packet,
            contract="linear_mixed_effects.result",
            artifact_id="linear_mixed_effects_1.result",
            path="artifacts/model_results/linear_mixed_effects_1.result.json",
            artifact_type="model_result_packet",
            directory_parts=("artifacts", "model_results"),
            final_part="linear_mixed_effects_1.result.json",
            inputs=(f"executed_input_sha256:{admission._seal.digest}",),
            terminal=True,
        )

    def persist_diagnostic(self, *, admission: _LmmExecutionAdmission, packet: Mapping[str, object], terminal: PinnedArtifactReceipt | None) -> PinnedArtifactReceipt:
        self._require(admission)
        content = self._packet_bytes(packet, "linear_mixed_effects.diagnostic")
        digest = hashlib.sha256(content).hexdigest()
        inputs: tuple[str, ...] = ()
        if terminal is not None:
            terminal_record = self._receipt_record(terminal)
            inputs = (f"terminal_sha256:{terminal_record['sha256']}",)
        return self._persist(
            admission=admission,
            packet=packet,
            contract="linear_mixed_effects.diagnostic",
            artifact_id=f"linear_mixed_effects_1.diagnostic.{digest}",
            path=f"artifacts/diagnostics/linear_mixed_effects_1.{digest}.json",
            artifact_type="lmm_diagnostic_packet",
            directory_parts=("artifacts", "diagnostics"),
            final_part=f"linear_mixed_effects_1.{digest}.json",
            inputs=inputs,
            terminal=False,
        )

    def persist_recovery(self, *, admission: _LmmExecutionAdmission, packet: Mapping[str, object], terminal: PinnedArtifactReceipt) -> PinnedArtifactReceipt:
        self._require(admission)
        terminal_record = self._receipt_record(terminal)
        if terminal_record["artifact_type"] != "model_result_packet":
            _raise("LMM_PERSISTENCE_RECEIPT_INVALID")
        content = self._packet_bytes(packet, "linear_mixed_effects.recovery_proposal")
        digest = hashlib.sha256(content).hexdigest()
        inputs = (
            f"terminal_artifact_id:{terminal_record['artifact_id']}",
            f"terminal_sha256:{terminal_record['sha256']}",
        )
        return self._persist(
            admission=admission,
            packet=packet,
            contract="linear_mixed_effects.recovery_proposal",
            artifact_id=f"linear_mixed_effects_1.recovery.{digest}",
            path=f"artifacts/recovery/linear_mixed_effects_1.{digest}.json",
            artifact_type="lmm_recovery_packet",
            directory_parts=("artifacts", "recovery"),
            final_part=f"linear_mixed_effects_1.{digest}.json",
            inputs=inputs,
            terminal=False,
        )

    def persist_lifecycle_failure(self, *, admission: object, code: object, retryable: object) -> None:
        self._lifecycle_failure_sink.persist(
            admission=admission, code=code, retryable=retryable
        )


def _persist_lmm_terminal_packet(*, admission: object, packet: Mapping[str, object]) -> PinnedArtifactReceipt:
    if not isinstance(admission, _LmmExecutionAdmission) or admission._facade is None:
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    return admission._facade.persist_terminal(admission=admission, packet=packet)


def _persist_lmm_diagnostic_packet(*, admission: object, packet: Mapping[str, object], terminal: PinnedArtifactReceipt | None) -> PinnedArtifactReceipt:
    if not isinstance(admission, _LmmExecutionAdmission) or admission._facade is None:
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    return admission._facade.persist_diagnostic(admission=admission, packet=packet, terminal=terminal)


def _persist_lmm_input_blocked_diagnostic(*, admission: object, packet: Mapping[str, object]) -> PinnedArtifactReceipt:
    """Use the sole post-seal blocked right for one diagnostic packet.

    This deliberately does not delegate to the full-admission facade: a
    tombstone-bound blocked capability has no seal, terminal, recovery, or
    generic indexing authority.  The one exact index mutation is kept local to
    this narrow function and occurs only after the tombstone is revalidated.
    """

    if not isinstance(admission, _LmmInputBlockedAdmission):
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    with _ADMISSION_LOCK:
        pinned = _consume_lmm_input_blocked_admission(admission)
        if admission._diagnostic_consumed:
            _raise("LMM_INPUT_BLOCKED_DIAGNOSTIC_CONSUMED")
        content = _lmm_packet_bytes(packet, "linear_mixed_effects.diagnostic")
        digest = hashlib.sha256(content).hexdigest()
        record = ArtifactRecord(
            artifact_id=f"linear_mixed_effects_1.diagnostic.{digest}",
            path=f"artifacts/diagnostics/linear_mixed_effects_1.{digest}.json",
            artifact_type="lmm_diagnostic_packet",
            step="estimation",
            sha256=digest,
            inputs=(),
            config_hash="",
            code_version="linear_mixed_effects@1.0",
        ).to_dict()
        root_fd = pinned._require_open()
        token_fd: int | None = None
        try:
            try:
                token_fd = os.open(
                    _WRITER_TOKEN_PART,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                    0o600,
                    dir_fd=root_fd,
                )
            except FileExistsError:
                _raise("LMM_PERSISTENCE_BUSY")
            except (OSError, ValueError):
                _raise("LMM_PERSISTENCE_IO_FAILED")
            parent_fd = _writer_directory(pinned, ("artifacts", "diagnostics"))
            try:
                _publish_immutable(parent_fd, f"linear_mixed_effects_1.{digest}.json", content)
            finally:
                _close(parent_fd)
            _index_lmm_record(pinned, record)
            admission._diagnostic_consumed = True
            return PinnedArtifactReceipt(_RECEIPT_ISSUER, object())
        finally:
            _close(token_fd)
            if token_fd is not None:
                try:
                    os.unlink(_WRITER_TOKEN_PART, dir_fd=root_fd)
                    os.fsync(root_fd)
                except (OSError, ValueError):
                    _raise("LMM_PERSISTENCE_IO_FAILED")


def _persist_lmm_recovery_packet(*, admission: object, packet: Mapping[str, object], terminal: PinnedArtifactReceipt) -> PinnedArtifactReceipt:
    if not isinstance(admission, _LmmExecutionAdmission) or admission._facade is None:
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    return admission._facade.persist_recovery(admission=admission, packet=packet, terminal=terminal)


def _persist_lmm_lifecycle_failure(*, admission: object, code: object, retryable: object) -> None:
    """Persist only stable non-result state through the live private facade."""

    if not isinstance(admission, _LmmExecutionAdmission) or admission._facade is None:
        _raise("LMM_EXECUTION_BINDING_REQUIRED")
    admission._facade.persist_lifecycle_failure(
        admission=admission, code=code, retryable=retryable
    )


def open_pinned_run_directory(runs_root: Path, run_id: str) -> PinnedRunDirectory:
    """Open one trusted run child with ``O_NOFOLLOW`` at both boundaries."""

    checked_id = _validate_run_id(run_id)
    # This boundary has no path-based compatibility mode.  Without all three
    # primitives it cannot honestly make its no-follow/anchoring guarantee.
    if not _O_DIRECTORY or not _O_NOFOLLOW or os.open not in os.supports_dir_fd:
        _raise("PINNED_RUN_UNSUPPORTED")
    root_fd: int | None = None
    child_fd: int | None = None
    try:
        root_fd = os.open(os.fspath(runs_root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            _raise("PINNED_RUN_ROOT_INVALID")
        child_fd = os.open(
            checked_id,
            os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
            dir_fd=root_fd,
        )
        if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
            _raise("PINNED_RUN_ROOT_INVALID")
        return PinnedRunDirectory(child_fd, checked_id)
    except PinnedRunError:
        _close(child_fd)
        raise
    except (OSError, ValueError):
        _close(child_fd)
        _raise("PINNED_RUN_ROOT_INVALID")
    finally:
        _close(root_fd)


def seal_executed_input_v1(
    pinned_run: PinnedRunDirectory, representation: object
) -> SealedExecutionInput:
    """Publish canonical execution input once, never overwriting an existing seal."""

    if not isinstance(pinned_run, PinnedRunDirectory):
        _raise("EXECUTED_INPUT_SEAL_INVALID")
    pinned_run._require_open()
    try:
        canonical = canonical_json_v1(representation).encode("utf-8")
    except (TypeError, ValueError):
        _raise("EXECUTED_INPUT_SEAL_INVALID")
    digest = hashlib.sha256(canonical).hexdigest()
    candidate = SealedExecutionInput(pinned_run.run_id, canonical, digest)
    try:
        existing = pinned_run._read_regular_snapshot(_SEAL_PARTS, 1024 * 1024)
    except PinnedRunError as exc:
        if exc.code not in {"PINNED_RUN_SNAPSHOT_INVALID"}:
            raise
        existing = None
    if existing is not None:
        if existing != canonical:
            _raise("EXECUTED_INPUT_SEAL_DIVERGENCE")
        parent_fd = pinned_run._seal_parent_fd()
        try:
            _sync_existing_regular_leaf(
                parent_fd, _SEAL_PARTS[-1], error_code="EXECUTED_INPUT_SEAL_INVALID"
            )
        finally:
            _close(parent_fd)
        return pinned_run.verify_sealed_execution_input(candidate)

    parent_fd = pinned_run._seal_parent_fd()
    temp_name = ".executed_input_v1.%d.%d.tmp" % (os.getpid(), id(candidate))
    _validate_part(temp_name)
    try:
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except (OSError, ValueError):
            _raise("EXECUTED_INPUT_SEAL_INVALID")
        try:
            offset = 0
            while offset < len(canonical):
                written = os.write(temp_fd, canonical[offset:])
                if written <= 0:
                    _raise("EXECUTED_INPUT_SEAL_INVALID")
                offset += written
            os.fsync(temp_fd)
        finally:
            _close(temp_fd)
        try:
            os.link(temp_name, _SEAL_PARTS[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        except FileExistsError:
            _sync_existing_regular_leaf(
                parent_fd, _SEAL_PARTS[-1], error_code="EXECUTED_INPUT_SEAL_INVALID"
            )
            existing = pinned_run._read_regular_snapshot(_SEAL_PARTS, 1024 * 1024)
            if existing != canonical:
                _raise("EXECUTED_INPUT_SEAL_DIVERGENCE")
        except (OSError, ValueError):
            _raise("EXECUTED_INPUT_SEAL_INVALID")
        else:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except (OSError, ValueError):
                _raise("EXECUTED_INPUT_SEAL_INVALID")
        finally:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
    finally:
        _close(parent_fd)
    return pinned_run.verify_sealed_execution_input(candidate)


__all__ = [
    "PinnedJsonSnapshot",
    "PinnedRunDirectory",
    "PinnedRunError",
    "SealedExecutionInput",
    "open_pinned_run_directory",
    "seal_executed_input_v1",
]
