from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.redaction import DomainMemoryRedactionError, build_redacted_summary_snapshot
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.source_access import SourceAccessBinding, SourceAccessValidityRecord


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _snapshot() -> object:
    return build_redacted_summary_snapshot(
        summary_text="Repeated checks found that clustered dependence should be inspected before fitting.",
        source_ref="trace-summary-1",
        source_kind="trace_summary",
        redaction_subject="user-a/project-a",
    )


def test_redaction_returns_only_non_expandable_snapshot_metadata() -> None:
    snapshot = _snapshot()
    assert not hasattr(snapshot, "summary_text")
    assert snapshot.summary_snapshot_ref.startswith("snapshot-")
    binding = SourceAccessBinding(
        binding_ref="binding-1", scope=SCOPE, summary_snapshot_ref=snapshot.summary_snapshot_ref,
        summary_snapshot_hash=snapshot.summary_snapshot_hash, summary_schema_version=snapshot.summary_schema_version,
        redaction_assessment_ref=snapshot.redaction_assessment_ref, redaction_subject_hash=snapshot.redaction_subject_hash,
        source_kind=snapshot.source_kind, source_ref=snapshot.source_ref, source_namespace_id="ns-a",
        source_profile_id="profile-a", source_owner_id="user-a", source_organization_id="org-a",
        grant_ref="grant-1", source_tombstone_ref=None,
    )
    assert SourceAccessBinding.from_dict(binding.to_dict()) == binding


def test_redaction_rejects_paths_identifiers_and_secrets() -> None:
    with pytest.raises(DomainMemoryRedactionError):
        build_redacted_summary_snapshot(summary_text="Read /Users/name/data.csv", source_ref="source-1", source_kind="trace_summary", redaction_subject="subject")
    with pytest.raises(DomainMemoryRedactionError):
        build_redacted_summary_snapshot(summary_text="row_id=42", source_ref="source-1", source_kind="trace_summary", redaction_subject="subject")


def test_source_validity_is_explicit_and_append_only() -> None:
    record = SourceAccessValidityRecord(
        binding_ref="binding-1", validity_revision=1, control_sequence=1, state="valid",
        effective_at="2026-07-27T00:00:00Z", reason="source grant verified", authority="source-acl-v1", evidence_refs=("acl-1",),
    )
    assert SourceAccessValidityRecord.from_dict(record.to_dict()) == record
    with pytest.raises(ValueError):
        SourceAccessValidityRecord.from_dict({**record.to_dict(), "state": "usable"})
