"""Regression assertions for independently reproduced M2 P1 findings."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics import count_models
from workbench.econometrics.runner import run_glm, run_negative_binomial

ROOT = Path(__file__).parent / "fixtures/count_models"


def frame(name="nb2"):
    return pd.read_csv(ROOT / f"reference-v3/{name}.csv", float_precision="round_trip")


@pytest.mark.parametrize("family", ["poisson", "negative_binomial"])
@pytest.mark.parametrize("value", [-1., np.inf, -np.inf])
def test_count_glm_rejects_unsupported_response_before_fitting(monkeypatch, family, value):
    data = frame().astype({"y": float})
    data.loc[0, "y"] = value
    def must_not_construct_model(**kwargs):
        pytest.fail("Invalid count support reached model fitting")
    monkeypatch.setattr(count_models.smf, "glm", must_not_construct_model)
    with pytest.raises(ValueError, match="GLM_RESPONSE_INVALID"):
        run_glm(data, "y", ["x1", "x2"], "invalid", family,
                alpha=.5 if family == "negative_binomial" else None)


@pytest.mark.parametrize("form", ["mean", "constant"])
def test_uncertified_natural_stationarity_fails_closed(form):
    with pytest.raises(ValueError, match="NB_INFERENCE_UNCERTIFIED"):
        run_negative_binomial(frame("poisson"), "y", ["x1", "x2"], "boundary", dispersion=form)


@pytest.mark.parametrize("family", ["poisson", "negative_binomial", "binomial"])
@pytest.mark.parametrize("broken", ["parameters", "likelihood", "information", "covariance"])
def test_glm_nonfinite_inference_never_returns_a_packet(monkeypatch, family, broken):
    original = count_models.smf.glm
    def corrupted_model(**kwargs):
        model = original(**kwargs)
        original_fit = model.fit
        def fit(**options):
            fitted = original_fit(**options)
            if broken == "parameters":
                fitted._results.params[0] = np.nan
            elif broken == "likelihood":
                model.family.loglike = lambda *args, **kwargs: -np.inf
                fitted._results._cache.clear()
            elif broken == "information":
                model.hessian = lambda *args, **kwargs: np.full((3, 3), np.nan)
            else:
                fitted._results.normalized_cov_params[:] = np.inf
            return fitted
        model.fit = fit
        return model
    monkeypatch.setattr(count_models.smf, "glm", corrupted_model)
    data = frame()
    if family == "binomial":
        data.y = (data.y > 1).astype(float)
    with pytest.raises(ValueError, match="GLM_RESULT_NONFINITE"):
        run_glm(data, "y", ["x1", "x2"], "nonfinite", family,
                alpha=.5 if family == "negative_binomial" else None)


def test_fixed_fractional_nb_matches_native_stata_oim_and_r_eim():
    directory = ROOT / "p1-remediation-20261004/fractional-oracle"
    data = pd.read_csv(directory / "data.csv", float_precision="round_trip")
    stata = json.loads((directory / "stata.json").read_text())
    r = json.loads((directory / "r.json").read_text())
    fixed, fitted = run_negative_binomial(data, "y", ["x1", "x2"], "fractional", alpha=.5)
    np.testing.assert_allclose(fitted.params, [stata[f"b_{term}"] for term in ["_cons", "x1", "x2"]], rtol=0, atol=1e-6)
    np.testing.assert_allclose(fitted.bse, [stata[f"se_{term}"] for term in ["_cons", "x1", "x2"]], rtol=1e-4)
    assert fitted.llf == pytest.approx(stata["ll"], abs=1e-8)
    assert fixed["ancillary_parameters"] == []
    glm, fitted = run_glm(data, "y", ["x1", "x2"], "fractional_glm", "negative_binomial", alpha=.5)
    np.testing.assert_allclose(fitted.params, r["coefficients"], rtol=0, atol=1e-8)
    np.testing.assert_allclose(fitted.bse, r["std_error"], rtol=1e-4)
    json.dumps(glm, allow_nan=False)


def test_binomial_fractional_response_remains_valid():
    data = frame()
    data.y = data.y / (1 + data.y)
    packet, _ = run_glm(data, "y", ["x1", "x2"], "binomial_proportions", "binomial")
    assert packet["convergence"]["converged"]
    json.dumps(packet, allow_nan=False)


@pytest.mark.parametrize("value", [-.1, 1.1, np.inf])
def test_binomial_support_is_bounded_before_fitting(monkeypatch, value):
    data = frame().astype({"y": float})
    data.y = (data.y > 1).astype(float)
    data.loc[0, "y"] = value
    def must_not_construct_model(**kwargs):
        pytest.fail("Invalid binomial support reached model fitting")
    monkeypatch.setattr(count_models.smf, "glm", must_not_construct_model)
    with pytest.raises(ValueError, match="GLM_RESPONSE_INVALID"):
        run_glm(data, "y", ["x1", "x2"], "invalid", "binomial")


@pytest.mark.parametrize("broken", ["beta_score", "ancillary_score", "information_nonfinite", "information_indefinite"])
def test_joint_inference_requires_every_natural_score_and_regular_information(monkeypatch, broken):
    original = count_models.smf.negativebinomial
    def uncertified_model(**kwargs):
        model = original(**kwargs)
        original_fit = model.fit
        def fit(**options):
            fitted = original_fit(**options)
            if broken in {"beta_score", "ancillary_score"}:
                score = np.zeros(len(fitted.params))
                score[0 if broken == "beta_score" else -1] = .1
                model.score = lambda *args, **kwargs: score
            else:
                hessian = np.full((4, 4), np.nan) if broken == "information_nonfinite" else np.eye(4)
                model.hessian = lambda *args, **kwargs: hessian
            return fitted
        model.fit = fit
        return model
    monkeypatch.setattr(count_models.smf, "negativebinomial", uncertified_model)
    with pytest.raises(ValueError, match="NB_INFERENCE_UNCERTIFIED"):
        run_negative_binomial(frame(), "y", ["x1", "x2"], "uncertified")
