"""Shared formula preparation and result normalization for model-owned fits."""
from __future__ import annotations
from typing import Any
import pandas as pd
from ..formula_terms import quote_column

def _formula_term(column: str, categorical: bool = False) -> str:
    quoted = quote_column(column)
    if categorical:
        return f"C({quoted})"
    return quoted



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



def _ensure_numeric_x(frame: pd.DataFrame, x: list[str]) -> pd.DataFrame:
    for col in x:
        if col not in frame.columns:
            continue
        series = frame[col]
        if pd.api.types.is_numeric_dtype(series):
            continue
        converted = pd.to_numeric(series, errors="coerce")
        if converted.notna().sum() > 0:
            frame[col] = converted
    return frame



def _add_engine(result: dict[str, Any], *, engine: str = "statsmodels") -> dict[str, Any]:
    result["engine"] = engine
    return result



def _root_cause_suffix(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = type(exc).__name__
    return f" Root cause: {message[:200]}"



def _attach_average_marginal_effects(result: dict[str, Any], fitted: Any) -> dict[str, Any]:
    """Add average marginal effects to a GLM-family result.

    logit, probit and poisson report coefficients on the log-odds or log-rate
    scale, which nobody interprets directly -- so without this the last step of
    the analysis was left for the user to do by hand, while ordinal and
    multinomial runs already carried it.

    The record shape is deliberately identical to the one those two families
    emit, so a consumer reads marginal effects the same way everywhere rather
    than learning a second layout.  Failure is non-fatal: a model that cannot
    produce them still returns its estimates, with the reason recorded.
    """
    from .normalize import _public_term

    try:
        frame = fitted.get_margeff(at="overall").summary_frame()
        records = frame.reset_index().to_dict(orient="records")
        for record in records:
            # statsmodels labels rows with the formula term, `Q('x1')`, while
            # coefficients are keyed by the plain column. Leaving both shapes in
            # one payload would make marginal effects impossible to line up with
            # the estimates they belong to.
            raw = record.pop("index", None)
            term = _public_term(raw) if raw is not None else None
            record["term"] = term
            record["index"] = term
        result["marginal_effects"] = records
        result["marginal_effects_basis"] = "average_marginal_effect"
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        result["marginal_effects"] = []
        result["marginal_effects_unavailable_reason"] = type(exc).__name__
    return result
