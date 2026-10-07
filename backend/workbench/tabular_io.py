"""One place that reads and writes tabular files, including SPSS and Stata.

Readers across the Workbench (ingestion, data operations, Notebook) dispatch on
the file suffix. They all go through ``read_table`` so a format is added once.

SPSS (.sav/.zsav) and Stata (.dta) carry variable metadata. It is translated
to and from the run ``labels`` vocabulary (variable_labels, value_labels,
measurement_level, user_missing_values), so an imported file's labels become
ordinary declared labels: visible, editable, persisted with the run. SPSS
user-missing codes are read as their raw values and declared, so the run's
missing-value stage converts them and records how many it converted. Stata's
extended missing values (.a-.z) are missing by definition and read as missing.

Writing reports every piece of metadata the target format cannot hold instead
of dropping it silently; where dropping it would change meaning (a declared
missing code with no native representation), the code is written as missing.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Mapping

import pandas as pd

from .user_missing import code_mask

STATISTICAL_FORMATS: dict[str, str] = {".sav": "sav", ".zsav": "zsav", ".dta": "dta"}
TABULAR_SUFFIXES = frozenset({".csv", ".xlsx", ".xls", ".parquet", ".pq", *STATISTICAL_FORMATS})

_SPSS_MEASURES = {"nominal", "ordinal", "scale"}
_SPSS_MAX_DISCRETE_MISSING = 3
_VALID_NAME = re.compile(r"^[^\W\d]\w*$")


class StatisticalFileError(ValueError):
    """An SPSS/Stata file that cannot be read or written as requested."""


@functools.cache
def _pyreadstat() -> Any:
    try:
        import pyreadstat
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise StatisticalFileError(
            "Reading SPSS/Stata files needs the pyreadstat package."
        ) from exc
    return pyreadstat


def statistical_format(path: Path | str, suffix: str | None = None) -> str | None:
    return STATISTICAL_FORMATS.get((suffix or Path(path).suffix).lower())


# ---------------------------------------------------------------- reading


def _read_native(path: Path | BinaryIO, fmt: str, **kwargs: Any) -> tuple[pd.DataFrame, Any]:
    module = _pyreadstat()
    source = str(path) if isinstance(path, (str, Path)) else path
    try:
        if fmt == "dta":
            return module.read_dta(source, **kwargs)
        return module.read_sav(source, user_missing=True, **kwargs)
    except Exception as exc:
        name = type(exc).__name__
        if name in {"ReadstatError", "PyreadstatError"} or isinstance(exc, (OSError, UnicodeError)):
            raise StatisticalFileError(
                f"{getattr(path, 'name', 'Verified source')} is not a readable {fmt.upper()} file ({exc})."
            ) from exc
        raise


def _restore_numeric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Give integer columns with missing values back their numeric dtype.

    pyreadstat returns a Stata integer column that has missing values as
    ``object`` holding Python ints and NaN. Downstream that reads as text, so
    a numeric variable would be treated as categorical or dropped.
    """

    for column in frame.columns:
        series = frame[column]
        if series.dtype != object:
            continue
        values = series.dropna()
        if len(values) and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in values
        ):
            frame[column] = pd.to_numeric(series)
    return frame


def read_statistical(
    path: Path | BinaryIO, fmt: str, *, nrows: int | None = None, usecols: list[str] | None = None
) -> pd.DataFrame:
    kwargs: dict[str, Any] = {"apply_value_formats": False}
    if nrows is not None:
        if nrows == 0:
            frame, _meta = _read_native(path, fmt, metadataonly=True, usecols=usecols)
            return frame
        kwargs["row_limit"] = nrows
    if usecols is not None:
        kwargs["usecols"] = list(usecols)
    frame, _meta = _read_native(path, fmt, **kwargs)
    return _restore_numeric_columns(frame)


