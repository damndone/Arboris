from __future__ import annotations

from typing import Any

import pandas as pd

from .config import WorkbenchConfig


def recommend_merge(left: pd.DataFrame, right: pd.DataFrame, config: WorkbenchConfig) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for column in sorted(set(left.columns).intersection(set(right.columns))):
        left_values = set(left[column].dropna().unique())
        right_values = set(right[column].dropna().unique())
        intersection = left_values.intersection(right_values)
        denominator = max(min(len(left_values), len(right_values)), 1)
        overlap = len(intersection) / denominator
        left_overlap = len(intersection) / max(len(left_values), 1)
        right_overlap = len(intersection) / max(len(right_values), 1)
        left_unique = left[column].dropna().is_unique
        right_unique = right[column].dropna().is_unique
        confidence = min(left_overlap, right_overlap)
        if left_unique or right_unique:
            confidence += 0.1
        join_type = (
            "inner"
            if overlap >= config.min_join_overlap
            and left_overlap >= config.min_join_overlap
            and right_overlap >= config.min_join_overlap
            else "left"
        )
        candidates.append(
            {
                "join_key": str(column),
                "join_type": join_type,
                "overlap": overlap,
                "left_overlap": left_overlap,
                "right_overlap": right_overlap,
                "confidence": min(confidence, 1.0),
            }
        )
    if not candidates:
        return {
            "join_key": "",
            "join_type": "none",
            "overlap": 0.0,
            "left_overlap": 0.0,
            "right_overlap": 0.0,
            "confidence": 0.0,
        }
    return max(candidates, key=lambda item: item["confidence"])
