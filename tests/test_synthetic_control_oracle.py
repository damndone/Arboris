"""Independent direct NumPy/SciPy oracle tests for synthetic control."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
from scipy.optimize import minimize


FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_control" / "oracle_cases.json"


def test_direct_simplex_oracle_matches_pre_fit_and_post_gap() -> None:
    from workbench.engine.packs.synthetic_control import fit_synthetic_control

    value = json.loads(FIXTURE.read_text())
    outcomes = np.asarray(value["outcomes"], dtype=float)
    donor = outcomes[1:, :3]
    target = outcomes[0, :3]

    def objective(weights: np.ndarray) -> float:
        residual = target - weights @ donor
        return float(residual @ residual)

    oracle = minimize(
        objective,
        np.full(3, 1 / 3),
        method="SLSQP",
        bounds=[(0.0, 1.0)] * 3,
        constraints={"type": "eq", "fun": lambda weights: float(weights.sum() - 1.0)},
        options={"ftol": 1e-12, "maxiter": 500},
    )
    assert oracle.success

    result = fit_synthetic_control(
        outcome_matrix=value["outcomes"],
        treated_unit="treated",
        donor_pool=["d1", "d2", "d3"],
        unit_labels=value["units"],
        periods=value["periods"],
        pre_periods=[0, 1, 2],
        post_periods=[3, 4, 5],
    )["result"]
    actual_weights = np.asarray([item["weight"] for item in result["weights"]])
    assert actual_weights @ donor.T == pytest.approx(oracle.x @ donor.T, abs=1e-6)
    assert result["pre_fit"]["rmse"] == pytest.approx(np.sqrt(oracle.fun / 3), abs=1e-7)


# v1.8.10 port: the P7 branch had an always-skipped placeholder here for the
# optional Synth/quadprog references. A test that never runs proves nothing,
# so it was not ported; the base-R constrained oracle below is the reference.


def test_base_r_constrained_oracle_matches_fit_summary() -> None:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript unavailable")
    fixture = Path(__file__).parent / "fixtures" / "synthetic_control" / "generate_oracle.R"
    completed = subprocess.run(["Rscript", "--vanilla", str(fixture)], check=True, capture_output=True, text=True)
    reference = {line.split(",", 1)[0]: float(line.split(",", 1)[1]) for line in completed.stdout.splitlines() if line.strip()}
    value = json.loads(FIXTURE.read_text())
    from workbench.engine.packs.synthetic_control import fit_synthetic_control

    result = fit_synthetic_control(
        outcome_matrix=value["outcomes"], treated_unit="treated", donor_pool=["d1", "d2", "d3"], unit_labels=value["units"], periods=value["periods"], pre_periods=[0, 1, 2], post_periods=[3, 4, 5],
    )["result"]
    # constrOptim's logarithmic barrier stays a few e-6 inside a boundary
    # optimum; the independent objective is the same and the tolerance is
    # explicit here rather than silently widening the production solver.
    assert result["pre_fit"]["rmse"] == pytest.approx(reference["rmse"], abs=1e-5)
    assert result["weight_sum"] == pytest.approx(reference["weight_sum"], abs=1e-8)
