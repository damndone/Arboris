"""Pooling models fitted to multiply imputed datasets (Rubin's rules).

Each of the m completed datasets is fitted separately; the m inference kernels
are combined here. For each parameter (Rubin 1987; van Buuren 2018, sec. 2.3):

    qbar = mean of the m estimates
    ubar = mean of the m complete-data variances (within-imputation)
    b    = sample variance of the m estimates (between-imputation)
    t    = ubar + (1 + 1/m) b

reported with the relative increase in variance riv = (1 + 1/m) b / ubar, the
proportion of variance due to missingness lambda = (1 + 1/m) b / t, and the
fraction of missing information fmi = (riv + 2 / (df + 3)) / (riv + 1).

Degrees of freedom follow Barnard and Rubin (1999), written as mice 3.19 writes
them so that lambda = 0 needs no special case:

    df = (m - 1) a / ((dfcom + 3)(m - 1) + lambda^2 a),   a = (1 - lambda)(1 + dfcom) dfcom

where dfcom is the complete-data degrees of freedom: the reference distribution
of the single fit decides it (N - K or G - 1 for a t-based fit, infinite for a
z-based one, which reduces df to Rubin's (m - 1) / lambda^2).

Only pairs of (family, covariance) checked against mice::pool are offered; the
arithmetic is the same for every family, but a family's kernel is trusted for
pooling only once a reference agrees with it, as for post-estimation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats

POOL_CONTRACT = "workbench.multiple_imputation_pool.v1"
POOLING_METHOD = "rubin_barnard_rubin"

MIN_IMPUTATIONS = 2
MAX_IMPUTATIONS = 100

#: (model family, covariance estimator) -> oracle cases in
#: tests/fixtures/multiple_imputation/oracle.json that validate pooling it.
MI_VALIDATED: Mapping[tuple[str, str], tuple[str, ...]] = {
    ("ols", "nonrobust"): ("ols",),
    ("ols", "HC1"): ("ols_robust",),
    ("ols", "cluster"): ("ols_cluster",),
    ("logit", "nonrobust"): ("logit",),
}

#: The fields every imputation's kernel must agree on: pooling estimates of
#: different quantities, or under different variance rules, is meaningless.
_MUST_AGREE = ("model_type", "param_names", "reference_distribution", "df_method",
               "covariance_estimator", "weights", "nobs", "df_resid")

#: Kernel covariance estimator -> the `covariance` value a run request uses for
#: it. The offer is written in the request's words: "default" would be read as
#: the product's OLS default, which is robust.
_COVARIANCE_REQUEST_VALUES = {"nonrobust": "unadjusted", "HC1": "robust", "cluster": "clustered"}


def _covariance_words(covariance: str) -> str:
    value = _COVARIANCE_REQUEST_VALUES.get(covariance)
    return f"covariance {value}" if value else f"the {covariance} covariance"


class MultipleImputationRefusal(ValueError):
    """A multiple-imputation request that is not offered, with the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def validated_text() -> str:
    """Which families and covariances pooling is offered for, read off MI_VALIDATED.

    A family validated only with its model-based covariance usually offers no
    covariance choice at all, so it is named without one.
    """
    by_family: dict[str, list[str]] = {}
    for family, covariance in MI_VALIDATED:
        by_family.setdefault(family, []).append(covariance)
    parts = []
    for family, covariances in by_family.items():
        if covariances == ["nonrobust"]:
            parts.append(f"{family} (its model-based covariance)")
        else:
            values = [_COVARIANCE_REQUEST_VALUES.get(item, item) for item in covariances]
            parts.append(f"{family} with covariance {', '.join(values[:-1])} or {values[-1]}"
                         if len(values) > 1 else f"{family} with covariance {values[0]}")
    return "; ".join(parts)


def require_poolable(model_type: str, kernel: Mapping[str, Any]) -> None:
    """Refuse a family or covariance whose pooling has not been validated."""
    if "coef_vcov" not in (kernel.get("interfaces") or []) or kernel.get("vcov_scope") != "full":
        reason = (kernel.get("unavailable") or {}).get("coef_vcov") or "it does not provide a full covariance matrix"
        raise MultipleImputationRefusal(
            "NO_INFERENCE_KERNEL",
            f"{model_type} results cannot be pooled across imputations: {reason}",
        )
    weights = kernel.get("weights") or "none"
    if weights != "none":
        raise MultipleImputationRefusal(
            "NOT_YET_VALIDATED",
            f"Pooling a {weights}-weighted {model_type} fit across imputations has not yet been "
            "checked against a reference implementation, so it is not offered yet; pooling is "
            "available for unweighted fits.",
        )
    covariance = str(kernel.get("covariance_estimator"))
    if (model_type, covariance) not in MI_VALIDATED:
        raise MultipleImputationRefusal(
            "NOT_YET_VALIDATED",
            f"Pooling {model_type} with {_covariance_words(covariance)} across "
            "imputations has not yet been checked against a reference implementation, so it is "
            f"not offered yet. Pooling is available for: {validated_text()}.",
        )


