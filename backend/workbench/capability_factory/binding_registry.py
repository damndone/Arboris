"""Durable identity index for the server-owned Notebook capability catalog.

The index is intentionally not a binding store.  It persists only the
capability name, the content reference of an already verified binding, and
the bounded Agent-facing planner projection.  A fresh service must resolve
the binding through a trusted loader before the catalog can expose it again.
Writes are FD-bound and append-only; this module has no execution or network
surface.
"""

from __future__ import annotations

import errno
import fcntl
import json
import math
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from ..custom_capability.canonical import domain_digest
from .notebook_binding import CapabilityResolutionBinding
from .notebook_catalog import CapabilityBindingCatalog


_JOURNAL_NAME = "capability-binding-index.jsonl"
_LOCK_NAME = ".capability-binding-index.lock"
_RECORD_TYPE = "capability_binding_index"
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_MAX_RECORD_BYTES = 256 * 1024
_MAX_ITEMS = 128
_MAX_DEPTH = 8
_HEX = frozenset("0123456789abcdef")


class DurableBindingIndexError(ValueError):
    """Raised when the durable binding index cannot be trusted."""


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise DurableBindingIndexError(f"{field} must be bounded non-empty text")
    if any(ord(char) < 0x20 for char in value):
        raise DurableBindingIndexError(f"{field} contains a control character")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise DurableBindingIndexError(f"{field} must be path-safe")
    return text


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise DurableBindingIndexError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DurableBindingIndexError(f"{field} must be a positive integer")
    return value


