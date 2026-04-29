from __future__ import annotations

from pathlib import Path

import pandas as pd

from .artifacts import write_json
from .domain import ColumnMetadata, DatasetSchema


TIME_TOKENS = ("date", "time", "timestamp", "year", "month", "quarter")
ID_TOKENS = ("id", "code", "key", "gvkey", "permno", "firm", "user", "store")


def infer_schema(
    dataset_id: str, frames: dict[str, pd.DataFrame], run_root: Path
) -> DatasetSchema:
    columns: list[ColumnMetadata] = []
    time_candidates: list[str] = []
    id_candidates: list[str] = []
    primary_key_candidates: list[str] = []
    for source_file, frame in frames.items():
        row_count = max(len(frame), 1)
        for name in frame.columns:
            series = frame[name]
            normalized = str(name).lower()
            dtype = str(series.dtype)
            evidence: list[str] = []
            role = "categorical"
            confidence = 0.5
            if pd.api.types.is_numeric_dtype(series):
                role = "numeric_measure"
                confidence = 0.7
            if any(token in normalized for token in TIME_TOKENS):
                role = "time"
                confidence = 0.85
                time_candidates.append(str(name))
                evidence.append("name_matches_time_token")
            if any(token in normalized for token in ID_TOKENS):
                role = "entity_id"
                confidence = 0.8
                id_candidates.append(str(name))
                evidence.append("name_matches_id_token")
            unique_ratio = float(series.nunique(dropna=True) / row_count)
            if unique_ratio == 1.0:
                primary_key_candidates.append(str(name))
                evidence.append("unique_column")
            columns.append(
                ColumnMetadata(str(name), dtype, role, confidence, source_file, evidence)
            )
    schema = DatasetSchema(
        dataset_id,
        list(frames.keys()),
        columns,
        primary_key_candidates,
        time_candidates,
        id_candidates,
    )
    write_json(run_root / "staged" / "metadata_registry.json", schema.to_dict())
    return schema
