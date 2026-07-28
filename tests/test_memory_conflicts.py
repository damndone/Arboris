from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.conflicts import ConflictDetector, ConflictStore, ConflictStoreConflict, MemoryConflictRecord
from workbench.domain_memory.contracts import DomainMemoryContentRevision
from workbench.domain_memory.curator_runtime import CuratorRuntime
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.candidate_store import MemoryCandidateStore

from test_memory_curator_contracts import _summary


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _content(compact_lesson: str, memory_id: str = "memory-1") -> DomainMemoryContentRevision:
    source = _summary().observations[0].source_summary_refs
    observation = _summary().observations[0]
    return DomainMemoryContentRevision(
        memory_id=memory_id, revision=1, scope=SCOPE, domain_tags=observation.domain_tags,
        memory_kind=observation.memory_kind, applicability_predicates=observation.applicability_predicates,
        compact_lesson=compact_lesson, recommended_effect_kind=observation.recommended_effect_kind,
        recommended_target_refs=observation.recommended_target_refs, source_summary_refs=source,
        evidence_status="observed_once", review_after="2026-12-01T00:00:00Z", supersedes_revision=None,
        conflicts_with=(), created_by="user-a",
    )


def test_detector_distinguishes_duplicate_and_conflict(tmp_path: Path) -> None:
    runtime = CuratorRuntime(MemoryCandidateStore(tmp_path, SCOPE))
    candidate = runtime.generate(_summary(), resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True)))[0]
    detector = ConflictDetector()
    duplicate = detector.detect(candidate, (_content(candidate.compact_lesson),))
    conflict = detector.detect(candidate, (_content("Use a different registered check."),))
    assert duplicate[0].relation == "duplicate"
    assert conflict[0].relation == "conflict"


def test_conflict_record_store_is_append_only_and_scope_bound(tmp_path: Path) -> None:
    store = ConflictStore(tmp_path, SCOPE)
    record = MemoryConflictRecord("conflict-1", 1, SCOPE, "candidate-1", "memory-1@1", "conflict", "2026-07-27T00:00:00Z", "open", ("manifest-1",))
    assert store.append(record) == record
    assert store.append(record) == record
    with pytest.raises(ConflictStoreConflict):
        store.append(MemoryConflictRecord("conflict-1", 1, SCOPE, "candidate-1", "memory-1@1", "duplicate", "2026-07-27T00:00:00Z", "open", ("manifest-1",)))
    resolved = store.transition(record.conflict_ref, expected_revision=1, status="resolved")
    assert resolved.revision == 2
    assert resolved.status == "resolved"
