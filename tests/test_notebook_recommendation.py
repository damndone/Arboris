"""Batch-level evidence gate tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.notebook.proposal import OptionDraft, TypedProposal
from workbench.agent.notebook.recommendation import (
    ProtocolResult,
    RecommendationValidator,
)


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


def test_duplicate_candidate_ids_are_rejected_before_decision() -> None:
    with pytest.raises(ValueError, match="unique"):
        RecommendationValidator().decide(
            batch_id="batch_1",
            candidates=(_candidate("opt_same"), _candidate("opt_same")),
            evidence_pack=_pack(scores={}),
        )
