"""Bounded, de-identified input contracts for the MEM3 curator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar
import re

from ..custom_capability.canonical import domain_digest
from .contracts import (
    ApplicabilityPredicate,
    DomainMemoryContractError,
    EFFECT_KINDS,
    MEMORY_KINDS,
    SourceSummaryRef,
)
from .scope import DomainMemoryScopeError, MemoryScope


CURATOR_CONTRACT_VERSION = "domain-memory-curator/v1"
SUMMARY_CONTRACT_VERSION = "accepted-analysis-summary/v1"
OBSERVATION_CONTRACT_VERSION = "curator-observation/v1"
_MAX_ID = 256
_MAX_TEXT = 512
_MAX_OBSERVATIONS = 16
_MAX_TAGS = 16
_UNSAFE = re.compile(r"(?:/Users/|/private/|/tmp/|[A-Za-z]:\\|\\\\|\b(?:row[_ -]?id|artifact[_ -]?ref|trace[_ -]?payload|api[_ -]?key|secret|token)\b)", re.IGNORECASE)


class CuratorReviewPoint(str, Enum):
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_ABANDONED = "analysis_abandoned"
    CAPABILITY_REVIEW_COMPLETED = "capability_review_completed"
    USER_REQUESTED_SUMMARY = "user_requested_summary"


def _text(value: Any, field_name: str, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(char) < 0x20 for char in value):
        raise DomainMemoryContractError(f"{field_name} must be bounded text")
    if _UNSAFE.search(value):
        raise DomainMemoryContractError(f"{field_name} contains a raw or sensitive reference")
    return value


def _identifier(value: Any, field_name: str) -> str:
    value = _text(value, field_name, _MAX_ID)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DomainMemoryContractError(f"{field_name} must be an opaque id")
    return value


def _scope(value: Any) -> MemoryScope:
    if isinstance(value, MemoryScope):
        return value
    try:
        return MemoryScope.from_dict(value)
    except (DomainMemoryScopeError, TypeError) as error:
        raise DomainMemoryContractError("curator scope is invalid") from error


def _predicates(value: Any) -> tuple[ApplicabilityPredicate, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 16:
        raise DomainMemoryContractError("curator predicates are out of bounds")
    result = tuple(item if isinstance(item, ApplicabilityPredicate) else ApplicabilityPredicate.from_dict(item) for item in value)
    if len({item.predicate_id for item in result}) != len(result):
        raise DomainMemoryContractError("curator predicate ids must be unique")
    if not result:
        raise DomainMemoryContractError("curator observations require a hard applicability gate")
    return result


def _refs(value: Any, field_name: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise DomainMemoryContractError(f"{field_name} is out of bounds")
    result = tuple(_identifier(item, field_name[:-1] if field_name.endswith("s") else field_name) for item in value)
    if len(set(result)) != len(result):
        raise DomainMemoryContractError(f"{field_name} must be unique")
    return result


def _sources(value: Any) -> tuple[SourceSummaryRef, ...]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > 8:
        raise DomainMemoryContractError("curator source refs must be bounded and non-empty")
    result = tuple(item if isinstance(item, SourceSummaryRef) else SourceSummaryRef.from_dict(item) for item in value)
    if len({item.source_access_binding_ref for item in result}) != len(result):
        raise DomainMemoryContractError("curator source bindings must be unique")
    return result


@dataclass(frozen=True, slots=True)
class CuratorObservation:
    observation_ref: str
    memory_kind: str
    domain_tags: tuple[str, ...]
    applicability_predicates: tuple[ApplicabilityPredicate, ...]
    compact_lesson: str
    recommended_effect_kind: str
    recommended_target_refs: tuple[str, ...]
    source_summary_refs: tuple[SourceSummaryRef, ...]
    evidence_status: str

    CONTRACT_VERSION: ClassVar[str] = OBSERVATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_ref", _identifier(self.observation_ref, "observation_ref"))
        if self.memory_kind not in MEMORY_KINDS:
            raise DomainMemoryContractError("curator memory_kind is not registered")
        object.__setattr__(self, "domain_tags", _refs(self.domain_tags, "domain_tags", _MAX_TAGS))
        if not self.domain_tags:
            raise DomainMemoryContractError("curator domain_tags must not be empty")
        object.__setattr__(self, "applicability_predicates", _predicates(self.applicability_predicates))
        object.__setattr__(self, "compact_lesson", _text(self.compact_lesson, "compact_lesson"))
        if self.recommended_effect_kind not in EFFECT_KINDS:
            raise DomainMemoryContractError("curator effect is not registered")
        object.__setattr__(self, "recommended_target_refs", _refs(self.recommended_target_refs, "recommended_target_refs", 16))
        object.__setattr__(self, "source_summary_refs", _sources(self.source_summary_refs))
        if self.evidence_status not in {"observed_once", "observed_repeatedly", "independently_reviewed"}:
            raise DomainMemoryContractError("curator evidence status is not registered")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.CONTRACT_VERSION,
            "observation_ref": self.observation_ref,
            "memory_kind": self.memory_kind,
            "domain_tags": list(self.domain_tags),
            "applicability_predicates": [item.to_dict() for item in self.applicability_predicates],
            "compact_lesson": self.compact_lesson,
            "recommended_effect_kind": self.recommended_effect_kind,
            "recommended_target_refs": list(self.recommended_target_refs),
            "source_summary_refs": [item.to_dict() for item in self.source_summary_refs],
            "evidence_status": self.evidence_status,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CuratorObservation":
        expected = {"contract_version", "observation_ref", "memory_kind", "domain_tags", "applicability_predicates", "compact_lesson", "recommended_effect_kind", "recommended_target_refs", "source_summary_refs", "evidence_status"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("curator observation fields are invalid")
        data = dict(value); data.pop("contract_version")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AcceptedAnalysisSummary:
    summary_ref: str
    summary_hash: str
    scope: MemoryScope
    review_point: CuratorReviewPoint
    analysis_state: str
    complete: bool
    critical_omission: bool
    policy_allows: bool
    observations: tuple[CuratorObservation, ...]
    created_at: str
    idempotency_key: str = field(init=False)

    CONTRACT_VERSION: ClassVar[str] = SUMMARY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary_ref", _identifier(self.summary_ref, "summary_ref"))
        if not isinstance(self.summary_hash, str) or len(self.summary_hash) != 64 or any(char not in "0123456789abcdef" for char in self.summary_hash):
            raise DomainMemoryContractError("summary_hash must be a lowercase SHA-256 digest")
        object.__setattr__(self, "scope", _scope(self.scope))
        try:
            point = self.review_point if isinstance(self.review_point, CuratorReviewPoint) else CuratorReviewPoint(self.review_point)
        except (TypeError, ValueError) as error:
            raise DomainMemoryContractError("review_point is not registered") from error
        object.__setattr__(self, "review_point", point)
        if self.analysis_state not in {"accepted", "abandoned"}:
            raise DomainMemoryContractError("analysis_state is not registered")
        if type(self.complete) is not bool or type(self.critical_omission) is not bool or type(self.policy_allows) is not bool:
            raise DomainMemoryContractError("curator summary gates must be booleans")
        if not isinstance(self.observations, (list, tuple)) or len(self.observations) > _MAX_OBSERVATIONS:
            raise DomainMemoryContractError("curator observations exceed the bound")
        normalized = tuple(item if isinstance(item, CuratorObservation) else CuratorObservation.from_dict(item) for item in self.observations)
        if len({item.observation_ref for item in normalized}) != len(normalized):
            raise DomainMemoryContractError("curator observation refs must be unique")
        object.__setattr__(self, "observations", normalized)
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at", 64))
        object.__setattr__(self, "idempotency_key", domain_digest("workbench.domain-memory.curator-summary/v1", self._semantic_dict()))

    def _semantic_dict(self) -> dict[str, Any]:
        return {
            "summary_ref": self.summary_ref,
            "summary_hash": self.summary_hash,
            "scope": self.scope.to_dict(),
            "review_point": self.review_point.value,
            "analysis_state": self.analysis_state,
            "complete": self.complete,
            "critical_omission": self.critical_omission,
            "policy_allows": self.policy_allows,
            "observations": [item.to_dict() for item in self.observations],
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.CONTRACT_VERSION, **self._semantic_dict(), "idempotency_key": self.idempotency_key}

    @classmethod
    def from_dict(cls, value: Any) -> "AcceptedAnalysisSummary":
        expected = {"contract_version", "summary_ref", "summary_hash", "scope", "review_point", "analysis_state", "complete", "critical_omission", "policy_allows", "observations", "created_at", "idempotency_key"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("accepted analysis summary fields are invalid")
        data = dict(value); expected_key = data.pop("idempotency_key"); data.pop("contract_version")
        result = cls(**data)
        if result.idempotency_key != expected_key:
            raise DomainMemoryContractError("summary idempotency_key does not match content")
        return result


__all__ = ["AcceptedAnalysisSummary", "CURATOR_CONTRACT_VERSION", "CuratorObservation", "CuratorReviewPoint"]
