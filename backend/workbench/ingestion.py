from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from .artifacts import register_artifact
from .config import WorkbenchConfig


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


def _read_frame(
    path: Path,
    config: WorkbenchConfig,
    sheet_name: str | None = None,
    transpose: bool = False,
) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=config.max_rows + 1)
    elif suffix in {".xlsx", ".xls"}:
        with pd.ExcelFile(path) as excel:
            if len(excel.sheet_names) > config.max_excel_sheets:
                raise ValueError(f"excel sheet count exceeds limit: {path.name}")
            target_sheet = sheet_name if sheet_name else excel.sheet_names[0]
            frame = pd.read_excel(excel, sheet_name=target_sheet, nrows=config.max_rows + 1)
    else:
        raise ValueError(f"unsupported file type: {path.suffix}")
    if len(frame) > config.max_rows:
        raise ValueError(f"row count exceeds limit: {path.name}")
    if transpose:
        frame = frame.transpose()
        frame.columns = frame.iloc[0]
        frame = frame.iloc[1:].reset_index(drop=True)
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
