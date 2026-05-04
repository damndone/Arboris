from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def build_claims(model_results: Iterable[Mapping[str, Any]], warnings: Iterable[Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []

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

            claim: dict[str, Any] = {
                "claim": (
                    f"In {model_id}, each one-unit increase in {term} is "
                    f"associated with an average change of {numeric_estimate:.4f} "
                    f"in the dependent variable; {significance}."
                ),
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
            label = "pseudo-R²" if model_result.get("pseudo_r2") is not None else "R²"
            claims.append(
                {
                    "claim": (
                        f"Model {model_id} ({label}) explains {r_squared * 100:.1f}% "
                        "of dependent-variable variation."
                    ),
                    "source_id": (
                        f"model_results.{model_id}.pseudo_r2"
                        if model_result.get("pseudo_r2") is not None
                        else f"model_results.{model_id}.r_squared"
                    ),
                    "confidence": 1.0,
                }
            )

    for warning in warnings:
        message = warning.get("message") if isinstance(warning, Mapping) else str(warning)
        claims.append({"claim": message, "source_id": "errors.json", "confidence": 1.0})

    return claims


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


def _significance_text(p_value: float | None) -> str:
    if p_value is None:
        return "statistical significance was not reported"
    if p_value < 0.01:
        return "this is significant at the 1% level"
    if p_value < 0.05:
        return "this is significant at the 5% level"
    return "this does not reach conventional significance levels"
