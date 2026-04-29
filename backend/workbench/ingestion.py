from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from .artifacts import register_artifact
from .config import WorkbenchConfig


def ingest_files(
    paths: list[Path], run_root: Path, config: WorkbenchConfig
) -> dict[str, pd.DataFrame]:
    if len(paths) > config.max_upload_files:
        raise ValueError(
            f"upload file count exceeds limit: {len(paths)} > {config.max_upload_files}"
        )
    frames: dict[str, pd.DataFrame] = {}
    for path in paths:
        size_gb = path.stat().st_size / (1024**3)
        if size_gb > config.max_single_file_gb:
            raise ValueError(f"file exceeds size limit: {path.name}")
        target = run_root / "raw_snapshot" / path.name
        shutil.copy2(path, target)
        register_artifact(run_root, f"raw_{path.name}", target, "raw_data", "ingestion", [])
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(target)
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            excel = pd.ExcelFile(target)
            if len(excel.sheet_names) > config.max_excel_sheets:
                raise ValueError(f"excel sheet count exceeds limit: {path.name}")
            frame = pd.read_excel(target, sheet_name=excel.sheet_names[0])
        else:
            raise ValueError(f"unsupported file type: {path.suffix}")
        if len(frame) > config.max_rows:
            raise ValueError(f"row count exceeds limit: {path.name}")
        frames[path.name] = frame
    return frames
