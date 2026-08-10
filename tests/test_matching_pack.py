"""Behavior and adversarial tests for matching.att and matching.balance."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "matching" / "oracle_cases.json"


def _frame(name: str = "balanced") -> pd.DataFrame:
    return pd.DataFrame(json.loads(FIXTURE.read_text())[name])


def _policy(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "treatment_column": "treated",
        "outcome_column": "outcome",
        "covariate_columns": ["x", "z"],
        "id_column": "unit",
        "propensity_policy": {
            "model": "logit",
            "solver": "newton",
            "max_iter": 200,
            "tolerance": 1e-10,
            "min_probability": 1e-6,
            "max_probability": 1.0 - 1e-6,
        },
        "distance_policy": "logit",
        "ratio": 1,
        "caliper": 0.75,
        "replacement": False,
        "tie_policy": "stable_first",
        "common_support_policy": "trim",
        "unmatched_policy": "reject",
        "balance_threshold": 0.1,
        "missing_policy": "reject",
    }
    value.update(overrides)
    return value


def test_matching_att_is_reproducible_and_reports_deterministic_provenance() -> None:
    from workbench.engine.packs.matching import estimate_att

    first = estimate_att(_frame(), **_policy())
    second = estimate_att(_frame(), **_policy())

    assert first == second
    assert first["operation_id"] == "matching.att"
    assert first["status"] == "completed"
    result = first["result"]
    assert result["estimand"] == "ATT"
    assert result["att"] == pytest.approx(2.0)
    assert result["matched_treated_count"] == 3
    assert result["matched_control_count"] == 3
    assert result["matched_pairs"] == [
        {"treated_position": 0, "control_position": 3, "control_unit": "c1"},
        {"treated_position": 1, "control_position": 4, "control_unit": "c2"},
        {"treated_position": 2, "control_position": 5, "control_unit": "c3"},
    ]
    assert result["provenance"]["row_order"] == "input_position_stable"
    assert result["scope"]["not_claimed"]
    assert any("causal" in item.lower() for item in result["scope"]["not_claimed"])


def test_matching_balance_reports_before_after_smd_and_variance_ratio_without_rows() -> None:
    from workbench.engine.packs.matching import assess_balance, estimate_att

    fit = estimate_att(_frame(), **_policy())
    balance = assess_balance(
        _frame(),
        treatment_column="treated",
        covariate_columns=["x", "z"],
        id_column="unit",
        matched_pairs=fit["result"]["matched_pairs"],
        balance_threshold=0.1,
        missing_policy="reject",
    )

    assert balance["operation_id"] == "matching.balance"
    assert balance["result"]["balance_ok"] is True
    assert set(balance["result"]["covariates"]) == {"x", "z"}
    for evidence in balance["result"]["covariates"].values():
        assert set(evidence) >= {
            "before_smd",
            "after_smd",
            "before_variance_ratio",
            "after_variance_ratio",
        }
    assert "raw_rows" not in balance["result"]
    assert "raw_data" not in balance["result"]


def test_matching_balance_failure_retains_diagnostics_but_blocks_causal_eligibility() -> None:
    from workbench.engine.packs.matching import assess_balance

    frame = pd.DataFrame(
        {
            "unit": ["t1", "t2", "c1", "c2"],
            "treated": [1, 1, 0, 0],
            "x": [10.0, 11.0, 0.0, 1.0],
        }
    )
    result = assess_balance(
        frame,
        treatment_column="treated",
        covariate_columns=["x"],
        id_column="unit",
        balance_threshold=0.01,
        missing_policy="reject",
    )
    assert result["result"]["balance_ok"] is False
    assert result["result"]["causal_claim_eligible"] is False
    assert result["result"]["covariates"]["x"]["before_smd"] > 1.0


@pytest.mark.parametrize(
    "mutator, reason",
    [
        (lambda f: f.assign(treated=[True, True, False, False, False, False]), "MATCHING"),
        (lambda f: f.assign(unit=["same"] * len(f)), "MATCHING_DUPLICATE_ID"),
        (lambda f: f.assign(x=[1.0, np.inf, 1.0, 1.0, 1.0, 1.0]), "MATCHING_NONFINITE"),
        (lambda f: f.assign(x=["1", "2", "3", "4", "5", "6"]), "MATCHING_NON_NUMERIC"),
    ],
)
def test_matching_fails_closed_on_unsafe_input(mutator, reason: str) -> None:
    from workbench.engine.packs.matching import MatchingPackError, estimate_att

    with pytest.raises(MatchingPackError, match=reason):
        estimate_att(_frame().pipe(mutator), **_policy())


def test_matching_rejects_no_common_support_and_caliper_unmatched_treated_units() -> None:
    from workbench.engine.packs.matching import MatchingPackError, estimate_att

    no_overlap = pd.DataFrame(
        {
            "unit": ["t1", "t2", "c1", "c2"],
            "treated": [1, 1, 0, 0],
            "outcome": [3.0, 4.0, 1.0, 2.0],
            "x": [8.0, 9.0, -9.0, -8.0],
            "z": [8.0, 9.0, -9.0, -8.0],
        }
    )
    with pytest.raises(MatchingPackError, match="MATCHING_(NO_COMMON_SUPPORT|PROPENSITY_EXTREME)"):
        estimate_att(no_overlap, **_policy(caliper=None))

    with pytest.raises(MatchingPackError, match="MATCHING_UNMATCHED_TREATED"):
        estimate_att(_frame(), **_policy(caliper=1e-12))


def test_matching_tie_policy_is_stable_and_replacement_is_explicit() -> None:
    from workbench.engine.packs.matching import estimate_att

    frame = _frame("tie")
    policy = _policy(
        covariate_columns=["x"],
        caliper=None,
        replacement=True,
        balance_threshold=None,
    )
    first = estimate_att(frame, **policy)
    second = estimate_att(frame, **policy)
    assert first == second
    assert first["result"]["matched_pairs"][0]["control_position"] == 1
    assert first["result"]["matching_policy"]["replacement"] is True
