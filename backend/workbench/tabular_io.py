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
from typing import Any, Mapping

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


def _read_native(path: Path, fmt: str, **kwargs: Any) -> tuple[pd.DataFrame, Any]:
    module = _pyreadstat()
    try:
        if fmt == "dta":
            return module.read_dta(str(path), **kwargs)
        return module.read_sav(str(path), user_missing=True, **kwargs)
    except Exception as exc:
        name = type(exc).__name__
        if name in {"ReadstatError", "PyreadstatError"} or isinstance(exc, (OSError, UnicodeError)):
            raise StatisticalFileError(
                f"{path.name} is not a readable {fmt.upper()} file ({exc})."
            ) from exc
        raise


def read_statistical(
    path: Path, fmt: str, *, nrows: int | None = None, usecols: list[str] | None = None
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
    return frame


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
    path: Path,
    *,
    suffix: str | None = None,
    nrows: int | None = None,
    usecols: list[str] | None = None,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    """Read any supported tabular file. ``nrows=0`` reads the header only."""

    path = Path(path)
    normalized = (suffix or path.suffix).lower()
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


def write_statistical(
    frame: pd.DataFrame, labels: Mapping[str, Any], path: Path, fmt: str
) -> ExportReport:
    """Write ``frame`` with its declared labels; report everything not carried."""

    if fmt not in {"sav", "zsav", "dta"}:
        raise StatisticalFileError(f"unsupported export format: {fmt}")
    module = _pyreadstat()
    report = ExportReport(format=fmt)
    data = frame.copy()
    names = _safe_names([str(column) for column in data.columns], fmt, report)
    data.columns = [names[str(column)] for column in data.columns]

    def target(column: str) -> str | None:
        return names.get(column)

    column_labels: dict[str, str] = {}
    for column, label in (labels.get("variable_labels") or {}).items():
        if target(column):
            column_labels[target(column)] = str(label)
    for original, renamed in report.renamed.items():
        column_labels.setdefault(renamed, original)

    value_labels: dict[str, dict[Any, str]] = {}
    for column, mapping in (labels.get("value_labels") or {}).items():
        name = target(column)
        if not name or not mapping:
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
                if fmt == "dta" and not number.is_integer():
                    # pyreadstat truncates 1.5 to 1 here without a word.
                    report.note(column, "value_labels", f"label for {raw!r} dropped: Stata labels only integers")
                    continue
                converted[int(number) if fmt == "dta" else number] = str(label)
            elif fmt == "dta":
                report.note(column, "value_labels", f"label for {raw!r} dropped: Stata labels only numeric values")
            else:
                converted[str(raw)] = str(label)
        if converted:
            value_labels[name] = converted

    options: dict[str, Any] = {}
    if column_labels:
        options["column_labels"] = column_labels
    if value_labels:
        options["variable_value_labels"] = value_labels

    levels = labels.get("measurement_level") or {}
    if fmt == "dta":
        for column in levels:
            if target(column):
                report.note(column, "measurement_level", "not stored: Stata has no measurement level")
    else:
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

    missing_ranges: dict[str, list[Any]] = {}
    for column, codes in (labels.get("user_missing_values") or {}).items():
        name = target(column)
        if not name or not codes:
            continue
        discrete = [code for code in codes if not isinstance(code, dict)]
        ranges = [code for code in codes if isinstance(code, dict)]
        native = fmt != "dta" and (
            (not ranges and len(discrete) <= _SPSS_MAX_DISCRETE_MISSING)
            or (len(ranges) == 1 and len(discrete) <= 1)
        ) and all(not isinstance(code, str) for code in discrete)
        if native:
            missing_ranges[name] = [
                *({"lo": code["low"], "hi": code["high"]} for code in ranges),
                *discrete,
            ]
            continue
        # No native form: write the codes as missing so the target software
        # can never treat them as valid values.
        mask = code_mask(data[name], codes)
        converted = int(mask.sum())
        if converted:
            data[name] = data[name].mask(mask)
        reason = (
            "Stata has no user-missing codes"
            if fmt == "dta"
            else "SPSS allows at most three codes, or one range and one code"
        )
        report.note(
            column,
            "user_missing_values",
            f"{converted} value(s) matching {codes} written as system missing: {reason}",
        )
    if missing_ranges:
        options["missing_ranges"] = missing_ranges

    path = Path(path)
    tmp = path.with_name(f".{path.name}.partial")
    try:
        if fmt == "dta":
            module.write_dta(data, str(tmp), version=15, **options)
        else:
            module.write_sav(data, str(tmp), compress=(fmt == "zsav"), **options)
        tmp.replace(path)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        if type(exc).__name__ in {"ReadstatError", "PyreadstatError"}:
            raise StatisticalFileError(f"could not write {fmt.upper()}: {exc}") from exc
        raise
    return report
