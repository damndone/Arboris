"""Current fast IV against retained, real Stata 18 recordings, not a new Stata run.

Only the original SHA-pinned CSV is fitted. The independently archived Stata do/log/TSV
record import-as-double, 650 complete rows and robust/no-small (HC0, normal/chi-square)
inference. Reconstructed data are never substituted. Coverage is this two-endogenous,
exactly identified recorded case, not a general Stata certification.

The independent stata_reference.json sidecar fails its archived manifest digest and is
untrusted/unused. Numerical expectations come only from the SHA-verified native TSV;
the separate local review records that integrity gap, not a statistical success for it.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.model.inference_kernel import kernel_from_fitted
from workbench.econometrics.panel_iv import run_iv_2sls
from workbench.estimation_engine import FAST_ENGINE_NAME, native
from workbench.postestimation.registry import run_operation


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "tests/fixtures/postestimation/iv_two_endogenous_v1811"
ARCHIVE = ROOT / "tests/eval_v1811/iv_two_endogenous_independent_evidence"
SOURCE_SHA256 = "d3b46c7cf6c42c4dc1db66b3ae63a0ef02ffe10ff3b24983687355daa238c497"
MANIFEST_SHA256 = "0ab3d2331fb3d68f20d6d7fe2271a083eaa1a38211feb85ac7b7854f5f122395"
TERMS = ["Intercept", "x1", "xe1", "xe2"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def recorded():
    assert digest(ARCHIVE / "manifest.json") == MANIFEST_SHA256
    manifest = json.loads((ARCHIVE / "manifest.json").read_text())
    for filename in ("stata.do", "stata.log", "stata.tsv", "r_moment_reference.json"):
        path = ARCHIVE / filename
        assert digest(path) == manifest["public_review_asset_sha256"][path.relative_to(ROOT).as_posix()]
    provenance = json.loads((ORIGINAL / "provenance.json").read_text())
    source_record = json.loads((ARCHIVE / "r_moment_reference.json").read_text())
    assert digest(ORIGINAL / "data.csv") == provenance["data_sha256"] == source_record["source_sha256"] == SOURCE_SHA256
    raw = dict(line.split("\t", 1) for line in (ARCHIVE / "stata.tsv").read_text().splitlines())
    text_fields = {"endogenous", "exogenous_and_instruments", "exogenous_regressors", "small_option", "vce", "control_small_option"}
    return {key: value.strip() if key in text_fields else float(value) for key, value in raw.items()}


@pytest.fixture(scope="module")
def original_frame(recorded):
    # read_csv's round_trip parser and Python's correctly rounded float parser
    # must supply identical binary64 values for the original recorded bytes.
    frame = pd.read_csv(ORIGINAL / "data.csv", float_precision="round_trip")
    with (ORIGINAL / "data.csv").open() as stream:
        rows = list(csv.reader(stream))
    parsed = np.array([[float(value) for value in row] for row in rows[1:]], dtype=np.float64)
    assert rows[0] == frame.columns.tolist() == ["y", "x1", "xe1", "xe2", "z1", "z2"]
    assert frame.shape == (650, 6) and np.isfinite(parsed).all()
    assert frame.to_numpy().tobytes() == parsed.tobytes()
    return frame


def test_recording_pins_the_original_input_and_hc0_normal_inference(recorded, original_frame):
    values = recorded
    commands = (ARCHIVE / "stata.do").read_text()
    log = (ARCHIVE / "stata.log").read_text()
    assert commands.startswith("version 18\n") and "18.0" in log
    assert "iv_two_endogenous_v1811/data.csv\", asdouble clear case(preserve)" in commands
    models = [line for line in commands.splitlines() if line.startswith("ivregress ")]
    assert models == ["ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust)",
                      "ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust) small"]
    assert "(6 vars, 650 obs)" in log
    assert re.search(r"Coefficient\s+std\. err\.\s+z\s+P>\|z\|", log)
    assert commands.count("2*normal(-abs(_b[") == len(TERMS)
    assert values["endogenous"].split() == ["xe1", "xe2"]
    assert values["exogenous_regressors"] == "x1"
    assert values["exogenous_and_instruments"].split() == ["x1", "z1", "z2"]
    assert values["vce"] == "robust" and values["small_option"] == ""
    assert values["nobs"] == 650 and values["nominal_residual_df"] == 646
    # The retained native small-option control distinguishes HC1/t/F from the
    # no-small recording being consumed; no conversion factor is applied here.
    for name in TERMS:
        ratio = (values[f"control_se_{name}"]/values[f"se_{name}"])**2
        assert ratio == pytest.approx(650/646, rel=1e-12, abs=0)


@pytest.fixture(scope="module")
def fitted(original_frame):
    if not native.available():
        pytest.skip("current native engine is not built; historical archive provenance remains testable")
    primary, result = run_iv_2sls(original_frame, y="y", exog=["x1"], endog=["xe1", "xe2"],
        instruments=["z1", "z2"], model_id="iv_2sls_1", covariance="robust", estimation_engine="fast")
    assert primary["engine"] == FAST_ENGINE_NAME
    assert result.params.index.tolist() == TERMS
    assert result.model.exog.cols == ["Intercept", "x1"]
    assert result.model.endog.cols == ["xe1", "xe2"] and result.model.instruments.cols == ["z1", "z2"]
    assert result.nobs == 650 and result.df_resid == 646 and result.debiased is False
    return primary, result


def assert_tail(actual, expected):
    assert 0 < actual <= 1
    assert actual == pytest.approx(expected, rel=1e-9, abs=0)
    assert abs(math.log(actual)-math.log(expected)) <= 1e-9


def test_fast_coefficients_full_covariance_and_standard_errors_match_recorded_stata(recorded, fitted):
    values = recorded
    primary, result = fitted
    covariance = np.array([[values[f"cov_{a}_{b}"] for b in TERMS] for a in TERMS])
    np.testing.assert_allclose(result.cov, covariance, rtol=1e-9, atol=0)
    scale = np.sqrt(np.outer(np.diag(covariance), np.diag(covariance)))
    assert np.max(np.abs(result.cov.to_numpy()-covariance)/scale) <= 1e-9
    for name in TERMS:
        assert result.params[name] == pytest.approx(values[f"b_{name}"], rel=1e-9, abs=1e-12)
        assert result.std_errors[name] == pytest.approx(values[f"se_{name}"], rel=1e-9, abs=0)
        assert primary["coefficients"][name]["estimate"] == result.params[name]
        assert primary["coefficients"][name]["std_error"] == result.std_errors[name]


def test_fast_z_and_positive_normal_tails_match_recorded_stata(recorded, fitted):
    values = recorded
    _, result = fitted
    for name in TERMS:
        # z is computed from the recorded Stata b/SE; the positive normal tail
        # itself is an independently exported native Stata value.
        expected_z = values[f"b_{name}"]/values[f"se_{name}"]
        assert result.tstats[name] == pytest.approx(expected_z, rel=1e-9, abs=1e-12)
        assert_tail(float(result.pvalues[name]), values[f"p_{name}"])


def test_current_fast_kernel_joint_wald_matches_recorded_stata_chi_square(recorded, fitted):
    values = recorded
    _, result = fitted
    kernel = kernel_from_fitted(result, model_id="iv_2sls_1", model_type="iv_2sls", nobs=650)
    assert kernel is not None
    assert kernel["param_names"] == TERMS and kernel["reference_distribution"] == "z"
    assert kernel["df_method"] == "asymptotic" and kernel["df_resid"] == 646
    joint = run_operation("wald", [kernel], {"constraints": [
        {"terms": {"xe1": 1}, "value": 0}, {"terms": {"xe2": 1}, "value": 0}]})
    assert joint["distribution"] == "chi2" and joint["df_num"] == values["wald_df"] == 2
    assert joint["df_den"] is None
    assert joint["statistic"] == pytest.approx(values["wald_statistic"], rel=1e-9, abs=1e-12)
    assert_tail(joint["p_value"], values["wald_p"])
