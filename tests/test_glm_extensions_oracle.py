from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from statsmodels.discrete.count_model import ZeroInflatedNegativeBinomialP, ZeroInflatedPoisson
from statsmodels.othermod.betareg import BetaModel

from workbench.engine.packs.glm_extensions import (
    fit_beta,
    fit_zero_inflated_negative_binomial,
    fit_zero_inflated_poisson,
)

from test_glm_extensions_pack import _beta_data, _zinb_data, _zip_data


def _design(X: pd.DataFrame) -> np.ndarray:
    return sm.add_constant(X.to_numpy(dtype=float), has_constant="add")


def _estimates(packet: dict[str, object], process: str, names: list[str]) -> np.ndarray:
    values = packet["result"]["coefficient_estimands"][process]
    return np.asarray([values[name]["estimate"] for name in names], dtype=float)


def test_zip_coefficients_and_mean_probability_summaries_match_statsmodels_matrix_oracle():
    y, X = _zip_data()
    design = _design(X)
    oracle = ZeroInflatedPoisson(y, design, exog_infl=design, inflation="logit").fit(
        method="bfgs", maxiter=300, disp=0
    )
    packet = fit_zero_inflated_poisson(y, X, predictor_columns=["x"])

    np.testing.assert_allclose(
        _estimates(packet, "zero", ["const", "x"]), oracle.params[:2], rtol=2e-5, atol=2e-5
    )
    np.testing.assert_allclose(
        _estimates(packet, "count", ["const", "x"]), oracle.params[2:4], rtol=2e-5, atol=2e-5
    )
    expected_mean = float(np.mean(oracle.predict(which="mean")))
    expected_zero = float(np.mean(oracle.predict(which="prob-zero")))
    assert packet["result"]["mean_estimands"]["unconditional_mean"]["sample_mean"] == pytest.approx(expected_mean, rel=2e-5)
    assert packet["result"]["zero_probability_estimands"]["observed_zero_probability"]["sample_mean"] == pytest.approx(expected_zero, rel=2e-5)


def test_zinb_coefficients_match_statsmodels_matrix_oracle_when_covariance_is_finite():
    y, X = _zinb_data()
    design = _design(X)
    oracle = ZeroInflatedNegativeBinomialP(y, design, exog_infl=design, inflation="logit").fit(
        method="bfgs", maxiter=500, disp=0
    )
    assert np.isfinite(np.asarray(oracle.cov_params(), dtype=float)).all()
    packet = fit_zero_inflated_negative_binomial(y, X, predictor_columns=["x"], maxiter=500)

    np.testing.assert_allclose(
        _estimates(packet, "zero", ["const", "x"]), oracle.params[:2], rtol=2e-4, atol=2e-4
    )
    np.testing.assert_allclose(
        _estimates(packet, "count", ["const", "x"]), oracle.params[2:4], rtol=2e-4, atol=2e-4
    )
    assert packet["result"]["coefficient_estimands"]["dispersion"]["alpha"]["estimate"] == pytest.approx(float(oracle.params[4]), rel=2e-4)


def test_beta_coefficients_match_statsmodels_beta_model_matrix_oracle():
    y, X = _beta_data()
    design = _design(X)
    oracle = BetaModel(y, design).fit(method="bfgs", maxiter=500, disp=False)
    packet = fit_beta(y, X, predictor_columns=["x"], maxiter=500)

    np.testing.assert_allclose(
        _estimates(packet, "mean", ["const", "x"]), oracle.params[:2], rtol=2e-5, atol=2e-5
    )
    assert packet["result"]["coefficient_estimands"]["precision"]["precision"]["estimate"] == pytest.approx(float(oracle.params[2]), rel=2e-5)


def test_hurdle_zero_probability_is_gate_probability_and_positive_mean_is_truncated():
    from workbench.engine.packs.glm_extensions import fit_hurdle_poisson
    from test_glm_extensions_pack import _hurdle_data

    y, X = _hurdle_data(negative_binomial=False)
    packet = fit_hurdle_poisson(y, X, predictor_columns=["x"])
    result = packet["result"]
    gate = result["zero_probability_estimands"]["zero_gate_probability"]["sample_mean"]
    observed = result["zero_probability_estimands"]["observed_zero_probability"]["sample_mean"]
    assert observed == gate
    assert result["mean_estimands"]["positive_truncated_count_mean"]["sample_mean"] > 0.0
    assert result["mean_estimands"]["unconditional_mean"]["factorized_marginal_product"] == pytest.approx(
        (1.0 - gate)
        * result["mean_estimands"]["positive_truncated_count_mean"]["sample_mean"],
        rel=1e-10,
    )
