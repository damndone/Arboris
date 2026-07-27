from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workbench.domain_memory.contracts import (
    DomainMemoryApprovalRecord,
    DomainMemoryContentRevision,
    DomainMemoryContractError,
    DomainMemoryValidityRecord,
    MemoryCandidate,
    SourceSummaryRef,
)
from workbench.domain_memory.scope import MemoryScope


SCOPE = MemoryScope(
    namespace_id="ns-a",
    profile_id="profile-a",
    owner_id="user-a",
    organization_id="org-a",
    visibility_scope="private",
    promotion_scope="user",
)


def _source_ref() -> SourceSummaryRef:
    return SourceSummaryRef(
        project_pseudonym="project-1",
        summary_snapshot_ref="snapshot-1",
        summary_snapshot_hash="a" * 64,
        summary_schema_version="redacted-summary-v1",
        source_access_binding_ref="binding-1",
    )


def _content(**overrides: object) -> DomainMemoryContentRevision:
    values: dict[str, object] = {
        "memory_id": "memory-1",
        "revision": 1,
        "scope": SCOPE,
        "domain_tags": ("panel-data",),
        "memory_kind": "workflow_lesson",
        "applicability_predicates": ({"predicate_id": "family", "operator": "equals", "value": "ols"},),
        "compact_lesson": "Check clustered dependence before selecting a covariance option.",
        "recommended_effect_kind": "assumption_check_hint",
        "recommended_target_refs": ("inspection-clustered-dependence",),
        "source_summary_refs": (_source_ref(),),
        "evidence_status": "observed_repeatedly",
        "review_after": "2026-12-01T00:00:00Z",
        "supersedes_revision": None,
        "conflicts_with": (),
        "created_by": "curator-v1",
    }
    values.update(overrides)
    return DomainMemoryContentRevision(**values)


def test_content_hash_is_server_computed_and_round_trips() -> None:
    content = _content()
    payload = content.to_dict()
    assert len(content.content_hash) == 64
    assert payload["content_hash"] == content.content_hash
    assert DomainMemoryContentRevision.from_dict(payload) == content
    with pytest.raises(DomainMemoryContractError):
        DomainMemoryContentRevision.from_dict({**payload, "content_hash": "b" * 64})


def test_contracts_reject_unsafe_effects_and_unbounded_or_raw_content() -> None:
    with pytest.raises(DomainMemoryContractError):
        _content(recommended_effect_kind="execute_code")
    with pytest.raises(DomainMemoryContractError):
        _content(compact_lesson="use /Users/example/project/data.csv")
    with pytest.raises(DomainMemoryContractError):
        _content(domain_tags=tuple(f"tag-{index}" for index in range(33)))


def test_candidate_is_not_an_approved_memory() -> None:
    candidate = MemoryCandidate(
        candidate_id="candidate-1",
        revision=1,
        scope=SCOPE,
        memory_kind="workflow_lesson",
        domain_tags=("panel-data",),
        applicability_predicates=({"predicate_id": "family", "operator": "equals", "value": "ols"},),
        compact_lesson="Check clustered dependence before selecting a covariance option.",
        recommended_effect_kind="assumption_check_hint",
        recommended_target_refs=("inspection-clustered-dependence",),
        source_summary_refs=(_source_ref(),),
        created_from_manifest_ref="manifest-1",
        status="needs_review",
        created_at="2026-07-27T00:00:00Z",
    )
    assert candidate.to_dict()["status"] == "needs_review"
    assert "approval" not in candidate.to_dict()


def test_approval_binds_exact_content_and_cas_reference() -> None:
    content = _content()
    approval = DomainMemoryApprovalRecord(
        approval_ref="approval-1",
        memory_id=content.memory_id,
        content_revision=content.revision,
        content_hash=content.content_hash,
        scope=SCOPE,
        approver_id="user-a",
        approved_at="2026-07-27T00:00:00Z",
        expected_current_approval_ref=None,
        supersedes_approval_ref=None,
        grant_control_sequence=1,
    )
    assert DomainMemoryApprovalRecord.from_dict(approval.to_dict()) == approval
    with pytest.raises(DomainMemoryContractError):
        DomainMemoryApprovalRecord(
            approval_ref="approval-2",
            memory_id=content.memory_id,
            content_revision=content.revision,
            content_hash="not-a-digest",
            scope=SCOPE,
            approver_id="user-a",
            approved_at="2026-07-27T00:00:00Z",
            expected_current_approval_ref=None,
            supersedes_approval_ref=None,
            grant_control_sequence=1,
        )


def test_validity_has_monotonic_per_approval_revision_and_closed_state_set() -> None:
    record = DomainMemoryValidityRecord(
        approval_ref="approval-1",
        memory_id="memory-1",
        content_revision=1,
        validity_revision=1,
        control_sequence=1,
        state="active",
        effective_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        reason="approved by user",
        authority="user-review",
        evidence_refs=("evidence-1",),
    )
    assert DomainMemoryValidityRecord.from_dict(record.to_dict()) == record
    with pytest.raises(DomainMemoryContractError):
        DomainMemoryValidityRecord.from_dict({**record.to_dict(), "state": "active-ish"})
