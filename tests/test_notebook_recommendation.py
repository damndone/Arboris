"""Batch-level evidence gate tests."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.notebook.proposal import OptionDraft, TypedProposal
from workbench.agent.notebook.recommendation import (
    ComparisonDecisionRecord,
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    ProtocolResult,
    RecommendationValidator,
    RecommendationDecisionV11,
    ServerDecisionRegistry,
    candidate_cohort_hash,
)
from workbench.contracts.agent.notebook_option import EvidenceRef


def _candidate(option_id: str, *, blocked: str | None = None) -> OptionDraft:
    return OptionDraft(
        rank=1,
        option_id=option_id,
        rationale="candidate",
        proposal=TypedProposal(proposal_id=f"p_{option_id}", operation_id="model.rerun"),
        blocked_reason=blocked,
    )


def _pack(*, scores: dict[str, float], status: str = "completed", margin: float = 0.0) -> DataEvidencePackV1:
    record = EvidenceRecord(
        evidence_id="evidence:forecast",
        inspection_id="forecast_rolling_origin.v1",
        source_refs=("forecast_rolling_origin:run_001",),
        protocol_version="forecast-rolling-origin/v1",
        status=status,
        observations={"cohort": "forecast.v1"},
        metrics={"candidate_scores": scores, "margin": margin},
        result_hash="sha256:forecast-result",
    )
    return DataEvidencePackV1(source_id="run:run_001", records=(record,))


@dataclass(frozen=True)
class FakeForecastProtocol:
    margin: float
    protocol_id: str = "forecast.v1"

    def evaluate(self, candidates: tuple[OptionDraft, ...], evidence: DataEvidencePackV1) -> ProtocolResult:
        record = evidence.records[0]
        return ProtocolResult(
            protocol_id=self.protocol_id,
            protocol_version=record.protocol_version,
            cohort="forecast.v1",
            scores=record.metrics["candidate_scores"],
            margin=self.margin,
            evidence_ids=(record.evidence_id,),
        )


def test_clear_winner_is_the_only_recommended_option() -> None:
    decision = RecommendationValidator(protocols={"forecast.v1": FakeForecastProtocol(0.02)}).decide(
        batch_id="batch_1",
        candidates=(_candidate("opt_ets"), _candidate("opt_arma")),
        evidence_pack=_pack(scores={"opt_ets": 0.10, "opt_arma": 0.20}),
    )

    assert decision.outcome == "recommended"
    assert decision.recommended_option_id == "opt_ets"
    assert decision.comparison_protocol_refs == ("forecast.v1:forecast-rolling-origin/v1",)


def test_close_candidates_are_tied_not_ranked() -> None:
    decision = RecommendationValidator(protocols={"forecast.v1": FakeForecastProtocol(0.02)}).decide(
        batch_id="batch_1",
        candidates=(_candidate("opt_ets"), _candidate("opt_arma")),
        evidence_pack=_pack(scores={"opt_ets": 0.10, "opt_arma": 0.11}),
    )

    assert decision.outcome == "tied"
    assert decision.recommended_option_id is None


def test_incomplete_evidence_cannot_produce_a_winner() -> None:
    decision = RecommendationValidator(protocols={"forecast.v1": FakeForecastProtocol(0.0)}).decide(
        batch_id="batch_1",
        candidates=(_candidate("opt_ets"), _candidate("opt_arma")),
        evidence_pack=_pack(scores={"opt_ets": 0.10, "opt_arma": 0.50}, status="partial"),
    )

    assert decision.outcome == "insufficient_evidence"
    assert decision.recommended_option_id is None


def test_one_hard_blocked_candidate_leaves_a_single_viable_recommendation() -> None:
    decision = RecommendationValidator().decide(
        batch_id="batch_1",
        candidates=(_candidate("opt_bad", blocked="TIME_INDEX_INVALID"), _candidate("opt_ets")),
        evidence_pack=_pack(scores={}),
    )

    assert decision.outcome == "recommended"
    assert decision.recommended_option_id == "opt_ets"
    assert decision.comparison_protocol_refs == ()


def test_no_common_protocol_is_insufficient_not_a_heuristic_winner() -> None:
    decision = RecommendationValidator().decide(
        batch_id="batch_1",
        candidates=(_candidate("opt_ets"), _candidate("opt_arma")),
        evidence_pack=_pack(scores={"opt_ets": 0.10, "opt_arma": 0.20}),
    )

    assert decision.outcome == "insufficient_evidence"
    assert decision.recommended_option_id is None


def test_structured_evidence_refs_support_natural_language_comparative_claims() -> None:
    evidence_ref = EvidenceRef(
        evidence_id="evidence:forecast",
        result_hash="sha256:forecast-result",
        source_refs=("forecast_rolling_origin:run_001",),
    )
    candidates = tuple(
        replace(
            _candidate(option_id),
            evidence_refs=(evidence_ref,),
            comparative_claims=(
                "The rolling-origin evidence supports this candidate.",
            ),
        )
        for option_id in ("opt_ets", "opt_arma")
    )

    decision = RecommendationValidator(
        protocols={"forecast.v1": FakeForecastProtocol(0.02)}
    ).decide(
        batch_id="batch_structured_refs",
        candidates=candidates,
        evidence_pack=_pack(scores={"opt_ets": 0.10, "opt_arma": 0.20}),
    )

    assert decision.outcome == "recommended"
    assert decision.recommended_option_id == "opt_ets"


def test_duplicate_candidate_ids_are_rejected_before_decision() -> None:
    with pytest.raises(ValueError, match="unique"):
        RecommendationValidator().decide(
            batch_id="batch_1",
            candidates=(_candidate("opt_same"), _candidate("opt_same")),
            evidence_pack=_pack(scores={}),
        )


def _feasibility(
    *results: tuple[str, str],
    batch_id: str = "batch_1",
    generation_context_hash: str = "sha256:context",
    freshness_dependency_fingerprint: str = "fresh1:fingerprint",
    evidence_pack_hashes: tuple[str, ...] = ("sha256:evidence",),
) -> FeasibilityDecision:
    decisions = tuple(
        FeasibilityCandidateDecision(
            option_id=option_id,
            protocol_id="feasibility.v1",
            protocol_version="feasibility/v1",
            inspection_refs=(f"inspection:{option_id}",),
            evidence_refs=(f"evidence:{option_id}",),
            outcome=outcome,
            reason_code="PASS" if outcome == "feasible" else "INPUT_CONTRACT_INVALID",
        )
        for option_id, outcome in results
    )
    ids = tuple(item.option_id for item in decisions)
    return FeasibilityDecision(
        feasibility_decision_id="feasibility_1",
        batch_id=batch_id,
        generation_context_hash=generation_context_hash,
        freshness_dependency_fingerprint=freshness_dependency_fingerprint,
        evidence_pack_hashes=evidence_pack_hashes,
        candidate_option_ids=ids,
        candidate_cohort_hash=candidate_cohort_hash(ids),
        candidates=decisions,
        validator_revision="feasibility-validator/v1",
    )


def test_server_feasibility_decision_requires_the_complete_candidate_cohort() -> None:
    with pytest.raises(ValueError, match="candidate_cohort_hash"):
        decision = _feasibility(("opt_ets", "feasible"), ("opt_arma", "blocked"))
        replace(decision, candidate_cohort_hash=candidate_cohort_hash(("opt_ets",)))


def test_v11_recommendation_uses_server_feasibility_not_agent_blocked_reason() -> None:
    registry = ServerDecisionRegistry()
    registry.register_feasibility(
        _feasibility(
            ("opt_bad", "blocked"),
            ("opt_ets", "feasible"),
        )
    )
    decision = RecommendationValidator().decide_v11(
        batch_id="batch_1",
        candidate_option_ids=("opt_bad", "opt_ets"),
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        decision_registry=registry,
        feasibility_decision_ref="feasibility_1",
    )

    assert decision.outcome == "recommended"
    assert decision.recommended_option_id == "opt_ets"
    assert decision.feasibility_decision_ref == "feasibility_1"
    assert decision.comparison_decision_ref is None
    assert RecommendationDecisionV11.from_dict(decision.to_dict()) == decision


def test_v11_wire_contract_rejects_unknown_fields() -> None:
    registry = ServerDecisionRegistry()
    registry.register_feasibility(_feasibility(("opt_ets", "feasible")))
    decision = RecommendationValidator().decide_v11(
        batch_id="batch_1",
        candidate_option_ids=("opt_ets",),
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        decision_registry=registry,
        feasibility_decision_ref="feasibility_1",
    )
    payload = decision.to_dict()
    payload["agent_blocked_reason"] = "pretend that alternatives were blocked"
    with pytest.raises(ValueError, match="unknown"):
        RecommendationDecisionV11.from_dict(payload)


def test_v11_does_not_choose_between_multiple_feasible_candidates_without_comparison() -> None:
    registry = ServerDecisionRegistry()
    registry.register_feasibility(
        _feasibility(
            ("opt_ets", "feasible"),
            ("opt_arma", "feasible"),
        )
    )
    decision = RecommendationValidator().decide_v11(
        batch_id="batch_1",
        candidate_option_ids=("opt_ets", "opt_arma"),
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        decision_registry=registry,
        feasibility_decision_ref="feasibility_1",
    )

    assert decision.outcome == "insufficient_evidence"
    assert decision.recommended_option_id is None


def test_v11_requires_exactly_one_server_decision_reference() -> None:
    registry = ServerDecisionRegistry()
    with pytest.raises(ValueError, match="exactly one"):
        RecommendationValidator().decide_v11(
            batch_id="batch_1",
            candidate_option_ids=("opt_ets",),
            generation_context_hash="sha256:context",
            freshness_dependency_fingerprint="fresh1:fingerprint",
            evidence_pack_hashes=("sha256:evidence",),
            decision_registry=registry,
        )


def test_v11_rejects_unregistered_or_mismatched_server_decisions() -> None:
    registry = ServerDecisionRegistry()
    with pytest.raises(ValueError, match="unavailable"):
        RecommendationValidator().decide_v11(
            batch_id="batch_1",
            candidate_option_ids=("opt_ets",),
            generation_context_hash="sha256:context",
            freshness_dependency_fingerprint="fresh1:fingerprint",
            evidence_pack_hashes=("sha256:evidence",),
            decision_registry=registry,
            feasibility_decision_ref="missing",
        )

    registry.register_feasibility(
        _feasibility(
            ("opt_ets", "feasible"),
            batch_id="batch_other",
        )
    )
    with pytest.raises(ValueError, match="does not cover"):
        RecommendationValidator().decide_v11(
            batch_id="batch_1",
            candidate_option_ids=("opt_ets",),
            generation_context_hash="sha256:context",
            freshness_dependency_fingerprint="fresh1:fingerprint",
            evidence_pack_hashes=("sha256:evidence",),
            decision_registry=registry,
            feasibility_decision_ref="feasibility_1",
        )


def test_v11_comparison_reference_is_validated_against_the_same_cohort() -> None:
    registry = ServerDecisionRegistry()
    registry.register_comparison(
        ComparisonDecisionRecord(
            comparison_decision_id="comparison_1",
            batch_id="batch_1",
            generation_context_hash="sha256:context",
            freshness_dependency_fingerprint="fresh1:fingerprint",
            evidence_pack_hashes=("sha256:evidence",),
            candidate_option_ids=("opt_ets", "opt_arma"),
            candidate_cohort_hash=candidate_cohort_hash(("opt_ets", "opt_arma")),
            outcome="recommended",
            recommended_option_id="opt_ets",
            protocol_ref="comparison.v1",
        )
    )
    decision = RecommendationValidator().decide_v11(
        batch_id="batch_1",
        candidate_option_ids=("opt_ets", "opt_arma"),
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        decision_registry=registry,
        comparison_decision_ref="comparison_1",
    )

    assert decision.outcome == "recommended"
    assert decision.recommended_option_id == "opt_ets"
    registry.validate_recommendation(decision)


def test_comparison_decision_has_a_strict_persisted_wire_contract() -> None:
    record = ComparisonDecisionRecord(
        comparison_decision_id="comparison_1",
        batch_id="batch_1",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        candidate_option_ids=("opt_ets", "opt_arma"),
        candidate_cohort_hash=candidate_cohort_hash(("opt_ets", "opt_arma")),
        outcome="recommended",
        recommended_option_id="opt_ets",
        protocol_ref="comparison.v1",
    )

    assert ComparisonDecisionRecord.from_dict(record.to_dict()) == record
    payload = record.to_dict()
    payload["untrusted_field"] = "must not survive persistence"
    with pytest.raises(ValueError, match="unknown"):
        ComparisonDecisionRecord.from_dict(payload)

    payload = record.to_dict()
    payload["evidence_pack_hashes"] = "sha256:evidence"
    with pytest.raises(ValueError):
        ComparisonDecisionRecord.from_dict(payload)


def test_registry_rejects_a_wire_recommendation_with_a_forged_comparison_ref() -> None:
    registry = ServerDecisionRegistry()
    forged = RecommendationDecisionV11(
        recommendation_decision_id="forged",
        batch_id="batch_1",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        candidate_option_ids=("opt_ets",),
        candidate_cohort_hash=candidate_cohort_hash(("opt_ets",)),
        outcome="recommended",
        recommended_option_id="opt_ets",
        feasibility_decision_ref=None,
        comparison_decision_ref="not_registered",
        reason_refs=(),
    )

    with pytest.raises(ValueError, match="unavailable"):
        registry.validate_recommendation(forged)


def test_registry_rejects_a_registered_decision_with_mismatched_binding() -> None:
    registry = ServerDecisionRegistry()
    registry.register_comparison(
        ComparisonDecisionRecord(
            comparison_decision_id="comparison_1",
            batch_id="batch_2",
            generation_context_hash="sha256:context_2",
            freshness_dependency_fingerprint="fresh1:fingerprint_2",
            evidence_pack_hashes=("sha256:evidence_2",),
            candidate_option_ids=("opt_ets",),
            candidate_cohort_hash=candidate_cohort_hash(("opt_ets",)),
            outcome="recommended",
            recommended_option_id="opt_ets",
            protocol_ref="comparison.v1",
        )
    )
    forged = RecommendationDecisionV11(
        recommendation_decision_id="forged_bound",
        batch_id="batch_1",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        candidate_option_ids=("opt_ets",),
        candidate_cohort_hash=candidate_cohort_hash(("opt_ets",)),
        outcome="recommended",
        recommended_option_id="opt_ets",
        feasibility_decision_ref=None,
        comparison_decision_ref="comparison_1",
        reason_refs=(),
    )

    with pytest.raises(ValueError, match="binding"):
        registry.validate_recommendation(forged)


def test_v11_candidate_cohort_is_bounded_to_three_options() -> None:
    with pytest.raises(ValueError, match="at most 3"):
        candidate_cohort_hash(("opt_1", "opt_2", "opt_3", "opt_4"))
