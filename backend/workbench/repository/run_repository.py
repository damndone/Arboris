"""Filesystem reads over a project's ``runs/`` directory.

Pure path-resolution + JSON/artifact reads. Every function is side-effect free
apart from reading files. Not-found / invalid-path conditions raise
``WorkbenchAPIError`` so the HTTP layer maps them to the right status code.

Extracted verbatim from ``api.py`` in v1.6.10 (D1 decomposition, Phase 1); the
symbols are re-exported from ``workbench.api`` for backward-compatible imports.
"""
from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from ..api_errors import (
    ERROR_ARTIFACT_NOT_FOUND,
    ERROR_INVALID_PATH,
    ERROR_PROJECT_NOT_FOUND,
    ERROR_REGISTRY_VERSION_INVALID,
    ERROR_REGISTRY_VERSION_UNSUPPORTED,
    ERROR_RUN_NOT_FOUND,
    WorkbenchAPIError,
)
from ..artifacts import read_json
from ..predictive_research.contracts import ContractError
from ..predictive_research.persistence import validate_classification_server_identity

# Highest artifacts_index.json schema_version this server understands.
SUPPORTED_REGISTRY_VERSION = 1
ERROR_ARTIFACTS_INDEX_UNAVAILABLE = "ARTIFACTS_INDEX_UNAVAILABLE"
ERROR_ARTIFACTS_INDEX_INVALID = "ARTIFACTS_INDEX_INVALID"

_ARTIFACT_RECORD_REQUIRED_FIELDS = frozenset(
    {
        "artifact_id",
        "path",
        "artifact_type",
        "step",
        "sha256",
        "inputs",
        "config_hash",
        "code_version",
    }
)
_ARTIFACT_RECORD_OPTIONAL_FIELDS = frozenset(
    {
        "payload_contract",
        "payload_schema",
        "schema_version",
        "server_identity",
        "receipt_path",
        "receipt_sha256",
    }
)
_ARTIFACT_INDEX_FIELDS = frozenset(
    {"schema_version", "artifacts", "classification_server_identity"}
)


def _validate_artifact_digest(value: Any) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("artifact digest is not a lowercase SHA-256 value")


def _validate_run_relative_path(run_root: Path, value: Any) -> None:
    if type(value) is not str or not value or value != value.strip() or "\\" in value:
        raise ValueError("artifact path is not a normalized relative POSIX path")
    if len(value.encode("utf-8")) > 512:
        raise ValueError("artifact path is too long")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("artifact path is not normalized")
    candidate = (run_root / value).resolve()
    try:
        candidate.relative_to(run_root.resolve())
    except ValueError as exc:
        raise ValueError("artifact path escapes the run root") from exc


def _validate_payload_contract(value: Any) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"payload_schema", "schema_version"}
        or type(value.get("payload_schema")) is not str
        or not value["payload_schema"]
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("artifact payload contract is invalid")


