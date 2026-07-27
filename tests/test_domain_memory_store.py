from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.domain_memory.contracts import DomainMemoryApprovalRecord, DomainMemoryContentRevision, DomainMemoryValidityRecord
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.source_access import SourceAccessBinding, SourceAccessValidityRecord
from workbench.domain_memory.store import DomainMemoryStore, DomainMemoryStoreConflict, DomainMemoryStoreError
from workbench.domain_memory.redaction import build_redacted_summary_snapshot


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _binding(ref: str = "binding-1", scope: MemoryScope = SCOPE) -> SourceAccessBinding:
    snapshot = build_redacted_summary_snapshot(
        summary_text="A bounded reviewed summary.", source_ref="source-1", source_kind="trace_summary", redaction_subject="subject-1"
    )
    return SourceAccessBinding(
        binding_ref=ref, scope=scope, summary_snapshot_ref=snapshot.summary_snapshot_ref,
        summary_snapshot_hash=snapshot.summary_snapshot_hash, summary_schema_version=snapshot.summary_schema_version,
        redaction_assessment_ref=snapshot.redaction_assessment_ref, redaction_subject_hash=snapshot.redaction_subject_hash,
        source_kind=snapshot.source_kind, source_ref=snapshot.source_ref, source_namespace_id=scope.namespace_id,
        source_profile_id=scope.profile_id, source_owner_id=scope.owner_id, source_organization_id=scope.organization_id,
        grant_ref="grant-1", source_tombstone_ref=None,
    )


def _content(binding: SourceAccessBinding, revision: int = 1) -> DomainMemoryContentRevision:
    from workbench.domain_memory.contracts import SourceSummaryRef

    return DomainMemoryContentRevision(
        memory_id="memory-1", revision=revision, scope=SCOPE, domain_tags=("domain-a",), memory_kind="workflow_lesson",
        applicability_predicates=({"predicate_id": "analysis_family", "operator": "equals", "value": "ols"},), compact_lesson="Perform the registered assumption check first.",
        recommended_effect_kind="assumption_check_hint", recommended_target_refs=("check-1",),
        source_summary_refs=(SourceSummaryRef("project-1", binding.summary_snapshot_ref, binding.summary_snapshot_hash, binding.summary_schema_version, binding.binding_ref),),
        evidence_status="observed_repeatedly", review_after="2026-12-01T00:00:00Z",
        supersedes_revision=revision - 1 if revision > 1 else None, conflicts_with=(), created_by="curator-v1",
    )


def _approval(content: DomainMemoryContentRevision, ref: str, sequence: int, expected: str | None, supersedes: str | None) -> DomainMemoryApprovalRecord:
    return DomainMemoryApprovalRecord(
        approval_ref=ref, memory_id=content.memory_id, content_revision=content.revision, content_hash=content.content_hash,
        scope=SCOPE, approver_id="user-a", approved_at="2026-07-27T00:00:00Z",
        expected_current_approval_ref=expected, supersedes_approval_ref=supersedes, grant_control_sequence=sequence,
    )


def _validity(approval: DomainMemoryApprovalRecord, revision: int, state: str = "active") -> DomainMemoryValidityRecord:
    return DomainMemoryValidityRecord(
        approval_ref=approval.approval_ref, memory_id=approval.memory_id, content_revision=approval.content_revision,
        validity_revision=revision, control_sequence=approval.grant_control_sequence, state=state,
        effective_at="2026-07-27T00:00:00Z", reason="user review", authority="user-review", evidence_refs=("review-1",),
    )


def test_store_is_append_only_idempotent_and_rejects_revision_reuse(tmp_path: Path) -> None:
    binding = _binding()
    store = DomainMemoryStore(tmp_path, SCOPE)
    assert store.append_binding(binding) == binding
    assert store.append_binding(binding) == binding
    first = _content(binding)
    assert store.append_content(first) == first
    assert store.append_content(first) == first
    with pytest.raises(DomainMemoryStoreConflict):
        store.append_content(DomainMemoryContentRevision(
            memory_id="memory-1", revision=1, scope=SCOPE, domain_tags=("domain-a",), memory_kind="workflow_lesson",
            applicability_predicates=({"predicate_id": "analysis_family", "operator": "equals", "value": "ols"},), compact_lesson="A different immutable lesson.", recommended_effect_kind="known_caveat",
            recommended_target_refs=("check-1",), source_summary_refs=first.source_summary_refs, evidence_status="observed_once",
            review_after="2026-12-01T00:00:00Z", supersedes_revision=None, conflicts_with=(), created_by="curator-v1",
        ))
    assert DomainMemoryStore(tmp_path, SCOPE).get_content("memory-1", 1) == first


def test_approval_requires_current_grant_cas_and_validity_cannot_restore_old_grant(tmp_path: Path) -> None:
    store = DomainMemoryStore(tmp_path, SCOPE)
    binding = _binding(); store.append_binding(binding)
    first = _content(binding); store.append_content(first)
    approval1 = _approval(first, "approval-1", 1, None, None); store.append_approval(approval1)
    validity1 = _validity(approval1, 1); store.append_validity(validity1)
    second = _content(binding, 2); store.append_content(second)
    approval2 = _approval(second, "approval-2", 2, "approval-1", "approval-1"); store.append_approval(approval2)
    with pytest.raises(DomainMemoryStoreConflict):
        store.append_approval(_approval(second, "approval-3", 2, None, None))
    assert store.current_approval("memory-1") == approval2
    assert store.current_validity("memory-1") is None
    with pytest.raises(DomainMemoryStoreConflict):
        store.append_validity(_validity(approval1, 2))


def test_source_access_validity_must_match_binding_and_revoke_is_fail_closed(tmp_path: Path) -> None:
    store = DomainMemoryStore(tmp_path, SCOPE)
    binding = _binding(); store.append_binding(binding)
    valid = SourceAccessValidityRecord("binding-1", 1, 1, "valid", "2026-07-27T00:00:00Z", "granted", "acl-v1", ("acl-1",))
    store.append_source_validity(valid)
    revoked = SourceAccessValidityRecord("binding-1", 2, 2, "revoked", "2026-07-27T00:01:00Z", "revoked", "acl-v1", ("acl-2",))
    store.append_source_validity(revoked)
    assert store.current_source_validity("binding-1") == revoked
    with pytest.raises(DomainMemoryStoreConflict):
        store.append_source_validity(SourceAccessValidityRecord("binding-1", 3, 3, "valid", "2026-07-27T00:02:00Z", "restored", "acl-v1", ("acl-3",)))


def test_malformed_or_truncated_journal_fails_closed(tmp_path: Path) -> None:
    store = DomainMemoryStore(tmp_path, SCOPE)
    store.journal_path.write_text('{"record_type":"unknown"}\n', encoding="utf-8")
    with pytest.raises(DomainMemoryStoreError):
        store.list_content()
