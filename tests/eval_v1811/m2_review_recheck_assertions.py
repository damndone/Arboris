"""Independent remediation certification and raw support regression checks."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics import count_models
from workbench.econometrics.runner import run_negative_binomial, run_glm

ROOT=Path(__file__).resolve().parents[2]
E=json.loads(Path(__file__).with_name("m2_review_recheck_evidence.json").read_text())


@pytest.mark.parametrize("name,index",[("nb2",0),("nb1",1)])
def test_published_joint_inference_has_native_r_stationarity_and_regular_oim(name,index):
    wb=E["points"][name];native=E["r"]["joint"][index]
    assert wb["returned"] and wb["strict_json"]
    assert wb["convergence"]["tolerance"]==count_models.ML_TOLERANCE==1e-8
    assert max(abs(s) for s in wb["score"])/wb["n"]<=1e-8
    assert native["max_score_per_observation"]<=1e-8
    np.testing.assert_allclose(wb["score"],native["score"],rtol=0,atol=1e-8)
    assert abs(wb["ll"]-native["ll"])<1e-8
    H=np.asarray(wb["information"]);V=np.asarray(wb["covariance"])
    assert np.isfinite(H).all() and np.isfinite(V).all()
    np.testing.assert_allclose(H,H.T,rtol=0,atol=1e-10)
    np.testing.assert_allclose(V,V.T,rtol=0,atol=1e-12)
    np.linalg.cholesky(H);np.linalg.cholesky(V)
    assert wb["inverse_residual"]<1e-10
    np.testing.assert_allclose(np.sqrt(np.diag(V)),np.sqrt(np.diag(native["covariance"])),rtol=1e-4,atol=0)


def test_fractional_fixed_nb_remains_native_stata_oim_and_r_glm_eim():
    fixed=E["points"]["fractional_fixed"];glm=E["points"]["fractional_glm"]
    stata=E["stata"];native=E["r"]["fractional"]
    for row in [fixed,glm]:
        assert row["returned"] and row["strict_json"] and not row["alpha_estimated"]
        assert row["ancillary"]==[]
    np.testing.assert_allclose(fixed["params"],[stata[f"b_{t}"] for t in ["_cons","x1","x2"]],rtol=0,atol=1e-6)
    np.testing.assert_allclose(fixed["se"],[stata[f"se_{t}"] for t in ["_cons","x1","x2"]],rtol=1e-4,atol=0)
    np.testing.assert_allclose(glm["params"],native["beta"],rtol=0,atol=1e-8)
    np.testing.assert_allclose(glm["se"],native["se"],rtol=1e-6,atol=0)
    assert fixed["information_matrix"]=="observed" and glm["information_matrix"]=="expected"
    assert abs(fixed["ll"]-stata["ll"])<1e-8
    assert not E["points"]["fractional_joint"]["returned"]
    assert "NB_COUNTS_INVALID" in E["points"]["fractional_joint"]["message"]


@pytest.mark.parametrize("term",[0,-1])
def test_all_natural_coordinates_are_checked_against_original_mean_score_tolerance(monkeypatch,term):
    original=count_models.smf.negativebinomial
    def altered(**kwargs):
        model=original(**kwargs);original_fit=model.fit
        def fit(**options):
            fitted=original_fit(**options)
            score=np.zeros(len(fitted.params));score[term]=2e-8*len(model.endog)
            model.score=lambda *args,**kw:score
            return fitted
        model.fit=fit
        return model
    monkeypatch.setattr(count_models.smf,"negativebinomial",altered)
    d=pd.read_csv(ROOT/"tests/fixtures/count_models/reference-v3/nb2.csv")
    with pytest.raises(ValueError,match="NB_INFERENCE_UNCERTIFIED"):
        run_negative_binomial(d,"y",["x1","x2"],"uncertified")


@pytest.mark.parametrize("information",[np.diag([1.,0.]),np.diag([1.,-1.]),np.diag([1.,np.inf])])
def test_nonregular_information_is_explicitly_unavailable(information):
    with pytest.raises(ValueError,match="NB_INFERENCE_UNCERTIFIED"):
        count_models._information_covariance(information,"NB_INFERENCE_UNCERTIFIED")


def test_nonfinite_inverse_is_rejected_after_positive_information(monkeypatch):
    monkeypatch.setattr(count_models.np.linalg,"inv",lambda matrix:np.full(matrix.shape,np.inf))
    with pytest.raises(ValueError,match="NB_INFERENCE_UNCERTIFIED"):
        count_models._information_covariance(np.eye(2),"NB_INFERENCE_UNCERTIFIED")


def test_nonpositive_inverse_is_rejected_after_positive_information(monkeypatch):
    monkeypatch.setattr(count_models.np.linalg,"inv",lambda matrix:-np.eye(len(matrix)))
    with pytest.raises(ValueError,match="NB_INFERENCE_UNCERTIFIED"):
        count_models._information_covariance(np.eye(2),"NB_INFERENCE_UNCERTIFIED")


@pytest.mark.parametrize("family,alpha",[("negative_binomial",.5),("poisson",None)])
@pytest.mark.parametrize("response",[-1.,np.inf,-np.inf])
def test_glm_invalid_support_is_rejected_before_smf_construction(monkeypatch,family,alpha,response):
    d=pd.read_csv(ROOT/"tests/fixtures/count_models/reference-v3/nb2.csv").astype({"y":float})
    d.loc[0,"y"]=response
    monkeypatch.setattr(count_models.smf,"glm",lambda **kwargs:pytest.fail("Illegal response reached GLM construction"))
    with pytest.raises(ValueError,match="GLM_RESPONSE_INVALID"):
        run_glm(d,"y",["x1","x2"],"invalid",family,alpha=alpha)


def test_normalized_nonfinite_packet_is_rejected_after_valid_fit(monkeypatch):
    normalize=count_models.normalize_statsmodels_result
    def poison(fitted,model_id):
        packet=normalize(fitted,model_id);packet["review_probe"]=np.inf
        return packet
    monkeypatch.setattr(count_models,"normalize_statsmodels_result",poison)
    d=pd.read_csv(ROOT/"tests/fixtures/count_models/reference-v3/nb2.csv")
    with pytest.raises(ValueError,match="GLM_RESULT_NONFINITE"):
        run_glm(d,"y",["x1","x2"],"invalid","negative_binomial",alpha=.5)