def _validate_artifact_record(run_root: Path, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("artifact record is not an object")
    if not _ARTIFACT_RECORD_REQUIRED_FIELDS.issubset(record) or set(record) - (
        _ARTIFACT_RECORD_REQUIRED_FIELDS | _ARTIFACT_RECORD_OPTIONAL_FIELDS
    ):
        raise ValueError("artifact record shape is not canonical")
    for field in ("artifact_id", "path", "artifact_type", "step", "code_version"):
        if type(record[field]) is not str or not record[field].strip():
            raise ValueError(f"artifact record field {field} is invalid")
    if record["artifact_type"] == "unknown":
        raise ValueError("artifact record kind is unknown")
    if not isinstance(record["inputs"], list) or any(
        type(item) is not str or not item.strip() for item in record["inputs"]
    ):
        raise ValueError("artifact record inputs are invalid")
    if type(record["config_hash"]) is not str:
        raise ValueError("artifact record config_hash is invalid")
    _validate_artifact_digest(record["sha256"])
    _validate_run_relative_path(run_root, record["path"])

    payload_contract = record.get("payload_contract")
    if "payload_contract" in record:
        _validate_payload_contract(payload_contract)
    if "payload_schema" in record or "schema_version" in record:
        if "payload_schema" not in record or "schema_version" not in record:
            raise ValueError("indexed payload schema fields must be supplied together")
        if (
            type(record["payload_schema"]) is not str
            or not record["payload_schema"]
            or type(record["schema_version"]) is not int
            or record["schema_version"] != 1
        ):
            raise ValueError("indexed payload schema is invalid")
        if payload_contract is not None and (
            record["payload_schema"] != payload_contract["payload_schema"]
            or record["schema_version"] != payload_contract["schema_version"]
        ):
            raise ValueError("indexed payload schema disagrees with its payload contract")

    server_identity = record.get("server_identity")
    if "server_identity" in record:
        if not isinstance(server_identity, dict) or type(server_identity.get("schema_version")) is not int:
            raise ValueError("artifact server identity is invalid")
        validate_classification_server_identity(server_identity, run_root)
    has_receipt_path = "receipt_path" in record
    has_receipt_sha256 = "receipt_sha256" in record
    receipt_path = record.get("receipt_path")
    receipt_sha256 = record.get("receipt_sha256")
    if has_receipt_path != has_receipt_sha256:
        raise ValueError("artifact receipt path and digest must be supplied together")
    if has_receipt_path:
        _validate_run_relative_path(run_root, receipt_path)
        _validate_artifact_digest(receipt_sha256)
    if record["artifact_type"] == "classification_artifacts" and (
        payload_contract is None
        or server_identity is None
        or receipt_path is None
        or receipt_sha256 is None
    ):
        raise ValueError("classification artifact record lacks its server-owned identity or receipt")
    return record


def _validate_artifacts_index(run_root: Path, data: Any) -> None:
    if not isinstance(data, dict) or set(data) - _ARTIFACT_INDEX_FIELDS or "artifacts" not in data:
        raise ValueError("artifacts_index.json has a noncanonical top-level shape")
    records = data["artifacts"]
    if not isinstance(records, list):
        raise ValueError("artifacts_index.json artifacts must be a list")
    top_identity = data.get("classification_server_identity")
    if "classification_server_identity" in data:
        if not isinstance(top_identity, dict) or type(top_identity.get("schema_version")) is not int:
            raise ValueError("classification server identity is invalid")
        validate_classification_server_identity(top_identity, run_root)
    seen_ids: set[str] = set()
    for record in records:
        validated = _validate_artifact_record(run_root, record)
        artifact_id = validated["artifact_id"]
        if artifact_id in seen_ids:
            raise ValueError("artifact_id is duplicated")
        seen_ids.add(artifact_id)
        if top_identity is not None and validated.get("server_identity") is not None and validated["server_identity"] != top_identity:
            raise ValueError("artifact server identity disagrees with the index identity")


def _resolve_project_root(run_root: Path) -> Path:
    return run_root.parent.parent


def _resolve_project_runs_dir(project_root: str) -> Path:
    project = Path(project_root).resolve()
    runs_dir = project / "runs"
    if not runs_dir.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_PROJECT_NOT_FOUND,
            message=f"Project not found: {project}",
            details={"project_root": str(project)},
        )
    return runs_dir


def _resolve_run_root(project_root: str, run_id: str) -> Path:
    runs_dir = _resolve_project_runs_dir(project_root)
    candidate = (runs_dir / run_id).resolve()
    try:
        candidate.relative_to(runs_dir.resolve())
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=400,
            code=ERROR_INVALID_PATH,
            message="run_id must resolve inside the project's runs directory",
            details={"run_id": run_id},
        ) from exc
    if not candidate.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message=f"Run not found: {run_id}",
            details={"run_id": run_id, "project_root": str(runs_dir.parent)},
        )
    return candidate


def _read_manifest(run_root: Path) -> dict:
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message=f"run_manifest.json missing for run: {run_root.name}",
            details={"run_id": run_root.name},
        )
    return read_json(manifest_path)


def _summarize_manifest(manifest: dict, *, run_id: str | None = None) -> dict:
    """Summarize one run manifest for the run list.

    The run directory name IS the run id (`runs/<run_id>/`), so a manifest that
    omits the field is incomplete, not unidentifiable — prefer the manifest and
    fall back to the directory. Emitting `run_id: null` would push a value no
    consumer can key, navigate to, or render.
    """

    return {
        "run_id": manifest.get("run_id") or run_id,
        "status": manifest.get("status"),
        "mode": manifest.get("mode"),
        "started_at": manifest.get("started_at"),
        "y": manifest.get("y"),
        "x": manifest.get("x"),
    }


