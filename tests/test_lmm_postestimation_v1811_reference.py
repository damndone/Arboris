"""LMM fixed-effect inference against lme4 and Stata ``mixed``.

Four settings: REML / ML x random intercept (admission fixture) / correlated
random intercept and slope (seeded fixture). R: generate_gls_reference.R
(lme4 vcov()); Stata: generate_gls_reference.do (mixed, default vce(oim)).
Both report the GLS covariance (X'V^-1 X)^-1 at the estimated variance
components; Workbench now reports the same (covariance.py). The earlier
inverse-Hessian definition is kept below as the measured reason for v2.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.linear_mixed_effects.covariance import REML_LIKELIHOOD_REASON
from workbench.engine.packs.linear_mixed_effects.input import prepare_lmm_input
from workbench.engine.packs.linear_mixed_effects.runner import _fit_prepared, _record_fixed_effects_kernel
from workbench.postestimation import PostestimationRefusal, lincom, lr_test, nlcom, wald_test
from workbench.postestimation.registry import require_validated, run_operation

FIXTURE = Path(__file__).parent / "fixtures/postestimation/lmm_v1811"
DATA = {
    "random_intercept": Path(__file__).parent / "fixtures/admission/linear_mixed_effects/data.csv",
    "random_slope": FIXTURE / "random_slope.csv",
}
REL = json.loads((FIXTURE.parent / "oracle.json").read_text())["tolerances"]["default"]
R = json.loads((FIXTURE / "gls_reference_r.json").read_text())
STATA = json.loads((FIXTURE / "gls_reference_stata.json").read_text())
SETTINGS = ["random_intercept_reml", "random_intercept_ml", "random_slope_reml", "random_slope_ml"]
JOINT = [{"terms": {"time": 1}, "value": 0}, {"terms": {"x": 1}, "value": 0}]
SHIFTED = [{"terms": {"time": 1, "x": -1}, "value": 1}]
# Workbench term -> native term, by position in the owner order.
NATIVE = ["(Intercept)", "armb", "time", "armb:time", "x"]


def _fit(setting):
    design, method = setting.rsplit("_", 1)
    prepared = prepare_lmm_input(pd.read_csv(DATA[design]), outcome="y", controls=["x"], options={
        "subject_id": "g", "time": "time", "group": "arm", "fit_method": method,
        "random_slope": design == "random_slope"})
    fitted = _fit_prepared(prepared)
    ctx = SimpleNamespace(artifacts={})
    _record_fixed_effects_kernel(ctx, fitted)
    return fitted, ctx.artifacts["_inference_kernels"]["linear_mixed_effects_1"]


@pytest.fixture(scope="module")
def fits():
    return {setting: _fit(setting) for setting in SETTINGS}


@pytest.mark.parametrize("setting", SETTINGS)
def test_native_references_agree_with_each_other(setting):
    r, s = R[setting], STATA[setting]
    assert r["converged"] and not r["singular"] and s["converged"]
    assert s["loglik"] == pytest.approx(r["loglik"], rel=1e-9)
    for term in NATIVE:
        assert s["std_error"][term] == pytest.approx(r["std_error"][term], rel=REL)


@pytest.mark.parametrize("setting", SETTINGS)
def test_fit_reaches_the_native_optimum(fits, setting):
    fitted, kernel = fits[setting]
    assert fitted.converged
    assert fitted.llf == pytest.approx(R[setting]["loglik"], rel=0, abs=1e-8)
    for i, term in enumerate(NATIVE):
        assert kernel["params"][i] == pytest.approx(R[setting]["params"][term], rel=0, abs=1e-7)


@pytest.mark.parametrize("setting", SETTINGS)
def test_fixed_effect_covariance_matches_lme4_and_stata(fits, setting):
    fitted, kernel = fits[setting]
    order = [R[setting]["terms"].index(term) for term in NATIVE]
    native = np.array(R[setting]["covariance"])[np.ix_(order, order)]
    np.testing.assert_allclose(np.array(kernel["vcov"]), native, rtol=REL, atol=0)
    assert kernel["covariance_estimator"] == "lmm_gls_conditional"
    for i, term in enumerate(NATIVE):
        assert fitted.bse.iloc[i] == pytest.approx(STATA[setting]["std_error"][term], rel=REL)


@pytest.mark.parametrize("setting", SETTINGS)
def test_postestimation_matches_lme4_and_stata(fits, setting):
    _, kernel = fits[setting]
    actual = {
        "wald_joint": wald_test(kernel, JOINT), "wald_shifted": wald_test(kernel, SHIFTED),
        "lincom": lincom(kernel, {"time": 1, "x": 2}, constant=-.5), "nlcom": nlcom(kernel, "time/x"),
    }
    for case, result in actual.items():
        for native in (R[setting][case], STATA[setting][case]):
            for key in ("statistic", "estimate", "std_error"):
                if key in native:
                    assert result[key] == pytest.approx(native[key], rel=REL), (case, key)
        if "p_value" in R[setting][case]:
            assert result["p_value"] == pytest.approx(R[setting][case]["p_value"], rel=1e-5)
        assert result.get("distribution") in ("chi2", "z")


def test_the_earlier_inverse_hessian_definition_was_the_gap(fits):
    # Kept as evidence for estimator v2: statsmodels' own covariance misses
    # lme4 by ~2e-5 on the random intercept and ~1e-3 on the random slope.
    for setting, floor in (("random_intercept_reml", 1e-5), ("random_slope_reml", 5e-4)):
        fitted, _ = fits[setting]
        hessian = np.sqrt(np.diag(np.asarray(fitted._fitted.cov_params(), dtype=float)))[:5]
        native = np.array([R[setting]["std_error"][term] for term in NATIVE])
        assert np.max(np.abs(hessian - native) / native) > floor


@pytest.mark.parametrize("operation", ["wald", "lincom", "nlcom"])
def test_validated_operations_are_offered(operation):
    require_validated("linear_mixed_effects", operation)


@pytest.mark.parametrize("operation", ["lr", "margins"])
def test_unvalidated_operations_stay_refused(operation):
    with pytest.raises(PostestimationRefusal) as caught:
        require_validated("linear_mixed_effects", operation)
    assert caught.value.code == "NOT_YET_VALIDATED"


def test_reml_offers_no_likelihood_and_says_why(fits):
    _, kernel = fits["random_intercept_reml"]
    assert "loglik" not in kernel["interfaces"] and kernel["unavailable"]["loglik"] == REML_LIKELIHOOD_REASON
    with pytest.raises(PostestimationRefusal) as caught:
        lr_test(kernel, kernel)
    assert caught.value.code == "INTERFACE_UNAVAILABLE" and "refit both models with ML" in caught.value.message
    with pytest.raises(PostestimationRefusal) as caught:
        run_operation("lr", [kernel, kernel], {})
    assert "refit both models with ML" in caught.value.message


def test_ml_keeps_its_likelihood(fits):
    fitted, kernel = fits["random_intercept_ml"]
    assert "loglik" in kernel["interfaces"] and kernel["loglik"] == pytest.approx(fitted.llf)


def test_a_fit_that_did_not_complete_offers_no_postestimation():
    # A non-converged or diagnostically failed LMM has no tested estimates; its
    # kernel must say so instead of exposing them to Wald/lincom/nlcom.
    fitted, _ = _fit("random_intercept_reml")
    ctx = SimpleNamespace(artifacts={})
    _record_fixed_effects_kernel(ctx, fitted, result_status="failed")
    kernel = ctx.artifacts["_inference_kernels"]["linear_mixed_effects_1"]
    assert kernel["vcov_scope"] == "unavailable" and "coef_vcov" not in kernel["interfaces"]
    with pytest.raises(PostestimationRefusal) as caught:
        run_operation("wald", [kernel], {"constraints": JOINT})
    assert caught.value.code == "INTERFACE_UNAVAILABLE" and "did not complete" in caught.value.message
