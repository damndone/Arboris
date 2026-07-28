"""Untrusted CF3 authoring candidates.

Candidates contain immutable references and risk metadata only.  They are not
registry entries, evidence assessments, admissions, or executable payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import _content_digest, _digest, _text


_SOURCE_KINDS = frozenset({"generated_adapter", "authored_implementation"})
_RISK_LEVELS = frozenset({"high", "critical"})


class CandidateStoreError(ValueError):
    """Raised when a candidate identity would be rebound."""


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    candidate_id: str
    capability_kind: str
    source_kind: str
    implementation_ref: str
    source_ref: str
    author_lineage_ref: str
    risk_level: str
    status: str = "submitted"

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "capability_kind", _text(self.capability_kind, "capability_kind"))
        if self.source_kind not in _SOURCE_KINDS:
            raise CandidateStoreError("unsupported candidate source_kind")
        object.__setattr__(self, "source_kind", self.source_kind)
        for field in ("implementation_ref", "source_ref", "author_lineage_ref"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if self.risk_level not in _RISK_LEVELS:
            raise CandidateStoreError("candidate authoring must be high risk")
        object.__setattr__(self, "risk_level", self.risk_level)
        if self.status != "submitted":
            raise CandidateStoreError("candidate status is server-owned and must start submitted")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class CandidateStore:
    """Append-only in-process store keyed by candidate id and content digest."""

    def __init__(self) -> None:
        self._items: dict[str, CapabilityCandidate] = {}
        self._lock = RLock()

    def put(self, candidate: CapabilityCandidate) -> str:
        if not isinstance(candidate, CapabilityCandidate):
            raise CandidateStoreError("only CapabilityCandidate values can be stored")
        with self._lock:
            previous = self._items.get(candidate.candidate_id)
            if previous is not None and previous != candidate:
                raise CandidateStoreError("candidate identity is already bound")
            self._items[candidate.candidate_id] = candidate
            return candidate.content_digest

    def get(self, candidate_id: str) -> CapabilityCandidate:
        try:
            return self._items[candidate_id]
        except KeyError as error:
            raise CandidateStoreError("candidate was not found") from error


__all__ = ["CapabilityCandidate", "CandidateStore", "CandidateStoreError"]
