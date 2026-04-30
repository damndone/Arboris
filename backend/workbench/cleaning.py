from __future__ import annotations

import re
from typing import Any

import pandas as pd


def normalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


def _unique_normalized_column_names(columns: pd.Index) -> tuple[list[str], list[dict[str, str]]]:
    counts: dict[str, int] = {}
    normalized_columns: list[str] = []
    deduplicated: list[dict[str, str]] = []
    for column in columns:
        original = str(column)
        normalized = normalize_column_name(original)
        base = normalized or "column"
        counts[base] = counts.get(base, 0) + 1
        unique_name = base if counts[base] == 1 else f"{base}_{counts[base]}"
        normalized_columns.append(unique_name)
        if unique_name != normalized:
            deduplicated.append({"from": original, "to": unique_name})
    return normalized_columns, deduplicated


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
                cleaned[column] = pd.to_datetime(cleaned[column], errors="coerce")
                actions.append({"action": "parse_date_candidate", "column": column})
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates()
    dropped = before - len(cleaned)
    if dropped:
        actions.append({"action": "drop_duplicate_rows", "rows_dropped": dropped})
    return cleaned, actions
