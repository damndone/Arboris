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


def normalize_statsmodels_result(fitted: Any, model_id: str) -> dict[str, Any]:
    params = _labelled_values(fitted, "params")
    bse = _labelled_values(fitted, "bse")
    pvalues = _labelled_values(fitted, "pvalues")
    return {
        "model_id": model_id,
        "nobs": int(fitted.nobs),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "fitted_values": _json_safe_sequence(getattr(fitted, "fittedvalues", [])),
        "residuals": _json_safe_sequence(getattr(fitted, "resid", [])),
        "coefficients": {
            term: {
                "estimate": _json_safe_float(estimate),
                "std_error": _json_safe_float(bse.get(term)),
                "p_value": _json_safe_float(pvalues.get(term)),
                "source_id": f"model_results.{model_id}.coefficients.{term}",
            }
            for term, estimate in params.items()
        },
    }
