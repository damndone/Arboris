from __future__ import annotations

from typing import Any

import pandas as pd


def _json_safe_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _numeric_summary(series: pd.Series) -> dict[str, float | None]:
    numeric = pd.to_numeric(series, errors="coerce")
    non_missing = numeric.dropna().astype("float64")
    if non_missing.empty:
        return {"mean": None, "std": None}
    return {
        "mean": _json_safe_float(non_missing.mean()),
        "std": _json_safe_float(non_missing.std()),
    }


def _json_safe_correlations(numeric: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    correlations = numeric.corr(numeric_only=True).to_dict()
    return {
        str(row): {
            str(column): _json_safe_float(value)
            for column, value in row_values.items()
        }
        for row, row_values in correlations.items()
    }


def profile_frame(frame: pd.DataFrame) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    for name in frame.columns:
        series = frame[name]
        row_count = len(series)
        columns[str(name)] = {
            "dtype": str(series.dtype),
            "missing_rate": 0.0 if row_count == 0 else float(series.isna().mean()),
            "unique_count": int(series.nunique(dropna=True)),
            "unique_ratio": float(series.nunique(dropna=True) / max(row_count, 1)),
        }
        if pd.api.types.is_numeric_dtype(series):
            columns[str(name)].update(_numeric_summary(series))
    numeric = frame.select_dtypes(include="number")
    correlations = _json_safe_correlations(numeric) if len(numeric.columns) else {}
    return {
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": columns,
        "correlations": correlations,
    }
