"""Behavior and adversarial tests for synthetic_control.fit/placebo."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_control" / "oracle_cases.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def _fit_kwargs() -> dict[str, object]:
    value = _fixture()
    return {
        "outcome_matrix": value["outcomes"],
        "treated_unit": "treated",
        "donor_pool": ["d1", "d2", "d3"],
        "unit_labels": value["units"],
        "periods": value["periods"],
        "pre_periods": [0, 1, 2],
        "post_periods": [3, 4, 5],
        "predictor_matrix": None,
        "solver_policy": {
            "solver": "scipy_slsqp",
            "max_iter": 500,
            "tolerance": 1e-10,
            "constraint_tolerance": 1e-8,
        },
        "tolerance_policy": {
            "weight_sum": 1e-8,
            "constraint": 1e-8,
            "finite": 0.0,
        },
    }


def test_synthetic_control_fit_is_reproducible_and_enforces_simplex_weights() -> None:
    from workbench.engine.packs.synthetic_control import fit_synthetic_control

    first = fit_synthetic_control(**_fit_kwargs())
    second = fit_synthetic_control(**_fit_kwargs())
    assert first == second
    assert first["operation_id"] == "synthetic_control.fit"
    assert first["status"] == "completed"
    result = first["result"]
    assert result["treated_unit"] == "treated"
    assert result["weight_sum"] == pytest.approx(1.0, abs=1e-8)
    assert all(0.0 <= item["weight"] <= 1.0 for item in result["weights"])
    assert result["nonzero_donor_count"] >= 1
    assert result["pre_fit"]["rmse"] == pytest.approx(0.0, abs=1e-7)
    assert result["post_treatment"]["gap_mean"] == pytest.approx(1.0, abs=1e-7)
    assert result["post_treatment"]["gap_cumulative"] == pytest.approx(3.0, abs=1e-7)
    assert result["scope"]["not_claimed"]
    assert "raw_matrix" not in result


@pytest.mark.parametrize(
    "mutator, reason",
    [
        (lambda k: {**k, "pre_periods": [0]}, "SYNTHETIC_CONTROL_INSUFFICIENT_PRE_PERIODS"),
        (lambda k: {**k, "donor_pool": ["d1"]}, "SYNTHETIC_CONTROL_DONOR_INFEASIBLE"),
        (lambda k: {**k, "periods": [0, 2, 1, 3, 4, 5]}, "SYNTHETIC_CONTROL_UNSORTED_PERIODS"),
        (lambda k: {**k, "outcome_matrix": [[0.0, 1.0, np.nan, 4.0, 5.0, 6.0], [0.0, 1.0, 2.0, 3.0, 4.0, 5.0], [0.0, 2.0, 4.0, 6.0, 8.0, 10.0], [2.0, 1.0, 0.0, 1.0, 1.0, 1.0]]}, "SYNTHETIC_CONTROL_NONFINITE_INPUT"),
    ],
)
def test_synthetic_control_fails_closed_on_boundary_violations(mutator, reason: str) -> None:
    from workbench.engine.packs.synthetic_control import SyntheticControlPackError, fit_synthetic_control

    with pytest.raises(SyntheticControlPackError, match=reason):
        fit_synthetic_control(**mutator(_fit_kwargs()))


def test_synthetic_control_rejects_degenerate_outcomes_and_constraint_violation() -> None:
    from workbench.engine.packs.synthetic_control import SyntheticControlPackError, fit_synthetic_control

    degenerate = _fit_kwargs()
    degenerate["outcome_matrix"] = np.ones((4, 6)).tolist()
    with pytest.raises(SyntheticControlPackError, match="SYNTHETIC_CONTROL_DEGENERATE"):
        fit_synthetic_control(**degenerate)

    bad_policy = _fit_kwargs()
    bad_policy["solver_policy"] = {
        "solver": "scipy_slsqp",
        "max_iter": 0,
        "tolerance": 1e-10,
        "constraint_tolerance": 1e-8,
    }
    with pytest.raises(SyntheticControlPackError, match="SYNTHETIC_CONTROL_INVALID_POLICY"):
        fit_synthetic_control(**bad_policy)


def test_synthetic_control_placebo_has_distinct_estimands_and_no_raw_placebo_rows() -> None:
    from workbench.engine.packs.synthetic_control import run_placebo

    value = _fixture()
    result = run_placebo(
        outcome_matrix=value["outcomes"],
        treated_unit="treated",
        donor_pool=["d1", "d2", "d3"],
        unit_labels=value["units"],
        periods=value["periods"],
        pre_periods=[0, 1, 2],
        post_periods=[3, 4, 5],
        placebo_policy={
            "unit_policy": "explicit",
            "placebo_units": ["d1", "d2"],
            "max_placebos": 2,
            "donor_policy": "exclude_original_treated",
            "failure_policy": "reject",
        },
    )

    payload = result["result"]
    assert result["operation_id"] == "synthetic_control.placebo"
    assert payload["estimands"]["pre_fit"] == "pre_treatment_fit_rmse"
    assert payload["estimands"]["post_gap"] == "post_treatment_placebo_gap"
    assert payload["placebo_count"] == 2
    assert len(payload["placebo_summaries"]) == 2
    for summary in payload["placebo_summaries"]:
        assert set(summary) >= {"unit", "pre_fit_rmse", "post_gap_mean", "post_gap_cumulative"}
        assert "raw_rows" not in summary
        assert "period_gaps" not in summary
    assert "significance" not in payload


def test_placebo_policy_is_bounded_and_cannot_include_treated_unit() -> None:
    from workbench.engine.packs.synthetic_control import SyntheticControlPackError, run_placebo

    kwargs = _fit_kwargs()
    kwargs.pop("predictor_matrix")
    kwargs.pop("solver_policy")
    kwargs.pop("tolerance_policy")
    with pytest.raises(SyntheticControlPackError, match="SYNTHETIC_CONTROL_INVALID_PLACEBO_POLICY"):
        run_placebo(
            **kwargs,
            placebo_policy={
                "unit_policy": "explicit",
                "placebo_units": ["treated"],
                "max_placebos": 1,
                "donor_policy": "exclude_original_treated",
                "failure_policy": "reject",
            },
        )
