from __future__ import annotations

from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from .normalize import normalize_statsmodels_result


def _formula_term(column: str) -> str:
    return f"Q({column!r})"


def _ols_formula(y: str, terms: list[str]) -> str:
    return f"{_formula_term(y)} ~ {' + '.join(terms)}"


def run_ols(
    frame: pd.DataFrame, y: str, x: list[str], robust: bool, model_id: str
) -> dict[str, Any]:
    formula = _ols_formula(y, [_formula_term(column) for column in x])
    fitted = smf.ols(formula=formula, data=frame).fit()
    if robust:
        fitted = fitted.get_robustcov_results(cov_type="HC1")
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "ols"
    return result


def run_fixed_effects(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str | None,
    model_id: str,
) -> dict[str, Any]:
    terms = [_formula_term(column) for column in x]
    terms.append(f"C({_formula_term(entity)})")
    if time is not None:
        terms.append(f"C({_formula_term(time)})")
    fitted = smf.ols(formula=_ols_formula(y, terms), data=frame).fit()
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "fixed_effects"
    return result


def run_time_series_diagnostics(
    frame: pd.DataFrame, y: str, time: str
) -> dict[str, float | None]:
    ordered = frame.sort_values(time)
    series = pd.to_numeric(ordered[y], errors="coerce")
    autocorrelation = series.autocorr(lag=1)
    if pd.isna(autocorrelation):
        autocorrelation = None
    return {
        "lag1_autocorrelation": None
        if autocorrelation is None
        else float(autocorrelation)
    }
