"""Append-only validation attempt accounting for CF3."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import _content_digest, _digest, _positive_int, _text


_OUTCOMES = frozenset({"passed", "failed", "inconclusive"})
DEFAULT_MAX_ATTEMPTS = 3


class ValidationLedgerError(ValueError):
    """Raised when an attempt stream is malformed."""


class AttemptBudgetExceeded(ValidationLedgerError):
    """Raised when a protocol attempt budget has been consumed."""


@dataclass(frozen=True, slots=True)
class ValidationAttempt:
    bundle_ref: str
    protocol_ref: str
    attempt_number: int
    outcome: str
    result_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_ref", _digest(self.bundle_ref, "bundle_ref"))
        object.__setattr__(self, "protocol_ref", _digest(self.protocol_ref, "protocol_ref"))
        object.__setattr__(self, "attempt_number", _positive_int(self.attempt_number, "attempt_number"))
        if self.outcome not in _OUTCOMES:
            raise ValidationLedgerError("unsupported validation attempt outcome")
        object.__setattr__(self, "outcome", _text(self.outcome, "outcome"))
        object.__setattr__(self, "result_ref", _digest(self.result_ref, "result_ref"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class ValidationAttemptLedger:
    def __init__(self) -> None:
        self._history: dict[tuple[str, str], list[ValidationAttempt]] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        bundle_ref: str,
        protocol_ref: str,
        attempt_number: int,
        outcome: str,
        result_ref: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> ValidationAttempt:
        bundle_ref = _digest(bundle_ref, "bundle_ref")
        protocol_ref = _digest(protocol_ref, "protocol_ref")
        max_attempts = _positive_int(max_attempts, "max_attempts")
        key = (bundle_ref, protocol_ref)
        with self._lock:
            history = self._history.setdefault(key, [])
            if len(history) >= max_attempts:
                raise AttemptBudgetExceeded("validation attempt budget is exhausted")
            expected = len(history) + 1
            if attempt_number != expected:
                raise ValidationLedgerError("attempt_number must be the next sequential attempt")
            attempt = ValidationAttempt(bundle_ref, protocol_ref, attempt_number, outcome, result_ref)
            history.append(attempt)
            return attempt

    def history(self, bundle_ref: str, protocol_ref: str) -> tuple[ValidationAttempt, ...]:
        key = (_digest(bundle_ref, "bundle_ref"), _digest(protocol_ref, "protocol_ref"))
        with self._lock:
            return tuple(self._history.get(key, ()))

    def stream_digest(self, bundle_ref: str, protocol_ref: str) -> str:
        history = self.history(bundle_ref, protocol_ref)
        return _content_digest({"bundle_ref": bundle_ref, "protocol_ref": protocol_ref, "attempts": history})


__all__ = [
    "AttemptBudgetExceeded",
    "DEFAULT_MAX_ATTEMPTS",
    "ValidationAttempt",
    "ValidationAttemptLedger",
    "ValidationLedgerError",
]
