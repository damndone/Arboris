"""Numerical implementations owned by this model family pack."""
from __future__ import annotations
from typing import Any
import pandas as pd
import statsmodels.formula.api as smf
from ....econometrics.normalize import normalize_statsmodels_result
from ....econometrics.fit_support import (
    _formula_term, _ols_formula, _ensure_numeric_y, _ensure_numeric_x,
    _add_engine, _root_cause_suffix, _attach_average_marginal_effects,
)

def run_logit(
    frame: pd.DataFrame, y: str, x: list[str], model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.logit(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        _raise_if_separated("Logit", model_id, smf.logit(formula=formula, data=frame))
        raise ValueError(
            f"Logit model {model_id} failed to fit. "
            f"Try OLS (Linear Probability Model) instead."
        ) from exc
    if not getattr(fitted, "converged", True):
        _raise_if_separated("Logit", model_id, fitted.model)
        raise ValueError(
            f"Logit model {model_id} did not converge. "
            f"Try OLS (Linear Probability Model) instead."
        )
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "logit"
    _attach_average_marginal_effects(result, fitted)
    return _add_engine(result), fitted



def _raise_if_separated(label: str, model_id: str, model: Any) -> None:
    """Name separation as the reason a binary fit failed, when it is."""
    from ....checks.fit_checks import separation_reason

    try:
        reason = separation_reason(model)
    except Exception:  # noqa: BLE001 - the original failure message still stands
        return
    if reason:
        raise ValueError(f"{label} model {model_id} cannot be estimated: {reason}.")



def run_probit(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.probit(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        _raise_if_separated("Probit", model_id, smf.probit(formula=formula, data=frame))
        raise ValueError(
            f"Probit model {model_id} failed to fit. "
            f"Check binary outcome values and predictors.{_root_cause_suffix(exc)}"
        ) from exc
    if not getattr(fitted, "converged", True):
        _raise_if_separated("Probit", model_id, fitted.model)
        raise ValueError(f"Probit model {model_id} did not converge.")
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "probit"
    _attach_average_marginal_effects(result, fitted)
    return _add_engine(result), fitted
