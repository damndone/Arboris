"""Lifecycle / contract fallback paths for the preview.

Owns: base unavailable payload, failed-run preview, malformed/legacy handling,
preview_status partial marking.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_manifest import build_artifact_manifest

PREVIEW_CONTRACT_VERSION = "1.0"
SOURCE_SCHEMA_VERSION = "diagnostic_summary.v1"

RUNNING_STATUSES = {"queued", "running"}
LIFECYCLE_UNAVAILABLE_STATUSES = {"interrupted", "cancelled"}
TERMINAL_FAILURE_STATUSES = {"failed"}


def base_unavailable(lifecycle: str, preview_status: str, trust_label: str) -> dict[str, Any]:
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


def failed_preview(
    run_root: Path,
    manifest: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    preview = base_unavailable(str(manifest.get("status") or "failed"), "unavailable", "run_failed")
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
    preview["artifact_manifest"] = build_artifact_manifest(run_root, model_results)
    return preview


def mark_partial_if_needed(preview: dict[str, Any]) -> dict[str, Any]:
    if preview.get("coefficient_risk") is None:
        preview["preview_status"] = "partial"
        preview["contract_warnings"].append("coefficient_risk is unavailable for this run.")
    return preview


def trust_status(counts: dict[str, int], has_model_results: bool) -> str:
    if not has_model_results:
        return "failed"
    if counts["blockers"] > 0:
        return "blocked"
    if counts["warnings"] > 0 or counts["cautions"] > 0:
        return "usable_with_caution"
    return "ok"


def trust_label_for_status(status: str) -> str:
    return {
        "ok": "ready_to_interpret",
        "usable_with_caution": "interpret_with_caution",
        "blocked": "not_ready_to_interpret",
        "failed": "run_failed",
    }[status]


def safe_to_interpret(status: str) -> str:
    return {
        "ok": "yes",
        "usable_with_caution": "partial",
        "blocked": "no",
        "failed": "unavailable",
    }[status]
