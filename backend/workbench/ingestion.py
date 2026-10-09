from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from .artifacts import register_artifact
from .config import WorkbenchConfig
from .tabular_io import STATISTICAL_FORMATS, read_table


def _ensure_unique_basenames(paths: list[Path]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for path in paths:
        if path.name in seen:
            duplicates.add(path.name)
        seen.add(path.name)
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate input filenames are not allowed: {names}")


_NUMERIC_HINT_TOKENS = frozenset({
    "year", "month", "age", "miles", "density", "score", "count",
    "claims", "days", "number", "num", "amount", "rate", "price",
    "cost", "value", "size", "weight", "volume", "sum",
})


def _coerce_datetime_to_numeric(frame: pd.DataFrame) -> None:
    for col in frame.columns:
        if not pd.api.types.is_datetime64_any_dtype(frame[col]):
            continue
        if not any(token in col.lower() for token in _NUMERIC_HINT_TOKENS):
            continue
        numeric = pd.to_numeric(frame[col], errors="coerce")
        good = numeric.notna().sum()
        total = len(numeric)
        if total > 0 and (good / total) >= 0.9:
            frame[col] = numeric


def _read_frame(
    path: Path,
    config: WorkbenchConfig,
    sheet_name: str | None = None,
    transpose: bool = False,
) -> pd.DataFrame:
    frame, truncated = read_frame_bounded(
        path,
        max_rows=config.max_rows,
        max_excel_sheets=config.max_excel_sheets,
        sheet_name=sheet_name,
    )
    if truncated:
        raise ValueError(f"row count exceeds limit: {path.name}")
    if transpose:
        frame = frame.transpose()
        frame.columns = frame.iloc[0]
        frame = frame.iloc[1:].reset_index(drop=True)
    return frame


def read_frame_bounded(
    path: Path,
    *,
    max_rows: int,
    max_excel_sheets: int = 32,
    sheet_name: str | None = None,
    file_suffix: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Read a supported tabular source with an explicit, observable row cap.

    The extra sentinel row makes truncation visible to inspection callers. It
    is deliberately read-only and does not accept a client-provided path
    policy; callers must resolve the path from a verified project identity.
    """

    if type(max_rows) is not int or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    if type(max_excel_sheets) is not int or max_excel_sheets < 1:
        raise ValueError("max_excel_sheets must be a positive integer")
    suffix = (file_suffix or path.suffix).lower()
    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=max_rows + 1)
    elif suffix in {".xlsx", ".xls"}:
        with pd.ExcelFile(path) as excel:
            if len(excel.sheet_names) > max_excel_sheets:
                raise ValueError(f"excel sheet count exceeds limit: {path.name}")
            target_sheet = sheet_name if sheet_name else excel.sheet_names[0]
            frame = pd.read_excel(excel, sheet_name=target_sheet, nrows=max_rows + 1)
        _coerce_datetime_to_numeric(frame)
    elif suffix in STATISTICAL_FORMATS:
        # Labels are not read here: they already travel with the run as
        # declared labels (see run_service._statistical_file_labels).
        frame = read_table(path, suffix=suffix, nrows=max_rows + 1)
        _coerce_datetime_to_numeric(frame)
    else:
        raise ValueError(f"unsupported file type: {path.suffix}")
    truncated = len(frame) > max_rows
    return frame.iloc[:max_rows].copy(), truncated


def _read_verified_dataset_parquet(
    path: Path, run_root: Path, config: WorkbenchConfig,
) -> pd.DataFrame:
    """Read only a server-bound, byte-identical selected dataset artifact.

    Parquet remains outside the public upload reader. Internal model dispatch
    may reuse a registered dataset without a lossy CSV conversion, but the
    persisted lineage and upload must identify these exact bytes.
    """
    from pyarrow.parquet import ParquetFile
    from .artifacts import sha256_file
    from .lineage.run_inputs import read_run_inputs
    from .statistical_exploration import resolve_statistical_source

    inputs = read_run_inputs(run_root)
    binding = inputs.get("dataset_source")
    if not isinstance(binding, dict):
        raise ValueError("parquet input requires a verified dataset source")
    digest = sha256_file(path)
    if digest != (inputs.get("upload") or {}).get("sha256"):
        raise ValueError("parquet input does not match the pinned run upload")
    # Inspect metadata before the source resolver reads any rows.
    if ParquetFile(path).metadata.num_rows > config.max_rows:
        raise ValueError(f"row count exceeds limit: {path.name}")
    source, frame = resolve_statistical_source(
        run_root.parent.parent,
        source_run_id=str(binding.get("source_run_id", "")),
        source_node_id=str(binding.get("op_node_id", "")),
        source_artifact_id=str(binding.get("source_artifact_id", "")),
    )
    if digest != source["source_sha256"] or (
        binding.get("source_sha256") is not None and binding["source_sha256"] != digest
    ):
        raise ValueError("parquet input does not match its registered dataset source")
    if len(frame) > config.max_rows:
        raise ValueError(f"row count exceeds limit: {path.name}")
    return frame


def ingest_files(
    paths: list[Path],
    run_root: Path,
    config: WorkbenchConfig,
    sheet_name: str | None = None,
    transpose: bool = False,
) -> dict[str, pd.DataFrame]:
    if len(paths) > config.max_upload_files:
        raise ValueError(
            f"upload file count exceeds limit: {len(paths)} > {config.max_upload_files}"
        )
    _ensure_unique_basenames(paths)
    frames: dict[str, pd.DataFrame] = {}
    for path in paths:
        size_gb = path.stat().st_size / (1024**3)
        if size_gb > config.max_single_file_gb:
            raise ValueError(f"file exceeds size limit: {path.name}")
        if path.suffix.lower() == ".parquet":
            if transpose or sheet_name:
                raise ValueError("verified dataset parquet cannot apply upload table transforms")
            frame = _read_verified_dataset_parquet(path, run_root, config)
        else:
            frame = _read_frame(path, config, sheet_name, transpose)
        target = run_root / "raw_snapshot" / path.name
        resolved_target = target.resolve()
        raw_snapshot_root = (run_root / "raw_snapshot").resolve()
        try:
            resolved_target.relative_to(raw_snapshot_root)
        except ValueError as exc:
            raise ValueError(f"raw snapshot path must stay inside raw_snapshot: {path.name}") from exc
        if resolved_target.exists():
            raise ValueError(f"raw snapshot already exists: {path.name}")
        shutil.copy2(path, target)
        register_artifact(
            run_root, f"raw_{path.name}", target, "raw_data", "ingestion", []
        )
        frames[path.name] = frame
    return frames
