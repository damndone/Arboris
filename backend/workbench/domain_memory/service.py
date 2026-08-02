"""Control-plane service: candidate iteration and bounded memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .candidate_store import MemoryCandidateStore
from .contracts import DomainMemoryApprovalRecord, DomainMemoryContentRevision, DomainMemoryValidityRecord, MemoryCandidate
from .preferences import DomainMemoryPreferences, DomainMemoryRequestOverride, EffectiveDomainMemoryPreferences, resolve_preferences
from .retrieval import DomainMemoryRetrieval, retrieve_domain_memory
from .scope import MemoryScope
from .store import DomainMemoryStore


class DomainMemoryServiceError(ValueError):
    """A memory operation is disabled, stale, or otherwise not authorized."""


@dataclass(frozen=True, slots=True)
class CandidateApprovalResult:
    content: DomainMemoryContentRevision
    approval: DomainMemoryApprovalRecord
    validity: DomainMemoryValidityRecord


class DomainMemoryService:
    """Memory is a hint provider only; this service has no execution dependency."""

    def __init__(self, store: DomainMemoryStore, candidate_store: MemoryCandidateStore) -> None:
        self.store = store
        self.candidate_store = candidate_store

    def effective_preferences(
        self, global_preferences: DomainMemoryPreferences, override: DomainMemoryRequestOverride | None = None
    ) -> EffectiveDomainMemoryPreferences:
        return resolve_preferences(self.store.scope, global_preferences, override)

    def retrieve(
        self, *, requester: MemoryScope, global_preferences: DomainMemoryPreferences, facts: Mapping[str, Any], now: str,
        override: DomainMemoryRequestOverride | None = None, max_entries: int = 8, max_bytes: int = 8192,
        vocabulary_version: str | None = None,
    ) -> DomainMemoryRetrieval:
        effective = self.effective_preferences(global_preferences, override)
        return retrieve_domain_memory(
            self.store, requester=requester, preferences=effective, facts=facts, now=now,
            max_entries=max_entries, max_bytes=max_bytes, vocabulary_version=vocabulary_version,
        )

    def create_candidate(
        self, candidate: MemoryCandidate, *, global_preferences: DomainMemoryPreferences,
        override: DomainMemoryRequestOverride | None = None,
    ) -> MemoryCandidate:
        effective = self.effective_preferences(global_preferences, override)
        if not effective.iteration:
            raise DomainMemoryServiceError("DOMAIN_MEMORY_DISABLED: iteration is off")
        if not candidate.scope.exact_match(self.store.scope):
            raise DomainMemoryServiceError("DOMAIN_MEMORY_SCOPE_MISMATCH")
        return self.candidate_store.append(candidate)

    def approve_candidate(
        self, candidate_id: str, *, expected_revision: int, approver_id: str, approved_at: str,
        review_after: str, global_preferences: DomainMemoryPreferences, override: DomainMemoryRequestOverride | None = None,
    ) -> CandidateApprovalResult:
        self.effective_preferences(global_preferences, override)
        pending = [item for item in self.candidate_store.pending(self.store.scope) if item.candidate_id == candidate_id]
        if not pending:
            raise DomainMemoryServiceError("DOMAIN_MEMORY_CANDIDATE_NOT_PENDING")
        candidate = pending[0]
        if candidate.revision != expected_revision:
            raise DomainMemoryServiceError("DOMAIN_MEMORY_CANDIDATE_STALE")
        if candidate.status != "needs_review":
            raise DomainMemoryServiceError("DOMAIN_MEMORY_APPROVAL_REQUIRED")
        history = [item for item in self.store.list_content() if item.memory_id == "memory-" + candidate.candidate_id]
        revision = max((item.revision for item in history), default=0) + 1
        content = DomainMemoryContentRevision(
            memory_id="memory-" + candidate.candidate_id, revision=revision, scope=candidate.scope,
            domain_tags=candidate.domain_tags, memory_kind=candidate.memory_kind,
            applicability_predicates=candidate.applicability_predicates, compact_lesson=candidate.compact_lesson,
            recommended_effect_kind=candidate.recommended_effect_kind, recommended_target_refs=candidate.recommended_target_refs,
            source_summary_refs=candidate.source_summary_refs, evidence_status="observed_once", review_after=review_after,
            supersedes_revision=revision - 1 if revision > 1 else None, conflicts_with=(), created_by=approver_id,
            apply_mode=candidate.apply_mode, vocabulary_version=candidate.vocabulary_version,
            verifier=candidate.verifier, last_validated_at=candidate.last_validated_at, expires_at=candidate.expires_at,
        )
        self.store.append_content(content)
        current = self.store.current_approval(content.memory_id)
        approval = DomainMemoryApprovalRecord(
            approval_ref=f"approval-{candidate.candidate_id}-{revision}", memory_id=content.memory_id,
            content_revision=content.revision, content_hash=content.content_hash, scope=content.scope,
            approver_id=approver_id, approved_at=approved_at,
            expected_current_approval_ref=current.approval_ref if current else None,
            supersedes_approval_ref=current.approval_ref if current else None,
            grant_control_sequence=current.grant_control_sequence + 1 if current else 1,
        )
        self.store.append_approval(approval)
        validity = DomainMemoryValidityRecord(
            approval_ref=approval.approval_ref, memory_id=content.memory_id, content_revision=content.revision,
            validity_revision=1, control_sequence=approval.grant_control_sequence, state="active",
            effective_at=approved_at, reason="explicit user approval", authority="user-review", evidence_refs=(candidate.created_from_manifest_ref,),
        )
        self.store.append_validity(validity)
        self.candidate_store.transition(candidate.candidate_id, expected_revision=expected_revision, status="approved")
        return CandidateApprovalResult(content, approval, validity)


__all__ = ["CandidateApprovalResult", "DomainMemoryService", "DomainMemoryServiceError"]
