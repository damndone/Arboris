"""Native CSV and Stata writers that write the bytes pandas and pyreadstat write.

``write_csv`` reproduces ``frame.to_csv(path, index=False, encoding="utf-8")``:
float64, integer and bool columns are formatted natively (repr, decimal, True/False),
every other column through pandas' own per-chunk formatter, and the native writer then
applies csv.writer's QUOTE_MINIMAL rules.

``write_dta`` reproduces ``pyreadstat.write_dta(frame, path, **options)``. pyreadstat
spends its time in a Python loop over rows; the metadata it writes depends only on the
column types, string widths and labels. So pyreadstat itself writes the file for a one-row
surrogate frame that has those, and this module replaces the row count, the four map
offsets after the data and the data section. The surrogate's own row is checked against
the native encoder before anything is written.

Both return False whenever they cannot guarantee the reference's bytes, and the caller
then runs the reference, which also raises the reference's own errors.
"""
from __future__ import annotations

import csv
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import native_io

_CSV_FORMAT = {"na_rep": "", "float_format": None, "date_format": None, "quoting": csv.QUOTE_MINIMAL, "decimal": "."}
_PANDAS_CHUNK_CELLS = 100_000  # pandas.io.formats.csvs._DEFAULT_CHUNKSIZE_CELLS
_DTA_CHUNK_ROWS = 65_536
#: Rows per written .dta chunk also stay under this many bytes: 1,000 double columns at
#: 65,536 rows were about 500 MiB per chunk (2026-11-06 risk review, finding 5).
_DTA_CHUNK_BYTES = 64 * 2**20
_DTA_RELEASES = {13: b"117", 14: b"118", 15: b"119"}
_DTA_OPTIONS = frozenset({"version", "column_labels", "variable_value_labels"})
_DTA_DOUBLE, _DTA_LONG = 65526, 65528
_DTA_MAX_STR = 2045  # pyreadstat writes strL from here
_DTA_MAX_DOUBLE = 8.988465674311579e307
_STATA_EPOCH_SECONDS = 315619200  # 1960-01-01 in Unix seconds
_TIME_UNITS = {"ns": 10**9, "us": 10**6, "ms": 10**3}


# ------------------------------------------------------------------------------------- CSV

def _csv_numeric(values: np.ndarray) -> tuple[str, np.ndarray] | None:
    kind = values.dtype.kind
    if values.dtype == np.float64:
        return "f", np.ascontiguousarray(values)
    if kind == "i":
        return "i", np.ascontiguousarray(values, dtype=np.int64)
    if kind == "u":
        return "u", np.ascontiguousarray(values, dtype=np.uint64)
    if kind == "b":
        return "b", np.ascontiguousarray(values).view(np.uint8)
    return None


