"""Maximum-likelihood ETS estimation against the locked result contract.

Point 1 of the contract: the fit method is `statsmodels` `ETSModel` maximum
likelihood, recorded as `fit_method` and part of the result identity.
Point 6: this is a conditional-mean model. Nothing resembling a variance
forecast, VaR or volatility ever enters `params`.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np

from workbench.canonical import sha256_canonical
from workbench.contracts.model.ets import (
    ETS_CONTRACT_VERSION,
    ETS_MODEL_TYPE,
    ETSResultContract,
)

from .diagnostics import classify_convergence, raise_non_convergence
from .errors import ETSDiagnostic, ETSEstimationError, diagnostic
from .input import PreparedETSInput


FIT_METHOD = "statsmodels.ets.mle"
PRODUCER_VERSION = "time_series.ets@1.0"

# Never let an estimator field that would read as a volatility claim reach the
# public params mapping (contract docstring point 6 — the contract also refuses).
FORBIDDEN_PARAM_NAMES = frozenset(
    {"var", "value_at_risk", "conditional_variance", "volatility"}
)


@dataclass(frozen=True)
class ETSFitOutcome:
    """The public result plus the pack-local facts a compare adapter needs."""

    result: ETSResultContract
    sample_fingerprint: str
    diagnostics: tuple[ETSDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.to_dict(),
            "sample_fingerprint": self.sample_fingerprint,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "producer_version": PRODUCER_VERSION,
        }


def _result_identity(
    *, prepared: PreparedETSInput, params: dict[str, float]
) -> str:
    """Identity = specification + sample + fit method, never the fitted noise."""

    specification = prepared.options.specification
    return sha256_canonical(
        {
            "contract_version": ETS_CONTRACT_VERSION,
            "model_type": ETS_MODEL_TYPE,
            "specification": specification.to_dict(),
            "endog": prepared.options.value_column,
            "sample_fingerprint": prepared.sample_fingerprint,
            "n_obs": prepared.audit.n_obs,
            "n_excluded": prepared.audit.n_excluded,
            "time_index_semantics": prepared.audit.time_index_semantics,
            "fit_method": FIT_METHOD,
            "param_names": sorted(params),
        }
    )


def _fit_statsmodels(prepared: PreparedETSInput) -> Any:
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    specification = prepared.options.specification
    model = ETSModel(
        prepared.endog,
        error=specification.error,
        trend=specification.trend,
        seasonal=specification.seasonal,
        seasonal_periods=specification.seasonal_periods,
        damped_trend=specification.damped_trend,
    )
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        return model.fit(disp=False)


def estimate_ets(prepared: PreparedETSInput) -> ETSFitOutcome:
    """Fit one specification and return a contract-valid result, or block."""

    specification = prepared.options.specification
    try:
        fitted = _fit_statsmodels(prepared)
    except Exception as exc:  # optimizer or numerical failure
        raise ETSEstimationError(
            diagnostic(
                "ETS_ESTIMATION_FAILED",
                f"the ETS estimator raised {type(exc).__name__}",
                evidence={
                    "specification": specification.canonical,
                    "n_obs": prepared.audit.n_obs,
                    "error_type": type(exc).__name__,
                },
                impact="No ETS result exists for this specification and sample.",
            )
        ) from exc

    convergence_code = classify_convergence(getattr(fitted, "mle_retvals", None))
    if convergence_code != "converged":
        raise_non_convergence(
            convergence_code=convergence_code,
            specification=specification,
            n_obs=prepared.audit.n_obs,
        )

    params = {
        str(name): float(value)
        for name, value in zip(fitted.param_names, np.asarray(fitted.params, dtype=float))
    }
    smuggled = sorted(FORBIDDEN_PARAM_NAMES & set(params))
    if smuggled:
        raise ETSEstimationError(
            diagnostic(
                "ETS_FORBIDDEN_PARAMETER",
                f"the estimator produced a non-mean parameter: {smuggled}",
                evidence={"params": smuggled},
                impact="ETS must never be reported as a volatility model.",
            )
        )
    aic = float(fitted.aic)
    bic = float(fitted.bic)
    log_likelihood = float(fitted.llf)
    sigma2 = float(fitted.mse)
    unstable = [
        name
        for name, value in (
            ("aic", aic),
            ("bic", bic),
            ("log_likelihood", log_likelihood),
            ("sigma2", sigma2),
            *params.items(),
        )
        if not math.isfinite(value)
    ]
    if unstable:
        raise ETSEstimationError(
            diagnostic(
                "ETS_NON_FINITE_ESTIMATE",
                "the estimator produced non-finite quantities: " + ", ".join(unstable),
                evidence={
                    "fields": unstable,
                    "specification": specification.canonical,
                },
                impact="Non-finite estimates are not reportable numbers.",
            )
        )

    result = ETSResultContract(
        model_type=ETS_MODEL_TYPE,
        specification=specification,
        endog=prepared.options.value_column,
        n_obs=prepared.audit.n_obs,
        n_excluded=prepared.audit.n_excluded,
        exclusion_reasons=dict(prepared.audit.exclusion_reasons),
        params=params,
        aic=aic,
        bic=bic,
        log_likelihood=log_likelihood,
        sigma2=sigma2,
        convergence_code=convergence_code,
        fit_method=FIT_METHOD,
        result_identity=_result_identity(prepared=prepared, params=params),
        time_index_semantics=prepared.audit.time_index_semantics,
    )
    return ETSFitOutcome(
        result=result,
        sample_fingerprint=prepared.sample_fingerprint,
        diagnostics=(),
    )


__all__ = [
    "FIT_METHOD",
    "FORBIDDEN_PARAM_NAMES",
    "PRODUCER_VERSION",
    "ETSFitOutcome",
    "estimate_ets",
]
