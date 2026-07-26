"""Append-only mutable validity/control state for CF1."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping

from ..custom_capability.canonical import domain_digest
from .contracts import _text


class OptimisticConcurrencyError(RuntimeError):
    """Raised when a control writer uses an old sequence."""


def _freeze(value: Any, *, depth: int = 0) -> Any:
    if depth > 16:
        raise ValueError("control value exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("control values must be finite")
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({_text(key, "control key"): _freeze(item, depth=depth + 1) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        if len(value) > 1024:
            raise ValueError("control sequence is too long")
        return tuple(_freeze(item, depth=depth + 1) for item in value)
    raise ValueError(f"unsupported control value: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ControlRecord:
    namespace: str
    sequence: int
    value: Mapping[str, Any]
    value_digest: str


class AppendOnlyControlStore:
    """Serializes writes while retaining every state revision."""

    def __init__(self) -> None:
        self._history: dict[str, list[ControlRecord]] = {}
        self._lock = RLock()

    def append(self, *, namespace: str, value: Mapping[str, Any], expected_sequence: int) -> ControlRecord:
        namespace = _text(namespace, "namespace")
        if not isinstance(expected_sequence, int) or isinstance(expected_sequence, bool) or expected_sequence < 0:
            raise ValueError("expected_sequence must be a non-negative integer")
        frozen = _freeze(value)
        if not isinstance(frozen, Mapping):
            raise ValueError("control value must be an object")
        with self._lock:
            history = self._history.setdefault(namespace, [])
            current_sequence = history[-1].sequence if history else 0
            if expected_sequence != current_sequence:
                raise OptimisticConcurrencyError(
                    f"namespace {namespace!r} is at sequence {current_sequence}, expected {expected_sequence}"
                )
            sequence = current_sequence + 1
            digest = domain_digest(
                "workbench.capability_factory.control/v1",
                {"namespace": namespace, "sequence": sequence, "value": _plain(frozen)},
            )
            record = ControlRecord(namespace, sequence, frozen, digest)
            history.append(record)
            return record

    def history(self, namespace: str) -> tuple[ControlRecord, ...]:
        return tuple(self._history.get(namespace, ()))

    def latest(self, namespace: str) -> ControlRecord | None:
        history = self._history.get(namespace)
        return history[-1] if history else None


__all__ = ["AppendOnlyControlStore", "ControlRecord", "OptimisticConcurrencyError"]
