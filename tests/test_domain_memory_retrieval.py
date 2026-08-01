from __future__ import annotations

from pathlib import Path

from workbench.domain_memory.contracts import DomainMemoryApprovalRecord, DomainMemoryContentRevision, SourceSummaryRef, DomainMemoryValidityRecord
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.redaction import build_redacted_summary_snapshot
from workbench.domain_memory.retrieval import retrieve_domain_memory
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.source_access import SourceAccessBinding, SourceAccessValidityRecord
from workbench.domain_memory.store import DomainMemoryStore


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _store(tmp_path: Path) -> DomainMemoryStore:
    store = DomainMemoryStore(tmp_path, SCOPE)
    snapshot = build_redacted_summary_snapshot(summary_text="Reviewed summary.", source_ref="source-1", source_kind="trace_summary", redaction_subject="subject-1")
    binding = SourceAccessBinding(
        "binding-1", SCOPE, snapshot.summary_snapshot_ref, snapshot.summary_snapshot_hash, snapshot.summary_schema_version,
        snapshot.redaction_assessment_ref, snapshot.redaction_subject_hash, snapshot.source_kind, snapshot.source_ref,
        "ns-a", "profile-a", "user-a", "org-a", "grant-1", None,
    )
    store.append_binding(binding)
    store.append_source_validity(SourceAccessValidityRecord("binding-1", 1, 1, "valid", "2026-07-27T00:00:00Z", "granted", "acl-v1", ("acl-1",)))
    content = DomainMemoryContentRevision(
        "memory-1", 1, SCOPE, ("domain-a",), "workflow_lesson",
        ({"predicate_id": "analysis_family", "operator": "equals", "value": "ols"},),
        "Inspect clustered dependence before fitting.", "assumption_check_hint", ("check-clustered",),
        (SourceSummaryRef("project-1", snapshot.summary_snapshot_ref, snapshot.summary_snapshot_hash, snapshot.summary_schema_version, "binding-1"),),
        "independently_reviewed", "2026-12-01T00:00:00Z", None, (), "user-a",
    )
    store.append_content(content)
    approval = DomainMemoryApprovalRecord("approval-1", "memory-1", 1, content.content_hash, SCOPE, "user-a", "2026-07-27T00:00:00Z", None, None, 1)
    store.append_approval(approval)
    store.append_validity(DomainMemoryValidityRecord("approval-1", "memory-1", 1, 1, 1, "active", "2026-07-27T00:00:00Z", "approved", "user-review", ("review-1",)))
    return store


def test_retrieval_requires_use_flag_and_is_bounded_projection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    disabled = resolve_preferences(SCOPE, DomainMemoryPreferences())
    result = retrieve_domain_memory(store, requester=SCOPE, preferences=disabled, facts={"analysis_family": "ols"}, now="2026-07-27T00:00:00Z")
    assert result.outcome == "not_used"
    assert result.reason == "DOMAIN_MEMORY_DISABLED"
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_use=True))
    result = retrieve_domain_memory(store, requester=SCOPE, preferences=enabled, facts={"analysis_family": "ols"}, now="2026-07-27T00:00:00Z")
    assert result.outcome == "used"
    assert result.entries[0].recommended_effect_kind == "assumption_check_hint"
    projection = result.to_context_projection()
    assert projection["contract_version"] == "domain-memory-context-input/v3"
    assert projection["memory_authority"] == "non_authoritative"
    assert projection["entries"][0]["source_scope_ref"] == SCOPE.scope_ref
    assert projection["entries"][0]["vocabulary_version"] is None


def test_predicate_scope_and_source_revocation_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_use=True))
    mismatch = retrieve_domain_memory(store, requester=SCOPE, preferences=enabled, facts={"analysis_family": "time_series"}, now="2026-07-27T00:00:00Z")
    assert mismatch.entries == ()
    assert any(item.reason == "predicate_mismatch" for item in mismatch.omissions)
    store.append_source_validity(SourceAccessValidityRecord("binding-1", 2, 2, "revoked", "2026-07-27T00:01:00Z", "revoked", "acl-v1", ("acl-2",)))
    revoked = retrieve_domain_memory(store, requester=SCOPE, preferences=enabled, facts={"analysis_family": "ols"}, now="2026-07-27T00:00:00Z")
    assert revoked.entries == ()
    assert any(item.reason == "source_access_unavailable" for item in revoked.omissions)


def test_cross_namespace_request_cannot_read_same_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_use=True))
    requester = MemoryScope("ns-b", "profile-a", "user-a", "org-a", "private", "user")
    result = retrieve_domain_memory(store, requester=requester, preferences=enabled, facts={"analysis_family": "ols"}, now="2026-07-27T00:00:00Z")
    assert result.outcome == "blocked"
    assert result.reason == "DOMAIN_MEMORY_SCOPE_MISMATCH"
