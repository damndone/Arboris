from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import stat
from pathlib import Path

import pandas as pd

from .artifacts import register_artifact
from .config import WorkbenchConfig
from . import data_interchange
from .data_interchange import InterchangeUnavailableError


class IngestionPathError(ValueError):
    """Raised when an ingestion path cannot be proven safe before writing."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class _RawSnapshotPreflight:
    source: Path
    target: Path
    run_root_identity: tuple[int, int]
    raw_snapshot_identity: tuple[int, int]
    source_identity: tuple[int, int]
    source_size: int


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _require_directory(path: Path, reason_code: str, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise IngestionPathError(reason_code, f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode):
        raise IngestionPathError(reason_code, f"{label} must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise IngestionPathError(reason_code, f"{label} must be a regular directory")
    return info


def _require_regular_file(path: Path, reason_code: str, label: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise IngestionPathError(reason_code, f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode):
        raise IngestionPathError(reason_code, f"{label} must not be a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise IngestionPathError(reason_code, f"{label} must be a regular file")
    return info


def _preflight_raw_snapshot(path: Path, run_root: Path) -> _RawSnapshotPreflight:
    run_info = _require_directory(run_root, "run_root_containment", "run root")
    raw_snapshot = run_root / "raw_snapshot"
    raw_info = _require_directory(
        raw_snapshot, "raw_snapshot_containment", "raw snapshot root"
    )
    source_info = _require_regular_file(path, "source_identity", "source file")
    target = raw_snapshot / path.name
    try:
        target_info = os.lstat(target)
    except FileNotFoundError:
        target_info = None
    except OSError as exc:
        raise IngestionPathError(
            "raw_snapshot_target", f"raw snapshot target cannot be checked: {path.name}"
        ) from exc
    if target_info is not None:
        if stat.S_ISLNK(target_info.st_mode):
            raise IngestionPathError(
                "raw_snapshot_target", f"raw snapshot target must not be a symlink: {path.name}"
            )
        if not stat.S_ISREG(target_info.st_mode):
            raise IngestionPathError(
                "raw_snapshot_target", f"raw snapshot target must be a regular file: {path.name}"
            )
        raise IngestionPathError(
            "raw_snapshot_duplicate", f"raw snapshot already exists: {path.name}"
        )
    try:
        target.resolve(strict=False).relative_to(run_root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise IngestionPathError(
            "raw_snapshot_containment",
            f"raw snapshot path must stay inside run root: {path.name}",
        ) from exc
    return _RawSnapshotPreflight(
        source=path,
        target=target,
        run_root_identity=_identity(run_info),
        raw_snapshot_identity=_identity(raw_info),
        source_identity=_identity(source_info),
        source_size=source_info.st_size,
    )


def _copy_raw_snapshot(preflight: _RawSnapshotPreflight) -> None:
    run_root = preflight.target.parent.parent
    raw_snapshot = preflight.target.parent
    run_info = _require_directory(run_root, "run_root_containment", "run root")
    raw_info = _require_directory(
        raw_snapshot, "raw_snapshot_containment", "raw snapshot root"
    )
    if _identity(run_info) != preflight.run_root_identity:
        raise IngestionPathError("run_root_identity", "run root identity changed before copy")
    if _identity(raw_info) != preflight.raw_snapshot_identity:
        raise IngestionPathError(
            "raw_snapshot_identity", "raw snapshot root identity changed before copy"
        )

    source_fd = -1
    raw_snapshot_fd = -1
    target_fd = -1
    target_identity: tuple[int, int] | None = None
    try:
        source_fd = os.open(preflight.source, os.O_RDONLY | os.O_NOFOLLOW)
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode) or _identity(source_info) != preflight.source_identity:
            raise IngestionPathError("source_identity", "source file identity changed before copy")
        raw_snapshot_fd = os.open(
            raw_snapshot,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        if _identity(os.fstat(raw_snapshot_fd)) != preflight.raw_snapshot_identity:
            raise IngestionPathError(
                "raw_snapshot_identity", "raw snapshot root identity changed before copy"
            )
        try:
            target_fd = os.open(
                preflight.target.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=raw_snapshot_fd,
            )
        except FileExistsError as exc:
            raise IngestionPathError(
                "raw_snapshot_duplicate", f"raw snapshot already exists: {preflight.target.name}"
            ) from exc
        target_info = os.fstat(target_fd)
        if not stat.S_ISREG(target_info.st_mode):
            raise IngestionPathError(
                "raw_snapshot_target", "raw snapshot target must be a regular file"
            )
        target_identity = _identity(target_info)
        with os.fdopen(source_fd, "rb", closefd=True) as source_handle:
            source_fd = -1
            with os.fdopen(target_fd, "wb", closefd=True) as target_handle:
                target_fd = -1
                shutil.copyfileobj(source_handle, target_handle)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        if _identity(os.fstat(raw_snapshot_fd)) != preflight.raw_snapshot_identity:
            raise IngestionPathError(
                "raw_snapshot_identity", "raw snapshot root identity changed after copy"
            )
        final_target = _require_regular_file(
            preflight.target, "raw_snapshot_target", "raw snapshot target"
        )
        if target_identity is None or _identity(final_target) != target_identity:
            raise IngestionPathError(
                "raw_snapshot_identity", "raw snapshot target identity changed after copy"
            )
        os.fsync(raw_snapshot_fd)
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if target_fd >= 0:
            os.close(target_fd)
        if raw_snapshot_fd >= 0:
            os.close(raw_snapshot_fd)


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
    elif suffix in {".parquet", ".pq"}:
        if data_interchange._parquet_engine() is None:
            raise InterchangeUnavailableError(
                data_interchange.interchange_capability("parquet")
            )
        parquet_adapter = data_interchange._parquet_adapter()
        if parquet_adapter is None:
            raise InterchangeUnavailableError(
                data_interchange._parquet_unavailable_capability()
            )
        pa, pq = parquet_adapter
        parquet_file = pq.ParquetFile(path)
        batches = parquet_file.iter_batches(batch_size=max_rows + 1)
        try:
            batch = next(batches)
            frame = pa.Table.from_batches([batch]).to_pandas()
        except StopIteration:
            frame = pa.Table.from_batches([], schema=parquet_file.schema_arrow).to_pandas()
    elif suffix in {".xlsx", ".xls"}:
        with pd.ExcelFile(path) as excel:
            if len(excel.sheet_names) > max_excel_sheets:
                raise ValueError(f"excel sheet count exceeds limit: {path.name}")
            target_sheet = sheet_name if sheet_name else excel.sheet_names[0]
            frame = pd.read_excel(excel, sheet_name=target_sheet, nrows=max_rows + 1)
        _coerce_datetime_to_numeric(frame)
    else:
        raise ValueError(f"unsupported file type: {path.suffix}")
    truncated = len(frame) > max_rows
    return frame.iloc[:max_rows].copy(), truncated


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
        preflight = _preflight_raw_snapshot(path, run_root)
        size_gb = preflight.source_size / (1024**3)
        if size_gb > config.max_single_file_gb:
            raise ValueError(f"file exceeds size limit: {path.name}")
        frame = _read_frame(path, config, sheet_name, transpose)
        _copy_raw_snapshot(preflight)
        register_artifact(
            run_root, f"raw_{path.name}", preflight.target, "raw_data", "ingestion", []
        )
        frames[path.name] = frame
    return frames
