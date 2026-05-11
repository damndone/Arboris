from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import read_json

PREVIEW_CONTRACT_VERSION = "1.0"
SOURCE_SCHEMA_VERSION = "diagnostic_summary.v1"

RUNNING_STATUSES = {"queued", "running"}
LIFECYCLE_UNAVAILABLE_STATUSES = {"interrupted", "cancelled"}
TERMINAL_FAILURE_STATUSES = {"failed"}


def build_diagnostic_summary_preview(
    run_root: Path,
    manifest: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    lifecycle = str(manifest.get("status") or "completed")
    if lifecycle in RUNNING_STATUSES:
        return _base_unavailable(lifecycle, "pending", "analysis_running")
    if lifecycle in LIFECYCLE_UNAVAILABLE_STATUSES:
        return _base_unavailable(lifecycle, "lifecycle_unavailable", "lifecycle_unavailable")
    if lifecycle in TERMINAL_FAILURE_STATUSES:
        return _failed_preview(run_root, manifest, model_results)

    summary_path = run_root / "diagnostic_summary.json"
    if not summary_path.is_file():
        preview = _base_unavailable(lifecycle, "unavailable", "legacy_unavailable")
        preview["contract_warnings"].append("diagnostic_summary.json is missing; using legacy/debug fallback.")
        preview["artifact_manifest"] = _artifact_manifest(run_root, model_results)
        return preview

    try:
        summary = read_json(summary_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        preview = _base_unavailable(lifecycle, "malformed", "contract_unavailable")
        preview["contract_warnings"].append(f"diagnostic_summary.json could not be parsed: {exc}")
        preview["artifact_manifest"] = _artifact_manifest(run_root, model_results)
        return preview

    return _complete_or_partial_preview(run_root, manifest, summary, model_results)


def _base_unavailable(lifecycle: str, preview_status: str, trust_label: str) -> dict[str, Any]:
    return {
        "available": False,
        "preview_contract_version": PREVIEW_CONTRACT_VERSION,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "preview_status": preview_status,
        "contract_warnings": [],
        "run_lifecycle_status": lifecycle,
        "trust_label": trust_label,
        "primary_reasons": [],
    }


def _failed_preview(
    run_root: Path,
    manifest: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    preview = _base_unavailable(str(manifest.get("status") or "failed"), "unavailable", "run_failed")
    preview["run_status"] = {
        "status": "failed",
        "status_scope": "run_level",
        "safe_to_generate_report": False,
        "safe_to_interpret": "unavailable",
        "has_blockers": True,
        "has_warnings": False,
        "has_cautions": False,
        "model_results_available": bool(model_results),
    }
    preview["trust_counts"] = {"blockers": 1, "warnings": 0, "cautions": 0, "info": 0}
    preview["artifact_manifest"] = _artifact_manifest(run_root, model_results)
    return preview


def _artifact_manifest(run_root: Path, model_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "report_html": _file_artifact(run_root / "reports" / "report.html", "report_html", "report.html"),
        "diagnostic_summary_json": {
            **_file_artifact(run_root / "diagnostic_summary.json", "diagnostic_summary", "diagnostic_summary.json"),
            "schema_valid": (run_root / "diagnostic_summary.json").is_file(),
        },
        "primary_model_results": {
            "expected": True,
            "available": bool(model_results),
            "readable": bool(model_results),
            "model_id": model_results[0].get("model_id") if model_results else None,
        },
        "secondary_model_results": {
            "expected": len(model_results) > 1,
            "available_count": max(len(model_results) - 1, 0),
        },
        "errors_json": {
            **_file_artifact(run_root / "errors.json", "errors_json", "errors.json"),
            "legacy_debug_only": True,
        },
    }


def _file_artifact(path: Path, artifact_id: str, filename: str) -> dict[str, Any]:
    available = path.is_file()
    return {
        "expected": True,
        "available": available,
        "readable": available,
        "artifact_id": artifact_id,
        "filename": filename,
    }


# Stubs for Task 2 — will be expanded
def _complete_or_partial_preview(
    run_root: Path,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {}
