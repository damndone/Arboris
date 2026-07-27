"""Immutable source bindings and append-only validity records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from .contracts import DomainMemoryContractError, _digest, _identifier, _refs, _text
from .scope import MemoryScope


SOURCE_ACCESS_BINDING_VERSION = "domain-memory-source-access-binding/v1"
SOURCE_ACCESS_VALIDITY_VERSION = "domain-memory-source-access-validity/v1"
SOURCE_KINDS = frozenset({"trace_summary", "evidence_summary", "accepted_fact", "capability_summary"})
SOURCE_ACCESS_STATES = frozenset({"valid", "revoked", "deleted", "tainted", "superseded"})


@dataclass(frozen=True, slots=True)
class SourceAccessBinding:
    binding_ref: str
    scope: MemoryScope
    summary_snapshot_ref: str
    summary_snapshot_hash: str
    summary_schema_version: str
    redaction_assessment_ref: str
    redaction_subject_hash: str
    source_kind: str
    source_ref: str
    source_namespace_id: str
    source_profile_id: str
    source_owner_id: str
    source_organization_id: str | None
    grant_ref: str
    source_tombstone_ref: str | None

    CONTRACT_VERSION: ClassVar[str] = SOURCE_ACCESS_BINDING_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _identifier(self.binding_ref, "binding_ref"))
        if not isinstance(self.scope, MemoryScope):
            raise DomainMemoryContractError("source binding scope is invalid")
        object.__setattr__(self, "summary_snapshot_ref", _identifier(self.summary_snapshot_ref, "summary_snapshot_ref"))
        object.__setattr__(self, "summary_snapshot_hash", _digest(self.summary_snapshot_hash, "summary_snapshot_hash"))
        object.__setattr__(self, "summary_schema_version", _identifier(self.summary_schema_version, "summary_schema_version"))
        object.__setattr__(self, "redaction_assessment_ref", _identifier(self.redaction_assessment_ref, "redaction_assessment_ref"))
        object.__setattr__(self, "redaction_subject_hash", _digest(self.redaction_subject_hash, "redaction_subject_hash"))
        if self.source_kind not in SOURCE_KINDS:
            raise DomainMemoryContractError("source_kind is not registered")
        object.__setattr__(self, "source_ref", _identifier(self.source_ref, "source_ref"))
        object.__setattr__(self, "source_namespace_id", _identifier(self.source_namespace_id, "source_namespace_id"))
        object.__setattr__(self, "source_profile_id", _identifier(self.source_profile_id, "source_profile_id"))
        object.__setattr__(self, "source_owner_id", _identifier(self.source_owner_id, "source_owner_id"))
        if self.source_organization_id is not None:
            object.__setattr__(self, "source_organization_id", _identifier(self.source_organization_id, "source_organization_id"))
        if self.source_namespace_id != self.scope.namespace_id or self.source_profile_id != self.scope.profile_id:
            raise DomainMemoryContractError("source binding cannot cross namespace or profile")
        if self.scope.visibility_scope == "private" and self.source_owner_id != self.scope.owner_id:
            raise DomainMemoryContractError("private source binding owner must match memory owner")
        if self.scope.visibility_scope == "organization" and self.source_organization_id != self.scope.organization_id:
            raise DomainMemoryContractError("organization source binding must match memory organization")
        object.__setattr__(self, "grant_ref", _identifier(self.grant_ref, "grant_ref"))
        if self.source_tombstone_ref is not None:
            object.__setattr__(self, "source_tombstone_ref", _identifier(self.source_tombstone_ref, "source_tombstone_ref"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.CONTRACT_VERSION,
            "binding_ref": self.binding_ref,
            "scope": self.scope.to_dict(),
            "summary_snapshot_ref": self.summary_snapshot_ref,
            "summary_snapshot_hash": self.summary_snapshot_hash,
            "summary_schema_version": self.summary_schema_version,
            "redaction_assessment_ref": self.redaction_assessment_ref,
            "redaction_subject_hash": self.redaction_subject_hash,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_namespace_id": self.source_namespace_id,
            "source_profile_id": self.source_profile_id,
            "source_owner_id": self.source_owner_id,
            "source_organization_id": self.source_organization_id,
            "grant_ref": self.grant_ref,
            "source_tombstone_ref": self.source_tombstone_ref,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SourceAccessBinding":
        expected = {
            "contract_version", "binding_ref", "scope", "summary_snapshot_ref", "summary_snapshot_hash",
            "summary_schema_version", "redaction_assessment_ref", "redaction_subject_hash", "source_kind",
            "source_ref", "source_namespace_id", "source_profile_id", "source_owner_id", "source_organization_id",
            "grant_ref", "source_tombstone_ref",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("source access binding fields are invalid")
        data = dict(value); data.pop("contract_version")
        return cls(scope=MemoryScope.from_dict(data.pop("scope")), **data)


@dataclass(frozen=True, slots=True)
class SourceAccessValidityRecord:
    binding_ref: str
    validity_revision: int
    control_sequence: int
    state: str
    effective_at: str
    reason: str
    authority: str
    evidence_refs: tuple[str, ...]

    CONTRACT_VERSION: ClassVar[str] = SOURCE_ACCESS_VALIDITY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _identifier(self.binding_ref, "binding_ref"))
        if not isinstance(self.validity_revision, int) or isinstance(self.validity_revision, bool) or self.validity_revision < 1:
            raise DomainMemoryContractError("source validity revision must be positive")
        if not isinstance(self.control_sequence, int) or isinstance(self.control_sequence, bool) or self.control_sequence < 1:
            raise DomainMemoryContractError("source control sequence must be positive")
        if self.state not in SOURCE_ACCESS_STATES:
            raise DomainMemoryContractError("source access state is not registered")
        object.__setattr__(self, "effective_at", _text(self.effective_at, "effective_at", maximum=64))
        object.__setattr__(self, "reason", _text(self.reason, "reason", maximum=256, unsafe=True))
        object.__setattr__(self, "authority", _identifier(self.authority, "authority"))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs", maximum=16))

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.CONTRACT_VERSION, "binding_ref": self.binding_ref,
                "validity_revision": self.validity_revision, "control_sequence": self.control_sequence,
                "state": self.state, "effective_at": self.effective_at, "reason": self.reason,
                "authority": self.authority, "evidence_refs": list(self.evidence_refs)}

    @classmethod
    def from_dict(cls, value: Any) -> "SourceAccessValidityRecord":
        expected = {"contract_version", "binding_ref", "validity_revision", "control_sequence", "state", "effective_at", "reason", "authority", "evidence_refs"}
        if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != cls.CONTRACT_VERSION:
            raise DomainMemoryContractError("source access validity fields are invalid")
        data = dict(value); data.pop("contract_version")
        return cls(**data)


__all__ = ["SOURCE_ACCESS_STATES", "SourceAccessBinding", "SourceAccessValidityRecord"]