def _artifact_counts(run_root: Path) -> dict[str, int]:
    index = _read_artifacts_index(run_root)
    counts: dict[str, int] = {}
    for record in index.get("artifacts", []):
        artifact_type = record.get("artifact_type", "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1
    return counts


def _read_artifacts_index(run_root: Path) -> dict:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        raise WorkbenchAPIError(
            status_code=503,
            code=ERROR_ARTIFACTS_INDEX_UNAVAILABLE,
            message="artifacts_index.json is unavailable",
            details={"run_id": run_root.name},
        )
    try:
        data = read_json(index_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_ARTIFACTS_INDEX_INVALID,
            message="artifacts_index.json is malformed",
            details={"run_id": run_root.name},
        ) from exc
    try:
        _validate_artifacts_index(run_root, data)
    except (ContractError, OSError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_ARTIFACTS_INDEX_INVALID,
            message="artifacts_index.json has an invalid canonical artifact list",
            details={"run_id": run_root.name},
        ) from exc
    raw = data.get("schema_version", 1)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message="artifacts_index.json schema_version is not an integer",
            details={"found": raw, "type": type(raw).__name__},
        )
    if raw < 1:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message=f"artifacts_index.json schema_version must be >= 1, got {raw}",
            details={"found": raw},
        )
    if raw > SUPPORTED_REGISTRY_VERSION:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_UNSUPPORTED,
            message=f"artifacts_index.json schema_version {raw} not supported",
            details={"found": raw, "supported": SUPPORTED_REGISTRY_VERSION},
        )
    return data


def _read_artifact_records(run_root: Path) -> list[dict]:
    return list(_read_artifacts_index(run_root).get("artifacts", []))


def _group_artifacts(records: list[dict]) -> list[dict]:
    by_type: dict[str, list[dict]] = {}
    for record in records:
        artifact_type = record.get("artifact_type", "unknown")
        by_type.setdefault(artifact_type, []).append(
            {
                "artifact_id": record.get("artifact_id"),
                "path": record.get("path"),
                "artifact_type": artifact_type,
                "step": record.get("step"),
                "sha256": record.get("sha256"),
            }
        )
    return [
        {"artifact_type": artifact_type, "items": items}
        for artifact_type, items in sorted(by_type.items())
    ]


def _resolve_artifact_path(run_root: Path, record: dict) -> Path:
    relative = record.get("path")
    if not isinstance(relative, str) or relative == "":
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message="Artifact has no path",
            details={"artifact_id": record.get("artifact_id")},
        )
    candidate = (run_root / relative).resolve()
    try:
        candidate.relative_to(run_root.resolve())
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=400,
            code=ERROR_INVALID_PATH,
            message="Artifact path resolved outside run root",
            details={"artifact_id": record.get("artifact_id")},
        ) from exc
    if not candidate.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Artifact file missing on disk: {relative}",
            details={"artifact_id": record.get("artifact_id")},
        )
    return candidate


def _list_existing_artifacts(run_root: Path) -> list[str]:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return []
    try:
        index = read_json(index_path)
        return [a.get("artifact_id", "?") for a in index.get("artifacts", [])]
    except Exception:
        return []


def _read_errors(run_root: Path) -> list[dict[str, Any]] | None:
    errors_path = run_root / "errors.json"
    if not errors_path.is_file():
        return None
    try:
        return read_json(errors_path).get("issues", [])
    except Exception:
        return None


def _detect_failed_stage(run_root: Path, existing: list[str]) -> str:
    if "report_html" in existing:
        return "report_registered_but_file_missing"
    if "poisson_1" in existing or "logit_1" in existing or "ols_1" in existing:
        return "model_fit_succeeded_report_build_failed"
    if "cleaned_dataset" in existing:
        return "data_cleaned_model_fit_failed_or_report_not_built"
    if "data_profile" in existing:
        return "data_profiled_cleaning_or_later_failed"
    return "early_failure"
