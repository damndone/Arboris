"""Immutable in-memory compilation records with server-only issuance."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Condition, RLock
from collections.abc import Iterator
import os
from pathlib import Path
import stat
from typing import Any

from ..contracts.agent.planning import (
    CompiledWorkflowV1,
    CompilationRecordReferenceV1,
    CompilationRecordStoreV1,
    CompilationRecordV1,
    ServerCompilationRecordReferenceV1,
)
from .failure_contract import failure


_PROCESS_RESERVATION_LOCK = RLock()
_PROCESS_ACTIVE_RESERVATIONS: dict[str, "CompilationStore"] = {}
_ROOT_MARKER_PREFIX = ".workbench-reservation-domain.v1-"


class CompilationStore:
    """A replay index; it never accepts caller-created authority objects."""

    def __init__(
        self,
        record_store: CompilationRecordStoreV1 | None = None,
        *,
        reservation_root: str | os.PathLike[str] | None = None,
    ) -> None:
        if record_store is not None and type(record_store) is not CompilationRecordStoreV1:
            raise TypeError("record_store must be CompilationRecordStoreV1")
        self._record_store = record_store or CompilationRecordStoreV1()
        self._results: dict[str, Any] = {}
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._reservations: set[str] = set()
        self._reservation_fd, self._reservation_identity = self._open_reservation_root(reservation_root)

    @staticmethod
    def _open_reservation_root(
        value: str | os.PathLike[str] | None,
    ) -> tuple[int | None, tuple[int, int] | None]:
        if value is None:
            return None, None
        root = Path(value)
        try:
            info = root.lstat()
        except OSError as exc:
            raise ValueError("reservation root is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("reservation root must be a non-symlink directory")
        try:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ValueError("reservation root could not be admitted") from exc
        identity = os.fstat(root_fd)
        root_identity = (identity.st_dev, identity.st_ino)
        marker_name = _ROOT_MARKER_PREFIX + root.name
        parent_fd: int | None = None
        try:
            parent_fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            marker_payload = f"{root_identity[0]}:{root_identity[1]}\n".encode("ascii")
            try:
                marker_fd = os.open(
                    marker_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                marker_fd = os.open(marker_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    existing = os.read(marker_fd, 256)
                finally:
                    os.close(marker_fd)
                if existing != marker_payload:
                    raise ValueError("reservation root identity changed")
            else:
                try:
                    os.write(marker_fd, marker_payload)
                    os.fsync(marker_fd)
                finally:
                    os.close(marker_fd)
                os.fsync(parent_fd)
        except Exception:
            os.close(root_fd)
            raise
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
        return root_fd, root_identity

    def close(self) -> None:
        """Release the admitted root descriptor; reservation markers remain durable."""

        fd = getattr(self, "_reservation_fd", None)
        self._reservation_fd = None
        self._reservation_identity = None
        if fd is not None:
            os.close(fd)

    def __del__(self) -> None:
        try:
            self.close()
        except (AttributeError, OSError):
            pass

    def _claim_durable_reservation(self, idempotency_key: str) -> None:
        if self._reservation_fd is None:
            return
        try:
            identity = os.fstat(self._reservation_fd)
        except OSError as exc:
            raise failure("DURABLE_RESERVATION_REQUIRED", stage="store") from exc
        if self._reservation_identity != (identity.st_dev, identity.st_ino):
            raise failure("FORGED_AUTHORITY", stage="store")
        filename = f"reservation-{idempotency_key}.v1"
        try:
            fd = os.open(
                filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._reservation_fd,
            )
        except FileExistsError as exc:
            raise failure("IDEMPOTENCY_CONFLICT", stage="store") from exc
        except OSError as exc:
            raise failure("IDEMPOTENCY_CONFLICT", stage="store") from exc
        try:
            os.write(fd, b"reserved-v1\n")
            os.fsync(fd)
        finally:
            os.close(fd)

    @property
    def record_store(self) -> CompilationRecordStoreV1:
        return self._record_store

    @property
    def raw_store(self) -> CompilationRecordStoreV1:
        """Internal compiler seam; callers cannot issue through this property."""

        return self._record_store

    @property
    def durable_reservation_available(self) -> bool:
        """Whether this store has an admitted cross-process reservation root."""

        return self._reservation_fd is not None

    def _validate_result(self, idempotency_key: str, result: Any) -> None:
        from .plan_compiler import CompilationResultV1

        if (
            type(result) is not CompilationResultV1
            or type(result.compiled_plan) is not CompiledWorkflowV1
            or type(result.record) is not CompilationRecordV1
            or type(result.reference) is not ServerCompilationRecordReferenceV1
        ):
            raise failure("FORGED_AUTHORITY", stage="store")
        if (
            type(idempotency_key) is not str
            or len(idempotency_key) != 64
            or any(char not in "0123456789abcdef" for char in idempotency_key)
            or result.idempotency_key != idempotency_key
            or result.record.record_id != f"compilation-record:{idempotency_key}"
        ):
            raise failure("FORGED_AUTHORITY", stage="store")
        if result.compiled_plan is not result.record.compiled_workflow:
            raise failure("FORGED_AUTHORITY", stage="store")
        if result.reference.to_dict() != result.record.reference.to_dict():
            raise failure("FORGED_AUTHORITY", stage="store")
        if result.record.semantic_plan_hash != result.compiled_plan.semantic_plan_hash:
            raise failure("FORGED_AUTHORITY", stage="store")
        try:
            if result.record.record_digest != result.record._computed_record_digest():
                raise failure("FORGED_AUTHORITY", stage="store")
            resolved = self._record_store.resolve(result.reference)
        except (TypeError, ValueError, KeyError) as exc:
            raise failure("FORGED_AUTHORITY", stage="store") from exc
        if resolved is not result.record:
            raise failure("FORGED_AUTHORITY", stage="store")

    def replay(self, idempotency_key: str) -> Any:
        if type(idempotency_key) is not str or not idempotency_key:
            raise failure("REPLAY_NOT_FOUND", stage="store")
        with self._lock:
            try:
                result = self._results[idempotency_key]
            except KeyError as exc:
                raise failure("REPLAY_NOT_FOUND", stage="store") from exc
            self._validate_result(idempotency_key, result)
            return result

    @contextmanager
    def reservation(self, idempotency_key: str) -> Iterator[Any | None]:
        """Atomically claim a compilation key before server-side side effects."""

        if (
            type(idempotency_key) is not str
            or len(idempotency_key) != 64
            or any(char not in "0123456789abcdef" for char in idempotency_key)
        ):
            raise failure("DRAFT_INVALID", stage="store")
        if self._reservation_fd is None:
            raise failure("DURABLE_RESERVATION_REQUIRED", stage="store")
        replay: Any | None = None
        with self._condition:
            while idempotency_key in self._reservations and idempotency_key not in self._results:
                self._condition.wait()
            previous = self._results.get(idempotency_key)
            if previous is not None:
                self._validate_result(idempotency_key, previous)
                replay = previous
            else:
                with _PROCESS_RESERVATION_LOCK:
                    active_owner = _PROCESS_ACTIVE_RESERVATIONS.get(idempotency_key)
                    if active_owner is not None and active_owner is not self:
                        raise failure("IDEMPOTENCY_CONFLICT", stage="store")
                    self._claim_durable_reservation(idempotency_key)
                    _PROCESS_ACTIVE_RESERVATIONS[idempotency_key] = self
                    self._reservations.add(idempotency_key)
        if replay is not None:
            yield replay
            return
        try:
            yield None
        finally:
            with self._condition:
                with _PROCESS_RESERVATION_LOCK:
                    self._reservations.discard(idempotency_key)
                    if _PROCESS_ACTIVE_RESERVATIONS.get(idempotency_key) is self:
                        _PROCESS_ACTIVE_RESERVATIONS.pop(idempotency_key, None)
                self._condition.notify_all()

    def save_result(self, idempotency_key: str, result: Any) -> Any:
        """Save one compiler result; the first immutable result wins."""

        if type(idempotency_key) is not str or not idempotency_key or result is None:
            raise failure("DRAFT_INVALID", stage="store")
        self._validate_result(idempotency_key, result)
        with self._lock:
            previous = self._results.get(idempotency_key)
            if previous is not None:
                self._validate_result(idempotency_key, previous)
                if previous.to_dict() != result.to_dict():
                    raise failure("IDEMPOTENCY_CONFLICT", stage="store")
                return previous
            self._results[idempotency_key] = result
            return result

    def resolve_client_reference(
        self,
        reference: CompilationRecordReferenceV1,
    ) -> tuple[CompilationRecordV1, ServerCompilationRecordReferenceV1]:
        try:
            return self._record_store.resolve_client_reference(reference)
        except (TypeError, ValueError, KeyError) as exc:
            raise failure("REPLAY_NOT_FOUND", stage="store") from exc

    def resolve(self, reference: ServerCompilationRecordReferenceV1) -> CompilationRecordV1:
        if type(reference) is not ServerCompilationRecordReferenceV1:
            raise failure("FORGED_AUTHORITY", stage="store")
        try:
            return self._record_store.resolve(reference)
        except (TypeError, ValueError, KeyError) as exc:
            raise failure("REPLAY_NOT_FOUND", stage="store") from exc

    def issue(self, record: CompilationRecordV1) -> ServerCompilationRecordReferenceV1:
        """Public issuance is intentionally closed to all caller records."""

        if type(record) is not CompilationRecordV1:
            raise failure("FORGED_AUTHORITY", stage="store")
        raise failure("FORGED_AUTHORITY", stage="store")


__all__ = ["CompilationStore"]
