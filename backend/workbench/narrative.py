from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def build_claims(
    model_results: Iterable[Mapping[str, Any]],
    warnings: Iterable[Any],
    binary_vars: set[str] | None = None,
    suspicious_vars: set[str] | None = None,
    model_type: str = "ols",
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    is_logit = model_type in ("logit",)
    is_poisson = model_type in ("poisson",)
    if binary_vars is None:
        binary_vars = set()
    if suspicious_vars is None:
        suspicious_vars = set()

    for model_result in model_results:
        model_id = str(model_result.get("model_id", "model"))
        coefficients = model_result.get("coefficients", {})
        if not isinstance(coefficients, Mapping):
            continue
        dummy_count = 0
        for term, coefficient in coefficients.items():
            if term == "Intercept" or not isinstance(coefficient, Mapping):
                continue
            source_id = coefficient.get("source_id")
            if not source_id:
                continue
            estimate = coefficient.get("estimate")
            numeric_estimate = _as_float(estimate)
            if numeric_estimate is None:
                continue
            p_value = _as_float(coefficient.get("p_value"))
            significance = _significance_text(p_value)

            if _is_dummy_term(term) or _is_categorical_term(term):
                dummy_count += 1
                continue

            if term in binary_vars or term in suspicious_vars:
                if is_logit:
                    or_val = _format_or(_exp_float(numeric_estimate))
                    claim_text = (
                        f"In {model_id}, holding other variables constant, "
                        f"the presence of {term} is associated with "
                        f"{'higher' if numeric_estimate > 0 else 'lower'} odds of the outcome "
                        f"(log-odds coefficient = {numeric_estimate:+.4f}"
                        f"{', odds ratio ≈ ' + or_val if or_val else ''}); "
                        f"{significance}."
                    )
                else:
                    claim_text = (
                        f"In {model_id}, holding other selected regressors constant, "
                        f"the presence of {term} is associated with an average change of "
                        f"{numeric_estimate:+.4f} in the dependent variable "
                        f"compared to its absence; {significance}."
                    )
            else:
                if is_logit:
                    or_val = _format_or(_exp_float(numeric_estimate))
                    claim_text = (
                        f"In {model_id}, holding other variables constant, "
                        f"each one-unit increase in {term} is associated with "
                        f"{'higher' if numeric_estimate > 0 else 'lower'} log-odds of the outcome "
                        f"(coefficient = {numeric_estimate:.4f} on log-odds scale"
                        f"{', odds ratio ≈ ' + or_val if or_val else ''}); "
                        f"{significance}."
                    )
                else:
                    claim_text = (
                        f"In {model_id}, holding other selected regressors constant, "
                        f"each one-unit increase in {term} is "
                        f"associated with an average change of {numeric_estimate:.4f} "
                        f"in the dependent variable; {significance}."
                    )

            if term in suspicious_vars:
                claim_text += (
                    f" Note: '{term}' may be a diagnostic or noise variable. "
                    f"Its correlation with the outcome is very weak. "
                    f"Interpret with caution."
                )

            claim: dict[str, Any] = {
                "claim": claim_text,
                "source_id": source_id,
            }
            if p_value is not None:
                claim["confidence"] = max(0.0, min(1.0, 1.0 - p_value))
            claims.append(claim)
        if dummy_count > 0:
            claims.append({
                "claim": (
                    f"Model {model_id} contains {dummy_count} dummy/categorical "
                    f"coefficient(s) not individually listed (see coefficient table for full output)."
                ),
                "source_id": f"model_results.{model_id}",
                "confidence": 1.0,
            })
        r_squared = _as_float(
            model_result.get("r_squared") or model_result.get("pseudo_r2")
        )
        if r_squared is not None:
            has_pseudo = model_result.get("pseudo_r2") is not None
            label = "pseudo-R²" if has_pseudo else "R²"
            if has_pseudo:
                fit_text = (
                    f"Model {model_id} has a McFadden pseudo-R² of {r_squared:.4f}, "
                    f"indicating improved fit relative to an intercept-only model. "
                    f"This is not directly comparable to OLS R²."
                )
            else:
                fit_text = (
                    f"Model {model_id} (R²) explains {r_squared * 100:.1f}% "
                    "of dependent-variable variation."
                )
            claims.append(
                {
                    "claim": fit_text,
                    "source_id": (
                        f"model_results.{model_id}.pseudo_r2" if has_pseudo
                        else f"model_results.{model_id}.r_squared"
                    ),
                    "confidence": 1.0,
                }
            )

    for warning in warnings:
        message = warning.get("message") if isinstance(warning, Mapping) else str(warning)
        claims.append({"claim": message, "source_id": "errors.json", "confidence": 1.0})

    if _count_coefficients(model_results) > 5:
        claims.append({
            "claim": (
                "Statistical significance does not imply causality. With multiple "
                "predictors and tests, some variables may appear significant by chance. "
                "Consider the economic or domain relevance of each predictor "
                "alongside its p-value."
            ),
            "source_id": "interpretation.caution",
            "confidence": 1.0,
        })

    return claims


def _count_coefficients(model_results: Iterable[Mapping[str, Any]]) -> int:
    total = 0
    for m in model_results:
        coeffs = m.get("coefficients", {})
        if isinstance(coeffs, Mapping):
            total += len(coeffs)
    return total


def _is_dummy_term(term: str) -> bool:
    return "[T." in term


def _is_categorical_term(term: str) -> bool:
    return term.startswith("C(")


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _exp_float(value: float) -> float | None:
    try:
        result = math.exp(value)
        return result if math.isfinite(result) else None
    except (OverflowError, ValueError):
        return None


def _format_or(or_val: float | None) -> str:
    if or_val is None:
        return ""
    if or_val >= 100:
        return f"{or_val:.0f}"
    if or_val >= 10:
        return f"{or_val:.1f}"
    return f"{or_val:.4f}"


def _significance_text(p_value: float | None) -> str:
    if p_value is None:
        return "statistical significance was not reported"
    if p_value < 0.01:
        return "this is significant at the 1% level"
    if p_value < 0.05:
        return "this is significant at the 5% level"
    return "this does not reach conventional significance levels"
