"""Explicit candidate and approved-memory review lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate_store import MemoryCandidateStore, MemoryCandidateStoreConflict
from .conflicts import ConflictDetector, ConflictStore, MemoryConflictRecord
from .contracts import DomainMemoryValidityRecord
from .preferences import DomainMemoryPreferences
from .service import CandidateApprovalResult, DomainMemoryService, DomainMemoryServiceError


class MemoryReviewServiceError(ValueError):
    """A review action is stale, conflicted, or not explicitly authorized."""


@dataclass(frozen=True, slots=True)
class ReviewStateResult:
    candidate_id: str
    revision: int
    status: str


class MemoryReviewService:
    def __init__(self, memory_service: DomainMemoryService, candidate_store: MemoryCandidateStore, conflict_store: ConflictStore) -> None:
        self.memory_service = memory_service
        self.candidate_store = candidate_store
        self.conflict_store = conflict_store
        self.detector = ConflictDetector()

    def reject_candidate(self, candidate_id: str, *, expected_revision: int, actor_id: str) -> ReviewStateResult:
        if not actor_id:
            raise MemoryReviewServiceError("review actor is required")
        try:
            item = self.candidate_store.transition(candidate_id, expected_revision=expected_revision, status="rejected")
        except (KeyError, MemoryCandidateStoreConflict) as error:
            raise MemoryReviewServiceError("DOMAIN_MEMORY_CANDIDATE_STALE") from error
        return ReviewStateResult(item.candidate_id, item.revision, item.status)

    def approve_candidate(
        self, candidate_id: str, *, expected_revision: int, actor_id: str, approved_at: str, review_after: str,
        resolve_conflicts: bool = False,
    ) -> CandidateApprovalResult:
        candidate = self.candidate_store.latest(candidate_id)
        if candidate.revision != expected_revision or candidate.status != "needs_review":
            raise MemoryReviewServiceError("DOMAIN_MEMORY_CANDIDATE_STALE")
        conflicts = self.detector.detect(candidate, self.memory_service.store.active_contents())
        for conflict in conflicts:
            existing = self.conflict_store.append(conflict)
            if existing.status == "open" and not resolve_conflicts:
                raise MemoryReviewServiceError("DOMAIN_MEMORY_CONFLICT_REVIEW_REQUIRED")
            if existing.status == "open":
                self.conflict_store.transition(existing.conflict_ref, expected_revision=existing.revision, status="resolved")
        try:
            return self.memory_service.approve_candidate(
                candidate_id, expected_revision=expected_revision, approver_id=actor_id, approved_at=approved_at,
                review_after=review_after, global_preferences=DomainMemoryPreferences(),
            )
        except (DomainMemoryServiceError, KeyError, ValueError) as error:
            raise MemoryReviewServiceError(str(error)) from error

    def change_memory_state(
        self, memory_id: str, *, expected_approval_ref: str, expected_validity_revision: int,
        state: str, actor_id: str, effective_at: str,
    ) -> DomainMemoryValidityRecord:
        if state not in {"stale", "archived"} or not actor_id:
            raise MemoryReviewServiceError("DOMAIN_MEMORY_REVIEW_STATE_INVALID")
        approval = self.memory_service.store.current_approval(memory_id)
        validity = self.memory_service.store.current_validity(memory_id)
        if approval is None or validity is None or approval.approval_ref != expected_approval_ref or validity.validity_revision != expected_validity_revision:
            raise MemoryReviewServiceError("DOMAIN_MEMORY_APPROVAL_STALE")
        record = DomainMemoryValidityRecord(
            approval_ref=approval.approval_ref, memory_id=memory_id, content_revision=approval.content_revision,
            validity_revision=validity.validity_revision + 1, control_sequence=approval.grant_control_sequence,
            state=state, effective_at=effective_at, reason=f"explicit review by {actor_id}", authority="user-review", evidence_refs=(actor_id,),
        )
        return self.memory_service.store.append_validity(record)

    def restore_memory(self, memory_id: str, *, actor_id: str, approved_at: str, evidence_ref: str) -> CandidateApprovalResult:
        if not actor_id:
            raise MemoryReviewServiceError("review actor is required")
        approval = self.memory_service.store.current_approval(memory_id)
        if approval is None:
            raise MemoryReviewServiceError("DOMAIN_MEMORY_APPROVAL_REQUIRED")
        content = self.memory_service.store.get_content(memory_id, approval.content_revision)
        current = approval
        new_approval = type(approval)(
            approval_ref=f"approval-{memory_id}-restore-{current.grant_control_sequence + 1}", memory_id=memory_id,
            content_revision=content.revision, content_hash=content.content_hash, scope=content.scope,
            approver_id=actor_id, approved_at=approved_at, expected_current_approval_ref=current.approval_ref,
            supersedes_approval_ref=current.approval_ref, grant_control_sequence=current.grant_control_sequence + 1,
        )
        self.memory_service.store.append_approval(new_approval)
        new_validity = DomainMemoryValidityRecord(
            approval_ref=new_approval.approval_ref, memory_id=memory_id, content_revision=content.revision,
            validity_revision=1, control_sequence=new_approval.grant_control_sequence, state="active",
            effective_at=approved_at, reason="explicit restore review", authority="user-review", evidence_refs=(evidence_ref,),
        )
        self.memory_service.store.append_validity(new_validity)
        return CandidateApprovalResult(content, new_approval, new_validity)


__all__ = ["MemoryReviewService", "MemoryReviewServiceError", "ReviewStateResult"]