def write_csv(frame: pd.DataFrame, path: Path) -> bool:
    """Write ``frame.to_csv(path, index=False, encoding="utf-8")``'s bytes, or return False."""
    loaded = native_io.module()
    if loaded is None or isinstance(frame.columns, pd.MultiIndex) or frame.shape[1] == 0:
        return False
    terminator = os.linesep
    rows, width = frame.shape
    numeric: dict[int, tuple[str, np.ndarray]] = {}
    for position, dtype in enumerate(frame.dtypes):
        if isinstance(dtype, np.dtype):
            column = _csv_numeric(frame.iloc[:, position].to_numpy())
            if column is not None:
                numeric[position] = column
    formatted = [position for position in range(width) if position not in numeric]
    chunk = (_PANDAS_CHUNK_CELLS // width) or 1
    try:
        header = frame.columns._get_values_for_csv(**_CSV_FORMAT).tolist()
        with Path(path).open("wb") as stream:
            stream.write(loaded.csv_rows([("o", [label]) for label in header], 0, 1, 1, terminator))
            for start in range(0, rows, chunk):
                stop = min(start + chunk, rows)
                texts = {}
                if formatted:
                    # pandas formats each chunk on its own (dates choose their format per chunk).
                    values = frame.iloc[start:stop, formatted]._get_values_for_csv(**_CSV_FORMAT)
                    texts = {position: array.tolist()
                             for position, array in zip(formatted, values._iter_column_arrays(), strict=True)}
                specs = [(numeric[position][0], numeric[position][1][start:stop]) if position in numeric
                         else ("o", texts[position]) for position in range(width)]
                stream.write(loaded.csv_rows(specs, 0, stop - start, stop - start, terminator))
    except (UnicodeEncodeError, AttributeError, TypeError):
        # Text UTF-8 cannot hold, or a pandas without these internals: pandas writes (or raises).
        return False
    return True


# ------------------------------------------------------------------------------------- Stata

@dataclass(frozen=True)
class _DtaColumn:
    type_code: int
    surrogate_row: int
    rows: Callable[[int, int], tuple]  # native spec for rows [start, stop)


def _float_rows(series: pd.Series) -> Callable[[int, int], tuple]:
    def rows(start: int, stop: int) -> tuple:
        return ("d", np.ascontiguousarray(series.iloc[start:stop].to_numpy(dtype=np.float64, na_value=np.nan)))
    return rows


def _long_rows(series: pd.Series, nullable: bool) -> Callable[[int, int], tuple]:
    def rows(start: int, stop: int) -> tuple:
        part = series.iloc[start:stop]
        if not nullable:
            return ("l", np.ascontiguousarray(part.to_numpy(), dtype=np.int32), None)
        missing = part.isna().to_numpy()
        values = part.to_numpy(dtype=np.int32, na_value=0)
        return ("l", np.ascontiguousarray(values), np.ascontiguousarray(missing).view(np.uint8))
    return rows


def _datetime_rows(series: pd.Series, unit: str) -> Callable[[int, int], tuple]:
    # pyreadstat: whole = ticks // f + epoch; frac = ticks % f; whole * 1000 + frac / f * 1000.
    factor = _TIME_UNITS[unit]

    def rows(start: int, stop: int) -> tuple:
        ticks = series.iloc[start:stop].to_numpy().view(np.int64)
        whole = (ticks // factor + _STATA_EPOCH_SECONDS).astype(np.float64)
        fraction = (ticks % factor).astype(np.float64)
        values = whole * 1000 + fraction / factor * 1000
        values[ticks == np.iinfo(np.int64).min] = np.nan
        return ("d", values)
    return rows


def _text_rows(series: pd.Series, width: int) -> Callable[[int, int], tuple]:
    def rows(start: int, stop: int) -> tuple:
        return ("s", series.iloc[start:stop].to_numpy(dtype=object, na_value=None).tolist(), width)
    return rows


def _text_extent(series: pd.Series, loaded) -> tuple[int, int] | None:
    longest, at = -1, -1
    for start in range(0, len(series), _DTA_CHUNK_ROWS):
        extent = loaded.utf8_extent(series.iloc[start:start + _DTA_CHUNK_ROWS].to_numpy(dtype=object, na_value=None).tolist())
        if extent is None:
            return None
        if extent[0] > longest:
            longest, at = extent[0], start + extent[1]
    return longest, at


def _dta_column(series: pd.Series, labelled: bool, loaded) -> _DtaColumn | None:
    """How pyreadstat stores this column, or None when only pyreadstat should write it."""
    dtype = series.dtype
    if isinstance(dtype, np.dtype):
        if dtype in (np.float64, np.float32, np.int64, np.uint32, np.uint64):
            return _DtaColumn(_DTA_DOUBLE, 0, _float_rows(series))
        if dtype.kind in "iub":
            return _DtaColumn(_DTA_LONG, 0, _long_rows(series, nullable=False))
        if dtype.kind == "M":
            unit = np.datetime_data(dtype)[0]
            return _DtaColumn(_DTA_DOUBLE, 0, _datetime_rows(series, unit)) if unit in _TIME_UNITS else None
    elif isinstance(dtype, (pd.Int8Dtype, pd.Int16Dtype, pd.Int32Dtype, pd.UInt8Dtype, pd.UInt16Dtype, pd.BooleanDtype)):
        return _DtaColumn(_DTA_LONG, 0, _long_rows(series, nullable=True))
    elif isinstance(dtype, (pd.Int64Dtype, pd.UInt32Dtype, pd.UInt64Dtype)):
        return _DtaColumn(_DTA_DOUBLE, 0, _float_rows(series))
    if labelled or not (isinstance(dtype, pd.StringDtype) or dtype == object):
        return None
    extent = _text_extent(series, loaded)
    if extent is None or (extent[0] < 0 and dtype == object):
        return None
    width = max(1, extent[0])
    if width >= _DTA_MAX_STR:
        return None
    return _DtaColumn(width, max(0, extent[1]), _text_rows(series, width))


@dataclass(frozen=True)
class _DtaLayout:
    n_at: int
    n_width: int
    map_at: int
    offsets: tuple[int, ...]
    type_codes: tuple[int, ...]
    data_at: int  # first byte after <data>
    data_end: int  # first byte of </data>


def _dta_layout(raw: bytes, release: bytes, columns: int) -> _DtaLayout | None:
    """The fields of a pyreadstat file that depend on its row count, after checking them."""
    head = b"<stata_dta><header><release>" + release + b"</release><byteorder>LSF</byteorder><K>"
    if not raw.startswith(head):
        return None
    k_width = 4 if release == b"119" else 2
    if int.from_bytes(raw[len(head):len(head) + k_width], "little") != columns:
        return None
    n_at = len(head) + k_width + len(b"</K><N>")
    n_width = 4 if release == b"117" else 8
    if raw[n_at - 7:n_at] != b"</K><N>" or raw[n_at + n_width:n_at + n_width + 4] != b"</N>":
        return None
    if int.from_bytes(raw[n_at:n_at + n_width], "little") != 1:
        return None
    map_at = raw.find(b"<map>") + 5
    if map_at < 5 or raw[map_at + 112:map_at + 118] != b"</map>":
        return None
    offsets = struct.unpack_from("<14Q", raw, map_at)
    types_at = offsets[2] + len(b"<variable_types>")
    if (offsets[0] != 0 or offsets[1] != map_at - 5 or offsets[13] != len(raw)
            or raw[offsets[2]:types_at] != b"<variable_types>"
            or raw[types_at + 2 * columns:types_at + 2 * columns + 17] != b"</variable_types>"
            or raw[offsets[9]:offsets[9] + 6] != b"<data>"
            or raw[offsets[10] - 7:offsets[10] + 7] != b"</data><strls>"
            or raw[offsets[11]:offsets[11] + 14] != b"<value_labels>"
            or raw[offsets[12]:offsets[12] + 12] != b"</stata_dta>"):
        return None
    type_codes = struct.unpack_from(f"<{columns}H", raw, types_at)
    return _DtaLayout(n_at, n_width, map_at, offsets, type_codes, offsets[9] + 6, offsets[10] - 7)


def _row_width(type_codes: tuple[int, ...]) -> int:
    return sum(8 if code == _DTA_DOUBLE else 4 if code == _DTA_LONG else code for code in type_codes)


def write_dta(frame: pd.DataFrame, path: Path, options: dict[str, Any], pyreadstat: Any) -> bool:
    """Write ``pyreadstat.write_dta(frame, path, **options)``'s bytes, or return False."""
    loaded = native_io.module()
    rows, width = frame.shape
    if (loaded is None or sys.byteorder != "little" or rows == 0 or width == 0
            or not set(options) <= _DTA_OPTIONS or options.get("version") not in _DTA_RELEASES
            or not all(type(name) is str for name in frame.columns) or frame.columns.has_duplicates
            or (_DTA_RELEASES[options["version"]] == b"117" and rows >= 2**32)):
        return False
    labelled = set(options.get("variable_value_labels") or {})
    columns = []
    for position, name in enumerate(frame.columns):
        column = _dta_column(frame.iloc[:, position], name in labelled, loaded)
        if column is None:
            return False
        columns.append(column)
    path = Path(path)
    layout_directory = tempfile.TemporaryDirectory(prefix="arboris-dta-layout-")
    layout_path = Path(layout_directory.name) / "layout.dta"
    surrogate = pd.DataFrame({
        name: frame.iloc[[column.surrogate_row], position].reset_index(drop=True)
        for position, (name, column) in enumerate(zip(frame.columns, columns, strict=True))
    })
    try:
        pyreadstat.write_dta(surrogate, str(layout_path), **options)
        raw = layout_path.read_bytes()
    except Exception:
        return False  # pyreadstat raises its own error again on the whole frame
    finally:
        layout_directory.cleanup()
    layout = _dta_layout(raw, _DTA_RELEASES[options["version"]], width)
    if layout is None or layout.type_codes != tuple(column.type_code for column in columns):
        return False
    row_width = _row_width(layout.type_codes)
    try:
        surrogate_row = loaded.dta_rows([column.rows(column.surrogate_row, column.surrogate_row + 1)
                                         for column in columns], 0, 1, 1)
    except (OverflowError, TypeError, ValueError):
        return False
    if layout.data_end - layout.data_at != row_width or raw[layout.data_at:layout.data_end] != surrogate_row:
        return False
    header = bytearray(raw[:layout.data_at])
    header[layout.n_at:layout.n_at + layout.n_width] = rows.to_bytes(layout.n_width, "little")
    grown = (rows - 1) * row_width
    struct.pack_into("<14Q", header, layout.map_at, *layout.offsets[:10], *(offset + grown for offset in layout.offsets[10:]))
    try:
        with path.open("wb") as stream:
            stream.write(header)
            chunk = max(1, min(_DTA_CHUNK_ROWS, _DTA_CHUNK_BYTES // max(1, row_width)))
            for start in range(0, rows, chunk):
                stop = min(start + chunk, rows)
                specs = [column.rows(start, stop) for column in columns]
                stream.write(loaded.dta_rows(specs, 0, stop - start, stop - start))
            stream.write(raw[layout.data_end:])
    except (OverflowError, TypeError, ValueError):
        return False  # a value ReadStat refuses, or one this writer does not know: pyreadstat decides
    return True
