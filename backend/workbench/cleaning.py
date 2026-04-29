from __future__ import annotations

import re
from typing import Any

import pandas as pd


def normalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


def clean_frame(frame: pd.DataFrame, date_candidates: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    cleaned = frame.copy()
    rename_map = {column: normalize_column_name(str(column)) for column in cleaned.columns}
    cleaned = cleaned.rename(columns=rename_map)
    actions.append({"action": "normalize_column_names", "details": rename_map})
    for candidate in date_candidates:
        normalized = normalize_column_name(candidate)
        if normalized in cleaned.columns:
            cleaned[normalized] = pd.to_datetime(cleaned[normalized], errors="coerce")
            actions.append({"action": "parse_date_candidate", "column": normalized})
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates()
    dropped = before - len(cleaned)
    if dropped:
        actions.append({"action": "drop_duplicate_rows", "rows_dropped": dropped})
    return cleaned, actions
