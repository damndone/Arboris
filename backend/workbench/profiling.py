from __future__ import annotations

from typing import Any

import pandas as pd


def profile_frame(frame: pd.DataFrame) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    for name in frame.columns:
        series = frame[name]
        columns[str(name)] = {
            "dtype": str(series.dtype),
            "missing_rate": float(series.isna().mean()),
            "unique_count": int(series.nunique(dropna=True)),
            "unique_ratio": float(series.nunique(dropna=True) / max(len(series), 1)),
        }
        if pd.api.types.is_numeric_dtype(series):
            columns[str(name)]["mean"] = (
                None if series.dropna().empty else float(series.mean())
            )
            columns[str(name)]["std"] = (
                None if series.dropna().empty else float(series.std())
            )
    numeric = frame.select_dtypes(include="number")
    correlations = (
        numeric.corr(numeric_only=True).fillna(0.0).to_dict()
        if len(numeric.columns)
        else {}
    )
    return {
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": columns,
        "correlations": correlations,
    }
