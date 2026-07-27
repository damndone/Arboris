"""Immutable, bounded contracts for cross-project domain memory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar
import re

from ..custom_capability.canonical import domain_digest
from .scope import DomainMemoryScopeError, MemoryScope


DOMAIN_MEMORY_CONTRACT_VERSION = "domain-memory/v1"
CONTENT_CONTRACT_VERSION = "domain-memory-content-revision/v1"
CANDIDATE_CONTRACT_VERSION = "domain-memory-candidate/v1"
APPROVAL_CONTRACT_VERSION = "domain-memory-approval/v1"
VALIDITY_CONTRACT_VERSION = "domain-memory-validity/v1"

MEMORY_KINDS = frozenset(
    {"workflow_lesson", "capability_caveat", "inspection_hint", "user_working_preference", "reporting_preference"}
)
EFFECT_KINDS = frozenset(
    {"candidate_retrieval_hint", "inspection_plan_hint", "assumption_check_hint", "known_caveat", "reporting_preference"}
)
PREDICATE_OPERATORS = frozenset({"equals", "not_equals", "one_of", "exists"})
EVIDENCE_STATUSES = frozenset({"observed_once", "observed_repeatedly", "independently_reviewed"})
CANDIDATE_STATES = frozenset({"proposed", "needs_review", "approved", "rejected", "expired"})
VALIDITY_STATES = frozenset({"active", "stale", "archived"})

_HEX = frozenset("0123456789abcdef")
_MAX_ID = 256
_MAX_TEXT = 512
_MAX_TAGS = 32
_MAX_PREDICATES = 16
_MAX_SOURCES = 8
_MAX_TARGET_REFS = 16
_MAX_CONFLICTS = 16
_MAX_EVIDENCE_REFS = 16
_UNSAFE_TEXT = re.compile(
    r"(?:/Users/|/private/|/tmp/|[A-Za-z]:\\|\\\\|\b(?:row[_ -]?id|artifact[_ -]?ref|trace[_ -]?payload|api[_ -]?key|secret|token)\b)",
    re.IGNORECASE,
)


class DomainMemoryContractError(ValueError):
    """A domain-memory record is malformed or violates a safety boundary."""


def _text(value: Any, field_name: str, *, maximum: int = _MAX_TEXT, unsafe: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise DomainMemoryContractError(f"{field_name} must be bounded non-empty text")
    if any(ord(char) < 0x20 for char in value):
        raise DomainMemoryContractError(f"{field_name} contains a control character")
    if unsafe and _UNSAFE_TEXT.search(value):
        raise DomainMemoryContractError(f"{field_name} contains a disallowed raw reference")
    return value


def _identifier(value: Any, field_name: str) -> str:
    value = _text(value, field_name, maximum=_MAX_ID)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DomainMemoryContractError(f"{field_name} must be an opaque path-safe id")
    return value


def _digest(value: Any, field_name: str) -> str:
    value = _text(value, field_name, maximum=64)
    if len(value) != 64 or any(char not in _HEX for char in value):
        raise DomainMemoryContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _revision(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DomainMemoryContractError(f"{field_name} must be a positive integer")
    return value


def _optional_id(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field_name)


def _refs(value: Any, field_name: str, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise DomainMemoryContractError(f"{field_name} exceeds its bounded field limit")
    normalized = tuple(_identifier(item, field_name[:-1] if field_name.endswith("s") else field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise DomainMemoryContractError(f"{field_name} must contain unique refs")
    return normalized


def _scalar(value: Any, field_name: str) -> str | int | bool | tuple[str, ...]:
    if type(value) in {str, int, bool}:
        if isinstance(value, str):
            return _text(value, field_name, maximum=128, unsafe=True)
        return value
    if isinstance(value, (list, tuple)) and 0 < len(value) <= 8 and all(isinstance(item, str) for item in value):
        values = tuple(_text(item, field_name, maximum=128, unsafe=True) for item in value)
        if len(set(values)) != len(values):
            raise DomainMemoryContractError(f"{field_name} contains duplicate values")
        return values
    raise DomainMemoryContractError(f"{field_name} must be a bounded scalar")


@dataclass(frozen=True, slots=True)
class ApplicabilityPredicate:
    predicate_id: str
    operator: str
    value: str | int | bool | tuple[str, ...] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "predicate_id", _identifier(self.predicate_id, "predicate_id"))
        if self.operator not in PREDICATE_OPERATORS:
            raise DomainMemoryContractError("predicate operator is not registered")
        if self.operator == "exists":
            if self.value is not None:
                raise DomainMemoryContractError("exists predicate must not carry a value")
        else:
            object.__setattr__(self, "value", _scalar(self.value, "predicate value"))

    def to_dict(self) -> dict[str, Any]:
        value: Any = list(self.value) if isinstance(self.value, tuple) else self.value
        return {"predicate_id": self.predicate_id, "operator": self.operator, "value": value}

    @classmethod
    def from_dict(cls, value: Any) -> "ApplicabilityPredicate":
        if not isinstance(value, Mapping) or set(value) != {"predicate_id", "operator", "value"}:
            raise DomainMemoryContractError("applicability predicate fields are invalid")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class SourceSummaryRef:
    project_pseudonym: str
    summary_snapshot_ref: str
    summary_snapshot_hash: str
    summary_schema_version: str
    source_access_binding_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_pseudonym", _identifier(self.project_pseudonym, "project_pseudonym"))
        object.__setattr__(self, "summary_snapshot_ref", _identifier(self.summary_snapshot_ref, "summary_snapshot_ref"))
        object.__setattr__(self, "summary_snapshot_hash", _digest(self.summary_snapshot_hash, "summary_snapshot_hash"))
        object.__setattr__(self, "summary_schema_version", _identifier(self.summary_schema_version, "summary_schema_version"))
        object.__setattr__(self, "source_access_binding_ref", _identifier(self.source_access_binding_ref, "source_access_binding_ref"))

    def to_dict(self) -> dict[str, str]:
        return {
            "project_pseudonym": self.project_pseudonym,
            "summary_snapshot_ref": self.summary_snapshot_ref,
            "summary_snapshot_hash": self.summary_snapshot_hash,
            "summary_schema_version": self.summary_schema_version,
            "source_access_binding_ref": self.source_access_binding_ref,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SourceSummaryRef":
        if not isinstance(value, Mapping) or set(value) != {
            "project_pseudonym",
            "summary_snapshot_ref",
            "summary_snapshot_hash",
            "summary_schema_version",
            "source_access_binding_ref",
        }:
            raise DomainMemoryContractError("source summary ref fields are invalid")
        return cls(**dict(value))


def _predicates(value: Any) -> tuple[ApplicabilityPredicate, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_PREDICATES:
        raise DomainMemoryContractError("applicability_predicates exceed their bounded field limit")
    normalized = tuple(
        item if isinstance(item, ApplicabilityPredicate) else ApplicabilityPredicate.from_dict(item) for item in value
    )
    if len({item.predicate_id for item in normalized}) != len(normalized):
        raise DomainMemoryContractError("applicability predicate ids must be unique")
    return normalized


def _sources(value: Any) -> tuple[SourceSummaryRef, ...]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > _MAX_SOURCES:
        raise DomainMemoryContractError("source_summary_refs must contain one to eight refs")
    normalized = tuple(item if isinstance(item, SourceSummaryRef) else SourceSummaryRef.from_dict(item) for item in value)
    if len({item.source_access_binding_ref for item in normalized}) != len(normalized):
        raise DomainMemoryContractError("source access bindings must be unique")
    return normalized


def _scope(value: Any) -> MemoryScope:
    if not isinstance(value, MemoryScope):
        try:
            value = MemoryScope.from_dict(value)
        except (DomainMemoryScopeError, TypeError) as error:
            raise DomainMemoryContractError("scope is invalid") from error
    return value


@dataclass(frozen=True, slots=True)
class DomainMemoryContentRevision:
    memory_id: str
    revision: int
    scope: MemoryScope
    domain_tags: tuple[str, ...]
    memory_kind: str
    applicability_predicates: tuple[ApplicabilityPredicate, ...]
    compact_lesson: str
    recommended_effect_kind: str
    recommended_target_refs: tuple[str, ...]
    source_summary_refs: tuple[SourceSummaryRef, ...]
    evidence_status: str
    review_after: str
    supersedes_revision: int | None
    conflicts_with: tuple[str, ...]
    created_by: str
    content_hash: str = field(init=False)

    CONTRACT_VERSION: ClassVar[str] = CONTENT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", _identifier(self.memory_id, "memory_id"))
        object.__setattr__(self, "revision", _revision(self.revision, "content revision"))
        object.__setattr__(self, "scope", _scope(self.scope))
        if not isinstance(self.domain_tags, (list, tuple)) or not 1 <= len(self.domain_tags) <= _MAX_TAGS:
            raise DomainMemoryContractError("domain_tags must be bounded and non-empty")
        tags = tuple(_identifier(tag, "domain_tag") for tag in self.domain_tags)
        if len(set(tags)) != len(tags):
            raise DomainMemoryContractError("domain_tags must be unique")
        object.__setattr__(self, "domain_tags", tuple(sorted(tags)))
        if self.memory_kind not in MEMORY_KINDS:
            raise DomainMemoryContractError("memory_kind is not registered")
        object.__setattr__(self, "applicability_predicates", _predicates(self.applicability_predicates))
        if not self.applicability_predicates:
            raise DomainMemoryContractError("applicability_predicates must contain a hard gate")
        object.__setattr__(self, "compact_lesson", _text(self.compact_lesson, "compact_lesson", unsafe=True))
        if self.recommended_effect_kind not in EFFECT_KINDS:
            raise DomainMemoryContractError("recommended_effect_kind is not registered")
        object.__setattr__(self, "recommended_target_refs", _refs(self.recommended_target_refs, "recommended_target_refs", maximum=_MAX_TARGET_REFS))
        object.__setattr__(self, "source_summary_refs", _sources(self.source_summary_refs))
        if self.evidence_status not in EVIDENCE_STATUSES:
            raise DomainMemoryContractError("evidence_status is not registered")
        object.__setattr__(self, "review_after", _text(self.review_after, "review_after", maximum=64))
        if self.supersedes_revision is not None:
            object.__setattr__(self, "supersedes_revision", _revision(self.supersedes_revision, "supersedes_revision"))
            if self.supersedes_revision >= self.revision:
                raise DomainMemoryContractError("supersedes_revision must be older than revision")
        object.__setattr__(self, "conflicts_with", _refs(self.conflicts_with, "conflicts_with", maximum=_MAX_CONFLICTS))
        object.__setattr__(self, "created_by", _identifier(self.created_by, "created_by"))
        object.__setattr__(self, "content_hash", domain_digest("workbench.domain-memory.content/v1", self._semantic_dict()))

    def _semantic_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "revision": self.revision,
            "scope": self.scope.to_dict(),
            "domain_tags": list(self.domain_tags),
            "memory_kind": self.memory_kind,
            "applicability_predicates": [item.to_dict() for item in self.applicability_predicates],
            "compact_lesson": self.compact_lesson,
            "recommended_effect_kind": self.recommended_effect_kind,
            "recommended_target_refs": list(self.recommended_target_refs),
            "source_summary_refs": [item.to_dict() for item in self.source_summary_refs],
            "evidence_status": self.evidence_status,
            "review_after": self.review_after,
            "supersedes_revision": self.supersedes_revision,
            "conflicts_with": list(self.conflicts_with),
            "created_by": self.created_by,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.CONTRACT_VERSION, **self._semantic_dict(), "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, value: Any) -> "DomainMemoryContentRevision":
        expected = {"contract_version", *cls._field_names(), "content_hash"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("domain memory content fields are invalid")
        item = cls(**{key: value[key] for key in cls._field_names()})
        if value["content_hash"] != item.content_hash:
            raise DomainMemoryContractError("content_hash does not match immutable content")
        return item

    @staticmethod
    def _field_names() -> tuple[str, ...]:
        return (
            "memory_id", "revision", "scope", "domain_tags", "memory_kind", "applicability_predicates",
            "compact_lesson", "recommended_effect_kind", "recommended_target_refs", "source_summary_refs",
            "evidence_status", "review_after", "supersedes_revision", "conflicts_with", "created_by",
        )


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    candidate_id: str
    revision: int
    scope: MemoryScope
    memory_kind: str
    domain_tags: tuple[str, ...]
    applicability_predicates: tuple[ApplicabilityPredicate, ...]
    compact_lesson: str
    recommended_effect_kind: str
    recommended_target_refs: tuple[str, ...]
    source_summary_refs: tuple[SourceSummaryRef, ...]
    created_from_manifest_ref: str
    status: str
    created_at: str
    expires_at: str | None = None

    CONTRACT_VERSION: ClassVar[str] = CANDIDATE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "revision", _revision(self.revision, "candidate revision"))
        object.__setattr__(self, "scope", _scope(self.scope))
        if self.memory_kind not in MEMORY_KINDS:
            raise DomainMemoryContractError("memory_kind is not registered")
        object.__setattr__(self, "domain_tags", tuple(sorted(_refs(self.domain_tags, "domain_tags", maximum=_MAX_TAGS))))
        if not self.domain_tags:
            raise DomainMemoryContractError("domain_tags must not be empty")
        object.__setattr__(self, "applicability_predicates", _predicates(self.applicability_predicates))
        if not self.applicability_predicates:
            raise DomainMemoryContractError("applicability_predicates must contain a hard gate")
        object.__setattr__(self, "compact_lesson", _text(self.compact_lesson, "compact_lesson", unsafe=True))
        if self.recommended_effect_kind not in EFFECT_KINDS:
            raise DomainMemoryContractError("recommended_effect_kind is not registered")
        object.__setattr__(self, "recommended_target_refs", _refs(self.recommended_target_refs, "recommended_target_refs", maximum=_MAX_TARGET_REFS))
        object.__setattr__(self, "source_summary_refs", _sources(self.source_summary_refs))
        object.__setattr__(self, "created_from_manifest_ref", _identifier(self.created_from_manifest_ref, "created_from_manifest_ref"))
        if self.status not in CANDIDATE_STATES:
            raise DomainMemoryContractError("candidate status is not registered")
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at", maximum=64))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _text(self.expires_at, "expires_at", maximum=64))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.CONTRACT_VERSION,
            "candidate_id": self.candidate_id,
            "revision": self.revision,
            "scope": self.scope.to_dict(),
            "memory_kind": self.memory_kind,
            "domain_tags": list(self.domain_tags),
            "applicability_predicates": [item.to_dict() for item in self.applicability_predicates],
            "compact_lesson": self.compact_lesson,
            "recommended_effect_kind": self.recommended_effect_kind,
            "recommended_target_refs": list(self.recommended_target_refs),
            "source_summary_refs": [item.to_dict() for item in self.source_summary_refs],
            "created_from_manifest_ref": self.created_from_manifest_ref,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "MemoryCandidate":
        if not isinstance(value, Mapping) or set(value) != {
            "contract_version", "candidate_id", "revision", "scope", "memory_kind", "domain_tags",
            "applicability_predicates", "compact_lesson", "recommended_effect_kind", "recommended_target_refs",
            "source_summary_refs", "created_from_manifest_ref", "status", "created_at", "expires_at",
        } or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("memory candidate fields are invalid")
        data = dict(value)
        data.pop("contract_version")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class DomainMemoryApprovalRecord:
    approval_ref: str
    memory_id: str
    content_revision: int
    content_hash: str
    scope: MemoryScope
    approver_id: str
    approved_at: str
    expected_current_approval_ref: str | None
    supersedes_approval_ref: str | None
    grant_control_sequence: int

    CONTRACT_VERSION: ClassVar[str] = APPROVAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _identifier(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "memory_id", _identifier(self.memory_id, "memory_id"))
        object.__setattr__(self, "content_revision", _revision(self.content_revision, "content_revision"))
        object.__setattr__(self, "content_hash", _digest(self.content_hash, "content_hash"))
        object.__setattr__(self, "scope", _scope(self.scope))
        object.__setattr__(self, "approver_id", _identifier(self.approver_id, "approver_id"))
        object.__setattr__(self, "approved_at", _text(self.approved_at, "approved_at", maximum=64))
        object.__setattr__(self, "expected_current_approval_ref", _optional_id(self.expected_current_approval_ref, "expected_current_approval_ref"))
        object.__setattr__(self, "supersedes_approval_ref", _optional_id(self.supersedes_approval_ref, "supersedes_approval_ref"))
        object.__setattr__(self, "grant_control_sequence", _revision(self.grant_control_sequence, "grant_control_sequence"))

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.CONTRACT_VERSION, "approval_ref": self.approval_ref, "memory_id": self.memory_id,
                "content_revision": self.content_revision, "content_hash": self.content_hash, "scope": self.scope.to_dict(),
                "approver_id": self.approver_id, "approved_at": self.approved_at,
                "expected_current_approval_ref": self.expected_current_approval_ref, "supersedes_approval_ref": self.supersedes_approval_ref,
                "grant_control_sequence": self.grant_control_sequence}

    @classmethod
    def from_dict(cls, value: Any) -> "DomainMemoryApprovalRecord":
        expected = {"contract_version", "approval_ref", "memory_id", "content_revision", "content_hash", "scope", "approver_id", "approved_at", "expected_current_approval_ref", "supersedes_approval_ref", "grant_control_sequence"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("approval fields are invalid")
        data = dict(value); data.pop("contract_version")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class DomainMemoryValidityRecord:
    approval_ref: str
    memory_id: str
    content_revision: int
    validity_revision: int
    control_sequence: int
    state: str
    effective_at: str
    reason: str
    authority: str
    evidence_refs: tuple[str, ...]

    CONTRACT_VERSION: ClassVar[str] = VALIDITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _identifier(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "memory_id", _identifier(self.memory_id, "memory_id"))
        object.__setattr__(self, "content_revision", _revision(self.content_revision, "content_revision"))
        object.__setattr__(self, "validity_revision", _revision(self.validity_revision, "validity_revision"))
        object.__setattr__(self, "control_sequence", _revision(self.control_sequence, "control_sequence"))
        if self.state not in VALIDITY_STATES:
            raise DomainMemoryContractError("validity state is not registered")
        object.__setattr__(self, "effective_at", _text(self.effective_at, "effective_at", maximum=64))
        object.__setattr__(self, "reason", _text(self.reason, "reason", maximum=256, unsafe=True))
        object.__setattr__(self, "authority", _identifier(self.authority, "authority"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs", maximum=_MAX_EVIDENCE_REFS))

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.CONTRACT_VERSION, "approval_ref": self.approval_ref, "memory_id": self.memory_id,
                "content_revision": self.content_revision, "validity_revision": self.validity_revision,
                "control_sequence": self.control_sequence, "state": self.state, "effective_at": self.effective_at,
                "reason": self.reason, "authority": self.authority, "evidence_refs": list(self.evidence_refs)}

    @classmethod
    def from_dict(cls, value: Any) -> "DomainMemoryValidityRecord":
        expected = {"contract_version", "approval_ref", "memory_id", "content_revision", "validity_revision", "control_sequence", "state", "effective_at", "reason", "authority", "evidence_refs"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("validity fields are invalid")
        data = dict(value); data.pop("contract_version")
        return cls(**data)


__all__ = [
    "ApplicabilityPredicate", "CANDIDATE_STATES", "DomainMemoryApprovalRecord", "DomainMemoryContentRevision",
    "DomainMemoryContractError", "DomainMemoryValidityRecord", "EFFECT_KINDS", "MemoryCandidate", "MEMORY_KINDS",
    "SourceSummaryRef", "VALIDITY_STATES",
]
