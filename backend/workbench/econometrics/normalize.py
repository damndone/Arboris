from __future__ import annotations

from typing import Any

import pandas as pd

# ============================================================
# AUTO-DETECTION (computed from data, dataset-agnostic):
#   - Coefficient rescaling: based on absolute coefficient size
#     to produce interpretable IRR / odds-ratio values
#   - Display estimate formatting: scientific notation for
#     tiny coefficients (|estimate| < 0.001, p < 0.05)
#   - Parameter labels: extracted from fitted model
#
# HARDCODED THRESHOLDS (configurable defaults):
#   _RESCALE_PER_10000 = 1e-5   # |coef| < 1e-5 → per 10,000
#   _RESCALE_PER_1000  = 0.0001  # |coef| < 0.0001 → per 1,000
#   _RESCALE_PER_100   = 0.01    # |coef| < 0.01 → per 100
#   Display estimate: |estimate| < 0.001 and p < 0.05
# ============================================================

_RESCALE_PER_1000_THRESHOLD = 0.0001  # |coef| < this → per-1,000
_RESCALE_PER_100_THRESHOLD = 0.01     # |coef| < this → per-100


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
            row = ci.iloc[i] if hasattr(ci, "iloc") else ci[i]
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


def _incidence_rate_ratios(
    fitted: Any,
    params: dict[str, float],
    ci_lower: dict[str, float],
    ci_upper: dict[str, float],
    pvalues: dict[str, float] | None = None,
) -> dict[str, dict[str, float | None]]:
    import math

    irr_dict: dict[str, dict[str, float | None]] = {}
    for idx, (term, coef) in enumerate(params.items()):
        try:
            irr_val = math.exp(float(coef))
            entry: dict[str, float | None] = {}
            p_val = _json_safe_float(pvalues.get(term)) if pvalues is not None else None
            coef_abs = abs(float(coef))
            if p_val is not None and p_val < 0.05:
                if coef_abs < 1e-5:
                    irr_per_10k = math.exp(10000 * float(coef))
                    pct_change = (irr_per_10k - 1) * 100
                    entry["irr"] = round(irr_per_10k, 6)
                    entry["irr_rescale_hint"] = f"Per 10,000 units: IRR = {irr_per_10k:.4f}"
                    entry["irr_pct_change"] = round(pct_change, 2)
                elif coef_abs < _RESCALE_PER_1000_THRESHOLD:
                    irr_per_1000 = math.exp(1000 * float(coef))
                    pct_change = (irr_per_1000 - 1) * 100
                    entry["irr"] = round(irr_per_1000, 6)
                    entry["irr_rescale_hint"] = f"Per 1,000 units: IRR = {irr_per_1000:.4f}"
                    entry["irr_pct_change"] = round(pct_change, 2)
                elif coef_abs < _RESCALE_PER_100_THRESHOLD:
                    irr_per_100 = math.exp(100 * float(coef))
                    entry["irr"] = round(irr_per_100, 4)
                    entry["irr_rescale_hint"] = f"Per 100 units: IRR = {irr_per_100:.4f}"
                else:
                    entry["irr"] = round(irr_val, 4)
            else:
                entry["irr"] = round(irr_val, 4)
            lo = ci_lower.get(term)
            hi = ci_upper.get(term)
            ci_terms_list = list(ci_lower.keys())
            if lo is None and idx < len(ci_terms_list):
                lo = ci_lower.get(ci_terms_list[idx])
            if hi is None and idx < len(ci_terms_list):
                hi = ci_upper.get(ci_terms_list[idx])
            if lo is not None:
                exp_lo = math.exp(float(lo))
                entry["irr_ci_lower"] = round(exp_lo, 4) if math.isfinite(exp_lo) else None
            else:
                entry["irr_ci_lower"] = None
            if hi is not None:
                exp_hi = math.exp(float(hi))
                entry["irr_ci_upper"] = round(exp_hi, 4) if math.isfinite(exp_hi) else None
            else:
                entry["irr_ci_upper"] = None
            irr_dict[term] = entry
        except Exception:
            irr_dict[term] = {"irr": None, "irr_ci_lower": None, "irr_ci_upper": None}
    return irr_dict


