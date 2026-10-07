"""Poisson boundary, sample preservation and convergence failures for count ML."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from workbench.econometrics.runner import run_negative_binomial

FIXTURE = Path(__file__).parent / "fixtures/count_models/reference-v3"


def test_underdispersed_sample_refuses_uncertified_regular_inference():
    frame = pd.read_csv(FIXTURE / "poisson.csv", float_precision="round_trip")
    # The native reference is retained. Optimizer log-coordinate convergence
    # does not certify the natural-parameter score for this near-boundary fit.
    with pytest.raises(ValueError, match="NB_INFERENCE_UNCERTIFIED"):
        run_negative_binomial(frame, "y", ["x1", "x2"], "boundary")


def test_restricted_poisson_uses_identical_complete_case_sample():
    frame = pd.read_csv(FIXTURE / "nb2.csv", float_precision="round_trip")
    frame.loc[::19, "x1"] = np.nan
    result, fitted = run_negative_binomial(frame, "y", ["x1", "x2"], "missing")
    complete = frame.dropna()
    reference = sm.GLM(complete.y, sm.add_constant(complete[["x1", "x2"]]), family=sm.families.Poisson()).fit(tol=1e-12)
    assert result["nobs"] == len(complete)
    assert result["overdispersion_test"]["log_likelihood_restricted"] == pytest.approx(reference.llf, abs=1e-8)
    assert fitted.nobs == len(complete)


@pytest.mark.parametrize("value,alpha", [(-1,None),(.5,None),(float("inf"),None),
                                       (-1,.5),(float("inf"),.5)])
def test_invalid_response_is_rejected_for_joint_and_fixed(value, alpha):
    frame = pd.read_csv(FIXTURE / "nb2.csv")
    frame["y"] = frame.y.astype(float)
    frame.loc[0, "y"] = value
    with pytest.raises(ValueError, match="NB_COUNTS_INVALID"):
        run_negative_binomial(frame, "y", ["x1", "x2"], "invalid", alpha=alpha)


def test_boundary_failure_can_be_serialized_without_nonfinite_numbers(tmp_path):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.artifacts import read_json
    project = create_project(tmp_path, "uncertified-boundary")
    outcome = run_workflow(project.root, [FIXTURE / "poisson.csv"], mode="auto",
        model_type="negative_binomial", y="y", x=["x1","x2"])
    assert outcome["status"] == "failed"
    errors = read_json(project.root / "runs" / outcome["run_id"] / "errors.json")
    assert "NB_INFERENCE_UNCERTIFIED" in json.dumps(errors, allow_nan=False)


def test_nonpositive_lr_uses_boundary_mixture_rule_without_clipping():
    from workbench.econometrics.count_models import overdispersion_test
    result = overdispersion_test(-10., -9.)
    assert result["statistic"] == -2.
    assert result["p_value"] == 1.


def test_stable_small_dispersion_likelihood_matches_r():
    from workbench.econometrics.count_models import _small_dispersion_likelihood
    frame = pd.read_csv(FIXTURE / "poisson.csv", float_precision="round_trip")
    reference = json.loads((FIXTURE.parent / "boundary_profile_stable.json").read_text())
    x = sm.add_constant(frame[["x1", "x2"]]).to_numpy()
    mu = np.exp(x @ np.array(reference["beta"]))
    for row in reference["loglike_checks"]:
        if row["alpha"] > .001:
            continue
        ll, score, hessian = _small_dispersion_likelihood(frame.y.to_numpy(), x, mu, row["alpha"], row["dispersion"])
        assert abs(ll-row["ll"]) < 1e-8
        assert np.isfinite(score).all()
        assert np.isfinite(hessian).all()
