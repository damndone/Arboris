from __future__ import annotations

from typing import Any

import pandas as pd

from .domain import DatasetKind


def classify_dataset(
    frame: pd.DataFrame, id_candidates: list[str], time_candidates: list[str]
) -> dict[str, Any]:
    ids = [column for column in id_candidates if column in frame.columns]
    times = [column for column in time_candidates if column in frame.columns]
    labels: list[str] = []
    if not times:
        return {
            "kind": DatasetKind.CROSS_SECTION.value,
            "confidence": 0.75,
            "secondary_labels": labels,
            "evidence": ["no_time_candidate"],
        }
    time_col = times[0]
    if ids:
        id_col = ids[0]
        duplicate_pairs = frame.duplicated(subset=[id_col, time_col]).any()
        if duplicate_pairs:
            return {
                "kind": DatasetKind.UNKNOWN_MIXED.value,
                "confidence": 0.4,
                "secondary_labels": ["id_time_not_unique"],
                "evidence": [f"{id_col}-{time_col} duplicates"],
            }
        counts = frame.groupby(id_col)[time_col].nunique()
        if counts.nunique() == 1:
            labels.append("panel_balanced")
        else:
            labels.append("panel_unbalanced")
        return {
            "kind": DatasetKind.PANEL.value,
            "confidence": 0.85,
            "secondary_labels": labels,
            "evidence": [f"id={id_col}", f"time={time_col}"],
        }
    per_time = frame.groupby(time_col).size()
    if len(per_time) > 1 and per_time.max() > 1:
        return {
            "kind": DatasetKind.REPEATED_CROSS_SECTION.value,
            "confidence": 0.7,
            "secondary_labels": ["multiple_observations_per_period"],
            "evidence": [f"time={time_col}"],
        }
    return {
        "kind": DatasetKind.TIME_SERIES.value,
        "confidence": 0.8,
        "secondary_labels": ["single_observation_per_period"],
        "evidence": [f"time={time_col}"],
    }
