from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.conflicts import ConflictStore
from workbench.domain_memory.contracts import DomainMemoryApprovalRecord, DomainMemoryValidityRecord
from workbench.domain_memory.curator_runtime import CuratorRuntime
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.review_service import MemoryReviewService, MemoryReviewServiceError
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.service import DomainMemoryService
from workbench.domain_memory.store import DomainMemoryStore

from test_memory_curator_contracts import _summary
from test_memory_conflicts import _content


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _services(tmp_path: Path) -> tuple[DomainMemoryService, MemoryCandidateStore, ConflictStore]:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    service = DomainMemoryService(DomainMemoryStore(tmp_path, SCOPE), candidates)
    conflicts = ConflictStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    runtime.generate(_summary(), resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True)))
    candidate = candidates.latest(next(iter({item.candidate_id for item in candidates.pending(SCOPE)})))
    candidates.transition(candidate.candidate_id, expected_revision=candidate.revision, status="needs_review")
    return service, candidates, conflicts


def test_explicit_rejection_does_not_create_official_memory(tmp_path: Path) -> None:
    service, candidates, conflicts = _services(tmp_path)
    review = MemoryReviewService(service, candidates, conflicts)
    candidate = candidates.pending(SCOPE)[0]
    result = review.reject_candidate(candidate.candidate_id, expected_revision=candidate.revision, actor_id="user-a")
    assert result.status == "rejected"
    assert service.store.list_content() == ()


def test_conflict_requires_explicit_resolution_and_approval_works_when_iteration_is_off(tmp_path: Path) -> None:
    service, candidates, conflicts = _services(tmp_path)
    review = MemoryReviewService(service, candidates, conflicts)
    candidate = candidates.pending(SCOPE)[0]
    official = _content(candidate.compact_lesson)
    service.store.append_content(official)
    approval = DomainMemoryApprovalRecord("approval-official", official.memory_id, official.revision, official.content_hash, SCOPE, "user-a", "2026-07-27T00:00:00Z", None, None, 1)
    service.store.append_approval(approval)
    service.store.append_validity(DomainMemoryValidityRecord("approval-official", official.memory_id, official.revision, 1, 1, "active", "2026-07-27T00:00:00Z", "approved", "user-review", ("review-1",)))
    with pytest.raises(MemoryReviewServiceError, match="CONFLICT_REVIEW_REQUIRED"):
        review.approve_candidate(
            candidate.candidate_id, expected_revision=candidate.revision, actor_id="user-a",
            approved_at="2026-07-27T00:00:00Z", review_after="2026-12-01T00:00:00Z",
        )
    # An explicit conflict resolution is required; approval remains a user review action,
    # independent of the candidate-generation iteration switch.
    result = review.approve_candidate(
        candidate.candidate_id, expected_revision=candidate.revision, actor_id="user-a",
        approved_at="2026-07-27T00:00:00Z", review_after="2026-12-01T00:00:00Z", resolve_conflicts=True,
    )
    assert result.content.memory_id.startswith("memory-")
    assert service.store.current_validity(result.content.memory_id) == result.validity


def test_stale_then_restore_uses_new_approval_and_current_grant(tmp_path: Path) -> None:
    service, candidates, conflicts = _services(tmp_path)
    review = MemoryReviewService(service, candidates, conflicts)
    candidate = candidates.pending(SCOPE)[0]
    approved = review.approve_candidate(candidate.candidate_id, expected_revision=candidate.revision, actor_id="user-a", approved_at="2026-07-27T00:00:00Z", review_after="2026-12-01T00:00:00Z")
    stale = review.change_memory_state(approved.content.memory_id, expected_approval_ref=approved.approval.approval_ref, expected_validity_revision=1, state="stale", actor_id="user-a", effective_at="2026-07-28T00:00:00Z")
    restored = review.restore_memory(approved.content.memory_id, actor_id="user-a", approved_at="2026-07-29T00:00:00Z", evidence_ref="review-2")
    assert stale.state == "stale"
    assert restored.approval.approval_ref != approved.approval.approval_ref
    assert restored.validity.state == "active"
    assert service.store.current_approval(approved.content.memory_id) == restored.approval
