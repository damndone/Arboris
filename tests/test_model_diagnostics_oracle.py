from __future__ import annotations

import math

import numpy as np
import pytest
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan, het_white


def _direct_fixture():
    x1 = np.linspace(-2.5, 2.5, 30)
    x2 = np.sin(np.linspace(-1.7, 2.1, 30)) + np.linspace(-0.2, 0.2, 30)
    x = np.column_stack((np.ones(30), x1, x2))
    y = 1.25 + 0.8 * x1 - 0.35 * x2 + 0.04 * x1**2 + 0.18 * np.cos(x1 * 2.0)
    fit = sm.OLS(y, x).fit()
    metadata = {
        "model_type": "ols",
        "parameter_count": 3,
        "residual_df": int(fit.df_resid),
        "residual_variance": float(fit.mse_resid),
        "covariance": "unadjusted",
        "parameter_names": ["const", "x1", "x2"],
    }
    return y, x, fit, metadata


def _kwargs(metadata):
    return {
        "design_columns": ["const", "x1", "x2"],
        "intercept": True,
        "intercept_column": "const",
        "model_metadata": metadata,
    }


def test_direct_breusch_pagan_formula_oracle_matches_runtime():
    from workbench.engine.packs.model_diagnostics import run_breusch_pagan

    y, x, fit, metadata = _direct_fixture()
    packet = run_breusch_pagan(
        y,
        x,
        fit.resid,
        fitted_values=fit.fittedvalues,
        **_kwargs(metadata),
    )
    auxiliary = sm.OLS(fit.resid**2, x).fit()
    lm = len(y) * auxiliary.rsquared
    df = int(auxiliary.df_model)
    direct_p = stats.chi2.sf(lm, df)
    direct_f = (auxiliary.rsquared / df) / (
        (1.0 - auxiliary.rsquared) / auxiliary.df_resid
    )
    direct_fp = stats.f.sf(direct_f, df, auxiliary.df_resid)
    expected = het_breuschpagan(fit.resid, x)

    assert packet["result"]["statistic"] == pytest.approx(lm)
    assert packet["result"]["p_value"] == pytest.approx(direct_p)
    assert packet["result"]["f_statistic"] == pytest.approx(direct_f)
    assert packet["result"]["f_p_value"] == pytest.approx(direct_fp)
    assert packet["result"]["statistic"] == pytest.approx(expected[0])


def test_direct_white_formula_oracle_exposes_expanded_auxiliary_terms():
    from workbench.engine.packs.model_diagnostics import run_white

    y, x, fit, metadata = _direct_fixture()
    packet = run_white(
        y,
        x,
        fit.resid,
        fitted_values=fit.fittedvalues,
        **_kwargs(metadata),
    )
    x1, x2 = x[:, 1], x[:, 2]
    auxiliary_design = np.column_stack((np.ones(len(y)), x1, x2, x1**2, x1 * x2, x2**2))
    auxiliary = sm.OLS(fit.resid**2, auxiliary_design).fit()
    lm = len(y) * auxiliary.rsquared
    expected = het_white(fit.resid, x)

    assert packet["result"]["statistic"] == pytest.approx(lm)
    assert packet["result"]["statistic"] == pytest.approx(expected[0])
    assert packet["result"]["df"] == int(auxiliary.df_model)
    assert packet["result"]["auxiliary_regression"]["terms"] == [
        "const",
        "x1",
        "x2",
        "x1^2",
        "x1:x2",
        "x2^2",
    ]
    assert math.isfinite(packet["result"]["p_value"])
