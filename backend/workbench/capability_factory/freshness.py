"""Shared validity cursor checks for CF1 resolution."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from ..custom_capability.canonical import domain_digest
from .contracts import _digest, _text


class FreshnessContractError(ValueError):
    """Raised when a validity cursor is malformed."""


@dataclass(frozen=True, slots=True)
class ValidityCursor:
    domain: str
    sequence: int
    state_digest: str
    authority_ref: str
    status: str = "valid"
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain", _text(self.domain, "domain"))
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise FreshnessContractError("sequence must be a positive integer")
        try:
            object.__setattr__(self, "state_digest", _digest(self.state_digest, "state_digest"))
            object.__setattr__(self, "authority_ref", _digest(self.authority_ref, "authority_ref"))
        except ValueError as error:
            raise FreshnessContractError(str(error)) from error
        if self.status not in {"valid", "revoked", "expired"}:
            raise FreshnessContractError("status must be valid, revoked, or expired")
        if not isinstance(self.valid_until, datetime) or self.valid_until.tzinfo is None:
            raise FreshnessContractError("valid_until must be timezone-aware")
        object.__setattr__(self, "valid_until", self.valid_until.astimezone(timezone.utc))


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ValidityCursorSnapshot:
    cursors: Mapping[str, ValidityCursor]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.cursors, Mapping) or not self.cursors:
            raise FreshnessContractError("cursors must be a non-empty object")
        normalized: dict[str, ValidityCursor] = {}
        for domain, cursor in self.cursors.items():
            if not isinstance(cursor, ValidityCursor) or cursor.domain != domain:
                raise FreshnessContractError("cursor map keys must match cursor domains")
            normalized[_text(domain, "cursor domain")] = cursor
        object.__setattr__(self, "cursors", MappingProxyType(normalized))
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise FreshnessContractError("observed_at must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.validity_cursor/v1", _plain(self))


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    status: str
    reason_code: str
    missing_domains: tuple[str, ...] = ()


def assess_freshness(
    *,
    required_domains: tuple[str, ...],
    candidate_refs: Mapping[str, str],
    current: ValidityCursorSnapshot,
) -> FreshnessResult:
    """Compare immutable candidate refs with the current mutable cursors."""

    if not isinstance(current, ValidityCursorSnapshot):
        raise FreshnessContractError("current must be a ValidityCursorSnapshot")
    domains = tuple(_text(domain, "required domain") for domain in required_domains)
    missing: list[str] = []
    stale = False
    for domain in domains:
        cursor = current.cursors.get(domain)
        candidate_ref = candidate_refs.get(domain) if isinstance(candidate_refs, Mapping) else None
        if cursor is None or candidate_ref is None:
            missing.append(domain)
            continue
        if cursor.status != "valid" or cursor.valid_until <= current.observed_at:
            stale = True
            continue
        if _digest(candidate_ref, "candidate validity reference") != cursor.state_digest:
            stale = True
    if missing:
        return FreshnessResult("unavailable", "validity_domain_missing", tuple(sorted(set(missing))))
    if stale:
        return FreshnessResult("stale", "validity_cursor_mismatch")
    return FreshnessResult("current", "validity_current")


__all__ = [
    "FreshnessContractError",
    "FreshnessResult",
    "ValidityCursor",
    "ValidityCursorSnapshot",
    "assess_freshness",
]
