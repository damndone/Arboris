from __future__ import annotations

from typing import Any

from workbench.narrative.claims import build_claims

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module


SOURCE_ID = "model_results.linear_mixed_effects_1.coefficients.group_time_interaction"


def _result(*, converged: bool, interval: list[float]) -> dict[str, Any]:
    return {
        "model_id": "linear_mixed_effects_1",
        "model_type": "linear_mixed_effects",
        "converged": converged,
        "coefficients": {
            "group_time_interaction": {
                "result_id": "group_time_interaction",
                "source_id": SOURCE_ID,
                "estimate": 0.2,
                "p_value": 0.02,
                "confidence_interval": interval,
                "confidence_level": 0.95,
            }
        },
    }


def _lmm_claims(result: dict[str, Any]) -> list[dict[str, Any]]:
    require_candidate_module("workbench.engine.packs.linear_mixed_effects.runner")
    return build_claims([result], [], model_type="linear_mixed_effects")


def test_lmm_report_uses_association_only_caution_without_causal_overclaim() -> None:
    claims = _lmm_claims(_result(converged=True, interval=[0.05, 0.35]))
    text = " ".join(str(claim["claim"]) for claim in claims).lower()

    assert "causal" in text
    assert all(
        forbidden not in text
        for forbidden in ("causes", "causal effect", "证明因果", "导致", "造成")
    )


def test_nonconverged_lmm_has_no_substantive_coefficient_conclusion() -> None:
    claims = _lmm_claims(_result(converged=False, interval=[0.05, 0.35]))

    assert all(claim["source_id"] != SOURCE_ID for claim in claims)


def test_confidence_interval_spanning_zero_cannot_claim_a_definite_direction() -> None:
    claims = _lmm_claims(_result(converged=True, interval=[-0.25, 0.65]))
    text = " ".join(str(claim["claim"]) for claim in claims).lower()

    assert any(marker in text for marker in ("spans zero", "uncertain", "cannot determine"))
    assert all(
        definite not in text
        for definite in ("definitely positive", "definitely negative", "positive effect", "negative effect")
    )
