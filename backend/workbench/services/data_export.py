"""Export a run's dataset node, chosen and shaped the way the user asks.

Like Stata's ``export``/``save`` options: which variables and in what order,
which rows (the data.subset filter language), the format and its version,
what to do with value labels and declared missing codes, and the file name.
``preview_export`` returns exactly what the file will contain -- counts,
renames, every piece of metadata the format cannot hold, and a few rows --
without writing anything.

The exported file is an immutable run artifact named by its content hash, so
exporting the same data and options twice returns the same artifact, and a
label edit followed by a re-export produces a new one.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import read_json, register_artifact, write_json
from ..data_operations import DataColumnCastValidationError, _execute_subset, _read_frame, resolve_data_column_cast_context
from ..lineage.run_inputs import read_run_inputs
from ..repository.run_repository import _resolve_run_root
from ..tabular_io import (
    DEFAULT_DTA_VERSION,
    DTA_VERSIONS,
    EXPORT_FORMATS,
    MISSING_CODE_MODES,
    VALUE_LABEL_MODES,
    PreparedExport,
    prepare_export,
    write_prepared,
)
from .dataset_view import json_records

PREVIEW_ROWS = 5
_FILENAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,120}$")


@dataclass(frozen=True)
class ExportOptions:
    format: str
    columns: tuple[str, ...] | None = None
    filters: tuple[Mapping[str, Any], ...] = ()
    dta_version: int = DEFAULT_DTA_VERSION
    value_labels: str = "labels"
    missing_codes: str = "as_missing"
    filename: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, value: "ExportOptions | str | Mapping[str, Any]") -> "ExportOptions":
        if isinstance(value, ExportOptions):
            return value
        if isinstance(value, str):
            return cls(format=value)
        known = {name: value[name] for name in cls.__dataclass_fields__ if name in value and name != "extra"}
        if known.get("columns") is not None:
            known["columns"] = tuple(str(column) for column in known["columns"])
        known["filters"] = tuple(known.get("filters") or ())
        return cls(**known)

    def validate(self) -> None:
        if self.format not in EXPORT_FORMATS:
            raise ValueError(f"format must be one of {list(EXPORT_FORMATS)}")
        if self.format == "dta" and self.dta_version not in DTA_VERSIONS:
            raise ValueError(f"dta_version must be one of {sorted(DTA_VERSIONS)}")
        if self.value_labels not in VALUE_LABEL_MODES:
            raise ValueError(f"value_labels must be one of {list(VALUE_LABEL_MODES)}")
        if self.missing_codes not in MISSING_CODE_MODES:
            raise ValueError(f"missing_codes must be one of {list(MISSING_CODE_MODES)}")
        if self.columns is not None and not self.columns:
            raise ValueError("choose at least one variable")
        if self.filename is not None and not _FILENAME.match(self.filename):
            raise ValueError("filename may not contain / \\\\ : * ? \" < > | or control characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "columns": list(self.columns) if self.columns is not None else None,
            "filters": [dict(item) for item in self.filters],
            "dta_version": self.dta_version if self.format == "dta" else None,
            "value_labels": self.value_labels,
            "missing_codes": self.missing_codes,
            "filename": self.filename,
        }


def _slug(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", node_id).strip("-") or "dataset"


def _registered(run_root: Path, artifact_id: str) -> bool:
    index = read_json(run_root / "artifacts_index.json")
    return any(record.get("artifact_id") == artifact_id for record in index.get("artifacts", []))


def _selected(frame: pd.DataFrame, options: ExportOptions) -> pd.DataFrame:
    columns = list(options.columns) if options.columns is not None else [str(column) for column in frame.columns]
    unknown = [column for column in columns if column not in frame.columns]
    if unknown:
        raise DataColumnCastValidationError(f"unknown variables {unknown}")
    if not options.filters:
        return frame[columns]
    # The row filter is the data.subset filter language, so the UI, the Agent
    # and the Transform panel all say "which rows" the same way.
    filter_columns = [str(item.get("column")) for item in options.filters]
    subset = _execute_subset(
        frame, {"columns": list(dict.fromkeys([*columns, *filter_columns])), "filters": [dict(item) for item in options.filters]}
    )
    return subset[columns]


def _labels_for(labels: Mapping[str, Any], columns: Sequence[str]) -> dict[str, Any]:
    keep = set(columns)
    return {
        field_name: {column: value for column, value in (entries or {}).items() if column in keep}
        for field_name, entries in labels.items()
        if isinstance(entries, Mapping)
    }


def _prepare(project_root: Path | str, run_id: str, node_id: str, options: ExportOptions):
    options.validate()
    run_root = _resolve_run_root(str(project_root), run_id)
    context = resolve_data_column_cast_context(project_root, source_run_id=run_id, source_node_id=node_id)
    frame = _read_frame(run_root / context["source_artifact_path"])
    labels = (read_run_inputs(run_root).get("form") or {}).get("labels") or {}
    selected = _selected(frame, options)
    prepared = prepare_export(
        selected,
        _labels_for(labels, [str(column) for column in selected.columns]),
        options.format,
        value_label_mode=options.value_labels,
        missing_code_mode=options.missing_codes,
        dta_version=options.dta_version,
    )
    return run_root, context, frame, prepared


def _summary(run_id: str, node_id: str, context: Mapping[str, Any], frame: pd.DataFrame,
             prepared: PreparedExport, options: ExportOptions) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "node_id": node_id,
        "source_artifact_id": context["source_artifact_id"],
        "source_rows": int(len(frame)),
        "rows": int(len(prepared.data)),
        "columns": int(len(prepared.data.columns)),
        "column_names": [str(column) for column in prepared.data.columns],
        "options": options.to_dict(),
        **prepared.report.to_dict(),
    }


def preview_export(project_root: Path | str, run_id: str, node_id: str,
                   options: ExportOptions | str | Mapping[str, Any]) -> dict[str, Any]:
    """What the file will contain, without writing it."""

    options = ExportOptions.of(options)
    _run_root, context, frame, prepared = _prepare(project_root, run_id, node_id, options)
    summary = _summary(run_id, node_id, context, frame, prepared, options)
    summary["sample"] = json_records(prepared.data.head(PREVIEW_ROWS))
    summary["filename"] = _filename(node_id, options, "")
    return summary


_EXTENSIONS = {"sav": "sav", "zsav": "zsav", "dta": "dta", "csv": "csv", "xlsx": "xlsx"}


def _filename(node_id: str, options: ExportOptions, digest: str) -> str:
    extension = _EXTENSIONS[options.format]
    if options.filename:
        stem = options.filename.removesuffix(f".{extension}")
        return f"{stem}.{extension}"
    return f"{_slug(node_id)}{'-' + digest if digest else ''}.{extension}"


def export_dataset(project_root: Path | str, run_id: str, node_id: str,
                   options: ExportOptions | str | Mapping[str, Any]) -> dict[str, Any]:
    options = ExportOptions.of(options)
    run_root, context, frame, prepared = _prepare(project_root, run_id, node_id, options)
    directory = run_root / "exports" / "data"
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".staging-{_slug(node_id)}.{_EXTENSIONS[options.format]}"
    report = write_prepared(prepared, staging)
    # Content and chosen name together: the same bytes under another name are
    # another download.
    digest = hashlib.sha256(staging.read_bytes() + (options.filename or "").encode("utf-8")).hexdigest()[:16]
    # A chosen file name keeps its name; the content hash names the folder,
    # so two different exports can share a file name without colliding.
    folder = directory / digest
    folder.mkdir(exist_ok=True)
    target = folder / _filename(node_id, options, digest)
    staging.replace(target)
    payload = _summary(run_id, node_id, context, frame, prepared, options)
    write_json(folder / f"{target.name}.report.json", payload)

    artifact_id = f"data_export_{options.format}_{digest}"
    if not _registered(run_root, artifact_id):
        register_artifact(run_root, artifact_id, target, "data_export", "export", [context["source_artifact_id"]])
    return {
        "artifact_id": artifact_id,
        "filename": target.name,
        "download_url": f"/runs/{run_id}/artifacts/{artifact_id}",
        "report": {**payload, "notes": report.to_dict()["notes"]},
    }
