"""AIC/BIC comparability is within-family and same-sample only."""

from __future__ import annotations

import pytest

from tests.fixtures.models.ets.known_truth import (
    additive_trend_series,
    damped_trend_series,
)
from workbench.contracts.model.ets import COMPARE_REASON_CODES
from workbench.engine.packs.ets.compare import CompareSide, build_ets_compare_packet
from workbench.engine.packs.ets.runner import fit_ets


def _options(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "time_column": "date",
        "value_column": "y",
        "error": "add",
        "trend": "add",
        "seasonal": None,
        "damped_trend": False,
    }
    payload.update(overrides)
    return payload


def _fit(series, **overrides):
    return fit_ets(series.frame(), _options(**overrides))


def test_compare_against_arma_garch_is_restricted() -> None:
    ets = _fit(additive_trend_series())
    packet = build_ets_compare_packet(
        CompareSide.from_outcome(ets, label="ets"),
        CompareSide.from_foreign_result(
            {"model_type": "time_series.arma_garch"}, label="arma_garch"
        ),
    )

    assert packet["comparability"] == "restricted"
    assert packet["reason_code"] == "ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE"
    assert packet["reason_code"] in COMPARE_REASON_CODES
    assert packet["criteria"] is None
    assert packet["contract"] == "time_series.ets.compare"
    assert packet["contract_version"] == "1.0"


def test_compare_across_different_samples_is_restricted() -> None:
    left = _fit(additive_trend_series())
    right = _fit(damped_trend_series(), damped_trend=True)
    packet = build_ets_compare_packet(
        CompareSide.from_outcome(left, label="a"),
        CompareSide.from_outcome(right, label="b"),
    )

    assert packet["comparability"] == "restricted"
    assert packet["reason_code"] == "ETS_SAMPLE_DIFFERS"
    assert packet["criteria"] is None


def test_within_family_same_sample_comparison_reports_deltas() -> None:
    series = damped_trend_series()
    undamped = _fit(series, damped_trend=False)
    damped = _fit(series, damped_trend=True)
    packet = build_ets_compare_packet(
        CompareSide.from_outcome(undamped, label="ETS(A,A,N)"),
        CompareSide.from_outcome(damped, label="ETS(A,Ad,N)"),
    )

    assert packet["comparability"] == "full"
    assert packet["reason_code"] == "ETS_SPECIFICATION_DIFFERS"
    criteria = packet["criteria"]
    assert criteria["basis"] == "within_family_same_sample"
    assert criteria["aic_delta"] == pytest.approx(
        damped.result.aic - undamped.result.aic, rel=0, abs=1e-9
    )
    assert criteria["bic_delta"] == pytest.approx(
        damped.result.bic - undamped.result.bic, rel=0, abs=1e-9
    )
    # The true damped series must prefer the damped specification by AIC.
    assert damped.result.aic < undamped.result.aic
    assert criteria["preferred_by_aic"] == "ETS(A,Ad,N)"


def test_identical_specification_refit_has_no_reason_code() -> None:
    series = additive_trend_series()
    first = _fit(series)
    second = _fit(series)
    packet = build_ets_compare_packet(
        CompareSide.from_outcome(first, label="a"),
        CompareSide.from_outcome(second, label="b"),
    )

    assert packet["comparability"] == "full"
    assert packet["reason_code"] is None
    assert packet["criteria"]["aic_delta"] == 0.0


def test_compare_requires_at_least_one_ets_side() -> None:
    foreign = CompareSide.from_foreign_result(
        {"model_type": "time_series.arma_garch"}, label="a"
    )
    with pytest.raises(ValueError):
        build_ets_compare_packet(foreign, foreign)
