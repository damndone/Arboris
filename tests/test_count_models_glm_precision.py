"""GLM fixed-alpha oracle at R's strictly converged final EIM point."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.econometrics.runner import run_glm


def test_explicit_alpha_one_matches_high_precision_admission_oracle():
    path = Path(__file__).parent / "fixtures/admission/glm_negative_binomial"
    oracle_path = Path(__file__).parent / "fixtures/count_models/integration-strict-v1811/glm-negative-binomial-v1811-oracle.json"
    oracle = json.loads(oracle_path.read_text())
    result, fitted = run_glm(pd.read_csv(path / "data.csv", float_precision="round_trip"), "y", ["x1", "x2"], "glm", "negative_binomial", alpha=1.)
    for term, value in oracle["coefficients"].items():
        assert abs(result["coefficients"][term]["estimate"]-value) < 1e-8
        assert abs(result["coefficients"][term]["std_error"]-oracle["std_error"][term]) < 1e-6
    expected = np.linalg.inv(-fitted.model.hessian(fitted.params, observed=False))
    np.testing.assert_allclose(fitted.cov_params(), expected, rtol=1e-12, atol=1e-14)


def test_final_optimum_matches_r_with_epsilon_16_and_final_expected_information():
    fixtures = Path(__file__).parent / "fixtures"
    reference = json.loads((fixtures / "count_models/glm_precision.json").read_text())["cases"][1]
    frame = pd.read_csv(fixtures / "admission/glm_negative_binomial/data.csv", float_precision="round_trip")
    result, fitted = run_glm(frame, "y", ["x1", "x2"], "glm", "negative_binomial", alpha=1.)
    np.testing.assert_allclose(fitted.params, reference["coefficients"], rtol=0, atol=1e-8)
    np.testing.assert_allclose(fitted.bse, reference["std_error"], rtol=0, atol=1e-6)
