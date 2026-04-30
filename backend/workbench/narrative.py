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
            direction = "positive" if numeric_estimate >= 0 else "negative"
            claim: dict[str, Any] = {
                "claim": f"{term} has a {direction} coefficient in {model_id}",
                "source_id": source_id,
            }
            p_value = _as_float(coefficient.get("p_value"))
            if p_value is not None:
                claim["confidence"] = max(0.0, min(1.0, 1.0 - p_value))
            claims.append(claim)

    for warning in warnings:
        message = warning.get("message") if isinstance(warning, Mapping) else str(warning)
        claims.append({"claim": message, "source_id": "errors.json", "confidence": 1.0})

    return claims


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
