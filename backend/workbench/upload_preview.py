"""Preview a CSV or Excel upload with the reader the run imports it with.

The browser once parsed these itself with a spreadsheet library that had known
vulnerabilities, on its main thread, and typed and transposed them differently
from the import (2026-11-06 risk review, finding 4). The server parses in a child
process it stops after ``PREVIEW_TIMEOUT_S``.
"""

from __future__ import annotations

import math
import multiprocessing
from pathlib import Path
from typing import Any

PREVIEW_TIMEOUT_S = 60.0
TABULAR_SUFFIXES = frozenset({".csv", ".xlsx", ".xls"})


class PreviewTimeout(Exception):
    """The child process did not finish within PREVIEW_TIMEOUT_S."""


class PreviewUnreadable(Exception):
    """The file could not be read as the import would read it."""


def json_rows(frame) -> list[dict[str, Any]]:
    import pandas as pd

    def cell(value: object) -> object:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if hasattr(value, "item"):
            return value.item()
        return value

    return [{str(column): cell(value) for column, value in record.items()}
            for record in frame.astype(object).where(frame.notna(), None).to_dict(orient="records")]


def preview_table(path: str, *, sheet_name: str | None, transpose: bool, row_limit: int,
                  max_rows: int, max_sheets: int) -> dict[str, Any]:
    import pandas as pd

    from .ingestion import check_spreadsheet_archive, read_frame_bounded, transposed_upload

    source = Path(path)
    suffix = source.suffix.lower()
    sheet_names: list[str] = []
    if suffix in {".xlsx", ".xls"}:
        if suffix == ".xlsx":
            check_spreadsheet_archive(source)
        with pd.ExcelFile(source) as excel:
            sheet_names = [str(name) for name in excel.sheet_names]
    selected = (sheet_name or sheet_names[0]) if sheet_names else None
    if transpose:
        # The import transposes the whole table; so does its preview.
        frame, truncated = read_frame_bounded(source, max_rows=max_rows, max_excel_sheets=max_sheets,
                                              sheet_name=selected)
        if truncated:
            raise ValueError(f"row count exceeds limit: {source.name}")
        frame = transposed_upload(frame)
        total_rows = len(frame)
        frame = frame.iloc[:row_limit]
    else:
        frame, truncated = read_frame_bounded(source, max_rows=row_limit, max_excel_sheets=max_sheets,
                                              sheet_name=selected)
        total_rows = len(frame)
        if truncated:
            counted = (pd.read_csv(source, usecols=[0]) if suffix == ".csv"
                       else pd.read_excel(source, sheet_name=selected, usecols=[0]))
            total_rows = len(counted)
    return {"columns": [str(column) for column in frame.columns], "rows": json_rows(frame),
            "total_rows": int(total_rows), "sheet_names": sheet_names, "selected_sheet": selected}


def _child(connection, path: str, options: dict[str, Any]) -> None:
    try:
        connection.send(("ok", preview_table(path, **options)))
    except Exception as exc:  # noqa: BLE001 - reported to the parent as unreadable
        connection.send(("error", str(exc) or type(exc).__name__))
    finally:
        connection.close()


def run_preview(path: Path, **options: Any) -> dict[str, Any]:
    """preview_table in a child process; stopped, not awaited, past the time limit."""

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(sender, str(path), options), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(PREVIEW_TIMEOUT_S):
            raise PreviewTimeout(f"preview did not finish within {PREVIEW_TIMEOUT_S:g} s")
        status, value = receiver.recv()
    except EOFError as exc:
        raise PreviewUnreadable("the preview process stopped without a result") from exc
    finally:
        if process.is_alive():
            process.kill()
        process.join()
        receiver.close()
    if status == "error":
        raise PreviewUnreadable(value)
    return value
