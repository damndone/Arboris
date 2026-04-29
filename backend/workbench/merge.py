from __future__ import annotations

from typing import Any

import pandas as pd

from .config import WorkbenchConfig


def recommend_merge(left: pd.DataFrame, right: pd.DataFrame, config: WorkbenchConfig) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for column in sorted(set(left.columns).intersection(set(right.columns))):
        left_values = set(left[column].dropna().unique())
        right_values = set(right[column].dropna().unique())
        denominator = max(min(len(left_values), len(right_values)), 1)
        overlap = len(left_values.intersection(right_values)) / denominator
        left_unique = left[column].is_unique
        right_unique = right[column].is_unique
        confidence = overlap
        if left_unique or right_unique:
            confidence += 0.1
        candidates.append(
            {
                "join_key": str(column),
                "join_type": "inner" if overlap >= config.min_join_overlap else "left",
                "overlap": overlap,
                "confidence": min(confidence, 1.0),
            }
        )
    if not candidates:
        return {"join_key": "", "join_type": "none", "overlap": 0.0, "confidence": 0.0}
    return max(candidates, key=lambda item: item["confidence"])
