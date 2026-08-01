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


def _candidate(**overrides: object) -> MemoryCandidate:
    values: dict[str, object] = {
        "candidate_id": "candidate-1",
        "revision": 1,
        "scope": SCOPE,
        "memory_kind": "workflow_lesson",
        "domain_tags": ("domain-a",),
        "applicability_predicates": ({"predicate_id": "analysis_family", "operator": "equals", "value": "ols"},),
        "compact_lesson": "Inspect clustered dependence before fitting.",
        "recommended_effect_kind": "assumption_check_hint",
        "recommended_target_refs": ("check-clustered",),
        "source_summary_refs": (SourceSummaryRef("project-1", "snapshot-1", "a" * 64, "redacted-summary-v1", "binding-1"),),
        "created_from_manifest_ref": "manifest-1",
        "status": "needs_review",
        "created_at": "2026-07-27T00:00:00Z",
    }
    values.update(overrides)
    return MemoryCandidate(**values)


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


def test_suggest_default_is_downgraded_or_omitted_when_its_validity_is_not_current(tmp_path: Path) -> None:
    store = DomainMemoryStore(tmp_path, SCOPE)
    snapshot = build_redacted_summary_snapshot(summary_text="Reviewed summary.", source_ref="source-1", source_kind="trace_summary", redaction_subject="subject-1")
    store.append_binding(SourceAccessBinding(
        "binding-1", SCOPE, snapshot.summary_snapshot_ref, snapshot.summary_snapshot_hash, snapshot.summary_schema_version,
        snapshot.redaction_assessment_ref, snapshot.redaction_subject_hash, snapshot.source_kind, snapshot.source_ref,
        "ns-a", "profile-a", "user-a", "org-a", "grant-1", None,
    ))
    store.append_source_validity(SourceAccessValidityRecord("binding-1", 1, 1, "valid", "2026-07-27T00:00:00Z", "granted", "acl-v1", ("acl-1",)))
    service = DomainMemoryService(store, MemoryCandidateStore(tmp_path, SCOPE))
    candidate = _candidate(
        apply_mode="suggest_default",
        vocabulary_version="workflow-v1",
        verifier={"verifier_id": "schema-coverage", "valid_for_seconds": 3600},
        last_validated_at="2026-07-27T00:00:00Z",
        expires_at="2026-08-01T00:00:00Z",
        source_summary_refs=(SourceSummaryRef(
            "project-1", snapshot.summary_snapshot_ref, snapshot.summary_snapshot_hash,
            snapshot.summary_schema_version, "binding-1",
        ),),
    )
    service.create_candidate(candidate, global_preferences=DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    approval = service.approve_candidate(
        "candidate-1", expected_revision=1, approver_id="user-a", approved_at="2026-07-27T00:00:00Z",
        review_after="2026-12-01T00:00:00Z", global_preferences=DomainMemoryPreferences(cross_project_domain_memory_iteration=True),
    )
    assert approval.content.apply_mode == "suggest_default"

    fresh = service.retrieve(
        requester=SCOPE, global_preferences=DomainMemoryPreferences(cross_project_domain_memory_use=True),
        facts={"analysis_family": "ols"}, now="2026-07-27T00:30:00Z", vocabulary_version="workflow-v1",
    )
    assert fresh.entries[0].apply_mode == "suggest_default"
    assert fresh.entries[0].memory_source == {"memory_id": "memory-candidate-1", "revision": 1}

    stale = service.retrieve(
        requester=SCOPE, global_preferences=DomainMemoryPreferences(cross_project_domain_memory_use=True),
        facts={"analysis_family": "ols"}, now="2026-07-27T01:00:01Z", vocabulary_version="workflow-v1",
    )
    assert stale.entries[0].apply_mode == "inform_only"
    assert stale.entries[0].apply_mode_reason == "verifier_stale"

    vocabulary_mismatch = service.retrieve(
        requester=SCOPE, global_preferences=DomainMemoryPreferences(cross_project_domain_memory_use=True),
        facts={"analysis_family": "ols"}, now="2026-07-27T00:30:00Z", vocabulary_version="workflow-v2",
    )
    assert vocabulary_mismatch.entries == ()
    assert vocabulary_mismatch.omissions[0].reason == "vocabulary_mismatch"

    expired = service.retrieve(
        requester=SCOPE, global_preferences=DomainMemoryPreferences(cross_project_domain_memory_use=True),
        facts={"analysis_family": "ols"}, now="2026-08-02T00:00:00Z", vocabulary_version="workflow-v1",
    )
    assert expired.entries == ()
    assert expired.omissions[0].reason == "expired"
