from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.candidate_store import MemoryCandidateStore, MemoryCandidateStoreConflict
from workbench.domain_memory.contracts import MemoryCandidate
from workbench.domain_memory.curator_runtime import CuratorRuntime
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.scope import MemoryScope

from test_memory_curator_contracts import _summary


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _legacy_candidate(summary, **overrides: object) -> MemoryCandidate:
    observation = summary.observations[0]
    values: dict[str, object] = {
        "candidate_id": "candidate-" + summary.idempotency_key[:32] + "-" + observation.observation_ref,
        "revision": 1,
        "scope": summary.scope,
        "memory_kind": observation.memory_kind,
        "domain_tags": observation.domain_tags,
        "applicability_predicates": observation.applicability_predicates,
        "compact_lesson": observation.compact_lesson,
        "recommended_effect_kind": observation.recommended_effect_kind,
        "recommended_target_refs": observation.recommended_target_refs,
        "source_summary_refs": observation.source_summary_refs,
        "created_from_manifest_ref": summary.summary_ref,
        "status": "proposed",
        "created_at": summary.created_at,
    }
    values.update(overrides)
    return MemoryCandidate(**values)


def test_curator_writes_only_pending_candidates_and_not_official_memory(tmp_path: Path) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    effective = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    created = runtime.generate(_summary(), effective)
    assert len(created) == 1
    assert created[0].status == "needs_review"
    assert candidates.pending(SCOPE) == created
    assert not (tmp_path / "domain-memory.jsonl").exists()


def test_curator_is_idempotent_and_default_off(tmp_path: Path) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    disabled = resolve_preferences(SCOPE, DomainMemoryPreferences())
    assert runtime.generate(_summary(), disabled) == ()
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    assert runtime.generate(_summary(), enabled) == runtime.generate(_summary(), enabled)


def test_curator_upgrades_a_matching_legacy_proposal_to_explicit_review(tmp_path: Path) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    summary = _summary()
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))

    legacy = candidates.append(_legacy_candidate(summary))

    upgraded = runtime.generate(summary, enabled)

    assert upgraded[0].candidate_id == legacy.candidate_id
    assert upgraded[0].revision == legacy.revision + 1
    assert upgraded[0].status == "needs_review"
    assert runtime.generate(summary, enabled) == upgraded


def test_curator_rejects_a_mismatched_legacy_candidate_with_the_same_id(tmp_path: Path) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    summary = _summary()
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    legacy = candidates.append(_legacy_candidate(
        summary,
        compact_lesson="This conflicting legacy lesson must not be upgraded.",
    ))

    with pytest.raises(MemoryCandidateStoreConflict, match="candidate revision was reused"):
        runtime.generate(summary, enabled)

    assert candidates.latest(legacy.candidate_id) == legacy


def test_curator_returns_the_peer_upgraded_legacy_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    summary = _summary()
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    legacy = candidates.append(_legacy_candidate(summary))
    original_transition = candidates.transition

    def peer_upgrades_first(candidate_id: str, *, expected_revision: int, status: str) -> MemoryCandidate:
        original_transition(candidate_id, expected_revision=expected_revision, status=status)
        return original_transition(candidate_id, expected_revision=expected_revision, status=status)

    monkeypatch.setattr(candidates, "transition", peer_upgrades_first)

    upgraded = runtime.generate(summary, enabled)

    assert upgraded[0].candidate_id == legacy.candidate_id
    assert upgraded[0].revision == legacy.revision + 1
    assert upgraded[0].status == "needs_review"
    assert runtime.generate(summary, enabled) == upgraded
