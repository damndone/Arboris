"""Fixed-effect covariance of a fitted LMM as lme4 and Stata ``mixed`` report it.

statsmodels' ``MixedLMResults.cov_params()`` inverts the Hessian of its own
profiled likelihood, so the fixed-effect block carries cross terms with the
variance parameters. lme4's ``vcov()`` and Stata ``mixed`` (REML and ML)
report the GLS covariance at the estimated variance components instead:

    Var(beta) = (sum_i X_i' V_i^-1 X_i)^-1,   V_i = Z_i Psi Z_i' + sigma^2 I

On the v1.8.11 fixtures the two differ by ~2e-5 (random intercept) to ~1e-3
(random slope) in standard errors; the GLS form agrees with lme4 to 4e-8 and
with Stata to 4e-7 (tests/test_lmm_postestimation_v1811_reference.py).

``GlsFixedEffectResults`` keeps every other attribute of the fit and replaces
only what derives from the fixed-effect covariance, so the result packet, the
inference kernel and post-estimation read one definition.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

COVARIANCE_DEFINITION = "lmm_gls_conditional"
REML_LIKELIHOOD_REASON = (
    "REML restricted likelihoods are not comparable across different fixed-effect "
    "designs; refit both models with ML for a likelihood-ratio test."
)


def gls_fixed_effect_covariance(fitted: Any) -> np.ndarray:
    """(sum_i X_i' V_i^-1 X_i)^-1 at the fit's variance components."""

    model = fitted.model
    psi = np.asarray(fitted.cov_re, dtype=float)
    sigma2 = float(fitted.scale)
    k = len(fitted.fe_params)
    information = np.zeros((k, k))
    for exog, exog_re in zip(model.exog_li, model.exog_re_li):
        marginal = exog_re @ psi @ exog_re.T + sigma2 * np.eye(len(exog))
        information += exog.T @ np.linalg.solve(marginal, exog)
    covariance = np.linalg.inv(information)
    return (covariance + covariance.T) / 2


class GlsFixedEffectResults:
    """A converged MixedLM fit whose fixed-effect inference uses the GLS covariance."""

    cov_type = COVARIANCE_DEFINITION

    def __init__(self, fitted: Any) -> None:
        self._fitted = fitted
        names = list(fitted.params.index)
        fixed = list(fitted.fe_params.index)
        self._fixed_positions = [names.index(name) for name in fixed]
        full = np.asarray(fitted.cov_params(), dtype=float).copy()
        positions = self._fixed_positions
        others = [i for i in range(len(names)) if i not in positions]
        # The GLS form treats the fixed effects as uncorrelated with the
        # variance parameters (their expected cross-information is zero).
        full[np.ix_(positions, others)] = 0.0
        full[np.ix_(others, positions)] = 0.0
        full[np.ix_(positions, positions)] = gls_fixed_effect_covariance(fitted)
        self._covariance = pd.DataFrame(full, index=names, columns=names)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fitted, name)

    @property
    def is_reml(self) -> bool:
        return str(getattr(self._fitted, "method", "")).upper() == "REML"

    def cov_params(self) -> pd.DataFrame:
        return self._covariance.copy()

    @property
    def bse(self) -> pd.Series:
        return pd.Series(np.sqrt(np.diag(self._covariance.to_numpy())), index=self._covariance.index)

    @property
    def tvalues(self) -> pd.Series:
        return self._fitted.params / self.bse

    @property
    def pvalues(self) -> pd.Series:
        return pd.Series(2 * stats.norm.sf(np.abs(self.tvalues)), index=self._covariance.index)

    def conf_int(self, alpha: float = 0.05) -> pd.DataFrame:
        margin = stats.norm.ppf(1 - alpha / 2) * self.bse
        params = self._fitted.params
        return pd.DataFrame({0: params - margin, 1: params + margin})

    def kernel_view(self) -> "GlsFixedEffectResults":
        """The fit as post-estimation sees it: no likelihood under REML."""

        return _KernelView(self._fitted) if self.is_reml else self


class _KernelView(GlsFixedEffectResults):
    llf = None
