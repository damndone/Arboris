"""User-declared missing-value codes (SPSS "Missing Values", Stata extended missing).

A declaration maps a column to codes that mean "no valid answer": discrete
values (``-99``, ``"NA"``) and closed numeric ranges (``{"low": 900, "high":
999}``). Declared codes are turned into real missing values when the data enters
a run, before profiling, cleaning or any model sees them; the conversion counts
are recorded so the report can say exactly what was treated as missing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

FIELD = "user_missing_values"
MAX_CODES_PER_COLUMN = 64

Code = int | float | str | dict[str, float]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_code(column: str, code: object) -> Code:
    if isinstance(code, str):
        if not code:
            raise ValueError(f"{FIELD}.{column} codes must not be empty strings")
        return code
    if _is_number(code):
        if not math.isfinite(float(code)):
            raise ValueError(f"{FIELD}.{column} codes must be finite numbers")
        return code  # type: ignore[return-value]
    if isinstance(code, Mapping):
        if set(code) != {"low", "high"}:
            raise ValueError(f"{FIELD}.{column} ranges must have exactly low and high")
        low, high = code["low"], code["high"]
        if not (_is_number(low) and _is_number(high)) or not (
            math.isfinite(float(low)) and math.isfinite(float(high))
        ):
            raise ValueError(f"{FIELD}.{column} range bounds must be finite numbers")
        if float(low) > float(high):
            raise ValueError(f"{FIELD}.{column} range low must not exceed high")
        return {"low": low, "high": high}
    raise ValueError(
        f"{FIELD}.{column} codes must be numbers, strings or {{low, high}} ranges"
    )


def normalize_user_missing(value: object) -> dict[str, list[Code]]:
    """Validate a declaration; raise ValueError naming the field on any defect."""

    if not isinstance(value, Mapping):
        raise ValueError(f"labels.{FIELD} must be an object")
    normalized: dict[str, list[Code]] = {}
    for column, codes in value.items():
        if not isinstance(column, str) or not column:
            raise ValueError(f"labels.{FIELD} must map non-empty column names to codes")
        if not isinstance(codes, list) or not codes:
            raise ValueError(f"labels.{FIELD}.{column} must be a non-empty list")
        if len(codes) > MAX_CODES_PER_COLUMN:
            raise ValueError(
                f"labels.{FIELD}.{column} declares more than {MAX_CODES_PER_COLUMN} codes"
            )
        normalized[column] = [_normalize_code(column, code) for code in codes]
    return normalized


def _matches(series: pd.Series, code: Code) -> pd.Series:
    numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    if isinstance(code, dict):
        if not numeric:
            as_number = pd.to_numeric(series, errors="coerce")
            return as_number.between(code["low"], code["high"]).fillna(False)
        return series.between(code["low"], code["high"]).fillna(False)
    if numeric:
        if isinstance(code, str):
            try:
                code = float(code)
            except ValueError:
                return pd.Series(False, index=series.index)
        return series == code
    return series.astype("string") == str(code)


def code_mask(series: pd.Series, codes: list[Code]) -> pd.Series:
    """True where a value matches any of the declared codes."""

    mask = pd.Series(False, index=series.index)
    for code in codes:
        mask |= _matches(series, code)
    return mask


def apply_user_missing(
    frame: pd.DataFrame, declaration: Mapping[str, list[Code]]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return a copy with declared codes set to missing, plus a conversion record.

    Refuses a declaration naming a column the data does not have: applied to
    nothing, it would leave the user believing codes were excluded.
    """

    absent = sorted(column for column in declaration if column not in frame.columns)
    if absent:
        raise ValueError(
            f"labels.{FIELD} names column(s) not present in the data: " + ", ".join(absent)
        )
    result = frame.copy()
    columns: dict[str, Any] = {}
    for column, codes in declaration.items():
        mask = code_mask(result[column], codes)
        converted = int(mask.sum())
        if converted:
            result[column] = result[column].mask(mask)
        columns[column] = {"codes": list(codes), "converted": converted}
    return result, {"schema_version": 1, "columns": columns}
