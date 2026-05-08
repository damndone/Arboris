from __future__ import annotations

import re
from typing import Any

import pandas as pd


def normalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


def _unique_normalized_column_names(columns: pd.Index) -> tuple[list[str], list[dict[str, str]]]:
    counts: dict[str, int] = {}
    used: set[str] = set()
    normalized_columns: list[str] = []
    deduplicated: list[dict[str, str]] = []
    for column in columns:
        original = str(column)
        normalized = normalize_column_name(original)
        base = normalized or "column"
        counts[base] = counts.get(base, 0) + 1
        unique_name = base if counts[base] == 1 else f"{base}_{counts[base]}"
        while unique_name in used:
            counts[base] += 1
            unique_name = f"{base}_{counts[base]}"
        used.add(unique_name)
        normalized_columns.append(unique_name)
        if unique_name != normalized:
            deduplicated.append({"from": original, "to": unique_name})
    return normalized_columns, deduplicated


_NUMERIC_HEURISTIC_PATTERNS = (
    "year", "month", "age", "miles", "density", "score", "count",
    "claims", "days", "number", "num", "amount", "rate", "price",
    "cost", "value", "size", "weight", "volume", "sum",
)


def _coerce_numeric_like_columns(
    frame: pd.DataFrame,
    date_candidates: list[str],
    actions: list[dict[str, Any]],
) -> None:
    normalized_date_candidates = {normalize_column_name(c) for c in date_candidates}
    for col in list(frame.columns):
        if col in normalized_date_candidates:
            continue
        dtype = frame[col].dtype
        if pd.api.types.is_numeric_dtype(dtype):
            continue
        is_likely_numeric = any(pat in col.lower() for pat in _NUMERIC_HEURISTIC_PATTERNS)
        threshold = 0.80 if is_likely_numeric else 0.90
        numeric = pd.to_numeric(frame[col], errors="coerce")
        good = numeric.notna().sum()
        total = numeric.notna().sum() + numeric.isna().sum()
        if total > 0 and (good / total) >= threshold:
            frame[col] = numeric
            actions.append({
                "action": "coerce_to_numeric",
                "column": col,
                "original_dtype": str(dtype),
                "conversion_rate": round(good / total, 4),
            })


def clean_frame(frame: pd.DataFrame, date_candidates: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    cleaned = frame.copy()
    original_columns = list(cleaned.columns)
    normalized_columns, deduplicated = _unique_normalized_column_names(cleaned.columns)
    cleaned.columns = normalized_columns
    actions.append(
        {
            "action": "normalize_column_names",
            "details": {
                original: normalized
                for original, normalized in zip(original_columns, normalized_columns, strict=True)
            },
        }
    )
    if deduplicated:
        actions.append({"action": "deduplicate_column_names", "details": deduplicated})
    for candidate in date_candidates:
        normalized = normalize_column_name(candidate)
        for column in cleaned.columns:
            if column == normalized or column.startswith(f"{normalized}_"):
                if pd.api.types.is_numeric_dtype(cleaned[column]):
                    continue
                cleaned[column] = pd.to_datetime(cleaned[column], errors="coerce")
                actions.append({"action": "parse_date_candidate", "column": column})

    _coerce_numeric_like_columns(cleaned, date_candidates, actions)
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates()
    dropped = before - len(cleaned)
    if dropped:
        actions.append({"action": "drop_duplicate_rows", "rows_dropped": dropped})
    return cleaned, actions
