"""Marginal effects on the response scale, by the delta method.

The family declares how its linear predictor maps to the mean (its inverse
link); this module never asks which family it is. The gradient of each effect
with respect to the coefficients is analytic, so the standard errors do not
depend on a finite-difference step.

Average marginal effects (``at="average"``) average the derivative over the
estimation sample; effects at the means (``at="means"``) evaluate it once at
the sample means of the regressors. The two answer different questions and are
always labelled.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats

from .core import PostestimationRefusal

#: For each inverse link F: its derivative f = F' and second derivative f'.
def _identity(eta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.ones_like(eta), np.zeros_like(eta)


def _logit(eta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = 1.0 / (1.0 + np.exp(-eta))
    f = p * (1.0 - p)
    return f, f * (1.0 - 2.0 * p)


def _probit(eta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    f = stats.norm.pdf(eta)
    return f, -eta * f


def _log(eta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = np.exp(eta)
    return mu, mu


INVERSE_LINKS = {"identity": _identity, "logit": _logit, "probit": _probit, "log": _log}
AT_OPTIONS = ("average", "means")


def marginal_effects(
    kernel: Mapping[str, Any],
    design: Mapping[str, np.ndarray],
    *,
    inverse_link: str | None,
    variables: Sequence[str],
    at: str = "average",
    level: float = 0.95,
) -> dict[str, Any]:
    """dE[y]/dx for each requested regressor.

    ``design`` maps every coefficient name to its column of the estimation
    sample (the intercept to ones), in the kernel's parameter order.
    """
    if inverse_link is None:
        raise PostestimationRefusal(
            "PREDICTION_NOT_DECLARED",
            f"{kernel['model_type']} models do not declare how they predict from the coefficients "
            "alone (they need more, such as an exposure or thresholds), so marginal effects are not "
            "offered for them yet",
        )
    derivatives = INVERSE_LINKS.get(inverse_link)
    if derivatives is None:
        raise PostestimationRefusal("PREDICTION_NOT_DECLARED", f"unknown inverse link {inverse_link}")
    if at not in AT_OPTIONS:
        raise PostestimationRefusal("INVALID_SPEC", f"at must be one of {', '.join(AT_OPTIONS)}")
    if not 0 < level < 1:
        raise PostestimationRefusal("INVALID_LEVEL", "the confidence level must be between 0 and 1")
    if "coef_vcov" not in (kernel.get("interfaces") or []) or kernel.get("vcov_scope") != "full":
        raise PostestimationRefusal(
            "COVARIANCE_NOT_STORED",
            "marginal effects need the covariance of every coefficient, which was not stored for this model",
        )
    names = list(kernel["param_names"])
    if list(design) != names:
        raise PostestimationRefusal("DESIGN_MISMATCH", "the estimation data do not line up with the coefficients")
    requested = [str(name) for name in variables]
    if not requested:
        raise PostestimationRefusal("INVALID_SPEC", "name at least one regressor")
    unknown = [name for name in requested if name not in names]
    if unknown:
        raise PostestimationRefusal(
            "UNKNOWN_PARAMETER",
            f"{', '.join(unknown)} is not a regressor of this model; its regressors are {', '.join(names)}",
        )

    beta = np.asarray(kernel["params"], dtype=float)
    vcov = np.asarray(kernel["vcov"], dtype=float)
    matrix = np.column_stack([np.asarray(design[name], dtype=float) for name in names])
    if at == "means":
        matrix = matrix.mean(axis=0, keepdims=True)
    eta = matrix @ beta
    first, second = derivatives(eta)
    if not (np.all(np.isfinite(first)) and np.all(np.isfinite(second))):
        raise PostestimationRefusal("UNDEFINED_AT_ESTIMATE", "the prediction is not finite on the estimation data")

    mean_first = float(first.mean())
    # d/d beta of mean_i f(eta_i): mean_i f'(eta_i) x_i
    curvature = (second[:, None] * matrix).mean(axis=0)
    use_t = kernel.get("reference_distribution") == "t" and (kernel.get("df_resid") or 0) > 0
    df = float(kernel["df_resid"]) if use_t else None
    critical = float(stats.t.ppf(0.5 + level / 2, df) if use_t else stats.norm.ppf(0.5 + level / 2))
    effects = []
    for name in requested:
        j = names.index(name)
        estimate = mean_first * beta[j]
        gradient = curvature * beta[j]
        gradient[j] += mean_first
        std_error = math.sqrt(max(float(gradient @ vcov @ gradient), 0.0))
        statistic = estimate / std_error if std_error > 0 else math.nan
        p_value = (
            float(2 * (stats.t.sf(abs(statistic), df) if use_t else stats.norm.sf(abs(statistic))))
            if std_error > 0 else math.nan
        )
        effects.append({
            "variable": name,
            "estimate": float(estimate),
            "std_error": float(std_error),
            "statistic": float(statistic),
            "p_value": p_value,
            "ci": [float(estimate - critical * std_error), float(estimate + critical * std_error)],
        })
    return {
        "operation": "margins",
        "model_id": kernel["model_id"],
        "model_type": kernel["model_type"],
        "covariance_estimator": kernel.get("covariance_estimator"),
        "at": at,
        "label": "average marginal effect" if at == "average" else "marginal effect at the means",
        "scale": "response",
        "inverse_link": inverse_link,
        "nobs": int(len(next(iter(design.values())))) if design else 0,
        "distribution": "t" if use_t else "z",
        "df": df,
        "level": level,
        "effects": effects,
    }
