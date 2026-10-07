"""Independent two-endogenous IV review, with native wrong-convention controls."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np
import pytest
from scipy import stats

from workbench.postestimation import PostestimationRefusal
from workbench.postestimation.registry import run_operation

ROOT=Path(__file__).resolve().parents[2]
AUTHOR=ROOT/"tests/fixtures/postestimation/iv_two_endogenous_v1811"
EVIDENCE=Path(__file__).with_name("iv_two_endogenous_independent_evidence")
BASELINE="01fb0752bce129c8d8848c021eca776dadccb515"
CANDIDATE="0a612419536a02fbba287e79114b6fab36dc025d"
REL=json.loads((AUTHOR.parent/"oracle.json").read_text())["tolerances"]["default"]
HEADER=re.compile(rb"(?m)^([ \t]*)(Serial number:|Licensed to:)([^\r\n]*)(\r?\n|$)")

def read(path):
    return json.loads(path.read_text())

@pytest.fixture(scope="module")
def evidence():
    return read(EVIDENCE/"r_moment_reference.json"),read(EVIDENCE/"stata_reference.json"),read(EVIDENCE/"owner.json")

def test_candidate_scope_and_nine_protected_assets():
    protected=read(AUTHOR/"protected_assets_before.json")
    assert protected==read(AUTHOR/"protected_assets_after.json")
    assert len(protected)==9
    for name,digest in protected.items():
        data=(ROOT/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==digest
        assert data==subprocess.run(["git","show",f"{BASELINE}:{name}"],check=True,capture_output=True).stdout
    changed=subprocess.run(["git","diff","--name-only",BASELINE,CANDIDATE],check=True,capture_output=True,text=True).stdout.splitlines()
    for name in changed:
        assert name.startswith("tests/fixtures/postestimation/iv_two_endogenous_v1811/") or name in {
            "tests/test_iv_two_endogenous_v1811_reference.py","docs/superpowers/handoffs/2026-10-04-v1.8.11-iv-two-endogenous-oracle-report.md"}
        assert (ROOT/name).read_bytes()==subprocess.run(["git","show",f"{CANDIDATE}:{name}"],check=True,capture_output=True).stdout

def test_author_log_only_license_values_changed_and_raw_is_ignored():
    record=read(AUTHOR/"license_header_protection.json")
    raw=(ROOT/record["raw_ignored_log"]).read_bytes()
    log=(ROOT/record["tracked_log"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==record["raw_sha256"]
    assert hashlib.sha256(log).hexdigest()==record["redacted_sha256"]
    assert log==HEADER.sub(lambda m:m.group(1)+m.group(2)+b" [REDACTED]"+m.group(4),raw)
    assert len(HEADER.findall(raw))==2
    subprocess.run(["git","check-ignore","--quiet",record["raw_ignored_log"]],check=True,cwd=ROOT)
    changed=[i+1 for i,(a,b) in enumerate(zip(raw.splitlines(),log.splitlines())) if a!=b]
    assert changed==record["changed_header_lines"]==[14,15]

def test_all_candidate_added_text_has_no_original_sensitive_header_values():
    protection=read(AUTHOR/"license_header_protection.json")
    raw=(ROOT/protection["raw_ignored_log"]).read_bytes()
    values=[m[2].strip() for m in HEADER.findall(raw)]
    added=subprocess.run(["git","diff","--name-only","--diff-filter=A",BASELINE,CANDIDATE],check=True,capture_output=True,text=True).stdout.splitlines()
    for name in added:
        data=(ROOT/name).read_bytes()
        assert not any(value and value in data for value in values),name
        assert all(m[2].strip()==b"[REDACTED]" for m in HEADER.findall(data)),name

def test_real_dgp_and_excluded_identification(evidence):
    r,_,_=evidence
    source=hashlib.sha256((AUTHOR/"data.csv").read_bytes()).hexdigest()
    assert r["source_sha256"]==read(AUTHOR/"provenance.json")["data_sha256"]==source
    assert r["nobs"]==650 and r["nominal_residual_df"]==646
    d=r["diagnostics"]
    assert d["X_rank"]==d["Z_rank"]==4
    assert d["conditional_instrument_rank"]==2
    assert all(abs(c)>.1 for c in d["corr_endogenous_structural_error"])
    assert d["moment_max_abs"]<1e-12
    exact=read(EVIDENCE/"reconstructed_exact.json")
    assert exact["byte_identical"] is True
    assert exact["source_sha256"]==exact["reconstructed_sha256"]==source
    assert r["inference"]==dict(HC0=True,unbiased=False,debiased=False,small_sample_factor=1,reference_distribution="z")

@pytest.mark.parametrize("software",["r","stata"])
def test_fresh_moment_solve_matches_all_author_coefficients_and_covariance(evidence,software):
    r,_,_=evidence; author=read(AUTHOR/f"{software}_reference.json")
    assert r["terms"]==author["terms"]==["Intercept","x1","xe1","xe2"]
    np.testing.assert_allclose(r["covariance"],author["covariance"],rtol=REL,atol=0)
    for term in r["terms"]:
        assert r["params"][term]==pytest.approx(author["params"][term],rel=0,abs=1e-8)
        assert r["std_error"][term]==pytest.approx(author["std_error"][term],rel=0,abs=1e-6)
        assert r["z"][term]==pytest.approx(author["z"][term],rel=REL,abs=0)
        assert r["p"][term]==pytest.approx(author["p"][term],rel=1e-5,abs=0)
    assert r["wald_joint"]["statistic"]==pytest.approx(author["wald_joint"]["statistic"],rel=REL,abs=0)
    assert r["wald_joint"]["p_value"]==pytest.approx(author["wald_joint"]["p_value"],rel=1e-5,abs=0)

def test_fresh_native_stata_declares_two_endogenous_two_excluded_no_small(evidence):
    _,s,_=evidence; v=s["values"]
    assert v["endogenous"].split()==["xe1","xe2"]
    assert set(v["exogenous_and_instruments"].split())=={"x1","z1","z2"}
    assert v["exogenous_regressors"].split()==["x1"]
    assert v["small_option"]=="" and v["vce"]=="robust"
    assert v["nobs"]==650 and v["nominal_residual_df"]==646
    assert v["wald_df"]==2

def test_fresh_native_stata_covariance_and_wald_matches_moment_solve(evidence):
    r,s,_=evidence; v=s["values"]
    covariance=[[v[f"cov_{a}_{b}"] for b in r["terms"]] for a in r["terms"]]
    np.testing.assert_allclose(covariance,r["covariance"],rtol=REL,atol=0)
    for term in r["terms"]:
        assert v[f"b_{term}"]==pytest.approx(r["params"][term],rel=0,abs=1e-8)
        assert v[f"se_{term}"]==pytest.approx(r["std_error"][term],rel=0,abs=1e-6)
        assert v[f"p_{term}"]==pytest.approx(r["p"][term],rel=1e-5,abs=0)
    assert v["wald_statistic"]==pytest.approx(r["wald_joint"]["statistic"],rel=REL,abs=0)
    assert v["wald_p"]==pytest.approx(r["wald_joint"]["p_value"],rel=1e-5,abs=0)

def test_native_small_control_is_detectably_different(evidence):
    r,s,_=evidence; v=s["values"]; factor=650/646
    assert v["control_small_option"]=="small"
    assert v["control_df_resid"]==v["control_wald_df_den"]==646
    for term in r["terms"]:
        assert (v[f"control_se_{term}"]/v[f"se_{term}"])**2==pytest.approx(factor,rel=1e-12)
        assert abs(v[f"control_se_{term}"]-v[f"se_{term}"])>1e-6
    assert v["control_wald_F"]==pytest.approx(v["wald_statistic"]/2/factor,rel=1e-12)
    assert v["control_wald_p"]==pytest.approx(stats.f.sf(v["control_wald_F"],2,646),rel=1e-5,abs=0)
    assert abs(v["control_wald_p"]/v["wald_p"]-1)>.01

def test_actual_public_owner_metadata_and_complete_kernel(evidence):
    r,_,o=evidence; k=o["kernel"]
    assert k["param_names"]==r["terms"]
    assert k["nobs"]==650 and k["df_resid"]==646
    assert k["reference_distribution"]=="z" and k["df_method"]=="asymptotic"
    assert k["covariance_estimator"]=="robust"
    assert json.loads(o["run_inputs"]["form"]["iv_endog"])==["xe1","xe2"]
    assert json.loads(o["run_inputs"]["form"]["iv_instruments"])==["z1","z2"]
    assert o["run_inputs"]["contract_summary"]["x"]==["x1"]
    np.testing.assert_allclose(k["vcov"],r["covariance"],rtol=REL,atol=0)
    for i,term in enumerate(k["param_names"]):
        assert k["params"][i]==pytest.approx(r["params"][term],rel=0,abs=1e-8)
        assert np.sqrt(k["vcov"][i][i])==pytest.approx(r["std_error"][term],rel=0,abs=1e-6)
        z=k["params"][i]/np.sqrt(k["vcov"][i][i])
        assert 2*stats.norm.sf(abs(z))==pytest.approx(r["p"][term],rel=1e-5,abs=0)

def test_actual_public_joint_wald_final_stat_df_p(evidence):
    r,_,o=evidence
    spec={"constraints":[{"terms":{"xe1":1},"value":0},{"terms":{"xe2":1},"value":0}]}
    w=run_operation("wald",[o["kernel"]],spec)
    assert w==o["wald"]
    assert w["distribution"]=="chi2" and w["df_num"]==2 and w["df_den"] is None
    assert w["constraints"]==spec["constraints"]
    assert w["statistic"]==pytest.approx(r["wald_joint"]["statistic"],rel=REL,abs=0)
    assert w["p_value"]==pytest.approx(r["wald_joint"]["p_value"],rel=1e-5,abs=0)

def test_public_lr_refusal_is_explicit(evidence):
    _,_,o=evidence
    with pytest.raises(PostestimationRefusal) as caught:
        run_operation("lr",[o["kernel"],o["kernel"]],{})
    assert caught.value.code=="INTERFACE_UNAVAILABLE"

def test_primary_rounding_is_distinct_from_exact_kernel_postestimation(evidence):
    r,_,o=evidence; rows=o["primary"]["coefficients"]
    for term in r["terms"]:
        assert rows[term]["p_value"]==round(r["p"][term],6)
    assert rows["xe1"]["p_value"]==0.0 and r["p"]["xe1"]>0
    assert rows["xe2"]["p_value"]==1e-6
    assert o["wald"]["p_value"]>0 and o["wald"]["p_value"]<1e-10

def test_wrong_coefficient_target_has_a_different_wald(evidence):
    _,_,o=evidence
    wrong={"constraints":[{"terms":{"x1":1},"value":0},{"terms":{"xe1":1},"value":0}]}
    w=run_operation("wald",[o["kernel"]],wrong)
    assert abs(w["statistic"]-o["wald"]["statistic"])>1

def test_review_native_log_also_preserves_private_original_without_sensitive_values(evidence):
    _,s,_=evidence; record=s["redaction"]
    raw=(ROOT/record["raw_ignored_path"]).read_bytes(); red=(EVIDENCE/"stata.log").read_bytes()
    assert hashlib.sha256(raw).hexdigest()==record["raw_sha256"]
    assert hashlib.sha256(red).hexdigest()==record["redacted_sha256"]
    assert red==HEADER.sub(lambda m:m.group(1)+m.group(2)+b" [REDACTED]"+m.group(4),raw)
    subprocess.run(["git","check-ignore","--quiet",record["raw_ignored_path"]],check=True,cwd=ROOT)

def test_native_owner_and_author_evidence_are_strict_finite_json(evidence):
    for entry in evidence:
        json.dumps(entry,allow_nan=False)
    for software in ["r","stata"]:
        json.dumps(read(AUTHOR/f"{software}_reference.json"),allow_nan=False)
    assert np.linalg.eigvalsh(evidence[0]["covariance"]).min()>0
