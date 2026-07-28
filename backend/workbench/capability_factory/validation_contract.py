"""Bounded validation evidence contracts for CF3.

Only digests and provenance labels cross this boundary.  Fixtures and outputs
are intentionally not accepted as raw values, and evidence does not itself
admit an implementation into the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError, _content_digest, _digest, _positive_int, _text
from .validation_protocols import CHECK_KINDS


VALIDATION_TIERS = frozenset({"E0", "E1", "E2", "E3"})
VALIDATION_STATUSES = frozenset({"passed", "failed", "inconclusive"})
FIXTURE_VISIBILITIES = frozenset({"author_visible", "service_holdout"})
ORACLE_KINDS = frozenset({"independent_implementation", "trusted_fixture", "independent_review"})
MAX_VALIDATION_CASES = 128
MAX_VALIDATION_EVIDENCE = 256


class ValidationContractError(ContractError):
    """Raised when validation provenance is incomplete or self-authored."""


@dataclass(frozen=True, slots=True)
class ValidationCase:
    case_id: str
    fixture_ref: str
    fixture_visibility: str = "author_visible"
    check_kind: str = "known_truth"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
            object.__setattr__(self, "fixture_ref", _digest(self.fixture_ref, "fixture_ref"))
            if self.fixture_visibility not in FIXTURE_VISIBILITIES:
                raise ValidationContractError("unsupported fixture visibility")
            object.__setattr__(self, "check_kind", _text(self.check_kind, "check_kind"))
            if self.check_kind not in CHECK_KINDS:
                raise ValidationContractError("unsupported validation check kind")
        except ContractError as error:
            if isinstance(error, ValidationContractError):
                raise
            raise ValidationContractError(str(error)) from error

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    evidence_id: str
    case_ref: str
    tier: str
    status: str
    observed_ref: str
    oracle_ref: str | None = None
    oracle_kind: str | None = None
    fixture_visibility: str = "author_visible"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id"))
            object.__setattr__(self, "case_ref", _digest(self.case_ref, "case_ref"))
            if self.tier not in VALIDATION_TIERS:
                raise ValidationContractError("unsupported validation tier")
            if self.status not in VALIDATION_STATUSES:
                raise ValidationContractError("unsupported validation status")
            object.__setattr__(self, "observed_ref", _digest(self.observed_ref, "observed_ref"))
            if self.fixture_visibility not in FIXTURE_VISIBILITIES:
                raise ValidationContractError("unsupported fixture visibility")
            if self.tier in {"E0", "E1"}:
                if self.oracle_ref is not None or self.oracle_kind is not None:
                    raise ValidationContractError("author evidence cannot declare an independent oracle")
            else:
                if self.oracle_ref is None or self.oracle_kind not in ORACLE_KINDS:
                    raise ValidationContractError("E2 and E3 evidence require an independent oracle")
                object.__setattr__(self, "oracle_ref", _digest(self.oracle_ref, "oracle_ref"))
                if self.tier == "E3" and self.fixture_visibility != "service_holdout":
                    raise ValidationContractError("E3 evidence requires a service holdout fixture")
        except ContractError as error:
            if isinstance(error, ValidationContractError):
                raise
            raise ValidationContractError(str(error)) from error

    @property
    def experimental(self) -> bool:
        return self.tier in {"E0", "E1"} or self.status != "passed"

    @property
    def source_eligible(self) -> bool:
        return self.tier in {"E2", "E3"} and self.status == "passed" and self.oracle_ref is not None

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ValidationBundle:
    bundle_id: str
    revision: int
    adapter_ref: str
    cases: tuple[ValidationCase, ...]
    evidence: tuple[ValidationEvidence, ...] = ()

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "bundle_id", _text(self.bundle_id, "bundle_id"))
            object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
            object.__setattr__(self, "adapter_ref", _digest(self.adapter_ref, "adapter_ref"))
            if not isinstance(self.cases, (tuple, list)) or not self.cases:
                raise ValidationContractError("cases must be a non-empty sequence")
            cases = tuple(self.cases)
            if len(cases) > MAX_VALIDATION_CASES or any(not isinstance(item, ValidationCase) for item in cases):
                raise ValidationContractError("cases must be bounded ValidationCase values")
            if len({item.case_id for item in cases}) != len(cases):
                raise ValidationContractError("case_id must be unique")
            if not isinstance(self.evidence, (tuple, list)) or len(self.evidence) > MAX_VALIDATION_EVIDENCE:
                raise ValidationContractError("evidence must be bounded")
            evidence = tuple(self.evidence)
            if any(not isinstance(item, ValidationEvidence) for item in evidence):
                raise ValidationContractError("evidence must contain ValidationEvidence values")
            if len({item.evidence_id for item in evidence}) != len(evidence):
                raise ValidationContractError("evidence_id must be unique")
            cases_by_ref = {item.content_digest: item for item in cases}
            for item in evidence:
                case = cases_by_ref.get(item.case_ref)
                if case is None:
                    raise ValidationContractError("evidence refers to an unknown case")
                if item.fixture_visibility != case.fixture_visibility:
                    raise ValidationContractError("evidence fixture visibility does not match case")
            object.__setattr__(self, "cases", cases)
            object.__setattr__(self, "evidence", evidence)
        except ContractError as error:
            if isinstance(error, ValidationContractError):
                raise
            raise ValidationContractError(str(error)) from error

    def append_evidence(self, evidence: ValidationEvidence) -> "ValidationBundle":
        if not isinstance(evidence, ValidationEvidence):
            raise ValidationContractError("evidence must be a ValidationEvidence")
        return ValidationBundle(
            bundle_id=self.bundle_id,
            revision=self.revision + 1,
            adapter_ref=self.adapter_ref,
            cases=self.cases,
            evidence=self.evidence + (evidence,),
        )

    @property
    def eligible_evidence_refs(self) -> tuple[str, ...]:
        return tuple(item.content_digest for item in self.evidence if item.source_eligible)

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = [
    "FIXTURE_VISIBILITIES",
    "MAX_VALIDATION_CASES",
    "MAX_VALIDATION_EVIDENCE",
    "ORACLE_KINDS",
    "VALIDATION_STATUSES",
    "VALIDATION_TIERS",
    "ValidationBundle",
    "ValidationCase",
    "ValidationContractError",
    "ValidationEvidence",
]
