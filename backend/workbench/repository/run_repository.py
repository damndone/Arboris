"""Filesystem reads over a project's ``runs/`` directory.

Pure path-resolution + JSON/artifact reads. Every function is side-effect free
apart from reading files. Not-found / invalid-path conditions raise
``WorkbenchAPIError`` so the HTTP layer maps them to the right status code.

Extracted verbatim from ``api.py`` in v1.6.10 (D1 decomposition, Phase 1); the
symbols are re-exported from ``workbench.api`` for backward-compatible imports.
"""
from __future__ import annotations

from pathlib import Path
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

# Highest artifacts_index.json schema_version this server understands.
SUPPORTED_REGISTRY_VERSION = 1


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
        return {"artifacts": []}
    data = read_json(index_path)
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
