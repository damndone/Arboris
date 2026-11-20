"""ATE, ATT and ATC by regression adjustment, inverse-probability weighting or doubly robust AIPW.

An OLS coefficient on the treatment is a variance-weighted average, not any of these when effects differ
across units; these estimators target the requested population directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
import math
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from workbench.contracts.treatment_effects import (
    TREATMENT_EFFECTS_CONTRACT,
    TREATMENT_EFFECTS_CONTRACT_VERSION,
    TREATMENT_EFFECTS_ESTIMANDS,
    TREATMENT_EFFECTS_METHODS,
)
from workbench.engine.packs.p7_common import make_p7_scope


class TreatmentEffectsError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _fail(code: str, message: str) -> None:
    raise TreatmentEffectsError(code, message)


def _nuisance(y: np.ndarray, t: np.ndarray, x: np.ndarray, trim: float, *, need_propensity: bool, need_outcome: bool):
    e = m0 = m1 = None
    if need_propensity:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = sm.Logit(t, x).fit(method="newton", maxiter=200, disp=False)
        if not fit.mle_retvals.get("converged", False):
            raise np.linalg.LinAlgError("the propensity model did not converge")
        e = np.clip(np.asarray(fit.predict(x)), trim, 1.0 - trim)
    if need_outcome:
        m0 = x @ np.linalg.lstsq(x[t == 0], y[t == 0], rcond=None)[0]
        m1 = x @ np.linalg.lstsq(x[t == 1], y[t == 1], rcond=None)[0]
    return e, m0, m1


def _weights(t: np.ndarray, e: np.ndarray, estimand: str) -> tuple[np.ndarray, np.ndarray]:
    """Weights on treated and control rows that reproduce the target population."""
    if estimand == "ATT":
        return t.astype(float), (1 - t) * e / (1 - e)
    if estimand == "ATC":
        return t * (1 - e) / e, (1.0 - t).astype(float)
    return t / e, (1 - t) / (1 - e)


def _point(y: np.ndarray, t: np.ndarray, x: np.ndarray, *, estimand: str, method: str, trim: float) -> tuple[float, np.ndarray | None, np.ndarray | None]:
    e, m0, m1 = _nuisance(y, t, x, trim, need_propensity=method != "ra", need_outcome=method != "ipw")
    if method == "ra":
        target = {"ATE": np.ones(len(t), dtype=bool), "ATT": t == 1, "ATC": t == 0}[estimand]
        return float(np.mean((m1 - m0)[target])), None, None
    w1, w0 = _weights(t, e, estimand)
    if method == "ipw":
        mean1, mean0 = np.sum(w1 * y) / np.sum(w1), np.sum(w0 * y) / np.sum(w0)
        psi = len(t) * (w1 * (y - mean1) / np.sum(w1) - w0 * (y - mean0) / np.sum(w0))
        # The propensity model is estimated too: stack its score, so the error is not left wide.
        d1 = -t * (1 - e) / e if estimand != "ATT" else 0.0
        d0 = (1 - t) * e / (1 - e) if estimand != "ATC" else 0.0
        slope = x.T @ (d1 * (y - mean1) / np.sum(w1) - d0 * (y - mean0) / np.sum(w0))
        information = (x * (e * (1 - e))[:, None]).T @ x / len(t)
        return float(mean1 - mean0), e, psi + (x * (t - e)[:, None]) @ np.linalg.solve(information, slope)
    # Normalized to the target population: the outcome models' contrast there, plus the weighted residuals they leave.
    population = {"ATE": np.ones(len(t)), "ATT": t.astype(float), "ATC": 1.0 - t}[estimand]
    scale = population.sum()
    residuals = w1 * (y - m1) / np.sum(w1) - w0 * (y - m0) / np.sum(w0)
    estimate = float(np.sum(population * (m1 - m0)) / scale + np.sum(residuals))
    # The contrast is centred within the target population: which units belong to it is not the effect's own noise.
    return estimate, e, len(t) * (population * (m1 - m0 - estimate) / scale + residuals)


def estimate_treatment_effect(
    frame: pd.DataFrame,
    *,
    treatment_column: str,
    outcome_column: str,
    covariate_columns: Sequence[str],
    estimand: str,
    method: str = "aipw",
    trim: float = 0.01,
    bootstrap_replications: int = 500,
    seed: int = 20261101,
    alpha: float = 0.05,
) -> dict[str, Any]:
    if estimand not in TREATMENT_EFFECTS_ESTIMANDS:
        _fail("TREATMENT_EFFECTS_INVALID_ESTIMAND", f"estimand must be one of {', '.join(TREATMENT_EFFECTS_ESTIMANDS)}")
    if method not in TREATMENT_EFFECTS_METHODS:
        _fail("TREATMENT_EFFECTS_INVALID_METHOD", f"method must be one of {', '.join(TREATMENT_EFFECTS_METHODS)}")
    if not 0 < trim < 0.5:
        _fail("TREATMENT_EFFECTS_INVALID_TRIM", "trim must lie strictly between 0 and 0.5")
    columns = [treatment_column, outcome_column, *covariate_columns]
    if treatment_column in covariate_columns or outcome_column in covariate_columns or len(set(columns)) != len(columns):
        _fail("TREATMENT_EFFECTS_INVALID_COLUMNS", "treatment, outcome and covariates must be different columns")
    non_numeric = [c for c in columns if not pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_bool_dtype(frame[c])]
    if non_numeric:
        _fail("TREATMENT_EFFECTS_NON_NUMERIC", f"these columns are not numeric: {', '.join(non_numeric)}. Encode them first.")
    values = frame.loc[:, columns].astype(float)
    infinite = [c for c in columns if np.isinf(values[c]).any()]
    if infinite:
        _fail("TREATMENT_EFFECTS_NON_FINITE", f"these columns hold infinite values: {', '.join(infinite)}")
    missing = {column: int(count) for column, count in values.isna().sum().items() if count}
    values = values.dropna()
    t = values[treatment_column].to_numpy()
    if set(np.unique(t)) != {0.0, 1.0}:
        _fail("TREATMENT_EFFECTS_TREATMENT", f"{treatment_column} must hold both 0 and 1; it holds {sorted(set(t.tolist()))[:6]}")
    y = values[outcome_column].to_numpy()
    x = np.column_stack((np.ones(len(values)), values.loc[:, list(covariate_columns)].to_numpy()))
    treated, controls = int(t.sum()), int((1 - t).sum())
    if min(treated, controls) <= x.shape[1]:
        _fail("TREATMENT_EFFECTS_TOO_FEW_ROWS", f"{treated} treated and {controls} control rows cannot fit {x.shape[1]} parameters in each group")
    for label, arm in (("treated", x[t == 1]), ("control", x[t == 0])):
        if np.linalg.matrix_rank(arm) < x.shape[1]:
            _fail("TREATMENT_EFFECTS_COLLINEAR", f"the covariates are collinear within the {label} group; drop the redundant ones")
    try:
        estimate, e, psi = _point(y, t, x, estimand=estimand, method=method, trim=trim)
    except (np.linalg.LinAlgError, ValueError) as exc:
        _fail("TREATMENT_EFFECTS_PROPENSITY", f"{exc}. Perfect separation is the usual cause; method ra does not use a propensity model.")
    n = len(values)
    if psi is not None:
        std_error = float(np.std(psi, ddof=1) / math.sqrt(n))
        se_method = "influence_function" if method == "aipw" else "influence_function_estimated_propensity"
    else:
        rng = np.random.default_rng(seed)
        draws = []
        for _ in range(bootstrap_replications):
            take = rng.integers(0, n, n)
            if 0 < t[take].sum() < n:
                draws.append(_point(y[take], t[take], x[take], estimand=estimand, method=method, trim=trim)[0])
        std_error = float(np.std(draws, ddof=1))
        se_method = f"bootstrap_{len(draws)}"
    z = float(stats.norm.ppf(1 - alpha / 2))
    result: dict[str, Any] = {
        "estimand": estimand, "method": method, "estimate": estimate, "std_error": std_error,
        "ci_lower": estimate - z * std_error, "ci_upper": estimate + z * std_error, "alpha": alpha, "se_method": se_method,
        "p_value": float(2 * stats.norm.sf(abs(estimate) / std_error)) if std_error > 0 else None,
        "treated_rows": treated, "control_rows": controls,
        "treatment_column": treatment_column, "outcome_column": outcome_column, "covariate_columns": list(covariate_columns),
    }
    if e is not None:
        fitted = e[(e > trim) & (e < 1 - trim)]
        w1, w0 = _weights(t, e, estimand)
        result["overlap"] = {
            "trim": trim, "rows_at_trim_bound": int(n - len(fitted)), "propensity_min": float(e.min()), "propensity_max": float(e.max()),
            "effective_treated": float(np.sum(w1) ** 2 / np.sum(w1 ** 2)), "effective_controls": float(np.sum(w0) ** 2 / np.sum(w0 ** 2)),
        }
    if missing:
        result["missing_rows"] = {"rows_total": len(frame), "rows_used": n, "missing_by_column": missing}
    result["scope"] = make_p7_scope(
        estimand=f"{estimand} of {treatment_column} on {outcome_column}",
        input_semantics="one row per unit, binary treatment, numeric covariates entered linearly",
        assumptions=["no unmeasured confounding given the covariates", "overlap between treated and controls", "no interference between units"],
        limitations=["propensity probabilities are clipped at the trim bound, not removed", "the data cannot confirm no unmeasured confounding"],
        not_claimed=["the covariates are sufficient to identify a causal effect"],
        unsupported_extensions=["survey weights, clusters, panels and continuous treatments are not included"],
    )
    return {
        "contract": TREATMENT_EFFECTS_CONTRACT, "contract_version": TREATMENT_EFFECTS_CONTRACT_VERSION,
        "operation_id": "treatment_effects.estimate", "status": "completed", "reason_code": "TREATMENT_EFFECTS_COMPLETED",
        "n_observations": n, "result": result,
    }


__all__ = ["TreatmentEffectsError", "estimate_treatment_effect"]
