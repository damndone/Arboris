"""One-time, server-issued confirmation receipts for local memory mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import secrets
from threading import RLock
from typing import Callable


class MemoryMutationConfirmationError(ValueError):
    """A confirmation receipt is absent, stale, consumed, or bound elsewhere."""


_ACTION = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


@dataclass(frozen=True, slots=True)
class MemoryMutationIntent:
    action: str
    scope_ref: str
    expected_revision: int
    target_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or not _ACTION.fullmatch(self.action):
            raise MemoryMutationConfirmationError("confirmation action is invalid")
        if not isinstance(self.scope_ref, str) or not self.scope_ref or len(self.scope_ref) > 256:
            raise MemoryMutationConfirmationError("confirmation scope is invalid")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise MemoryMutationConfirmationError("confirmation revision is invalid")
        if not isinstance(self.target_refs, tuple) or len(self.target_refs) > 1024:
            raise MemoryMutationConfirmationError("confirmation targets are invalid")
        if tuple(sorted(set(self.target_refs))) != self.target_refs or any(
            not isinstance(item, str) or not item or len(item) > 256 for item in self.target_refs
        ):
            raise MemoryMutationConfirmationError("confirmation targets must be unique and sorted")

    @property
    def binding_hash(self) -> str:
        payload = {
            "action": self.action,
            "scope_ref": self.scope_ref,
            "expected_revision": self.expected_revision,
            "target_refs": list(self.target_refs),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryMutationConfirmation:
    receipt: str
    action: str
    scope_ref: str
    expected_revision: int
    target_count: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _IssuedConfirmation:
    binding_hash: str
    expires_at: datetime


class MemoryMutationConfirmationRegistry:
    """In-memory short-lived receipts: restart discards them and therefore fails closed."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0) or ttl > timedelta(minutes=10):
            raise MemoryMutationConfirmationError("confirmation TTL is invalid")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl
        self._issued: dict[str, _IssuedConfirmation] = {}
        self._lock = RLock()

    def issue(self, intent: MemoryMutationIntent) -> MemoryMutationConfirmation:
        if not isinstance(intent, MemoryMutationIntent):
            raise MemoryMutationConfirmationError("confirmation intent is required")
        now = self._now()
        receipt = secrets.token_urlsafe(32)
        expires_at = now + self._ttl
        with self._lock:
            self._purge_expired(now)
            self._issued[receipt] = _IssuedConfirmation(intent.binding_hash, expires_at)
        return MemoryMutationConfirmation(
            receipt=receipt,
            action=intent.action,
            scope_ref=intent.scope_ref,
            expected_revision=intent.expected_revision,
            target_count=len(intent.target_refs),
            expires_at=expires_at,
        )

    def consume(self, receipt: str, intent: MemoryMutationIntent) -> None:
        if not isinstance(receipt, str) or not receipt or len(receipt) > 256:
            raise MemoryMutationConfirmationError("confirmation receipt is invalid")
        if not isinstance(intent, MemoryMutationIntent):
            raise MemoryMutationConfirmationError("confirmation intent is required")
        now = self._now()
        with self._lock:
            issued = self._issued.pop(receipt, None)
            if issued is None:
                raise MemoryMutationConfirmationError("confirmation is unknown or consumed")
            if issued.expires_at <= now:
                raise MemoryMutationConfirmationError("confirmation is expired")
            if not secrets.compare_digest(issued.binding_hash, intent.binding_hash):
                raise MemoryMutationConfirmationError("confirmation binding does not match")

    def _purge_expired(self, now: datetime) -> None:
        for receipt, issued in tuple(self._issued.items()):
            if issued.expires_at <= now:
                self._issued.pop(receipt, None)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise MemoryMutationConfirmationError("confirmation clock is invalid")
        if value.tzinfo is None:
            raise MemoryMutationConfirmationError("confirmation clock must be timezone-aware")
        return value.astimezone(UTC)


__all__ = [
    "MemoryMutationConfirmation",
    "MemoryMutationConfirmationError",
    "MemoryMutationConfirmationRegistry",
    "MemoryMutationIntent",
]
