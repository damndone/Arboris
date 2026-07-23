"""Bounded, source-bound Data Evidence Packs for Notebook planning.

Evidence is a read-only projection. It can explain why an option was proposed,
but it cannot create a Draft, Run, Artifact, or Graph mutation. Paths are
resolved only from a persisted raw-data artifact or a content-addressed upload;
the serialized pack never contains the resolved path or raw file bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ...artifacts import read_json, sha256_file
from ...canonical import sha256_canonical
from ...ingestion import read_frame_bounded
from ...lineage.upload_store import verify_upload


MAX_SOURCE_ROWS = 100_000
MAX_FORECAST_ROWS = 20_000
MAX_SAMPLE_ROWS = 10
MAX_SAMPLE_COLUMNS = 8
MAX_CELL_CHARS = 128
MAX_RECORD_BYTES = 16 * 1024
MAX_PACK_BYTES = 48 * 1024


class EvidenceError(ValueError):
    """Base for typed, fail-closed inspection errors."""

    code = "EVIDENCE_ERROR"


class UnsupportedEvidenceSource(EvidenceError):
    code = "UNSUPPORTED_SOURCE"


@dataclass(frozen=True)
class RunSource:
    run_id: str

    def __post_init__(self) -> None:
        _require_pathless(self.run_id, "run_id")

    @property
    def kind(self) -> str:
        return "run"


@dataclass(frozen=True)
class DatasetSource:
    upload_sha256: str
    filename: str
    sheet_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_pathless(self.upload_sha256, "upload_sha256")
        if not self.filename or Path(self.filename).name != self.filename:
            raise ValueError("filename must be a safe basename")
        if not isinstance(self.sheet_names, tuple):
            raise ValueError("sheet_names must be a tuple")

    @property
    def kind(self) -> str:
        return "dataset"


@dataclass(frozen=True)
class InspectionRequest:
    inspection_id: str
    target_ref: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.inspection_id or not isinstance(self.inspection_id, str):
            raise ValueError("inspection_id must be nonempty")
        if not self.target_ref or not isinstance(self.target_ref, str):
            raise ValueError("target_ref must be nonempty")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("arguments must be a mapping")
        json.dumps(dict(self.arguments), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    inspection_id: str
    source_refs: tuple[str, ...]
    protocol_version: str
    status: str
    observations: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    omissions: tuple[dict[str, Any], ...] = ()
    failure_code: str | None = None
    result_hash: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"completed", "partial", "failed"}:
            raise ValueError("evidence status is invalid")
        if self.failure_code is not None and self.status != "failed":
            raise ValueError("failure_code is only valid for failed evidence")

    def _content(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "inspection_id": self.inspection_id,
            "source_refs": list(self.source_refs),
            "protocol_version": self.protocol_version,
            "status": self.status,
            "observations": self.observations,
            "metrics": self.metrics,
            "warnings": list(self.warnings),
            "omissions": list(self.omissions),
            "failure_code": self.failure_code,
        }

    def to_dict(self) -> dict[str, Any]:
        value = self._content()
        value["result_hash"] = self.result_hash or _hash(value)
        return value


@dataclass(frozen=True)
class DataEvidencePackV1:
    source_id: str
    records: tuple[EvidenceRecord, ...]
    pack_omissions: tuple[dict[str, Any], ...] = ()
    schema_version: str = "data-evidence-pack/v1"

    @property
    def content_hash(self) -> str:
        return _hash(self._content())

    @property
    def evidence_pack_hash(self) -> str:
        return self.content_hash

    def _content(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "records": [record.to_dict() for record in self.records],
            "pack_omissions": list(self.pack_omissions),
        }

    def to_dict(self) -> dict[str, Any]:
        value = self._content()
        value["content_hash"] = self.content_hash
        value["evidence_pack_hash"] = self.evidence_pack_hash
        return value


@dataclass(frozen=True)
class _ResolvedSource:
    source_id: str
    path: Path
    suffix: str
    sheet_name: str | None = None


def _require_pathless(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{label} must be pathless")


def _hash(value: Any) -> str:
    return "sha256:" + sha256_canonical(value)


def _canonical_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _source_identity(project_root: Path, source: RunSource | DatasetSource) -> _ResolvedSource:
    if isinstance(source, RunSource):
        run_root = (project_root / "runs" / source.run_id).resolve()
        if not run_root.is_dir():
            raise EvidenceError("RUN_NOT_FOUND")
        index_path = run_root / "artifacts_index.json"
        try:
            index = read_json(index_path)
        except (OSError, ValueError) as exc:
            raise EvidenceError("RAW_ARTIFACT_INDEX_UNAVAILABLE") from exc
        artifacts = index.get("artifacts") if isinstance(index, dict) else None
        matches = [item for item in artifacts or () if isinstance(item, dict) and item.get("artifact_type") == "raw_data"]
        if len(matches) != 1:
            raise EvidenceError("RAW_ARTIFACT_NOT_UNIQUE")
        artifact = matches[0]
        relative = artifact.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise EvidenceError("RAW_ARTIFACT_PATH_INVALID")
        path = (run_root / relative).resolve()
        try:
            path.relative_to(run_root)
        except ValueError as exc:
            raise EvidenceError("RAW_ARTIFACT_OUTSIDE_RUN") from exc
        if not path.is_file():
            raise EvidenceError("RAW_ARTIFACT_MISSING")
        expected_hash = artifact.get("sha256")
        if expected_hash and sha256_file(path) != expected_hash:
            raise EvidenceError("RAW_ARTIFACT_HASH_MISMATCH")
        return _ResolvedSource(f"run:{source.run_id}", path, path.suffix.lower())
    if isinstance(source, DatasetSource):
        path = verify_upload(project_root, source.upload_sha256)
        sheet_name = source.sheet_names[0] if source.sheet_names else None
        return _ResolvedSource(f"dataset:{source.upload_sha256}", path, Path(source.filename).suffix.lower(), sheet_name)
    raise UnsupportedEvidenceSource("source must be RunSource or DatasetSource")


def _read_source(source: _ResolvedSource, inspection_id: str, arguments: Mapping[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    cap = MAX_FORECAST_ROWS if inspection_id == "forecast_rolling_origin.v1" else MAX_SOURCE_ROWS
    requested = arguments.get("max_rows", cap)
    if type(requested) is not int or requested < 1:
        raise EvidenceError("BUDGET_INVALID")
    omissions: list[dict[str, Any]] = []
    limit = min(requested, cap)
    if requested > cap:
        omissions.append({"section": inspection_id, "included_count": cap, "available_count": requested, "reason": "inspection_input_cap"})
    frame, truncated = read_frame_bounded(
        source.path, max_rows=limit, sheet_name=source.sheet_name, file_suffix=source.suffix
    )
    if truncated:
        omissions.append({"section": inspection_id, "included_count": limit, "available_count": None, "reason": "source_row_cap"})
    return frame, omissions


def _record(
    request: InspectionRequest,
    source: _ResolvedSource,
    *,
    source_refs: tuple[str, ...],
    protocol: str,
    status: str = "completed",
    observations: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
    omissions: list[dict[str, Any]] | None = None,
    failure_code: str | None = None,
) -> EvidenceRecord:
    content = {
        "inspection_id": request.inspection_id,
        "source_refs": list(source_refs),
        "protocol_version": protocol,
        "status": status,
        "observations": observations or {},
        "metrics": metrics or {},
        "warnings": list(warnings),
        "omissions": list(omissions or []),
        "failure_code": failure_code,
    }
    digest = _hash(content)
    return EvidenceRecord(
        evidence_id=f"evidence:{digest.removeprefix('sha256:')}",
        inspection_id=request.inspection_id,
        source_refs=source_refs,
        protocol_version=protocol,
        status=status,
        observations=observations or {},
        metrics=metrics or {},
        warnings=warnings,
        omissions=tuple(omissions or ()),
        failure_code=failure_code,
        result_hash=digest,
    )


def _failure(request: InspectionRequest, source_id: str, code: str, detail: str | None = None) -> EvidenceRecord:
    warnings = (detail,) if detail else ()
    return _record(
        request,
        _ResolvedSource(source_id, Path("."), ""),
        source_refs=(f"inspection_failure:{source_id}",),
        protocol="inspection-error/v1",
        status="failed",
        warnings=warnings,
        failure_code=code,
    )


def _profile(request: InspectionRequest, source: _ResolvedSource) -> EvidenceRecord:
    frame, omissions = _read_source(source, request.inspection_id, request.arguments)
    columns = []
    for name in frame.columns:
        series = frame[name]
        columns.append({
            "name": str(name),
            "dtype": str(series.dtype),
            "row_count": int(len(series)),
            "missing_count": int(series.isna().sum()),
            "unique_count": int(series.nunique(dropna=True)),
        })
    source_refs = (f"dataset_profile:{source.source_id.removeprefix('run:').removeprefix('dataset:')}",)
    observations = {"row_count": int(len(frame)), "columns": columns, "source_rows_capped": bool(omissions)}
    record = _record(request, source, source_refs=source_refs, protocol="profile/v1", status="partial" if omissions else "completed", observations=observations, omissions=omissions)
    if _canonical_size(record.to_dict()) <= MAX_RECORD_BYTES:
        return record
    # Keep a useful partial profile under the hard record budget. The removed
    # columns are deterministic and explicitly visible to the recommendation
    # gate rather than silently disappearing.
    ordered = sorted(columns, key=lambda item: str(item.get("name", "")))
    while ordered:
        ordered.pop()
        profile_omissions = list(omissions) + [{"section": "profile.columns", "included_count": len(ordered), "available_count": len(columns), "reason": "record_budget_exceeded"}]
        candidate = _record(request, source, source_refs=source_refs, protocol="profile/v1", status="partial", observations={"row_count": int(len(frame)), "columns": ordered, "source_rows_capped": bool(omissions)}, omissions=profile_omissions)
        if _canonical_size(candidate.to_dict()) <= MAX_RECORD_BYTES:
            return candidate
    return _fit_record(record)


def _quality(request: InspectionRequest, source: _ResolvedSource) -> EvidenceRecord:
    frame, omissions = _read_source(source, request.inspection_id, request.arguments)
    missing = {str(name): int(value) for name, value in frame.isna().sum().items() if int(value)}
    observations = {"row_count": int(len(frame)), "duplicate_row_count": int(frame.duplicated().sum()), "missing_counts": missing}
    return _record(request, source, source_refs=(f"quality:{source.source_id}",), protocol="quality/v1", status="partial" if omissions else "completed", observations=observations, omissions=omissions)


def _time_index(request: InspectionRequest, source: _ResolvedSource) -> EvidenceRecord:
    frame, omissions = _read_source(source, request.inspection_id, request.arguments)
    candidate = None
    parsed = None
    for name in frame.columns:
        lowered = str(name).lower()
        if not any(token in lowered for token in ("date", "time", "when", "period", "timestamp", "index")):
            continue
        converted = pd.to_datetime(frame[name], errors="coerce")
        if len(frame) and converted.notna().mean() >= 0.8:
            candidate, parsed = str(name), converted
            break
    observations: dict[str, Any] = {"candidate_column": candidate, "ordered": None, "duplicate_count": None, "gap_count": None}
    if candidate is not None and parsed is not None:
        values = parsed.dropna()
        diffs = values.sort_values().diff().dropna()
        observations.update({"ordered": bool(values.is_monotonic_increasing), "duplicate_count": int(values.duplicated().sum()), "gap_count": int((diffs > diffs.median()).sum()) if len(diffs) and diffs.median() > pd.Timedelta(0) else 0})
    return _record(request, source, source_refs=(f"time_index:{source.source_id}",), protocol="time-index/v1", status="partial" if omissions else "completed", observations=observations, omissions=omissions)


_IDENTIFIER_TOKENS = ("id", "uuid", "email", "phone", "ssn", "account", "patient", "user")


def _is_private_sample_column(name: str, series: pd.Series) -> bool:
    lowered = name.lower()
    if any(token in lowered.split("_") for token in _IDENTIFIER_TOKENS) or any(token in lowered for token in ("email", "phone", "uuid")):
        return True
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        values = series.dropna().astype(str)
        if len(values) and (values.str.len().mean() > 48 or values.nunique() / len(values) > 0.8):
            return True
    return False


def _safe_cell(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, str):
        return value[:MAX_CELL_CHARS]
    if isinstance(value, (int, float, bool)) or value is None:
        return value if not isinstance(value, float) or math.isfinite(value) else None
    return str(value)[:MAX_CELL_CHARS]


def _sample(request: InspectionRequest, source: _ResolvedSource) -> EvidenceRecord:
    frame, omissions = _read_source(source, request.inspection_id, request.arguments)
    safe_columns = [str(name) for name in frame.columns if not _is_private_sample_column(str(name), frame[name])]
    if len(safe_columns) > MAX_SAMPLE_COLUMNS:
        omissions.append({"section": "sample.columns", "included_count": MAX_SAMPLE_COLUMNS, "available_count": len(safe_columns), "reason": "sample_column_cap"})
    safe_columns = safe_columns[:MAX_SAMPLE_COLUMNS]
    rows = [{column: _safe_cell(row[column]) for column in safe_columns} for _, row in frame.head(MAX_SAMPLE_ROWS).iterrows()]
    observations = {"columns": safe_columns, "rows": rows}
    return _record(request, source, source_refs=(f"sample:{source.source_id}",), protocol="sample/v1", status="partial" if omissions else "completed", observations=observations, omissions=omissions)


def _forecast_capability(arguments: Mapping[str, Any], capabilities: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    capability_id = arguments.get("capability_id", "forecast.v1")
    declared = (capabilities or {}).get(capability_id) if isinstance(capabilities, Mapping) else None
    if not isinstance(declared, Mapping):
        return None, "CAPABILITY_NOT_REGISTERED"
    for key in ("cohort", "protocol_version", "horizon", "folds"):
        if key in arguments and declared.get(key) != arguments[key]:
            return None, "CAPABILITY_PROTOCOL_MISMATCH"
    if declared.get("cohort") != arguments.get("cohort") or declared.get("protocol_version") != arguments.get("protocol_version"):
        return None, "CAPABILITY_PROTOCOL_MISMATCH"
    return dict(declared), None


def _forecast(request: InspectionRequest, source: _ResolvedSource, capabilities: Mapping[str, Any] | None) -> EvidenceRecord:
    declared, error = _forecast_capability(request.arguments, capabilities)
    if error:
        return _failure(request, source.source_id, error)
    frame, omissions = _read_source(source, request.inspection_id, request.arguments)
    target = request.arguments.get("target_column")
    if not isinstance(target, str) or target not in frame.columns:
        return _failure(request, source.source_id, "TARGET_NOT_FOUND")
    horizon = int(request.arguments.get("horizon", declared.get("horizon", 1)))
    folds = int(request.arguments.get("folds", declared.get("folds", 1)))
    values = pd.to_numeric(frame[target], errors="coerce").dropna().tolist()
    if horizon < 1 or folds < 1 or len(values) < folds * horizon + 1:
        return _failure(request, source.source_id, "FORECAST_PROBE_INSUFFICIENT_ROWS")
    errors: list[float] = []
    for fold in range(folds):
        train_end = len(values) - (folds - fold) * horizon
        train = values[:train_end]
        actual = values[train_end:train_end + horizon]
        baseline = float(train[-1])
        errors.extend(abs(float(item) - baseline) for item in actual)
    mae = sum(errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    return _record(request, source, source_refs=(f"forecast_rolling_origin:{source.source_id}",), protocol=str(declared["protocol_version"]), status="partial" if omissions else "completed", observations={"folds": folds, "horizon": horizon, "cohort": declared["cohort"]}, metrics={"mae": mae, "rmse": rmse}, omissions=omissions)


INSPECTIONS = {
    "profile.v1": _profile,
    "quality.v1": _quality,
    "time_index.v1": _time_index,
    "sample.v1": _sample,
}


def _fit_record(record: EvidenceRecord) -> EvidenceRecord:
    if _canonical_size(record.to_dict()) <= MAX_RECORD_BYTES:
        return record
    omissions = list(record.omissions) + [{"section": record.inspection_id, "included_count": 0, "available_count": None, "reason": "record_budget_exceeded"}]
    return _record(InspectionRequest(record.inspection_id, "bounded", {}), _ResolvedSource("bounded", Path("."), ""), source_refs=record.source_refs, protocol=record.protocol_version, status="partial", observations={}, metrics={}, warnings=record.warnings, omissions=omissions)


def compile_evidence_pack(
    project_root: Path | str,
    *,
    source: RunSource | DatasetSource | Path,
    requests: tuple[InspectionRequest, ...],
    capabilities: Mapping[str, Any] | None = None,
    trace: Any | None = None,
) -> DataEvidencePackV1:
    """Execute only registered, bounded inspections and return an immutable pack."""

    root = Path(project_root)
    if not isinstance(requests, tuple):
        requests = tuple(requests)
    try:
        resolved = _source_identity(root, source)  # type: ignore[arg-type]
    except (EvidenceError, UnsupportedEvidenceSource, FileNotFoundError, ValueError) as exc:
        source_id = "unsupported"
        records = tuple(_failure(request, source_id, getattr(exc, "code", "SOURCE_UNAVAILABLE"), str(exc)) for request in requests)
        return DataEvidencePackV1(source_id=source_id, records=records)

    records: list[EvidenceRecord] = []
    for request in requests:
        if trace is not None:
            trace.emit("evidence.inspection.requested", payload={"inspection_id": request.inspection_id, "target_ref": request.target_ref, "request_hash": _hash(dict(request.arguments))})
        target_valid = request.target_ref in {"run:active", "dataset:active"} and ((resolved.source_id.startswith("run:") and request.target_ref == "run:active") or (resolved.source_id.startswith("dataset:") and request.target_ref == "dataset:active"))
        if not target_valid:
            record = _failure(request, resolved.source_id, "TARGET_REF_INVALID")
        elif request.inspection_id == "forecast_rolling_origin.v1":
            record = _forecast(request, resolved, capabilities)
        else:
            handler = INSPECTIONS.get(request.inspection_id)
            if handler is None:
                record = _failure(request, resolved.source_id, "UNKNOWN_INSPECTION")
            else:
                try:
                    record = handler(request, resolved)
                except (EvidenceError, FileNotFoundError, OSError, ValueError, TypeError) as exc:
                    record = _failure(request, resolved.source_id, getattr(exc, "code", "INSPECTION_FAILED"), str(exc))
        records.append(record)
        if trace is not None:
            if record.status == "failed":
                trace.emit("evidence.inspection.failed", payload={"inspection_id": record.inspection_id, "failure_code": record.failure_code or "INSPECTION_FAILED", "evidence_id": record.evidence_id})
            else:
                trace.emit("evidence.inspection.completed", payload={"inspection_id": record.inspection_id, "evidence_id": record.evidence_id, "result_hash": record.result_hash, "status": record.status, "omissions": list(record.omissions)})

    pack = DataEvidencePackV1(source_id=resolved.source_id, records=tuple(records))
    if _canonical_size(pack.to_dict()) <= MAX_PACK_BYTES:
        return pack
    trimmed = tuple(_record(InspectionRequest(record.inspection_id, "bounded", {}), resolved, source_refs=record.source_refs, protocol=record.protocol_version, status="partial" if record.status != "failed" else "failed", observations={}, metrics={}, warnings=record.warnings, omissions=list(record.omissions) + [{"section": record.inspection_id, "included_count": 0, "available_count": None, "reason": "pack_budget_exceeded"}], failure_code=record.failure_code) for record in records)
    return DataEvidencePackV1(source_id=resolved.source_id, records=trimmed, pack_omissions=({"reason": "pack_budget_exceeded"},))


__all__ = [
    "DataEvidencePackV1",
    "DatasetSource",
    "EvidenceError",
    "EvidenceRecord",
    "INSPECTIONS",
    "InspectionRequest",
    "RunSource",
    "UnsupportedEvidenceSource",
    "compile_evidence_pack",
]
