from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.contracts import MemoryCandidate, SourceSummaryRef
from workbench.domain_memory.preferences import DomainMemoryPreferences
from workbench.domain_memory.redaction import build_redacted_summary_snapshot
from workbench.domain_memory.service import DomainMemoryService, DomainMemoryServiceError
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.source_access import SourceAccessBinding, SourceAccessValidityRecord
from workbench.domain_memory.store import DomainMemoryStore


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _candidate() -> MemoryCandidate:
    return MemoryCandidate(
        "candidate-1", 1, SCOPE, "workflow_lesson", ("domain-a",),
        ({"predicate_id": "analysis_family", "operator": "equals", "value": "ols"},),
        "Inspect clustered dependence before fitting.", "assumption_check_hint", ("check-clustered",),
        (SourceSummaryRef("project-1", "snapshot-1", "a" * 64, "redacted-summary-v1", "binding-1"),),
        "manifest-1", "needs_review", "2026-07-27T00:00:00Z",
    )


def test_service_keeps_use_and_iteration_independent(tmp_path: Path) -> None:
    service = DomainMemoryService(DomainMemoryStore(tmp_path, SCOPE), MemoryCandidateStore(tmp_path, SCOPE))
    with pytest.raises(DomainMemoryServiceError):
        service.create_candidate(_candidate(), global_preferences=DomainMemoryPreferences())
    candidate = service.create_candidate(_candidate(), global_preferences=DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    assert candidate.status == "needs_review"
    # A candidate has no official content and cannot be used as a hint.
    result = service.retrieve(
        requester=SCOPE, global_preferences=DomainMemoryPreferences(cross_project_domain_memory_use=True),
        facts={"analysis_family": "ols"}, now="2026-07-27T00:00:00Z",
    )
    assert result.entries == ()


def test_service_does_not_expose_execution_or_authority_effects(tmp_path: Path) -> None:
    service = DomainMemoryService(DomainMemoryStore(tmp_path, SCOPE), MemoryCandidateStore(tmp_path, SCOPE))
    candidate = service.create_candidate(_candidate(), global_preferences=DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    assert candidate.recommended_effect_kind == "assumption_check_hint"
    assert "execute" not in candidate.to_dict()
    assert "authorization" not in candidate.to_dict()


def test_explicit_candidate_approval_creates_current_content_but_not_a_run(tmp_path: Path) -> None:
    store = DomainMemoryStore(tmp_path, SCOPE)
    snapshot = build_redacted_summary_snapshot(summary_text="Reviewed summary.", source_ref="source-1", source_kind="trace_summary", redaction_subject="subject-1")
    store.append_binding(SourceAccessBinding(
        "binding-1", SCOPE, snapshot.summary_snapshot_ref, snapshot.summary_snapshot_hash, snapshot.summary_schema_version,
        snapshot.redaction_assessment_ref, snapshot.redaction_subject_hash, snapshot.source_kind, snapshot.source_ref,
        "ns-a", "profile-a", "user-a", "org-a", "grant-1", None,
    ))
    store.append_source_validity(SourceAccessValidityRecord("binding-1", 1, 1, "valid", "2026-07-27T00:00:00Z", "granted", "acl-v1", ("acl-1",)))
    service = DomainMemoryService(store, MemoryCandidateStore(tmp_path, SCOPE))
    service.create_candidate(_candidate(), global_preferences=DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    result = service.approve_candidate(
        "candidate-1", expected_revision=1, approver_id="user-a", approved_at="2026-07-27T00:00:00Z",
        review_after="2026-12-01T00:00:00Z", global_preferences=DomainMemoryPreferences(cross_project_domain_memory_iteration=True),
    )
    assert store.current_validity("memory-candidate-1") == result.validity
    assert not hasattr(result, "run_id")