def _key(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def read_statistical_labels(path: Path, fmt: str) -> dict[str, Any]:
    """The file's metadata, expressed as run ``labels``."""

    _frame, meta = _read_native(path, fmt, metadataonly=True)
    labels: dict[str, Any] = {}
    variable_labels = {
        str(column): str(label)
        for column, label in (meta.column_names_to_labels or {}).items()
        if isinstance(label, str) and label.strip()
    }
    if variable_labels:
        labels["variable_labels"] = variable_labels
    value_labels = {
        str(column): {_key(value): str(label) for value, label in mapping.items() if str(label).strip()}
        for column, mapping in (meta.variable_value_labels or {}).items()
        if mapping
    }
    value_labels = {column: mapping for column, mapping in value_labels.items() if mapping}
    if value_labels:
        labels["value_labels"] = value_labels
    if fmt != "dta":
        levels = {
            str(column): str(measure)
            for column, measure in (meta.variable_measure or {}).items()
            if measure in _SPSS_MEASURES
        }
        if levels:
            labels["measurement_level"] = levels
        missing: dict[str, list[Any]] = {}
        for column, ranges in (meta.missing_ranges or {}).items():
            codes: list[Any] = []
            for item in ranges or ():
                low, high = item.get("lo"), item.get("hi")
                if isinstance(low, str) or isinstance(high, str):
                    if low == high and low:
                        codes.append(str(low))
                    continue
                if low is None or high is None:
                    continue
                if low == high:
                    codes.append(_number(low))
                else:
                    codes.append({"low": _number(low), "high": _number(high)})
            if codes:
                # SPSS stores the range first; list discrete codes first, as
                # people declare them.
                missing[str(column)] = [c for c in codes if not isinstance(c, dict)] + [
                    c for c in codes if isinstance(c, dict)
                ]
        if missing:
            labels["user_missing_values"] = missing
    return labels


def statistical_row_count(path: Path, fmt: str) -> int:
    _frame, meta = _read_native(Path(path), fmt, metadataonly=True)
    return int(meta.number_rows or 0)


def read_table(
    path: Path | BinaryIO,
    *,
    suffix: str | None = None,
    nrows: int | None = None,
    usecols: list[str] | None = None,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    """Read any supported tabular file. ``nrows=0`` reads the header only."""

    if not hasattr(path, 'read'):
        path = Path(path)
    normalized = (suffix or getattr(path, 'suffix', '')).lower()
    fmt = STATISTICAL_FORMATS.get(normalized)
    if fmt is not None:
        return read_statistical(path, fmt, nrows=nrows, usecols=usecols)
    if normalized == ".csv":
        return pd.read_csv(path, nrows=nrows, usecols=usecols)
    if normalized in {".parquet", ".pq"}:
        frame = pd.read_parquet(path, columns=usecols)
        return frame if nrows is None else frame.iloc[:nrows]
    if normalized in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name or 0, nrows=nrows, usecols=usecols)
    raise ValueError(f"unsupported file type: {normalized or '<none>'}")


# ---------------------------------------------------------------- writing


@dataclass
class ExportReport:
    """What the written file could not carry exactly as declared."""

    format: str
    renamed: dict[str, str] = field(default_factory=dict)
    notes: list[dict[str, str]] = field(default_factory=list)

    def note(self, column: str, field_name: str, message: str) -> None:
        self.notes.append({"column": column, "field": field_name, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "renamed": dict(self.renamed), "notes": list(self.notes)}


def _name_fits(name: str, fmt: str) -> bool:
    # SPSS limits names to 64 bytes; Stata to 32 characters. Both accept
    # Unicode letters (SPSS, Stata 14+), so Chinese names are kept as-is.
    if fmt == "dta":
        return len(name) <= 32
    return len(name.encode("utf-8")) <= 64


def _truncate(name: str, fmt: str, reserve: int = 0) -> str:
    while name and not _name_fits(name + "x" * reserve, fmt):
        name = name[:-1]
    return name


def _safe_names(columns: list[str], fmt: str, report: ExportReport) -> dict[str, str]:
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for column in columns:
        name = str(column)
        candidate = name
        if not _VALID_NAME.match(candidate) or not _name_fits(candidate, fmt):
            candidate = re.sub(r"\W", "_", candidate) or "v"
            if not _VALID_NAME.match(candidate):
                candidate = f"v_{candidate}"
            candidate = _truncate(candidate, fmt)
        base, index = candidate, 1
        while candidate.lower() in used:
            suffix = f"_{index}"
            candidate = _truncate(base, fmt, reserve=len(suffix)) + suffix
            index += 1
        used.add(candidate.lower())
        mapping[name] = candidate
        if candidate != name:
            report.renamed[name] = candidate
            report.note(name, "name", f"renamed to {candidate}: not a valid {fmt.upper()} variable name")
    return mapping


EXPORT_FORMATS = ("sav", "zsav", "dta", "csv", "xlsx")
# pyreadstat's version argument -> the .dta release it writes and who reads it.
DTA_VERSIONS: dict[int, str] = {
    13: "Stata 13 (format 117)",
    14: "Stata 14-18 (format 118)",
    15: "Stata 15-18, over 32,767 variables (format 119)",
}
# Format 118 is what Stata 14-18 save by default; 119 is unreadable before 15.
DEFAULT_DTA_VERSION = 14
VALUE_LABEL_MODES = ("labels", "strings", "none")
MISSING_CODE_MODES = ("as_missing", "keep_codes")


def _codes_text(codes: list[Any]) -> str:
    """Declared missing codes as a person writes them: -99, 900 to 999."""

    def one(code: Any) -> str:
        if isinstance(code, dict):
            return f"{_number(code['low'])} to {_number(code['high'])}"
        return str(_number(code)) if isinstance(code, (int, float)) else repr(str(code))

    return ", ".join(one(code) for code in codes)


@dataclass
class PreparedExport:
    """A frame ready to write, the writer's options, and what was not carried."""

    data: pd.DataFrame
    fmt: str
    options: dict[str, Any]
    report: ExportReport


def _labelled_as_text(series: pd.Series, mapping: Mapping[str, Any]) -> pd.Series:
    by_key = {str(key): str(label) for key, label in mapping.items()}

    def text(value: Any) -> Any:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        key = _key(value) if isinstance(value, (int, float)) else str(value)
        return by_key.get(key, key)

    return series.map(text).astype("string")


def prepare_export(
    frame: pd.DataFrame,
    labels: Mapping[str, Any],
    fmt: str,
    *,
    value_label_mode: str = "labels",
    missing_code_mode: str = "as_missing",
    dta_version: int = DEFAULT_DTA_VERSION,
) -> PreparedExport:
    """Translate declared metadata into what ``fmt`` can hold; report the rest.

    ``value_label_mode``: ``labels`` writes codes with their label sets,
    ``strings`` replaces labelled codes by their label text, ``none`` writes
    codes only. ``missing_code_mode``: ``as_missing`` writes declared missing
    codes as missing (SPSS keeps them as native user-missing where it can),
    ``keep_codes`` writes them as ordinary values.
    """

    if fmt not in EXPORT_FORMATS:
        raise StatisticalFileError(f"unsupported export format: {fmt}")
    if value_label_mode not in VALUE_LABEL_MODES:
        raise StatisticalFileError(f"value_label_mode must be one of {VALUE_LABEL_MODES}")
    if missing_code_mode not in MISSING_CODE_MODES:
        raise StatisticalFileError(f"missing_code_mode must be one of {MISSING_CODE_MODES}")
    if fmt == "dta" and dta_version not in DTA_VERSIONS:
        raise StatisticalFileError(f"dta_version must be one of {sorted(DTA_VERSIONS)}")
    statistical = fmt in {"sav", "zsav", "dta"}
    report = ExportReport(format=fmt)
    data = frame.copy()
    if statistical:
        names = _safe_names([str(column) for column in data.columns], fmt, report)
        data.columns = [names[str(column)] for column in data.columns]
    else:
        names = {str(column): str(column) for column in data.columns}

    def target(column: str) -> str | None:
        return names.get(column)

    # Missing codes first: the label step may turn a column into text.
    missing_ranges: dict[str, list[Any]] = {}
    for column, codes in (labels.get("user_missing_values") or {}).items():
        name = target(column)
        if not name or not codes:
            continue
        discrete = [code for code in codes if not isinstance(code, dict)]
        ranges = [code for code in codes if isinstance(code, dict)]
        native = fmt in {"sav", "zsav"} and (
            (not ranges and len(discrete) <= _SPSS_MAX_DISCRETE_MISSING)
            or (len(ranges) == 1 and len(discrete) <= 1)
        ) and all(not isinstance(code, str) for code in discrete)
        if native:
            # SPSS keeps the values and knows they are missing: both modes agree.
            missing_ranges[name] = [
                *({"lo": code["low"], "hi": code["high"]} for code in ranges),
                *discrete,
            ]
            continue
        mask = code_mask(data[name], codes)
        count = int(mask.sum())
        if missing_code_mode == "keep_codes":
            where = {"dta": "Stata (declare them with mvdecode)", "csv": "the CSV file", "xlsx": "the Excel file"}.get(
                fmt, "SPSS (at most three codes, or one range and one code, can be declared)"
            )
            report.note(
                column, "user_missing_values",
                f"{count} value(s) matching {_codes_text(codes)} kept as ordinary values, as chosen; {where} treats them as valid",
            )
            continue
        if count:
            data[name] = data[name].mask(mask)
        reason = {
            "dta": "Stata has no user-missing codes",
            "csv": "CSV has no user-missing codes",
            "xlsx": "Excel has no user-missing codes",
        }.get(fmt, "SPSS allows at most three codes, or one range and one code")
        report.note(column, "user_missing_values", f"{count} value(s) matching {_codes_text(codes)} written as missing: {reason}")

    value_labels: dict[str, dict[Any, str]] = {}
    for column, mapping in (labels.get("value_labels") or {}).items():
        name = target(column)
        if not name or not mapping:
            continue
        if value_label_mode == "none":
            report.note(column, "value_labels", "not written, as chosen: codes only")
            continue
        if value_label_mode == "strings" or not statistical:
            data[name] = _labelled_as_text(data[name], mapping)
            if value_label_mode != "strings":
                report.note(column, "value_labels", f"codes replaced by their labels: {fmt.upper()} has no value labels")
            continue
        series = data[name]
        numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
        converted: dict[Any, str] = {}
        for raw, label in mapping.items():
            if numeric:
                try:
                    number = float(raw)
                except ValueError:
                    report.note(column, "value_labels", f"label for {raw!r} dropped: column is numeric")
                    continue
                integral_column = pd.api.types.is_integer_dtype(series)
                if (fmt == "dta" or integral_column) and not number.is_integer():
                    # pyreadstat truncates 1.5 to 1 here without a word.
                    report.note(column, "value_labels", f"label for {raw!r} dropped: only integer values can be labelled here")
                    continue
                # pyreadstat requires keys of the column's own type.
                converted[int(number) if fmt == "dta" or integral_column else number] = str(label)
            elif fmt == "dta":
                report.note(column, "value_labels", f"label for {raw!r} dropped: Stata labels only numeric values")
            else:
                converted[str(raw)] = str(label)
        if converted:
            value_labels[name] = converted

    column_labels: dict[str, str] = {}
    for column, label in (labels.get("variable_labels") or {}).items():
        if target(column):
            if statistical:
                column_labels[target(column)] = str(label)
            else:
                report.note(column, "variable_labels", f"not stored: {fmt.upper()} has no variable labels")
    for original, renamed in report.renamed.items():
        column_labels.setdefault(renamed, original)

    options: dict[str, Any] = {}
    if column_labels:
        options["column_labels"] = column_labels
    if value_labels:
        options["variable_value_labels"] = value_labels
    if missing_ranges:
        options["missing_ranges"] = missing_ranges

    levels = labels.get("measurement_level") or {}
    if fmt in {"sav", "zsav"}:
        measures: dict[str, str] = {}
        for column, level in levels.items():
            name = target(column)
            if not name or level == "unspecified":
                continue
            if level == "count":
                measures[name] = "scale"
                report.note(column, "measurement_level", "count written as scale: SPSS has no count level")
            elif level in _SPSS_MEASURES:
                measures[name] = level
        if measures:
            options["variable_measure"] = measures
    else:
        for column, level in levels.items():
            if target(column) and level != "unspecified":
                software = "Stata" if fmt == "dta" else fmt.upper()
                report.note(column, "measurement_level", f"not stored: {software} has no measurement level")

    if fmt == "dta":
        options["version"] = dta_version
        if dta_version == 13:
            _ascii_for_stata13(data, options, report)
    return PreparedExport(data=data, fmt=fmt, options=options, report=report)


def _ascii_for_stata13(data: pd.DataFrame, options: dict[str, Any], report: ExportReport) -> None:
    """Stata 13 files are not Unicode; say which names and labels cannot survive."""

    for name in data.columns:
        if not str(name).isascii():
            report.note(str(name), "name", "Stata 13 files cannot hold non-ASCII names; choose Stata 14-18")
    for name, label in (options.get("column_labels") or {}).items():
        if not str(label).isascii():
            report.note(str(name), "variable_labels", "Stata 13 files cannot hold non-ASCII labels; choose Stata 14-18")


def write_prepared(prepared: PreparedExport, path: Path) -> ExportReport:
    path = Path(path)
    tmp = path.with_name(f".{path.name}.partial")
    fmt, options = prepared.fmt, dict(prepared.options)
    try:
        if fmt == "dta":
            if any(note["field"] in {"name", "variable_labels"} and "Stata 13" in note["message"]
                   for note in prepared.report.notes):
                raise StatisticalFileError(
                    "Stata 13 cannot hold this dataset's non-ASCII names or labels; export for Stata 14-18"
                )
            _pyreadstat().write_dta(prepared.data, str(tmp), **options)
        elif fmt in {"sav", "zsav"}:
            _pyreadstat().write_sav(prepared.data, str(tmp), compress=(fmt == "zsav"), **options)
        elif fmt == "csv":
            prepared.data.to_csv(tmp, index=False, encoding="utf-8")
        else:
            prepared.data.to_excel(tmp, index=False, engine="openpyxl")
        tmp.replace(path)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        if type(exc).__name__ in {"ReadstatError", "PyreadstatError"}:
            raise StatisticalFileError(f"could not write {fmt.upper()}: {exc}") from exc
        raise
    return prepared.report


def write_statistical(
    frame: pd.DataFrame, labels: Mapping[str, Any], path: Path, fmt: str
) -> ExportReport:
    """Write ``frame`` with its declared labels; report everything not carried."""

    if fmt not in {"sav", "zsav", "dta"}:
        raise StatisticalFileError(f"unsupported export format: {fmt}")
    return write_prepared(prepare_export(frame, labels, fmt), path)