def _format_estimate_string(estimate: float, p_value: float | None) -> str | None:
    """Return scientific notation string for tiny coefficients near zero with p<0.05."""
    if p_value is None:
        return None
    if abs(estimate) < 0.001 and p_value < 0.05:
        return f"{estimate:.2e}"
    return None


def _is_poisson_model_id(model_id: str) -> bool:
    return model_id is not None and "poisson" in model_id.lower()


def _is_count_model(fitted: Any, model_id: str) -> bool:
    model = getattr(fitted, "model", None)
    family = getattr(model, "family", None)
    names = {
        type(model).__name__.lower(),
        type(family).__name__.lower(),
    }
    return _is_poisson_model_id(model_id) or any(
        name in {"poisson", "negativebinomial", "negativebinomialp"}
        for name in names
    )


def normalize_statsmodels_result(fitted: Any, model_id: str) -> dict[str, Any]:
    params = _labelled_values(fitted, "params")
    bse = _labelled_values(fitted, "bse")
    pvalues = _labelled_values(fitted, "pvalues")
    ci_lower, ci_upper = _confidence_intervals(fitted)
    has_pr2 = getattr(fitted, "prsquared", None) is not None
    is_count_model = _is_count_model(fitted, model_id)

    coefficients: dict[str, dict[str, Any]] = {}
    for term, estimate in params.items():
        estimate_float = _json_safe_float(estimate)
        p_value = _json_safe_float(pvalues.get(term))
        coef_entry: dict[str, Any] = {
            "estimate": estimate_float,
            "std_error": _json_safe_float(bse.get(term)),
            "p_value": round(p_value, 6) if p_value is not None else None,
            "ci_lower": _json_safe_float(ci_lower.get(term)),
            "ci_upper": _json_safe_float(ci_upper.get(term)),
            "source_id": f"model_results.{model_id}.coefficients.{term}",
        }
        if p_value is not None and round(p_value, 4) < 0.001:
            coef_entry["p_value_display"] = "< 0.001"
        formatted = _format_estimate_string(estimate_float, p_value) if estimate_float is not None else None
        if formatted is not None:
            coef_entry["display_estimate"] = formatted
        coefficients[term] = coef_entry

    fitted_values = _json_safe_sequence(getattr(fitted, "fittedvalues", []))
    residuals = _json_safe_sequence(getattr(fitted, "resid", []))
    result: dict[str, Any] = {
        "schema_version": 1,
        "model_id": model_id,
        "nobs": int(fitted.nobs),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "pseudo_r2": _json_safe_float(getattr(fitted, "prsquared", None)),
        "llf": _json_safe_float(getattr(fitted, "llf", None)),
        "aic": _json_safe_float(getattr(fitted, "aic", None)),
        "bic": _json_safe_float(getattr(fitted, "bic", None)),
        "fitted_values_preview": fitted_values[:500],
        "residuals_preview": residuals[:500],
        "coefficients": coefficients,
    }

    if has_pr2 or is_count_model:
        if is_count_model:
            count_irr = _incidence_rate_ratios(fitted, params, ci_lower, ci_upper, pvalues=pvalues)
            if count_irr:
                result["irr"] = count_irr
                for term, irr_data in count_irr.items():
                    if term in coefficients:
                        coefficients[term]["irr"] = irr_data.get("irr")
                        coefficients[term]["irr_ci_lower"] = irr_data.get("irr_ci_lower")
                        coefficients[term]["irr_ci_upper"] = irr_data.get("irr_ci_upper")
        elif has_pr2:
            odds_or = _odds_ratios(fitted, params)
            if odds_or:
                result["odds_ratios"] = odds_or
    return result
