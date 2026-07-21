"""Do-file parity gap 2: the explicit "is AICc ~ AIC?" evidence.

The reference builds a table with `delta = aicc - aic`, summarizes it
(max/mean), and checks that ranking by AIC agrees with ranking by AICc.
"""

from __future__ import annotations

import pytest

from workbench.engine.packs.arma_garch.arma import information_criterion_agreement


def _candidate(candidate_id: str, aic: float | None, aicc: float | None) -> dict[str, object]:
    return {"candidate_id": candidate_id, "aic": aic, "aicc": aicc}


def test_agreement_summarizes_delta_and_identical_ranking() -> None:
    candidates = [
        _candidate("a", 100.0, 100.5),
        _candidate("b", 110.0, 110.8),
        _candidate("c", 120.0, 121.4),
    ]
    result = information_criterion_agreement(candidates)

    assert result["n"] == 3
    assert result["delta_max"] == pytest.approx(1.4)
    assert result["delta_mean"] == pytest.approx((0.5 + 0.8 + 1.4) / 3)
    # AIC and AICc order the candidates identically here.
    assert result["rank_agreement_identical"] is True
    assert result["rank_agreement_spearman"] == 1.0


def test_agreement_detects_a_ranking_disagreement() -> None:
    # AICc reverses the top two because the second model has more parameters.
    candidates = [
        _candidate("a", 100.0, 105.0),
        _candidate("b", 101.0, 102.0),
    ]
    result = information_criterion_agreement(candidates)

    assert result["rank_agreement_identical"] is False
    assert result["rank_agreement_spearman"] == -1.0


def test_agreement_ignores_candidates_without_finite_criteria() -> None:
    candidates = [
        _candidate("a", 100.0, 100.5),
        _candidate("failed", None, None),
        _candidate("b", 110.0, 110.8),
    ]
    result = information_criterion_agreement(candidates)
    assert result["n"] == 2


def test_agreement_is_null_safe_when_nothing_is_comparable() -> None:
    result = information_criterion_agreement([_candidate("failed", None, None)])
    assert result["n"] == 0
    assert result["delta_max"] is None
    assert result["delta_mean"] is None
    assert result["rank_agreement_spearman"] is None
    assert result["rank_agreement_identical"] is None


def test_candidate_records_expose_the_delta_column() -> None:
    import numpy as np

    from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec, fit_arma_candidate

    rng = np.random.default_rng(5)
    values = np.zeros(400)
    errors = rng.normal(size=400)
    for index in range(1, 400):
        values[index] = 0.5 * values[index - 1] + errors[index]

    fitted = fit_arma_candidate(values, ArmaCandidateSpec("c", p=1, q=0, constant=False))
    payload = fitted.to_dict()

    assert "aicc_minus_aic" in payload
    assert payload["aicc_minus_aic"] == payload["aicc"] - payload["aic"]
