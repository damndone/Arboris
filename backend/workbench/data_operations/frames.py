"""Reading, writing and describing the data files that operations produce."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal, Mapping
import pandas as pd
from ..artifacts import (
    register_artifact,
    read_json,
    sha256_file,
    write_bytes_durable,
    write_json,
    write_text_durable,
)
from ..tabular_io import TABULAR_SUFFIXES, read_table
from ..graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from ..predictive_research.contracts import FeatureRecipeV1
from ..predictive_research.feature_recipe import apply_feature_recipe
from .specs import DataCastTarget, DataColumnCastValidationError, _SCHEMA_SIDECAR_SUFFIX


def read_column_names(path: Path) -> list[str] | None:
    """A tabular artifact's column names without reading its rows; None when the format needs a full read."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [str(column) for column in pd.read_csv(path, nrows=0).columns]
    if suffix in {".parquet", ".pq"}:
        import pyarrow.parquet as parquet

        return [str(name) for name in parquet.read_schema(path).names]
    return None


def _read_frame(path: Path, *, stream: BinaryIO | None = None) -> pd.DataFrame:
    """Read a tabular artifact, restoring exact dtypes from a schema sidecar.

    CSV and Excel both lose pandas dtypes on read (a string column of digits
    re-infers as int64). When a derived artifact was written by a data
    operation we co-locate a ``<stem>.schema.json`` recording the exact dtypes,
    so re-reads (e.g. a chained cast on a cast child) are dtype-exact. Source
    artifacts without a sidecar (parquet is already self-describing) read as
    before.
    """

    suffix = path.suffix.lower()
    if suffix not in TABULAR_SUFFIXES:
        raise DataColumnCastValidationError(
            f"unsupported tabular artifact format: {path.suffix or '<none>'}"
        )
    # The source view passes its already-open, verified file. The path still
    # supplies the format and locates the separate schema sidecar.
    frame = read_table(stream if stream is not None else path, suffix=suffix)
    return _apply_schema_sidecar(path, frame)


def _schema_sidecar_path(data_path: Path) -> Path:
    return data_path.with_name(data_path.stem + _SCHEMA_SIDECAR_SUFFIX)


def _apply_schema_sidecar(data_path: Path, frame: pd.DataFrame) -> pd.DataFrame:
    sidecar = _schema_sidecar_path(data_path)
    if not sidecar.is_file():
        return frame
    dtypes = read_json(sidecar).get("dtypes", {})
    for column, dtype in dtypes.items():
        if column in frame.columns:
            frame[column] = _coerce_to_dtype(frame[column], str(dtype))
    return frame


def _coerce_to_dtype(series: pd.Series, dtype: str) -> pd.Series:
    if dtype.startswith("datetime64"):
        return pd.to_datetime(series, errors="coerce")
    try:
        return series.astype(dtype)
    except (TypeError, ValueError):
        return series


def _frame_dtypes(frame: pd.DataFrame) -> dict[str, str]:
    return {str(name): str(frame[name].dtype) for name in frame.columns}


def _write_frame_artifact(data_path: Path, frame: pd.DataFrame, fmt: str) -> None:
    """Write the derived data file plus its dtype sidecar, idempotently.

    The sidecar is written first so a crash never leaves a data file without
    its schema. The existence guard compares by re-read frame equality (not raw
    bytes) because xlsx serialization is not byte-deterministic. A CSV also
    matches on its text: a reshape's integer column labels come back from a CSV
    as strings, so the same result would not equal its own file.
    """

    write_json(_schema_sidecar_path(data_path), {"dtypes": _frame_dtypes(frame)})
    if data_path.exists():
        same_text = fmt == "csv" and data_path.read_text(encoding="utf-8") == frame.to_csv(index=False)
        if not same_text and not _read_frame(data_path).equals(frame):
            raise DataColumnCastValidationError(
                "deterministic cast artifact path is occupied"
            )
        return
    if fmt == "csv":
        write_text_durable(data_path, frame.to_csv(index=False))
    elif fmt == "xlsx":
        import io

        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        write_bytes_durable(data_path, buffer.getvalue())
    else:
        raise DataColumnCastValidationError(f"unsupported output format: {fmt!r}")


def _convert_strict(series: pd.Series, target_dtype: DataCastTarget) -> tuple[pd.Series, pd.Series]:
    if target_dtype == "numeric":
        converted = pd.to_numeric(series, errors="coerce")
    elif target_dtype == "datetime":
        converted = pd.to_datetime(series, errors="coerce")
    else:
        converted = series.astype("string")
    failures = series.notna() & converted.isna()
    return converted, failures


def _schema_fingerprint(frame: pd.DataFrame) -> str:
    payload = {
        "columns": [{"name": str(name), "dtype": str(frame[name].dtype)} for name in frame.columns],
        "row_count": len(frame),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "ALLOWED_CAST_TARGETS",
    "DataColumnCastPreview",
    "DataColumnCastSpecV1",
    "DataColumnCastValidationError",
    "DataColumnCastEffect",
    "DataCastItem",
    "DataColumnsCastSpecV1",
    "DataColumnCastItemResult",
    "DataColumnsCastPreview",
    "DataColumnsCastEffect",
    "apply_data_column_cast",
    "apply_data_columns_cast",
    "data_column_cast_execution_key",
    "data_columns_cast_execution_key",
    "preview_data_column_cast",
    "preview_data_columns_cast",
    "resolve_data_column_cast_context",
]
