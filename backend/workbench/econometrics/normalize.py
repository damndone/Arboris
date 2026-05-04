from __future__ import annotations

from typing import Any

import pandas as pd


def _public_term(label: Any) -> str:
    term = str(label)
    if term.startswith("Q('") and term.endswith("')"):
        return term[3:-2]
    if term.startswith('Q("') and term.endswith('")'):
        return term[3:-2]
    return term


def _json_safe_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _json_safe_sequence(values: Any) -> list[float | None]:
    try:
        iterable = list(values)
    except TypeError:
        return []
    return [_json_safe_float(value) for value in iterable]


def _labelled_values(fitted: Any, name: str) -> dict[str, Any]:
    values = getattr(fitted, name)
    if hasattr(values, "items"):
        return {_public_term(label): value for label, value in values.items()}
    labels = getattr(getattr(fitted, "model", None), "exog_names", [])
    return {
        _public_term(label): value
        for label, value in zip(labels, values, strict=False)
    }


def _confidence_intervals(fitted: Any) -> tuple[dict[str, float], dict[str, float]]:
    try:
        ci = fitted.conf_int()
        labels = getattr(getattr(fitted, "model", None), "exog_names", None)
        if labels is None:
            labels = [fitted.model.data.param_names[i] for i in range(ci.shape[0])] if hasattr(fitted.model.data, "param_names") else []
        lower: dict[str, float] = {}
        upper: dict[str, float] = {}
        for i in range(ci.shape[0]):
            row = ci[i] if hasattr(ci, "iloc") else ci[i]
            lo = float(row[0]) if len(row) >= 2 else None
            hi = float(row[1]) if len(row) >= 2 else None
            term = _public_term(labels[i]) if i < len(labels) else f"x{i}"
            if lo is not None:
                lower[term] = lo
            if hi is not None:
                upper[term] = hi
        return lower, upper
    except Exception:
        return {}, {}


def _odds_ratios(
    fitted: Any, params: dict[str, float]
) -> dict[str, dict[str, float | None]]:
    import math

    or_dict: dict[str, dict[str, float | None]] = {}
    for term, coef in params.items():
        try:
            or_val = math.exp(float(coef))
            or_dict[term] = {"odds_ratio": round(or_val, 4)}
        except Exception:
            or_dict[term] = {"odds_ratio": None}
    return or_dict


def normalize_statsmodels_result(fitted: Any, model_id: str) -> dict[str, Any]:
    params = _labelled_values(fitted, "params")
    bse = _labelled_values(fitted, "bse")
    pvalues = _labelled_values(fitted, "pvalues")
    ci_lower, ci_upper = _confidence_intervals(fitted)
    has_pr2 = getattr(fitted, "prsquared", None) is not None
    odds_or = _odds_ratios(fitted, params) if has_pr2 else {}
    result: dict[str, Any] = {
        "model_id": model_id,
        "nobs": int(fitted.nobs),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "pseudo_r2": _json_safe_float(getattr(fitted, "prsquared", None)),
        "llf": _json_safe_float(getattr(fitted, "llf", None)),
        "aic": _json_safe_float(getattr(fitted, "aic", None)),
        "bic": _json_safe_float(getattr(fitted, "bic", None)),
        "fitted_values": _json_safe_sequence(getattr(fitted, "fittedvalues", [])),
        "residuals": _json_safe_sequence(getattr(fitted, "resid", [])),
        "coefficients": {
            term: {
                "estimate": _json_safe_float(estimate),
                "std_error": _json_safe_float(bse.get(term)),
                "p_value": _json_safe_float(pvalues.get(term)),
                "ci_lower": _json_safe_float(ci_lower.get(term)),
                "ci_upper": _json_safe_float(ci_upper.get(term)),
                "source_id": f"model_results.{model_id}.coefficients.{term}",
            }
            for term, estimate in params.items()
        },
    }
    if odds_or:
        result["odds_ratios"] = odds_or
    return result