def _barnard_rubin(m: int, lam: float, dfcom: float) -> float:
    if math.isinf(dfcom):
        return math.inf if lam == 0 else (m - 1) / lam**2
    a = (1.0 - lam) * (1.0 + dfcom) * dfcom
    return (m - 1) * a / ((dfcom + 3.0) * (m - 1) + lam**2 * a)


def _check_agreement(kernels: Sequence[Mapping[str, Any]]) -> None:
    first = kernels[0]
    for index, kernel in enumerate(kernels[1:], start=2):
        differing = [field for field in _MUST_AGREE if kernel.get(field) != first.get(field)]
        if differing:
            raise MultipleImputationRefusal(
                "IMPUTATIONS_DISAGREE",
                f"imputation {index} was not fitted like imputation 1 ({', '.join(differing)} "
                "differ); the estimates do not describe the same quantity and cannot be pooled",
            )


def pool_kernels(kernels: Sequence[Mapping[str, Any]], *, alpha: float = 0.05) -> dict[str, Any]:
    """Pool m kernels fitted to m completed datasets.

    Returns per-parameter results and the pooled matrices (ubar, b, t), which a
    later multi-parameter test (D1) will need. Estimates are pooled unrounded;
    p-values and intervals are never averaged.
    """
    m = len(kernels)
    if not MIN_IMPUTATIONS <= m <= MAX_IMPUTATIONS:
        raise MultipleImputationRefusal(
            "IMPUTATION_COUNT",
            f"pooling needs between {MIN_IMPUTATIONS} and {MAX_IMPUTATIONS} imputations; got {m}",
        )
    _check_agreement(kernels)
    first = kernels[0]
    names = list(first["param_names"])
    estimates = np.asarray([kernel["params"] for kernel in kernels], dtype=float)
    covariances = np.asarray([kernel["vcov"] for kernel in kernels], dtype=float)
    if not (np.isfinite(estimates).all() and np.isfinite(covariances).all()):
        raise MultipleImputationRefusal("NON_FINITE", "an imputation produced a non-finite estimate or variance")

    qbar = estimates.mean(axis=0)
    ubar = covariances.mean(axis=0)
    deviations = estimates - qbar
    between = deviations.T @ deviations / (m - 1)
    total = ubar + (1.0 + 1.0 / m) * between
    asymptotic = first.get("reference_distribution") == "z"
    dfcom = math.inf if asymptotic else float(first["df_resid"])

    terms: dict[str, dict[str, Any]] = {}
    for j, name in enumerate(names):
        u, b, t = float(ubar[j, j]), float(between[j, j]), float(total[j, j])
        if not (u > 0 and t > 0):
            raise MultipleImputationRefusal("NON_POSITIVE_VARIANCE", f"{name} has no positive pooled variance")
        riv = (1.0 + 1.0 / m) * b / u
        lam = (1.0 + 1.0 / m) * b / t
        df = _barnard_rubin(m, lam, dfcom)
        fmi = (riv + 2.0 / (df + 3.0)) / (riv + 1.0) if math.isfinite(df) else riv / (riv + 1.0)
        se = math.sqrt(t)
        statistic = float(qbar[j]) / se
        if math.isfinite(df):
            p_value = float(2.0 * stats.t.sf(abs(statistic), df))
            critical = float(stats.t.ppf(1.0 - alpha / 2.0, df))
        else:
            p_value = float(2.0 * stats.norm.sf(abs(statistic)))
            critical = float(stats.norm.ppf(1.0 - alpha / 2.0))
        terms[name] = {
            "estimate": float(qbar[j]),
            "std_error": se,
            "df": df if math.isfinite(df) else None,
            "statistic": statistic,
            "p_value": p_value,
            "ci_lower": float(qbar[j]) - critical * se,
            "ci_upper": float(qbar[j]) + critical * se,
            "within_variance": u,
            "between_variance": b,
            "total_variance": t,
            "riv": riv,
            "lambda": lam,
            "fmi": fmi,
        }
    return {
        "contract": POOL_CONTRACT,
        "method": POOLING_METHOD,
        "m": m,
        "model_type": first["model_type"],
        "covariance_estimator": first.get("covariance_estimator"),
        "dfcom": None if math.isinf(dfcom) else dfcom,
        "dfcom_basis": "asymptotic" if asymptotic else first.get("df_method"),
        "confidence_level": 1.0 - alpha,
        "nobs": first.get("nobs"),
        "param_names": names,
        "terms": terms,
        "ubar": ubar.tolist(),
        "between": between.tolist(),
        "total": total.tolist(),
    }


def pooled_kernel_reason(m: int) -> str:
    """Why post-estimation on a pooled result is refused (design section 3.3)."""
    return (
        f"This result pools m = {m} imputations by Rubin's rules. A test of several coefficients "
        "on pooled estimates needs the D1 statistic (Li, Raghunathan and Rubin 1991), which is "
        "not implemented yet; each coefficient's own pooled t test is in the result."
    )
