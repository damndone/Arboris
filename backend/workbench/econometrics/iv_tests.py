"""Wooldridge's robust IV tests, as linearmodels computes them, without its auxiliary _OLS models."""
from __future__ import annotations

from typing import Any

import numpy as np

_OVERID = "Wooldridge's score test of overidentification"
_EXOGENEITY = "Wooldridge's regression test of exogeneity"


def wooldridge_overid(fitted: Any) -> Any:
    """``fitted.wooldridge_overid`` with the same arithmetic and statistic, bit for bit.

    linearmodels ends the test with ``_OLS(ones, test_functions).fit()``, a whole IV model
    whose construction alone held about 330 MiB for 1M rows (data frames, weights, row
    labels, six weighted copies) to produce one R squared (2026-11-09 footprint
    diagnostics: +453 MiB at the peak of the robust IV reference path). Here the same
    statistic comes from the arrays that R squared uses: unit weights, kappa 0, the same
    ``estimate_parameters`` and sums of squares. Anything that model would reject or
    adjust for (missing values, rank deficiency, a constant test function) goes through
    linearmodels itself.
    """
    from linearmodels.iv._utility import annihilate, proj
    from linearmodels.iv.model import IVLIML
    from linearmodels.shared.hypotheses import InvalidTestStatistic, WaldTestStatistic
    from linearmodels.shared.linalg import has_constant

    model = fitted.model
    exog, endog, instruments = model.exog, model.endog, model.instruments
    nobs, nendog = endog.shape
    ninstr = instruments.shape[1]
    if ninstr - nendog == 0:
        return InvalidTestStatistic("Test requires more instruments than endogenous variables.", name=_OVERID)
    endog_hat = proj(endog.ndarray, np.c_[exog.ndarray, instruments.ndarray])
    q = instruments.ndarray[:, : (ninstr - nendog)]
    q_res = annihilate(q, np.c_[exog.ndarray, endog_hat])
    test_functions = q_res * fitted.resids.to_numpy()[:, None]
    if (not np.isfinite(test_functions).all()
            or np.linalg.matrix_rank(test_functions) < test_functions.shape[1]
            or has_constant(test_functions)[0]):
        return fitted.wooldridge_overid
    weights = np.ones((nobs, 1))
    weights = weights / np.nanmean(weights)
    w = np.sqrt(weights)
    wy = np.ones((nobs, 1)) * w
    x = np.c_[test_functions, np.empty((nobs, 0))]
    wx = x * w
    wz = np.c_[test_functions, np.empty((nobs, 0))] * w
    params = IVLIML.estimate_parameters(wx, wy, wz, 0.0)
    weps = wy - wx @ params
    residual_ss = np.squeeze(weps.T @ weps)
    total_ss = float(np.squeeze(wy.T @ wy))
    r2 = float(np.squeeze(1 - residual_ss / total_ss))
    return WaldTestStatistic(nobs * r2, "Model is not overidentified.", ninstr - nendog, name=_OVERID)


def wooldridge_regression(fitted: Any) -> Any:
    """``fitted.wooldridge_regression`` with the same arithmetic and statistic, bit for bit.

    linearmodels refits ``_OLS(dependent, [x, r])`` with the fit's covariance settings, where
    ``r`` are the endogenous regressors' residuals on the instruments, and tests the ``r``
    coefficients. That model's construction copies every column several times (the next
    peak of the 1M-row robust IV path once wooldridge_overid stopped building one). Here its
    estimate and covariance come from linearmodels' own ``IVLIML.estimate_parameters`` and
    covariance estimator on the same arrays, with the configuration ``fit`` would pass.
    A rank-deficient augmented design goes through linearmodels itself.
    """
    from linearmodels.iv._utility import annihilate
    from linearmodels.iv.model import COVARIANCE_ESTIMATORS, IVLIML
    from linearmodels.shared.hypotheses import WaldTestStatistic

    model = fitted.model
    r = annihilate(model.endog.ndarray, model._z)
    augx = np.ascontiguousarray(np.c_[model._x, r])  # row-major, as _OLS's own copy of it
    if not np.isfinite(augx).all() or np.linalg.matrix_rank(augx) < augx.shape[1]:
        return fitted.wooldridge_regression
    nobs = augx.shape[0]
    weights = np.ones((nobs, 1))
    weights = weights / np.nanmean(weights)
    w = np.sqrt(weights)
    wy = model.dependent.ndarray * w
    wx = augx * w
    wz = np.c_[augx, np.empty((nobs, 0))] * w
    params = IVLIML.estimate_parameters(wx, wy, wz, 0.0)
    cov_config = dict(fitted.cov_config)
    debiased = cov_config.pop("debiased", False)
    cov_config["debiased"] = debiased
    cov_config["kappa"] = 0.0
    cov_config.pop("center", None)
    cov = COVARIANCE_ESTIMATORS[fitted.cov_type](wx, wy, wz, params, **cov_config).cov
    norig = model._x.shape[1]
    test_params = np.asarray(params.squeeze()[norig:], dtype=float)
    test_cov = cov[norig:, norig:]
    stat = test_params.T @ np.linalg.inv(test_cov) @ test_params
    return WaldTestStatistic(stat, "Endogenous variables are exogenous", len(test_params), name=_EXOGENEITY)


def prime_robust_iv_tests(fitted: Any) -> None:
    """Fill the cached Wooldridge tests so every reader gets the lean computations."""
    cache = vars(fitted)
    if "wooldridge_overid" not in cache:
        cache["wooldridge_overid"] = wooldridge_overid(fitted)
    if "wooldridge_regression" not in cache:
        cache["wooldridge_regression"] = wooldridge_regression(fitted)
