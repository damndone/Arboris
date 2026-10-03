from __future__ import annotations

import numpy as np
import pytest

from statsmodels.sandbox.regression.gmm import IV2SLS, IVGMM

from workbench.engine.packs.iv_gmm import fit_gmm

from test_iv_gmm_pack import _iv_data


def test_two_step_gmm_matches_statsmodels_ivgmm_oracle() -> None:
    y, exog, endog, instruments = _iv_data()
    ours = fit_gmm(y, exog, endog, instruments, estimator="two_step")

    x = np.column_stack((exog, endog))
    z = np.column_stack((exog, instruments))
    oracle = IVGMM(y, x, z).fit(
        maxiter=2,
        weights_method="cov",
        wargs={"centered": False},
        optim_method="bfgs",
    )

    estimates = np.array(
        [entry["estimate"] for entry in ours["result"]["coefficients"].values()]
    )
    np.testing.assert_allclose(estimates, oracle.params, rtol=1e-8, atol=1e-10)
    np.testing.assert_allclose(
        np.asarray(ours["result"]["covariance"]),
        oracle.cov_params(),
        rtol=1e-7,
        atol=1e-10,
    )


def test_one_step_gmm_matches_statsmodels_iv2sls_oracle() -> None:
    y, exog, endog, instruments = _iv_data()
    ours = fit_gmm(y, exog, endog, instruments, estimator="one_step")
    x = np.column_stack((exog, endog))
    z = np.column_stack((exog, instruments))
    oracle = IV2SLS(y, x, z).fit()
    estimates = np.array(
        [entry["estimate"] for entry in ours["result"]["coefficients"].values()]
    )
    np.testing.assert_allclose(estimates, oracle.params, rtol=1e-8, atol=1e-10)
