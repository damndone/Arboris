"""What an Agent reading of a coefficient says about whether the rows identify it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .requests import _MAX_PUBLIC_MODEL_PREDICTORS


def _unidentified_note(coefficient: Mapping[str, Any]) -> dict[str, Any]:
    """Flag a coefficient whose standard error is exactly zero.

    The least-squares pseudo-inverse still returns a number for a term that is constant
    on the analysis rows or an exact combination of the others: QRData 355 (6af0a0da
    round) read such a term as an effect of 0.00 with standard error 0. OLS now omits
    such a term; this still covers results written before that and other estimators.
    """
    std_error = coefficient.get("std_error")
    if isinstance(std_error, bool) or not isinstance(std_error, (int, float)) or std_error != 0:
        return {}
    return {
        "identified": False,
        "note": ("standard error is exactly 0: this term is constant on the analysis rows or an exact "
                 "combination of the other terms, so its estimate is not identified and is not an effect. "
                 "Check how the column was built."),
    }


_NOT_IDENTIFIED_NOTE = (
    "not identified: other terms determine this category level exactly on the analysis rows, so its "
    "estimate is one arbitrary split of a shared effect and is not an effect. Drop or merge the overlapping term."
)


def _omitted_terms(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Terms the fit omitted, Stata's way, because they add nothing to the terms before them."""
    omitted = result.get("omitted_terms")
    if not isinstance(omitted, list):
        return []
    reasons = {
        "zero_variance": "constant on the analysis rows",
        "perfect_collinearity": "an exact combination of the terms before it on the analysis rows",
    }
    return [
        {
            "variable": entry.get("variable"),
            "term": entry.get("term"),
            "reason": f"omitted: {reasons.get(entry.get('reason'), 'not identified')}; it has no estimate",
        }
        for entry in omitted[:_MAX_PUBLIC_MODEL_PREDICTORS]
        if isinstance(entry, dict)
    ]


def _identification_fields(result: Mapping[str, Any], term: str, coefficient: Mapping[str, Any]) -> dict[str, Any]:
    """`identified: False` and why, for a coefficient the rows cannot pin down; else nothing."""
    not_identified = result.get("not_identified_terms")
    if isinstance(not_identified, list) and term in not_identified:
        return {"identified": False, "note": _NOT_IDENTIFIED_NOTE}
    return _unidentified_note(coefficient)

