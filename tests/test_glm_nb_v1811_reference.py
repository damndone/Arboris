"""Native fixed-alpha NB GLM evidence, without changing consumer admission."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.econometrics.runner import run_glm
from workbench.orchestrator import run_workflow
from workbench.postestimation import lincom, lr_test, nlcom, wald_test
from workbench.postestimation.estimation_data import estimation_design
from workbench.postestimation.margins import marginal_effects
from workbench.projects import create_project

FIXTURE = Path(__file__).parent / "fixtures/postestimation/glm_negative_binomial_v1811"
INPUT = FIXTURE.parent / "data.csv"
CASES = {"wald_joint", "wald_shifted", "lincom", "nlcom", "lr_drop_x2_x3", "margins"}
JOINT = [{"terms":{"x1":1},"value":0},{"terms":{"x2":1},"value":0}]
SHIFTED = [{"terms":{"x1":1,"x2":-1},"value":1}]


def load_oracle():
    path = FIXTURE / "native-r/oracle.json"
    assert path.exists(), "Frozen fixed-alpha GLM-NB native five-operation reference is missing"
    return json.loads(path.read_text())


def test_native_reference_exists_and_has_all_five_operation_shapes():
    reference = load_oracle()
    assert CASES <= reference.keys()
    assert reference["meta"]["source_sha256"] == hashlib.sha256(INPUT.read_bytes()).hexdigest()
    assert reference["meta"]["alpha_fixed"] == 1
    assert reference["meta"]["scale"] == 1
    assert reference["meta"]["epsilon"] == 1e-16
    assert reference["meta"]["information_matrix"] == "expected"
    assert set(reference["params"]) == {"(Intercept)","x1","x2","x3"}
    assert set(reference["margins"]) == {"average","at_means"}
    assert reference["native_diagnostics"]["full"]["converged"] is True
    assert reference["native_diagnostics"]["restricted"]["converged"] is True
    json.dumps(reference, allow_nan=False)


def test_native_log_redaction_preserves_all_non_header_bytes():
    manifest=json.loads((FIXTURE / "manifest.json").read_text())
    assert "log_redaction" in manifest, "Native license headers need documented preservation and redaction"
    records=manifest["log_redaction"]["files"]
    assert len(records) == 4
    header=re.compile(rb"(?m)^[ \t]*(?:Serial number:|Licensed to:)[^\r\n]*(?:\r?\n|$)")
    for name,record in records.items():
        log=(FIXTURE / name).read_bytes()
        assert hashlib.sha256(log).hexdigest() == record["redacted_sha256"]
        assert len(header.findall(log)) == 2
        assert all(line.rstrip().endswith(b"[REDACTED]") for line in header.findall(log))
        assert hashlib.sha256(header.sub(b"",log)).hexdigest() == record["non_header_payload_sha256"]
        assert record["raw_copy_ignored"] is True
        assert record["raw_copy_byte_identical"] is True
        assert record["changed_line_numbers"] in [[14,15],[185,186]]


@pytest.fixture(scope="module")
def oracle():
    return load_oracle()


def collect_owner_results(project_root):
    kernels = {}; roots = {}
    for label, columns in [("full",["x1","x2","x3"]),("restricted",["x1"])]:
        project = create_project(project_root,label)
        outcome = run_workflow(project.root,[INPUT],mode="auto",model_type="glm:negative_binomial",
                               y="ynb",x=columns,model_options={"alpha":1.0})
        root = project.root / "runs" / outcome["run_id"]
        assert outcome["status"] == "completed", read_json(root / "errors.json")
        kernels[label] = read_json(root / kernel_relative_path("glm_1"))
        roots[label] = root
    design = estimation_design(roots["full"],kernels["full"])
    frame = pd.read_csv(INPUT,float_precision="round_trip")
    packet,fitted = run_glm(frame,"ynb",["x1","x2","x3"],"direct_owner","negative_binomial",alpha=1)
    full=kernels["full"]
    return {"full_kernel":full,"restricted_kernel":kernels["restricted"],
            "run_roots":{label:str(root) for label,root in roots.items()},
            "packet":packet,"direct_fit_params":np.asarray(fitted.params).tolist(),
            "direct_fit_vcov":np.asarray(fitted.cov_params()).tolist(),
            "direct_score":fitted.model.score(fitted.params).tolist(),
            "expected_information":(-fitted.model.hessian(fitted.params,observed=False)).tolist(),
            "wald_joint":wald_test(full,JOINT),"wald_shifted":wald_test(full,SHIFTED),
            "lincom":lincom(full,{"x1":1,"x2":2},constant=-.5),"nlcom":nlcom(full,"x1/x2"),
            "lr_drop_x2_x3":lr_test(full,kernels["restricted"]),
            "margins":{key:marginal_effects(full,design,inverse_link="log",variables=["x1","x2"],at=at)
                       for key,at in [("average","average"),("at_means","means")]}}


@pytest.fixture(scope="module")
def owner(oracle,tmp_path_factory):
    return collect_owner_results(tmp_path_factory.mktemp("glm-nb-owner-reference"))


def test_actual_owner_coefficient_kernel_matches_final_native_eim(owner,oracle):
    kernel=owner["full_kernel"]
    assert kernel["model_type"] == "glm:negative_binomial"
    assert kernel["param_names"] == ["Intercept","x1","x2","x3"]
    assert kernel["nobs"] == oracle["nobs"] == 300
    assert kernel["df_resid"] == 296
    assert kernel["reference_distribution"] == "z"
    assert kernel["covariance_estimator"] == "nonrobust"
    for i,term in enumerate(kernel["param_names"]):
        name="(Intercept)" if term == "Intercept" else term
        assert abs(kernel["params"][i]-float(oracle["full_precision"]["params"][name])) <= 1e-8
        assert abs(np.sqrt(kernel["vcov"][i][i])-float(oracle["full_precision"]["std_error"][name])) <= 1e-6
    # Independent CSV readers can differ in the last binary digit.
    np.testing.assert_allclose(kernel["vcov"],owner["direct_fit_vcov"],rtol=1e-12,atol=0)
    np.testing.assert_allclose(owner["direct_fit_vcov"],np.linalg.inv(owner["expected_information"]),rtol=1e-12)
    assert owner["packet"]["alpha_estimated"] is False
    assert owner["packet"]["alpha_fixed_value"] == 1
    assert owner["packet"]["ancillary_parameters"] == []
    assert owner["packet"]["overdispersion_test"] is None


@pytest.mark.parametrize("case",["wald_joint","wald_shifted","lincom","nlcom","lr_drop_x2_x3"])
def test_owner_postestimation_primitives_match_original_tolerances(owner,oracle,case):
    result=owner[case]; reference=oracle[case]
    for key in ["statistic","estimate","std_error","loglik_full","loglik_restricted"]:
        if key in reference:
            assert result[key] == pytest.approx(float(oracle["full_precision"][case][key]),rel=1e-6),key
    if "p_value" in reference:
        assert result["p_value"] == pytest.approx(float(oracle["full_precision"][case]["p_value"]),rel=1e-5)
    for key in ["df_num","df_den","df","distribution"]:
        if key in reference:
            assert result[key] == reference[key]


@pytest.mark.parametrize("at",["average","at_means"])
def test_owner_margins_matches_native_average_and_at_means(owner,oracle,at):
    for effect in owner["margins"][at]["effects"]:
        reference=oracle["full_precision"]["margins"][at][effect["variable"]]
        assert effect["estimate"] == pytest.approx(float(reference["estimate"]),rel=1e-6)
        assert effect["std_error"] == pytest.approx(float(reference["std_error"]),rel=1e-5)


def test_owner_matches_independent_stata_fixed_alpha_eim(owner):
    reference=json.loads((FIXTURE / "native-stata-v3/reference.json").read_text())
    assert reference["converged"] == 1
    for i,term in enumerate(owner["full_kernel"]["param_names"]):
        name="_cons" if term == "Intercept" else term
        assert owner["full_kernel"]["params"][i] == pytest.approx(reference[f"b_{name}"],rel=0,abs=1e-8)
        assert np.sqrt(owner["full_kernel"]["vcov"][i][i]) == pytest.approx(reference[f"se_{name}"],rel=0,abs=1e-6)
    for case,prefix in [("wald_joint","wj"),("wald_shifted","ws"),("lr_drop_x2_x3","lr")]:
        assert owner[case]["statistic"] == pytest.approx(reference[f"{prefix}_stat"],rel=1e-6)
        assert owner[case]["p_value"] == pytest.approx(reference[f"{prefix}_p"],rel=1e-5)
    for case,prefix in [("lincom","lc"),("nlcom","nl")]:
        assert owner[case]["estimate"] == pytest.approx(reference[f"{prefix}_est"],rel=1e-6)
        assert owner[case]["std_error"] == pytest.approx(reference[f"{prefix}_se"],rel=1e-6)
    for at,prefix in [("average","ma"),("at_means","mm")]:
        for effect in owner["margins"][at]["effects"]:
            term=effect["variable"]
            assert effect["estimate"] == pytest.approx(reference[f"{prefix}_{term}_est"],rel=1e-6)
            assert effect["std_error"] == pytest.approx(reference[f"{prefix}_{term}_se"],rel=1e-5)
