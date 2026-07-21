"""Entry point: assembles the diagnostic_summary_preview payload.

V1.3.2: refactored into a thin orchestrator. Most work delegated to
artifact_manifest, contract_validation, coefficient_risk, and guidance.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifacts import read_json
from ._shared import issue_list
from .artifact_manifest import build_artifact_manifest
from .contract_validation import (
    LIFECYCLE_UNAVAILABLE_STATUSES,
    PREVIEW_CONTRACT_VERSION,
    RUNNING_STATUSES,
    SOURCE_SCHEMA_VERSION,
    TERMINAL_FAILURE_STATUSES,
    base_unavailable,
    failed_preview,
    mark_partial_if_needed,
    safe_to_interpret,
    trust_label_for_status,
    trust_status,
)
from .coefficient_risk import build_coefficient_risk
from .guidance import (
    diagnostic_highlights,
    interpretation_restrictions,
    model_identity,
    primary_reasons,
    recommended_actions,
)


def build_diagnostic_summary_preview(
    run_root: Path,
    manifest: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    lifecycle = str(manifest.get("status") or "completed")
    if lifecycle in RUNNING_STATUSES:
        return base_unavailable(lifecycle, "pending", "analysis_running")
    if lifecycle in LIFECYCLE_UNAVAILABLE_STATUSES:
        return base_unavailable(lifecycle, "lifecycle_unavailable", "lifecycle_unavailable")
    if lifecycle in TERMINAL_FAILURE_STATUSES:
        return failed_preview(run_root, manifest, model_results)

    summary_path = run_root / "diagnostic_summary.json"
    if not summary_path.is_file():
        preview = base_unavailable(lifecycle, "unavailable", "legacy_unavailable")
        preview["contract_warnings"].append("diagnostic_summary.json is missing; using legacy/debug fallback.")
        preview["artifact_manifest"] = build_artifact_manifest(run_root, model_results)
        return preview

    try:
        summary = read_json(summary_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        preview = base_unavailable(lifecycle, "malformed", "contract_unavailable")
        preview["contract_warnings"].append(f"diagnostic_summary.json could not be parsed: {exc}")
        preview["artifact_manifest"] = build_artifact_manifest(run_root, model_results)
        return preview

    return _complete_or_partial_preview(run_root, manifest, summary, model_results)


def _complete_or_partial_preview(
    run_root: Path,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    diagnostics = summary.get("diagnostics", {})
    blockers = issue_list(diagnostics.get("blockers"))
    warnings = issue_list(diagnostics.get("warnings"))
    cautions = issue_list(diagnostics.get("cautions"))
    infos = issue_list(diagnostics.get("info"))
    counts = {
        "blockers": len(blockers),
        "warnings": len(warnings),
        "cautions": len(cautions),
        "info": len(infos),
    }
    persisted_status = summary.get("run_status")
    if not isinstance(persisted_status, dict):
        persisted_status = {}
    # A completed run can produce a primary model result that the coefficient
    # projection does not surface (e.g. the ARMA-GARCH pack has no classic
    # coefficient table). Trust the backend's persisted model_results_available
    # flag so such runs are not mislabelled "run failed".
    has_results = bool(model_results) or bool(
        persisted_status.get("model_results_available")
    )
    status = trust_status(counts, has_results)
    label = trust_label_for_status(status)
    identity = model_identity(summary, manifest, model_results)
    all_issues = [*blockers, *warnings, *cautions]
    preview = {
        "available": True,
        "preview_contract_version": PREVIEW_CONTRACT_VERSION,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "preview_status": "complete",
        "contract_warnings": [],
        "run_lifecycle_status": str(manifest.get("status") or "completed"),
        "run_status": {
            "status": status,
            "status_scope": "primary_model",
            "safe_to_generate_report": status in {"ok", "usable_with_caution"},
            "safe_to_interpret": safe_to_interpret(status),
            "has_blockers": counts["blockers"] > 0,
            "has_warnings": counts["warnings"] > 0,
            "has_cautions": counts["cautions"] > 0,
            "model_results_available": has_results,
            "report_render_status": persisted_status.get("report_render_status", "unknown"),
            "report_available": bool(persisted_status.get("report_available", False)),
        },
        "trust_label": label,
        "trust_counts": counts,
        "primary_reasons": primary_reasons(all_issues, limit=4),
        "model_identity": identity,
        "artifact_manifest": build_artifact_manifest(run_root, model_results),
        "diagnostic_highlights": diagnostic_highlights([*all_issues, *infos]),
        "coefficient_risk": build_coefficient_risk(summary, model_results),
        "interpretation_restrictions": interpretation_restrictions(summary, all_issues),
        "recommended_actions": recommended_actions(status, summary, all_issues),
    }
    return mark_partial_if_needed(preview)
