from __future__ import annotations

from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from .normalize import _json_safe_float, normalize_statsmodels_result


def _formula_term(column: str) -> str:
    return f"Q({column!r})"


def _ols_formula(y: str, terms: list[str]) -> str:
    return f"{_formula_term(y)} ~ {' + '.join(terms)}"


def _ensure_numeric_y(frame: pd.DataFrame, y: str) -> pd.DataFrame:
    series = frame[y]
    if pd.api.types.is_numeric_dtype(series):
        return frame
    converted = pd.to_numeric(series, errors="coerce")
    if converted.isna().all():
        cleaned = series.astype(str).str.replace(r"[$,€£¥\s%]", "", regex=True)
        converted = pd.to_numeric(cleaned, errors="coerce")
    if converted.isna().all():
        raise ValueError(
            f"Column '{y}' is non-numeric and could not be converted. "
            f"Check that the correct sheet, column, and transpose setting are selected."
        )
    frame[y] = converted
    return frame


def run_ols(
    frame: pd.DataFrame, y: str, x: list[str], robust: bool, model_id: str
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    formula = _ols_formula(y, [_formula_term(column) for column in x])
    original = smf.ols(formula=formula, data=frame).fit()
    fitted = original.get_robustcov_results(cov_type="HC1") if robust else original
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "ols_robust" if robust else "ols"
    return result, original


def run_logit(
    frame: pd.DataFrame, y: str, x: list[str], model_id: str
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    formula = _ols_formula(y, [_formula_term(column) for column in x])
    try:
        fitted = smf.logit(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        raise ValueError(
            f"Logit model {model_id} failed to fit (possible perfect separation). "
            f"Try OLS (Linear Probability Model) instead."
        ) from exc
    if not getattr(fitted, "converged", True):
        raise ValueError(
            f"Logit model {model_id} did not converge. "
            f"Try OLS (Linear Probability Model) instead."
        )
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "logit"
    return result, fitted


def run_poisson(
    frame: pd.DataFrame, y: str, x: list[str], model_id: str
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    series = frame[y].dropna()
    if (series < 0).any():
        raise ValueError(
            f"Poisson model requires non-negative y, "
            f"but column '{y}' has negative values."
        )
    if not pd.api.types.is_numeric_dtype(series):
        raise ValueError(
            f"Poisson model requires numeric y, "
            f"but column '{y}' is non-numeric."
        )
    if not (series == series.astype(int)).all():
        raise ValueError(
            f"Poisson model requires integer y (counts), "
            f"but column '{y}' has non-integer values."
        )
    formula = _ols_formula(y, [_formula_term(column) for column in x])
    fitted = smf.poisson(formula=formula, data=frame).fit(disp=False, maxiter=100)
    if not getattr(fitted, "converged", True):
        raise ValueError(
            f"Poisson model {model_id} did not converge."
        )
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "poisson"
    return result, fitted


def run_fixed_effects(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str | None,
    model_id: str,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    terms = [_formula_term(column) for column in x]
    terms.append(f"C({_formula_term(entity)})")
    if time is not None:
        terms.append(f"C({_formula_term(time)})")
    fitted = smf.ols(formula=_ols_formula(y, terms), data=frame).fit()
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "fixed_effects"
    return result, fitted


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
