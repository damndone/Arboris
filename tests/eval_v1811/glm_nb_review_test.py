"""Independent assertions on fresh real R, Stata, and persisted owner evidence."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).with_name("glm_nb_review_evidence_final")
ASSET = ROOT / "tests/fixtures/postestimation/glm_negative_binomial_v1811"

def read(path):
    return json.loads(path.read_text())

R = read(EVIDENCE / "r-reference.json")
STATA = read(EVIDENCE / "stata-reference.json")
OWNER = read(EVIDENCE / "owner.json")

def close(actual, expected, *, rel=1e-6, absolute=0):
    assert abs(actual-expected) <= max(absolute, rel*abs(expected)), (actual,expected)

def test_all_producer_hashes_and_original_bytes_are_verified():
    p = read(Path(__file__).with_name("glm_nb_review_protected.json"))
    assert p["asset_hashes_verified"] == 24 and not p["asset_errors"]
    assert len(p["protected"]) == 9
    assert all(x["baseline_identical"] and x["manifest_hash_matches"] for x in p["protected"])
    assert p["all_changes_are_additions"] and len(p["changes"]) == 26

def test_epsilon_convergence_is_supported_by_score_and_separate_likelihood():
    sequence = R["epsilon_sequence"]
    assert [s["epsilon"] for s in sequence] == [1e-8,1e-12,1e-14,1e-16]
    assert all(s["converged"] for s in sequence)
    assert all(sequence[i+1]["score_max"] < sequence[i]["score_max"] for i in range(3))
    assert sequence[-1]["score_max"] < 1e-11
    assert R["restricted"]["score_max"] < 1e-11
    assert R["bfgs"]["convergence"] == 0
    assert R["polished_likelihood"]["score_max"] < 1e-11
    np.testing.assert_allclose(R["polished_likelihood"]["params"],R["full"]["beta"],rtol=0,atol=1e-12)
    close(R["polished_likelihood"]["ll"],R["full"]["ll"],rel=0,absolute=1e-12)
    # Ordinary R deviance stopping at 1e-8 leaves coefficients above the frozen owner threshold.
    assert max(abs(np.array(sequence[0]["beta"])-np.array(sequence[-1]["beta"]))) > 1e-8

def test_scale_one_is_unscaled_final_eim_not_default_pearson_dispersion():
    d = pd.read_csv(ASSET.parent / "data.csv",float_precision="round_trip")
    X = np.column_stack([np.ones(len(d)),d[["x1","x2","x3"]]])
    b = np.array(R["full"]["beta"]); mu = np.exp(X@b)
    expected = np.linalg.inv(X.T@(X*(mu/(1+mu))[:,None]))
    np.testing.assert_allclose(R["full"]["covariance"],expected,rtol=1e-12,atol=0)
    assert R["full"]["covariance_scale"] == 1
    assert abs(R["full"]["native_summary_dispersion"]-1) > .1
    v = np.array([[STATA[f"cov_{i}_{j}"] for j in range(1,5)] for i in range(1,5)])
    order = [3,0,1,2]
    np.testing.assert_allclose(v[np.ix_(order,order)],expected,rtol=1e-12,atol=0)
    np.linalg.cholesky(expected)

def test_fresh_stata_native_outputs_reproduce_all_retained_numbers():
    frozen = read(ASSET / "native-stata-v3/reference.json")
    assert len(frozen) == 34
    for key, value in frozen.items():
        close(STATA[key],value,rel=0,absolute=1e-12)

def test_fresh_r_native_outputs_reproduce_retained_reference():
    frozen = read(ASSET / "native-r/oracle.json")
    np.testing.assert_allclose(R["full"]["covariance"],frozen["covariance"],rtol=1e-12,atol=0)
    for term, value in frozen["full_precision"]["params"].items():
        key="_cons" if term=="(Intercept)" else term
        close(R["values"]["b_"+key],float(value),rel=0,absolute=1e-12)
    for case, prefix in [("wald_joint","wj"),("wald_shifted","ws"),("lr_drop_x2_x3","lr")]:
        close(R["values"][prefix+"_stat"],float(frozen["full_precision"][case]["statistic"]),rel=1e-12)
        close(R["values"][prefix+"_p"],float(frozen["full_precision"][case]["p_value"]),rel=1e-12)
    for case, prefix in [("lincom","lc"),("nlcom","nl")]:
        for field,key in [("estimate","est"),("std_error","se")]:
            close(R["values"][prefix+"_"+key],float(frozen["full_precision"][case][field]),rel=1e-12)
    for case,prefix in [("average","ma"),("at_means","mm")]:
        for term in ["x1","x2"]:
            for field,key in [("estimate","est"),("std_error","se")]:
                close(R["values"][f"{prefix}_{term}_{key}"],float(frozen["full_precision"]["margins"][case][term][field]),rel=1e-12)

@pytest.mark.parametrize("reference",[R["values"],STATA],ids=["real_R","real_Stata"])
def test_fresh_persisted_owner_matches_native_full_final_inference(reference):
    k = OWNER["kernels"]["full"]
    assert OWNER["outcomes"] == {"full":"completed","restricted":"completed"}
    assert k["param_names"] == ["Intercept","x1","x2","x3"]
    assert k["nobs"] == 300 and k["df_resid"] == 296
    assert k["reference_distribution"] == "z" and k["covariance_estimator"] == "nonrobust"
    for i,term in enumerate(["_cons","x1","x2","x3"]):
        close(k["params"][i],reference["b_"+term],rel=0,absolute=1e-8)
        close(np.sqrt(k["vcov"][i][i]),reference["se_"+term],rel=0,absolute=1e-6)
    close(k["loglik"],reference["ll_full"])
    for prefix in ["wj","ws","lr"]:
        close(OWNER[prefix]["statistic"],reference[prefix+"_stat"])
        close(OWNER[prefix]["p_value"],reference[prefix+"_p"],rel=1e-5,absolute=0)
    for prefix in ["lc","nl"]:
        close(OWNER[prefix]["estimate"],reference[prefix+"_est"])
        close(OWNER[prefix]["std_error"],reference[prefix+"_se"])
    assert OWNER["wj"]["df_num"] == reference["wj_df"] == 2
    assert OWNER["ws"]["df_num"] == reference["ws_df"] == 1
    assert OWNER["lr"]["df"] == reference["lr_df"] == 2
    for prefix in ["ma","mm"]:
        for effect in OWNER["margins"][prefix]["effects"]:
            term = effect["variable"]
            close(effect["estimate"],reference[f"{prefix}_{term}_est"])
            close(effect["std_error"],reference[f"{prefix}_{term}_se"],rel=1e-5)

def test_native_margins_and_owner_are_independently_supported_by_analytic_gradient():
    for key,value in R["analytic_margins"].items():
        close(R["values"][key],value,rel=0,absolute=1e-8)
        close(STATA[key],value,rel=0,absolute=1e-8)
    np.testing.assert_allclose(OWNER["kernels"]["full"]["vcov"],R["full"]["covariance"],rtol=1e-12,atol=0)
