"""Independent direct NumPy oracle tests for matching evidence."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest


FIXTURE = Path(__file__).parent / "fixtures" / "matching" / "oracle_cases.json"


def _frame() -> pd.DataFrame:
    return pd.DataFrame(json.loads(FIXTURE.read_text())["balanced"])


def _direct_smd(treated: np.ndarray, control: np.ndarray) -> float:
    pooled = np.sqrt((np.var(treated, ddof=1) + np.var(control, ddof=1)) / 2.0)
    return float((np.mean(treated) - np.mean(control)) / pooled)


def test_direct_nearest_neighbor_oracle_matches_att_and_balance_evidence() -> None:
    from workbench.engine.packs.matching import estimate_att

    frame = _frame()
    output = estimate_att(
        frame,
        treatment_column="treated",
        outcome_column="outcome",
        covariate_columns=["x", "z"],
        id_column="unit",
        propensity_policy={
            "model": "logit",
            "solver": "newton",
            "max_iter": 200,
            "tolerance": 1e-10,
            "min_probability": 1e-6,
            "max_probability": 1.0 - 1e-6,
        },
        distance_policy="logit",
        ratio=1,
        caliper=0.75,
        replacement=False,
        tie_policy="stable_first",
        common_support_policy="trim",
        unmatched_policy="reject",
        balance_threshold=0.1,
        missing_policy="reject",
    )
    result = output["result"]

    # Independent reference uses the fixture's known monotone nearest pairs.
    treated_outcomes = frame.loc[[0, 1, 2], "outcome"].to_numpy(dtype=float)
    control_outcomes = frame.loc[[3, 4, 5], "outcome"].to_numpy(dtype=float)
    oracle_att = float(np.mean(treated_outcomes - control_outcomes))
    assert result["att"] == pytest.approx(oracle_att)

    oracle_smd = _direct_smd(frame.loc[[0, 1, 2], "x"].to_numpy(), control_outcomes * 0 + frame.loc[[3, 4, 5], "x"].to_numpy())
    assert result["balance"]["covariates"]["x"]["after_smd"] == pytest.approx(oracle_smd)


def test_optional_matchit_oracle_is_explicitly_skipped_when_unavailable() -> None:
    pytest.importorskip("rpy2", reason="optional MatchIt oracle is unavailable")
    pytest.skip("MatchIt oracle is optional and does not define the NumPy contract")


def test_base_r_glm_oracle_matches_propensity_support_summary() -> None:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript unavailable")
    fixture = Path(__file__).parent / "fixtures" / "matching" / "generate_oracle.R"
    completed = subprocess.run(["Rscript", "--vanilla", str(fixture)], check=True, capture_output=True, text=True)
    reference = {line.split(",", 1)[0]: float(line.split(",", 1)[1]) for line in completed.stdout.splitlines() if line.strip()}
    from workbench.engine.packs.matching import estimate_att

    output = estimate_att(
        _frame(), treatment_column="treated", outcome_column="outcome", covariate_columns=["x", "z"], id_column="unit",
        propensity_policy={"model": "logit", "solver": "newton", "max_iter": 200, "tolerance": 1e-10, "min_probability": 1e-6, "max_probability": 1.0 - 1e-6},
        distance_policy="logit", ratio=1, caliper=0.75, replacement=False, tie_policy="stable_first", common_support_policy="trim", unmatched_policy="reject", balance_threshold=0.1, missing_policy="reject",
    )
    assert output["result"]["propensity"]["min"] == pytest.approx(reference["min"], rel=1e-10)
    assert output["result"]["propensity"]["max"] == pytest.approx(reference["max"], rel=1e-10)
