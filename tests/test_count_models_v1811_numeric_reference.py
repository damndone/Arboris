"""Native R precision evidence for projected NB2 and fixed-alpha GLM kernels.

Run with Integration's backend until the central positional projection API has
been incorporated into the numerical-reference branch. Override pytest's
configured pythonpath as well as the process PYTHONPATH. This tests primitives;
it does not change the operation registry or admit a model family.
"""
from pathlib import Path
import json
import inspect

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.model.inference_kernel import kernel_from_fitted
from workbench.econometrics.normalize import _public_term
from workbench.econometrics.runner import run_glm, run_negative_binomial
from workbench.econometrics import count_models
from workbench.postestimation import lincom, nlcom, wald_test
from workbench.postestimation.margins import marginal_effects

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / "count_models/integration-strict-v1811/native-reference"
NB = json.loads((REFERENCE / "nb2-postestimation-reference.json").read_text())
GLM = json.loads((REFERENCE / "glm-fixed-alpha-reference.json").read_text())
JOINT = [{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]
SHIFTED = [{"terms": {"x1": 1, "x2": -1}, "value": 1}]


def collect_numeric_results():
    frame = pd.read_csv(FIXTURES / "postestimation/data.csv", float_precision="round_trip")
    packet, fitted = run_negative_binomial(frame, "ynb", ["x1", "x2", "x3"], "strict_nb")
    k = fitted.model.exog.shape[1]
    kernel = kernel_from_fitted(fitted, model_id="strict_nb", model_type="negative_binomial",
                                nobs=len(frame), param_positions=list(range(k)), public_name=_public_term)
    design = dict(zip(kernel["param_names"], np.asarray(fitted.model.exog).T))
    results = {"params": dict(zip(kernel["param_names"], kernel["params"])),
               "production_source":inspect.getfile(count_models), "kernel_source":inspect.getfile(kernel_from_fitted),
               "kernel": kernel, "joint_vcov": np.asarray(fitted.cov_params()).tolist(),
               "beta_vcov": kernel["vcov"], "alpha": packet["ancillary_parameters"][1],
               "lnalpha": packet["ancillary_parameters"][0], "ll": float(fitted.llf),
               "natural_score": fitted.model.score(np.asarray(fitted.params)).tolist(),
               "natural_mean_score_max": float(np.max(abs(fitted.model.score(np.asarray(fitted.params))))/len(frame)),
               "wald_joint": wald_test(kernel, JOINT), "wald_shifted": wald_test(kernel, SHIFTED),
               "lincom": lincom(kernel, {"x1":1,"x2":2}, constant=-.5), "nlcom": nlcom(kernel,"x1/x2"),
               "margins": {"average": marginal_effects(kernel, design, inverse_link="log", variables=["x1","x2"], at="average"),
                           "at_means": marginal_effects(kernel, design, inverse_link="log", variables=["x1","x2"], at="means")}}
    frame = pd.read_csv(FIXTURES / "admission/glm_negative_binomial/data.csv", float_precision="round_trip")
    glm_packet, glm_fit = run_glm(frame,"y",["x1","x2"],"strict_glm","negative_binomial",alpha=1)
    results["glm"] = {"params": dict(zip([_public_term(t) for t in glm_fit.params.index], glm_fit.params.tolist())),
                      "std_error": glm_fit.bse.tolist(), "covariance": np.asarray(glm_fit.cov_params()).tolist(),
                      "ll": float(glm_fit.llf), "convergence": glm_packet["convergence"],
                      "max_absolute_score": float(np.max(abs(glm_fit.model.score(glm_fit.params))))}
    return results


@pytest.fixture(scope="module")
def measured():
    return collect_numeric_results()


def test_projected_kernel_has_only_beta_and_full_joint_inverse_block(measured):
    assert measured["kernel"]["param_names"] == ["Intercept","x1","x2","x3"]
    np.testing.assert_array_equal(measured["beta_vcov"], np.asarray(measured["joint_vcov"])[:4,:4])
    assert measured["natural_mean_score_max"] <= 1e-8
    for term,value in measured["params"].items():
        reference = NB["full_precision"]["params"]["(Intercept)" if term == "Intercept" else term]
        assert value == pytest.approx(float(reference), abs=1e-6)
    np.testing.assert_allclose(measured["beta_vcov"], np.asarray(NB["full_precision"]["beta_vcov"],float), rtol=1e-4)
    for stat in ["estimate","std_error","conf_low","conf_high"]:
        assert measured["alpha"][stat] == pytest.approx(float(NB["full_precision"]["ancillary"]["alpha"][stat]), rel=1e-4)


@pytest.mark.parametrize("operation",["wald_joint","wald_shifted","lincom","nlcom"])
def test_nb2_postestimation_matches_native_r_at_existing_tolerance(measured,operation):
    for key in ["statistic","estimate","std_error","p_value"]:
        if key in NB[operation]:
            tolerance = 1e-3 if key == "p_value" else 1e-4
            assert measured[operation][key] == pytest.approx(float(NB["full_precision"][operation][key]),rel=tolerance)


@pytest.mark.parametrize("at",["average","at_means"])
def test_nb2_margins_matches_native_r_with_projected_beta_covariance(measured,at):
    for effect in measured["margins"][at]["effects"]:
        reference = NB["full_precision"]["margins"][at][effect["variable"]]
        assert effect["estimate"] == pytest.approx(float(reference["estimate"]),rel=1e-6)
        assert effect["std_error"] == pytest.approx(float(reference["std_error"]),rel=1e-5)


def test_fixed_alpha_glm_matches_epsilon16_final_expected_information(measured):
    reference = GLM["full_precision"]["epsilon1e-16"]
    for term,value in measured["glm"]["params"].items():
        assert value == pytest.approx(float(reference["params"]["(Intercept)" if term == "Intercept" else term]),abs=1e-8)
    np.testing.assert_allclose(measured["glm"]["std_error"],np.asarray(reference["std_error"],float),rtol=0,atol=1e-6)
    np.testing.assert_allclose(measured["glm"]["covariance"],np.asarray(reference["covariance"],float),rtol=1e-8,atol=1e-12)


def test_original_nb_reference_already_has_certified_precision():
    old = json.loads((FIXTURES / "postestimation/oracle.json").read_text())["families"]["negative_binomial"]
    assert NB["diagnostics"]["epsilon14"]["natural_mean_score_max"] < 1e-13
    for operation in ["wald_joint","wald_shifted","lincom","nlcom"]:
        for key,value in old[operation].items():
            if isinstance(value,(float,int)) and key in NB[operation]:
                assert NB[operation][key] == pytest.approx(value,rel=1e-8)


@pytest.mark.parametrize("regressor",["alpha","lnalpha","delta","lndelta"])
def test_projected_positions_preserve_ordinary_ancillary_named_regressors(regressor):
    frame = pd.read_csv(FIXTURES / "postestimation/data.csv",float_precision="round_trip").rename(columns={"x1":regressor})
    _,fitted = run_negative_binomial(frame,"ynb",[regressor,"x2","x3"],"named_beta")
    k = fitted.model.exog.shape[1]
    kernel = kernel_from_fitted(fitted,model_id="named_beta",model_type="negative_binomial",nobs=len(frame),
                                param_positions=list(range(k)),public_name=_public_term)
    assert kernel["param_names"] == ["Intercept",regressor,"x2","x3"]
    np.testing.assert_array_equal(kernel["vcov"],np.asarray(fitted.cov_params())[:k,:k])
    assert kernel["params"][1] == pytest.approx(float(NB["full_precision"]["params"]["x1"]),abs=1e-6)
