"""Server-owned CF3 evidence assessments and validity records."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import _content_digest, _digest, _positive_int, _sequence, _text


_STATUSES = frozenset({"passed", "failed", "inconclusive"})
_VALIDITY_STATUSES = frozenset({"valid", "superseded", "invalid"})
_TIERS = frozenset({"E0", "E1", "E2", "E3"})


class EvidenceAssessmentError(ValueError):
    """Raised when evidence validity would become ambiguous or unsafe."""


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    assessment_id: str
    bundle_ref: str
    protocol_ref: str
    attempt_ledger_ref: str
    tier: str
    status: str
    evidence_refs: tuple[str, ...]
    producer_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        for field in ("bundle_ref", "protocol_ref", "attempt_ledger_ref", "producer_ref"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if self.tier not in _TIERS:
            raise EvidenceAssessmentError("unsupported evidence tier")
        object.__setattr__(self, "tier", self.tier)
        if self.status not in _STATUSES:
            raise EvidenceAssessmentError("unsupported evidence assessment status")
        object.__setattr__(self, "status", self.status)
        refs = tuple(_digest(item, "evidence_ref") for item in _sequence(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "evidence_refs", refs)

    @property
    def source_eligible(self) -> bool:
        return self.tier in {"E2", "E3"} and self.status == "passed"

    @property
    def experimental(self) -> bool:
        return not self.source_eligible

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class EvidenceValidityRecord:
    assessment_ref: str
    revision: int
    status: str
    reason: str
    authority_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_ref", _digest(self.assessment_ref, "assessment_ref"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        if self.status not in _VALIDITY_STATUSES:
            raise EvidenceAssessmentError("unsupported evidence validity status")
        object.__setattr__(self, "status", self.status)
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "authority_ref", _digest(self.authority_ref, "authority_ref"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class EvidenceValidityStore:
    def __init__(self) -> None:
        self._history: dict[str, list[EvidenceValidityRecord]] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        assessment: EvidenceAssessment,
        status: str,
        reason: str,
        authority_ref: str,
    ) -> EvidenceValidityRecord:
        if not isinstance(assessment, EvidenceAssessment):
            raise EvidenceAssessmentError("assessment must be an EvidenceAssessment")
        assessment_ref = assessment.content_digest
        with self._lock:
            history = self._history.setdefault(assessment_ref, [])
            latest = history[-1] if history else None
            if latest is not None:
                if latest.status == "invalid":
                    raise EvidenceAssessmentError("invalid evidence validity is terminal")
                if latest.status == "superseded" and status == "valid":
                    raise EvidenceAssessmentError("superseded evidence validity cannot be restored")
                if status == latest.status:
                    raise EvidenceAssessmentError("duplicate evidence validity status")
            record = EvidenceValidityRecord(
                assessment_ref=assessment_ref,
                revision=len(history) + 1,
                status=status,
                reason=reason,
                authority_ref=authority_ref,
            )
            history.append(record)
            return record

    def latest(self, assessment_ref: str) -> EvidenceValidityRecord:
        assessment_ref = _digest(assessment_ref, "assessment_ref")
        try:
            return self._history[assessment_ref][-1]
        except (KeyError, IndexError) as error:
            raise EvidenceAssessmentError("evidence validity was not found") from error


__all__ = [
    "EvidenceAssessment",
    "EvidenceAssessmentError",
    "EvidenceValidityRecord",
    "EvidenceValidityStore",
]
