from __future__ import annotations

import pytest

from workbench.domain_memory.contracts import ApplicabilityPredicate, DomainMemoryContractError, SourceSummaryRef
from workbench.domain_memory.curator_contracts import AcceptedAnalysisSummary, CuratorObservation, CuratorReviewPoint
from workbench.domain_memory.scope import MemoryScope


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")
SOURCE = SourceSummaryRef("project-1", "snapshot-1", "a" * 64, "redacted-summary-v1", "binding-1")


def _observation(**overrides: object) -> CuratorObservation:
    values: dict[str, object] = {
        "observation_ref": "observation-1",
        "memory_kind": "workflow_lesson",
        "domain_tags": ("domain-a",),
        "applicability_predicates": (ApplicabilityPredicate("analysis_family", "equals", "ols"),),
        "compact_lesson": "Inspect the registered assumption before fitting.",
        "recommended_effect_kind": "assumption_check_hint",
        "recommended_target_refs": ("check-1",),
        "source_summary_refs": (SOURCE,),
        "evidence_status": "observed_once",
    }
    values.update(overrides)
    return CuratorObservation(**values)


def _summary(**overrides: object) -> AcceptedAnalysisSummary:
    values: dict[str, object] = {
        "summary_ref": "manifest-1",
        "summary_hash": "b" * 64,
        "scope": SCOPE,
        "review_point": CuratorReviewPoint.ANALYSIS_COMPLETED,
        "analysis_state": "accepted",
        "complete": True,
        "critical_omission": False,
        "policy_allows": True,
        "observations": (_observation(),),
        "created_at": "2026-07-27T00:00:00Z",
    }
    values.update(overrides)
    return AcceptedAnalysisSummary(**values)


def test_curator_summary_is_bounded_and_round_trips_without_raw_payload() -> None:
    summary = _summary()
    assert len(summary.idempotency_key) == 64
    assert AcceptedAnalysisSummary.from_dict(summary.to_dict()) == summary
    assert "raw_data" not in summary.to_dict()


def test_curator_contract_rejects_raw_paths_and_unregistered_effects() -> None:
    with pytest.raises(DomainMemoryContractError):
        _observation(compact_lesson="Read /Users/example/data.csv first")
    with pytest.raises(DomainMemoryContractError):
        _observation(recommended_effect_kind="execute_code")


def test_summary_review_point_is_explicit() -> None:
    assert _summary().review_point is CuratorReviewPoint.ANALYSIS_COMPLETED
    with pytest.raises(DomainMemoryContractError):
        _summary(review_point="automatic_background")
