from __future__ import annotations

from pathlib import Path

from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.contracts import MemoryCandidate, SourceSummaryRef
from workbench.domain_memory.scope import MemoryScope


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _candidate(status: str = "proposed", revision: int = 1) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-1", revision=revision, scope=SCOPE, memory_kind="workflow_lesson", domain_tags=("domain-a",),
        applicability_predicates=({"predicate_id": "analysis_family", "operator": "equals", "value": "ols"},), compact_lesson="Perform the registered assumption check first.",
        recommended_effect_kind="assumption_check_hint", recommended_target_refs=("check-1",),
        source_summary_refs=(SourceSummaryRef("project-1", "snapshot-1", "a" * 64, "redacted-summary-v1", "binding-1"),),
        created_from_manifest_ref="manifest-1", status=status, created_at="2026-07-27T00:00:00Z",
    )


def test_candidate_store_is_separate_and_status_transition_is_explicit(tmp_path: Path) -> None:
    store = MemoryCandidateStore(tmp_path, SCOPE)
    first = _candidate()
    assert store.append(first) == first
    reviewed = store.transition("candidate-1", expected_revision=1, status="needs_review")
    assert reviewed.revision == 2
    assert reviewed.status == "needs_review"
    assert store.pending(SCOPE) == (reviewed,)
    assert "domain-memory-candidates" in store.journal_path.name


def test_candidate_store_never_turns_a_candidate_into_content(tmp_path: Path) -> None:
    store = MemoryCandidateStore(tmp_path, SCOPE)
    store.append(_candidate())
    record_types = {line and __import__("json").loads(line)["record_type"] for line in store.journal_path.read_text().splitlines()}
    assert record_types == {"memory_candidate"}
