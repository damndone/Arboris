"""Native R/Stata references for two genuinely endogenous IV regressors."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation import PostestimationRefusal
from workbench.postestimation.registry import run_operation
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures/postestimation/iv_two_endogenous_v1811"
ORIGINAL = json.loads((FIXTURES.parent / "oracle.json").read_text())
POST_REL = float(ORIGINAL["tolerances"]["default"])
JOINT = {"constraints": [{"terms": {"xe1": 1}, "value": 0},
                         {"terms": {"xe2": 1}, "value": 0}]}


def test_both_native_oracles_are_required():
    missing = [name for name in ("r_reference.json", "stata_reference.json")
               if not (FIXTURES / name).is_file()]
    assert not missing, f"Frozen two-endogenous native references missing: {missing}"


@pytest.fixture(scope="module")
def references():
    for name in ("r_reference.json", "stata_reference.json", "data.csv", "provenance.json"):
        assert (FIXTURES / name).is_file(), f"Frozen two-endogenous native evidence missing: {name}"
    return {software: read_json(FIXTURES / f"{software}_reference.json") for software in ("r", "stata")}


@pytest.fixture(scope="module")
def fitted(tmp_path_factory, references):
    project = create_project(tmp_path_factory.mktemp("iv-two-endogenous-v1811"), "oracle")
    outcome = run_workflow(
        project.root, [FIXTURES / "data.csv"], mode="auto", model_type="iv_2sls",
        y="y", x=["x1"], iv_endog=["xe1", "xe2"], iv_instruments=["z1", "z2"])
    root = project.root / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root / "errors.json")
    print("Retained public IV run:", root)
    return (read_json(root / kernel_relative_path("iv_2sls_1")),
            read_json(root / "model_results/iv_2sls_1.json"))


def test_public_data_provenance_has_two_endogenous_variables(references):
    provenance = read_json(FIXTURES / "provenance.json")
    assert provenance["endogenous"] == ["xe1", "xe2"]
    assert provenance["excluded_instruments"] == ["z1", "z2"]
    assert provenance["exogenous"] == ["x1"]
    assert provenance["data_sha256"] == hashlib.sha256((FIXTURES / "data.csv").read_bytes()).hexdigest()
    assert references["r"]["data_sha256"] == references["stata"]["data_sha256"] == provenance["data_sha256"]
    assert abs(provenance["sample_correlations"]["xe1_structural_error"]) > .1
    assert abs(provenance["sample_correlations"]["xe2_structural_error"]) > .1
    assert provenance["regressor_rank"] == provenance["instrument_rank"] == 4
    assert references["r"]["nobs"] == references["stata"]["nobs"] == provenance["nobs"]


@pytest.mark.parametrize("software", ["r", "stata"])
def test_public_iv_coefficients_covariance_and_z_match_native(fitted, references, software):
    kernel, primary = fitted
    reference = references[software]
    assert kernel["reference_distribution"] == "z"
    assert kernel["covariance_estimator"] == "robust"
    assert kernel["df_method"] == "asymptotic"
    assert kernel["df_resid"] == reference["nominal_residual_df"] == 646
    assert kernel["nobs"] == reference["nobs"]
    assert set(kernel["param_names"]) == set(reference["terms"]) == {"Intercept", "x1", "xe1", "xe2"}
    order = [reference["terms"].index(t) for t in kernel["param_names"]]
    expected = np.asarray(reference["covariance"])[np.ix_(order, order)]
    np.testing.assert_allclose(kernel["vcov"], expected, rtol=POST_REL, atol=1e-12)
    for i, term in enumerate(kernel["param_names"]):
        estimate = kernel["params"][i]
        se = np.sqrt(kernel["vcov"][i][i])
        assert estimate == pytest.approx(reference["params"][term], rel=0, abs=1e-8)
        assert se == pytest.approx(reference["std_error"][term], rel=0, abs=1e-6)
        assert estimate / se == pytest.approx(reference["z"][term], rel=POST_REL)
        assert 2 * stats.norm.sf(abs(estimate / se)) == pytest.approx(reference["p"][term], rel=max(POST_REL * 10, 1e-5), abs=0)
        assert primary["coefficients"][term]["estimate"] == pytest.approx(reference["params"][term], rel=0, abs=1e-8)
        assert primary["coefficients"][term]["std_error"] == pytest.approx(reference["std_error"][term], rel=0, abs=1e-6)
    print(software, "max coefficient/covariance error:",
          max(abs(kernel["params"][i] - reference["params"][t]) for i, t in enumerate(kernel["param_names"])),
          float(np.max(np.abs(np.asarray(kernel["vcov"]) - expected))))


@pytest.mark.parametrize("software", ["r", "stata"])
def test_joint_wald_targets_both_endogenous_coefficients(fitted, references, software):
    kernel, _ = fitted
    actual = run_operation("wald", [kernel], JOINT)
    reference = references[software]["wald_joint"]
    assert actual["constraints"] == JOINT["constraints"]
    assert actual["distribution"] == reference["distribution"] == "chi2"
    assert actual["df_num"] == reference["df_num"] == 2
    assert actual["df_den"] is reference["df_den"] is None
    assert actual["statistic"] == pytest.approx(reference["statistic"], rel=POST_REL)
    assert actual["p_value"] == pytest.approx(reference["p_value"], rel=max(POST_REL * 10, 1e-5), abs=0)
    print(software, "joint endogenous Wald Workbench/native:", actual, reference)


def test_native_r_and_stata_independently_agree(references):
    r, stata = references["r"], references["stata"]
    assert r["terms"] == stata["terms"]
    np.testing.assert_allclose(r["covariance"], stata["covariance"], rtol=POST_REL, atol=1e-12)
    for term in r["terms"]:
        assert r["params"][term] == pytest.approx(stata["params"][term], rel=0, abs=1e-8)
        assert r["std_error"][term] == pytest.approx(stata["std_error"][term], rel=0, abs=1e-6)
    assert r["wald_joint"]["statistic"] == pytest.approx(stata["wald_joint"]["statistic"], rel=POST_REL)


def test_two_endogenous_iv_does_not_claim_a_likelihood_ratio(fitted):
    kernel, _ = fitted
    with pytest.raises(PostestimationRefusal) as caught:
        run_operation("lr", [kernel, kernel], {})
    assert caught.value.code == "INTERFACE_UNAVAILABLE"
