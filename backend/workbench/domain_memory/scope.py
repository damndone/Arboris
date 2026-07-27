"""Explicit namespace and access scope for cross-project domain memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..custom_capability.canonical import domain_digest


class DomainMemoryScopeError(ValueError):
    """A domain-memory scope is missing, malformed, or not authorized."""


_MAX_ID = 128
_VISIBILITY = frozenset({"private", "organization"})
_PROMOTION = frozenset({"user", "organization"})


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_ID:
        raise DomainMemoryScopeError(f"{field} must be bounded non-empty text")
    if value in {".", ".."} or "/" in value or "\\" in value or any(ord(char) < 0x20 for char in value):
        raise DomainMemoryScopeError(f"{field} must be an opaque path-safe id")
    return value


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Server-resolved identity scope; paths are only a storage projection."""

    namespace_id: str
    profile_id: str
    owner_id: str
    organization_id: str | None
    visibility_scope: str
    promotion_scope: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace_id", _identifier(self.namespace_id, "namespace_id"))
        object.__setattr__(self, "profile_id", _identifier(self.profile_id, "profile_id"))
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        if self.organization_id is not None:
            object.__setattr__(self, "organization_id", _identifier(self.organization_id, "organization_id"))
        if self.visibility_scope not in _VISIBILITY:
            raise DomainMemoryScopeError("visibility_scope is not registered")
        if self.promotion_scope not in _PROMOTION:
            raise DomainMemoryScopeError("promotion_scope is not registered")
        if self.visibility_scope == "organization" and self.organization_id is None:
            raise DomainMemoryScopeError("organization visibility requires organization_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace_id": self.namespace_id,
            "profile_id": self.profile_id,
            "owner_id": self.owner_id,
            "organization_id": self.organization_id,
            "visibility_scope": self.visibility_scope,
            "promotion_scope": self.promotion_scope,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "MemoryScope":
        if not isinstance(value, dict) or set(value) != {
            "namespace_id",
            "profile_id",
            "owner_id",
            "organization_id",
            "visibility_scope",
            "promotion_scope",
        }:
            raise DomainMemoryScopeError("memory scope fields are invalid")
        return cls(**value)

    @property
    def scope_ref(self) -> str:
        return domain_digest("workbench.domain-memory.scope/v1", self.to_dict())

    def exact_match(self, other: "MemoryScope") -> bool:
        return isinstance(other, MemoryScope) and self.to_dict() == other.to_dict()

    def can_read(self, requester: "MemoryScope") -> bool:
        if not isinstance(requester, MemoryScope):
            return False
        if self.namespace_id != requester.namespace_id or self.profile_id != requester.profile_id:
            return False
        if self.visibility_scope == "private":
            return self.owner_id == requester.owner_id
        return self.organization_id is not None and self.organization_id == requester.organization_id


__all__ = ["DomainMemoryScopeError", "MemoryScope"]
