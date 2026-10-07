"""Count model contract tests against preserved Stata and R numerical oracles."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2, norm

from workbench.econometrics.runner import run_glm, run_negative_binomial

FIXTURE = Path(__file__).parent / "fixtures/count_models/reference-v3"


def data(name="nb2"):
    return pd.read_csv(FIXTURE / f"{name}.csv", float_precision="round_trip")


def oracle(name):
    return json.loads((FIXTURE / "stata.json").read_text())[name]


def regression(result):
    return [result["coefficients"][term] for term in ["Intercept", "x1", "x2"]]


@pytest.mark.parametrize("name,dispersion,logname", [("nb2", "mean", "lnalpha"), ("nb1", "constant", "lndelta")])
def test_joint_mle_and_oim_match_stata(name, dispersion, logname):
    reference = oracle(name)
    result, fitted = run_negative_binomial(data(name), "y", ["x1", "x2"], "nb", dispersion=dispersion)
    assert set(result["coefficients"]) == {"Intercept", "x1", "x2"}
    rows = regression(result)
    np.testing.assert_allclose([r["estimate"] for r in rows], [reference[f"b_{t}"] for t in ["_cons", "x1", "x2"]], rtol=0, atol=1e-6)
    np.testing.assert_allclose([r["std_error"] for r in rows], [reference[f"se_{t}"] for t in ["_cons", "x1", "x2"]], rtol=1e-4, atol=0)
    ancillary = {r["name"]: r for r in result["ancillary_parameters"]}
    logrow = ancillary[logname]
    natural = ancillary["alpha" if name == "nb2" else "delta"]
    assert natural["estimate"] == pytest.approx(np.exp(reference[f"b_{logname}"]), rel=1e-4)
    assert logrow["std_error"] == pytest.approx(reference[f"se_{logname}"], rel=1e-4)
    assert natural["std_error"] == pytest.approx(natural["estimate"] * logrow["std_error"], rel=1e-12)
    assert natural["conf_low"] == pytest.approx(np.exp(logrow["estimate"] - norm.ppf(.975) * logrow["std_error"]), rel=1e-12)
    assert natural["conf_high"] == pytest.approx(np.exp(logrow["estimate"] + norm.ppf(.975) * logrow["std_error"]), rel=1e-12)
    assert result["alpha_estimated"] is True
    assert result["alpha_fixed_value"] is None
    assert result["dispersion"] == dispersion
    assert result["information_matrix"] == "observed"
    assert result["convergence"]["converged"] is True
    lr = result["overdispersion_test"]
    assert lr["statistic"] == pytest.approx(reference["lr"], rel=1e-5)
    assert lr["p_value"] == pytest.approx(.5 * chi2.sf(lr["statistic"], 1), rel=1e-12)
    assert lr["distribution"] == "chibar2(01)"
    assert lr["df"] == 1
    assert lr["restricted_model"] == "poisson"
    assert fitted.__class__.__module__.startswith("statsmodels")
    assert len(fitted.params) == 4
    assert fitted.model.exog_names[-1] == "alpha"


def test_nb2_joint_mle_matches_r_mass_observed_information():
    reference = json.loads((FIXTURE / "r.json").read_text())["nb2"]
    result, _ = run_negative_binomial(data(), "y", ["x1", "x2"], "nb")
    np.testing.assert_allclose([r["estimate"] for r in regression(result)], reference["coefficients"], atol=1e-6, rtol=0)
    np.testing.assert_allclose([r["std_error"] for r in regression(result)], reference["std_error"], rtol=1e-4)
    natural = result["ancillary_parameters"][1]
    assert natural["estimate"] == pytest.approx(reference["alpha"], rel=1e-4)
    assert natural["std_error"] == pytest.approx(reference["se_alpha"], rel=1e-4)


def test_fixed_alpha_uses_observed_information_and_has_no_estimation_claim():
    reference = oracle("fixed")
    result, fitted = run_negative_binomial(data(), "y", ["x1", "x2"], "nbfixed", alpha=.5)
    np.testing.assert_allclose([r["estimate"] for r in regression(result)], [reference[f"b_{t}"] for t in ["_cons", "x1", "x2"]], atol=1e-6, rtol=0)
    np.testing.assert_allclose([r["std_error"] for r in regression(result)], [reference[f"se_{t}"] for t in ["_cons", "x1", "x2"]], rtol=1e-4)
    assert result["ancillary_parameters"] == []
    assert result["overdispersion_test"] is None
    assert result["alpha_estimated"] is False
    assert result["alpha_fixed_value"] == .5
    assert result["information_matrix"] == "observed"
    assert len(fitted.params) == 3


def test_glm_negative_binomial_requires_explicit_alpha():
    with pytest.raises(ValueError, match="GLM_NB_ALPHA_REQUIRED"):
        run_glm(data(), "y", ["x1", "x2"], "glm", "negative_binomial")


def test_glm_fixed_alpha_matches_r_expected_information():
    reference = json.loads((FIXTURE / "r.json").read_text())["fixed_glm"]
    result, fitted = run_glm(data(), "y", ["x1", "x2"], "glm", "negative_binomial", alpha=.5)
    np.testing.assert_allclose([r["estimate"] for r in regression(result)], reference["coefficients"], atol=1e-8, rtol=0)
    np.testing.assert_allclose([r["std_error"] for r in regression(result)], reference["std_error"], rtol=1e-6)
    assert result["information_matrix"] == "expected"
    assert result["alpha_fixed_value"] == .5
    assert result["overdispersion_test"] is None
    assert fitted.family.alpha == .5


@pytest.mark.parametrize("alpha", [0, -1, float("inf"), float("nan")])
def test_invalid_fixed_alpha_is_rejected(alpha):
    with pytest.raises(ValueError, match="NB_ALPHA_INVALID"):
        run_negative_binomial(data(), "y", ["x1", "x2"], "bad", alpha=alpha)


def test_unknown_dispersion_is_rejected():
    with pytest.raises(ValueError, match="NB_DISPERSION_INVALID"):
        run_negative_binomial(data(), "y", ["x1", "x2"], "bad", dispersion="bad")


def test_fixed_nb1_is_explicitly_rejected_instead_of_changing_dispersion():
    with pytest.raises(ValueError, match="NB_FIXED_DISPERSION_UNSUPPORTED"):
        run_negative_binomial(data("nb1"), "y", ["x1", "x2"], "unsupported", dispersion="constant", alpha=.5)


@pytest.mark.parametrize("regressor", ["alpha", "lnalpha", "delta", "lndelta"])
@pytest.mark.parametrize("name,dispersion,logname", [("nb2", "mean", "lnalpha"), ("nb1", "constant", "lndelta")])
def test_regressor_named_like_ancillary_is_not_confused(regressor, name, dispersion, logname):
    frame = data(name).rename(columns={"x1": regressor})
    result, fitted = run_negative_binomial(frame, "y", [regressor, "x2"], "named_ancillary", dispersion=dispersion)
    assert set(result["coefficients"]) == {"Intercept", regressor, "x2"}
    assert result["coefficients"][regressor]["estimate"] == pytest.approx(oracle(name)["b_x1"], abs=1e-6)
    assert result["ancillary_parameters"][1]["estimate"] == pytest.approx(np.exp(oracle(name)[f"b_{logname}"]), rel=1e-4)
    assert regressor in result["irr"]
    assert fitted.params.index[-1] == "alpha"
