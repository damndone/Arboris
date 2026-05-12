from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifacts import read_json
from .artifact_manifest import build_artifact_manifest
from .contract_validation import (
    PREVIEW_CONTRACT_VERSION,
    SOURCE_SCHEMA_VERSION,
    RUNNING_STATUSES,
    LIFECYCLE_UNAVAILABLE_STATUSES,
    TERMINAL_FAILURE_STATUSES,
    base_unavailable,
    failed_preview,
    mark_partial_if_needed,
)
from .coefficient_risk import build_coefficient_risk
from ._shared import issue_list as _issue_list, SEVERITY_ORDER
from .guidance import (
    primary_reasons,
    diagnostic_highlights,
    interpretation_restrictions,
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
    blockers = _issue_list(diagnostics.get("blockers"))
    warnings = _issue_list(diagnostics.get("warnings"))
    cautions = _issue_list(diagnostics.get("cautions"))
    infos = _issue_list(diagnostics.get("info"))
    counts = {
        "blockers": len(blockers),
        "warnings": len(warnings),
        "cautions": len(cautions),
        "info": len(infos),
    }
    has_results = bool(model_results)
    trust_status = _trust_status(counts, has_results)
    trust_label = _trust_label_for_status(trust_status)
    model_identity = _model_identity(summary, manifest, model_results)
    all_issues = [*blockers, *warnings, *cautions]
    preview = {
        "available": True,
        "preview_contract_version": PREVIEW_CONTRACT_VERSION,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "preview_status": "complete",
        "contract_warnings": [],
        "run_lifecycle_status": str(manifest.get("status") or "completed"),
        "run_status": {
            "status": trust_status,
            "status_scope": "primary_model",
            "safe_to_generate_report": trust_status in {"ok", "usable_with_caution"},
            "safe_to_interpret": _safe_to_interpret(trust_status),
            "has_blockers": counts["blockers"] > 0,
            "has_warnings": counts["warnings"] > 0,
            "has_cautions": counts["cautions"] > 0,
            "model_results_available": has_results,
        },
        "trust_label": trust_label,
        "trust_counts": counts,
        "primary_reasons": primary_reasons(all_issues, limit=4),
        "model_identity": model_identity,
        "artifact_manifest": build_artifact_manifest(run_root, model_results),
        "diagnostic_highlights": diagnostic_highlights([*all_issues, *infos]),
        "coefficient_risk": build_coefficient_risk(summary, model_results),
        "interpretation_restrictions": interpretation_restrictions(summary, all_issues),
        "recommended_actions": recommended_actions(trust_status, summary, all_issues),
    }
    return mark_partial_if_needed(preview)


def _trust_status(counts: dict[str, int], has_model_results: bool) -> str:
    if not has_model_results:
        return "failed"
    if counts["blockers"] > 0:
        return "blocked"
    if counts["warnings"] > 0 or counts["cautions"] > 0:
        return "usable_with_caution"
    return "ok"


def _trust_label_for_status(status: str) -> str:
    return {
        "ok": "ready_to_interpret",
        "usable_with_caution": "interpret_with_caution",
        "blocked": "not_ready_to_interpret",
        "failed": "run_failed",
    }[status]


def _safe_to_interpret(status: str) -> str:
    return {
        "ok": "yes",
        "usable_with_caution": "partial",
        "blocked": "no",
        "failed": "unavailable",
    }[status]


def _model_identity(
    summary: dict[str, Any],
    manifest: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = summary.get("model_identity", {}) if isinstance(summary.get("model_identity"), dict) else {}
    primary = model_results[0] if model_results else {}
    x_vars = raw.get("x_variables") or manifest.get("x") or []
    model_type = primary.get("model_type") or raw.get("model_family") or "unknown"
    identity = {
        "primary_model_id": primary.get("model_id") or "unavailable",
        "model_label": raw.get("model_label") or _model_label(model_type),
        "model_type": model_type,
        "y_variable": raw.get("y_variable") or manifest.get("y") or "",
        "n_observations": raw.get("n_observations") or primary.get("nobs") or 0,
    }
    if isinstance(x_vars, list):
        identity["x_variables"] = x_vars
        identity["x_variable_count"] = len(x_vars)
    identity["standard_error_type"] = _standard_error_type(model_type)
    return identity


def _model_label(model_type: str) -> str:
    labels = {
        "ols": "OLS regression",
        "ols_robust": "OLS regression",
        "logit": "Logistic regression",
        "poisson": "Poisson regression",
        "poisson_rate": "Poisson rate model",
    }
    return labels.get(model_type, str(model_type))


def _standard_error_type(model_type: str) -> str:
    if model_type == "ols_robust":
        return "robust"
    return "unavailable"