def _freeze(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise DurableBindingIndexError("planner projection is too deeply nested")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            return _text(value, "planner projection text", maximum=1024)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DurableBindingIndexError("planner projection numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_ITEMS:
            raise DurableBindingIndexError("planner projection has too many keys")
        return {
            _text(key, "planner projection key", maximum=256): _freeze(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_ITEMS:
            raise DurableBindingIndexError("planner projection has too many items")
        return [_freeze(item, depth=depth + 1) for item in value]
    raise DurableBindingIndexError(
        f"planner projection contains unsupported value: {type(value).__name__}"
    )


def _projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DurableBindingIndexError("planner_projection must be an object or null")
    frozen = _freeze(value)
    if not isinstance(frozen, dict):
        raise DurableBindingIndexError("planner_projection must be an object")
    return frozen


@dataclass(frozen=True, slots=True)
class DurableBindingIndexRecord:
    sequence: int
    capability_id: str
    binding_ref: str
    planner_projection: Mapping[str, Any] | None
    record_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence", _positive_int(self.sequence, "sequence"))
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        object.__setattr__(self, "binding_ref", _digest(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "planner_projection", _projection(self.planner_projection))
        object.__setattr__(self, "record_digest", _digest(self.record_digest, "record_digest"))

    def _payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "capability_id": self.capability_id,
            "binding_ref": self.binding_ref,
            "planner_projection": self.planner_projection,
        }

    @property
    def expected_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.binding_index_record/v1",
            {"record_type": _RECORD_TYPE, **self._payload()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": _RECORD_TYPE,
            **self._payload(),
            "record_digest": self.record_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DurableBindingIndexRecord":
        expected = {
            "record_type",
            "sequence",
            "capability_id",
            "binding_ref",
            "planner_projection",
            "record_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["record_type"] != _RECORD_TYPE:
            raise DurableBindingIndexError("binding index journal record shape is invalid")
        try:
            result = cls(
                sequence=value["sequence"],
                capability_id=value["capability_id"],
                binding_ref=value["binding_ref"],
                planner_projection=value["planner_projection"],
                record_digest=value["record_digest"],
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, DurableBindingIndexError):
                raise
            raise DurableBindingIndexError("binding index journal record is invalid") from error
        if result.record_digest != result.expected_digest:
            raise DurableBindingIndexError("binding index journal record digest mismatch")
        return result


class DurableBindingIndex:
    """FD-bound append-only index with fail-closed replay."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._root_fd = os.open(
                self.root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as error:
            raise DurableBindingIndexError("binding index root is not a trusted directory") from error
        self.journal_path = self.root / _JOURNAL_NAME
        try:
            with self._lock():
                self._load_locked()
        except Exception:
            os.close(self._root_fd)
            raise

    def append(
        self,
        *,
        capability_id: str,
        binding_ref: str,
        planner_projection: Mapping[str, Any] | None,
    ) -> DurableBindingIndexRecord:
        capability_id = _identifier(capability_id, "capability_id")
        binding_ref = _digest(binding_ref, "binding_ref")
        projection = _projection(planner_projection)
        with self._lock():
            records = self._load_locked()
            current = next((item for item in records if item.capability_id == capability_id), None)
            if current is not None:
                if current.binding_ref != binding_ref:
                    raise DurableBindingIndexError("capability binding identity is immutable")
                if current.planner_projection != projection:
                    raise DurableBindingIndexError("capability planner projection is immutable")
                return current
            record = DurableBindingIndexRecord(
                sequence=(records[-1].sequence + 1 if records else 1),
                capability_id=capability_id,
                binding_ref=binding_ref,
                planner_projection=projection,
                record_digest="0" * 64,
            )
            record = DurableBindingIndexRecord(
                sequence=record.sequence,
                capability_id=record.capability_id,
                binding_ref=record.binding_ref,
                planner_projection=record.planner_projection,
                record_digest=record.expected_digest,
            )
            self._append_locked(record)
            return record

    def records(self) -> tuple[DurableBindingIndexRecord, ...]:
        with self._lock():
            return self._load_locked()

    def _load_locked(self) -> tuple[DurableBindingIndexRecord, ...]:
        try:
            fd = self._open_at(_JOURNAL_NAME, os.O_RDONLY)
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise DurableBindingIndexError("binding index journal cannot be opened safely") from error
        try:
            size = os.fstat(fd).st_size
            if size > _MAX_JOURNAL_BYTES:
                raise DurableBindingIndexError("binding index journal is too large")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        except OSError as error:
            raise DurableBindingIndexError("binding index journal cannot be read") from error
        finally:
            os.close(fd)
        if not raw:
            return ()
        records: list[DurableBindingIndexRecord] = []
        seen: set[str] = set()
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line or len(line) > _MAX_RECORD_BYTES:
                raise DurableBindingIndexError(f"binding index journal line {number} is invalid")
            try:
                value = json.loads(line.decode("utf-8"))
                record = DurableBindingIndexRecord.from_dict(value)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
                if isinstance(error, DurableBindingIndexError):
                    raise
                raise DurableBindingIndexError(
                    f"binding index journal line {number} is malformed"
                ) from error
            if record.sequence != number:
                raise DurableBindingIndexError("binding index sequence is not strictly monotonic")
            if record.capability_id in seen:
                raise DurableBindingIndexError("binding index contains a duplicate capability id")
            seen.add(record.capability_id)
            records.append(record)
        return tuple(records)

    def _append_locked(self, record: DurableBindingIndexRecord) -> None:
        line = (json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        if len(line) > _MAX_RECORD_BYTES:
            raise DurableBindingIndexError("binding index record is too large")
        try:
            fd = self._open_at(
                _JOURNAL_NAME,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                mode=0o600,
            )
            try:
                view = memoryview(line)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError(errno.EIO, "binding index append made no progress")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as error:
            raise DurableBindingIndexError("binding index append failed") from error

    def _open_at(self, name: str, flags: int, *, mode: int = 0o600) -> int:
        return os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=self._root_fd)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        try:
            fd = self._open_at(_LOCK_NAME, os.O_RDWR | os.O_CREAT, mode=0o600)
        except OSError as error:
            raise DurableBindingIndexError("binding index lock cannot be opened safely") from error
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        except OSError as error:
            raise DurableBindingIndexError("binding index lock failed") from error
        finally:
            os.close(fd)


class DurableCapabilityBindingCatalog(CapabilityBindingCatalog):
    """Notebook-compatible catalog backed by verified binding references."""

    def __init__(self, *, verifier: Callable[[CapabilityResolutionBinding], None], index: DurableBindingIndex) -> None:
        if not isinstance(index, DurableBindingIndex):
            raise DurableBindingIndexError("index must be a DurableBindingIndex")
        super().__init__(verifier=verifier)
        self._index = index

    def register(
        self,
        capability_id: str,
        binding: CapabilityResolutionBinding,
        *,
        planner_projection: Mapping[str, Any] | None = None,
    ) -> str:
        probe = CapabilityBindingCatalog(verifier=self._verifier)
        probe.register(capability_id, binding, planner_projection=planner_projection)
        normalized = (
            probe.planner_projection(capability_id)
            if planner_projection is not None
            else None
        )
        digest = self._index.append(
            capability_id=capability_id,
            binding_ref=binding.content_digest,
            planner_projection=normalized,
        )
        registered = super().register(
            capability_id,
            binding,
            planner_projection=normalized,
        )
        if registered != digest.binding_ref:
            raise DurableBindingIndexError("durable binding identity did not match catalog")
        return registered

    def restore(
        self,
        binding_loader: Callable[[str], CapabilityResolutionBinding],
    ) -> None:
        if not callable(binding_loader):
            raise DurableBindingIndexError("binding loader must be callable")
        for record in self._index.records():
            try:
                binding = binding_loader(record.binding_ref)
            except Exception as error:
                raise DurableBindingIndexError("trusted binding loader failed") from error
            if not isinstance(binding, CapabilityResolutionBinding):
                raise DurableBindingIndexError("trusted binding loader returned an invalid binding")
            if binding.content_digest != record.binding_ref:
                raise DurableBindingIndexError("trusted binding loader returned a mismatched binding")
            try:
                super().register(
                    record.capability_id,
                    binding,
                    planner_projection=record.planner_projection,
                )
            except Exception as error:
                raise DurableBindingIndexError("restored binding is not currently usable") from error


__all__ = [
    "DurableBindingIndex",
    "DurableBindingIndexError",
    "DurableBindingIndexRecord",
    "DurableCapabilityBindingCatalog",
]
