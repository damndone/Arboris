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


SEVERITY_ORDER: dict[str, int] = {"BLOCKER": 4, "WARNING": 3, "CAUTION": 2, "INFO": 1}


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
        "primary_reasons": _primary_reasons(all_issues, limit=4),
        "model_identity": model_identity,
        "artifact_manifest": _artifact_manifest(run_root, model_results),
        "diagnostic_highlights": _diagnostic_highlights([*all_issues, *infos]),
        "coefficient_risk": _coefficient_risk(summary, model_results),
        "interpretation_restrictions": _interpretation_restrictions(summary, all_issues),
        "recommended_actions": _recommended_actions(trust_status, summary, all_issues),
    }
    return _mark_partial_if_needed(preview)


def _issue_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


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


def _primary_reasons(issues: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    sorted_issues = sorted(
        issues,
        key=lambda issue: SEVERITY_ORDER.get(str(issue.get("severity")), 0),
        reverse=True,
    )
    return [_reason_from_issue(issue, index) for index, issue in enumerate(sorted_issues[:limit], start=1)]


def _reason_from_issue(issue: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "reason_id": f"reason_{index:03d}",
        "reason_key": str(issue.get("code") or "DIAGNOSTIC_ISSUE"),
        "severity": str(issue.get("severity") or "INFO"),
        "message": str(issue.get("message") or issue.get("code") or "Diagnostic issue"),
        "message_params": _message_params(issue),
        "affected_variables": list(issue.get("variables") or []),
        "linked_issue_ids": [issue["issue_id"]] if issue.get("issue_id") else [],
    }


def _diagnostic_highlights(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "highlight_id": f"highlight_{index:03d}",
            "highlight_key": str(issue.get("code") or "DIAGNOSTIC_ISSUE"),
            "category": _highlight_category(issue),
            "affected_stage": str(issue.get("affected_stage") or ""),
            "severity": str(issue.get("severity") or "INFO"),
            "message": str(issue.get("message") or issue.get("code") or "Diagnostic issue"),
            "message_params": _message_params(issue),
            "code": str(issue.get("code") or ""),
            "variables": list(issue.get("variables") or []),
            "metric": str(issue.get("metric") or ""),
            "value": issue.get("value"),
            "threshold": issue.get("threshold"),
            "linked_issue_ids": [issue["issue_id"]] if issue.get("issue_id") else [],
            "user_action_required": bool(issue.get("is_user_action_required")),
            "recommended_action_keys": [issue["recommended_action_key"]] if issue.get("recommended_action_key") else [],
        }
        for index, issue in enumerate(issues, start=1)
    ]


def _message_params(issue: dict[str, Any]) -> dict[str, Any]:
    params = issue.get("template_params")
    if isinstance(params, dict) and params:
        return params
    evidence = issue.get("evidence")
    return dict(evidence) if isinstance(evidence, dict) else {}


def _highlight_category(issue: dict[str, Any]) -> str:
    code = str(issue.get("code") or "")
    if "CATEGORICAL" in code:
        return "categorical"
    if "TREATMENT" in code or "PROXY" in code:
        return "coefficient_interpretation"
    if issue.get("severity") == "BLOCKER":
        return "blocking"
    return "diagnostic"


def _mark_partial_if_needed(preview: dict[str, Any]) -> dict[str, Any]:
    if preview.get("coefficient_risk") is None:
        preview["preview_status"] = "partial"
        preview["contract_warnings"].append("coefficient_risk is unavailable for this run.")
    return preview


# ---------------------------------------------------------------------------
# Coefficient risk, restrictions, actions (Task 3)
# ---------------------------------------------------------------------------

def _coefficient_risk(summary: dict[str, Any], model_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not model_results:
        return None
    primary_id = str(model_results[0].get("model_id") or "primary_model")
    rows = summary.get("coefficients_summary", {}).get("rows", [])
    if not isinstance(rows, list):
        rows = []
    issue_by_id = _issue_by_id(summary)
    models = []
    for index, model in enumerate(model_results):
        model_id = str(model.get("model_id") or f"model_{index + 1}")
        models.append({
            "model_id": model_id,
            "model_label": "Primary model" if index == 0 else "Secondary model",
            "is_primary": index == 0,
            "model_type": model.get("model_type") or "unknown",
            "outcome": summary.get("model_identity", {}).get("y_variable", ""),
            "risk_groups": _risk_groups(rows if index == 0 else [], issue_by_id, summary, model_id),
        })
    return {"primary_model_id": primary_id, "models": models}


def _risk_groups(
    rows: list[dict[str, Any]],
    issue_by_id: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    model_id: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_term = str(row.get("variable") or "")
        variable = str(row.get("display_name") or _original_variable(raw_term))
        if variable == "Intercept":
            continue
        group = grouped.setdefault(variable, _new_risk_group(variable, summary))
        linked = [item for item in row.get("linked_issues", []) if isinstance(item, str)]
        group["linked_issue_ids"] = sorted(set(group["linked_issue_ids"]) | set(linked))
        group["risk_level"] = _highest_severity(group["risk_level"], linked, issue_by_id)
        ref = group.pop("_reference_level", "1")
        group["terms"].append(_term_row(row, variable, ref, model_id))
    for group in grouped.values():
        group.pop("_reference_level", None)
        if group["variable_kind"] == "dummy_coded":
            group["interpretation_guide"] = "categorical_levels_vs_reference"
            group["summary"] = f"{group['variable']} was dummy-coded. Coefficients compare each level to the reference level."
    return list(grouped.values())


def _new_risk_group(variable: str, summary: dict[str, Any]) -> dict[str, Any]:
    encoded = _encoded_map(summary).get(variable)
    role_summary = _role_summary(summary, variable)
    variable_kind = "dummy_coded" if encoded else _variable_kind(role_summary)
    ref = str((encoded or {}).get("reference") or "1")
    return {
        "variable": variable,
        "display_name": variable,
        "variable_kind": variable_kind,
        "risk_level": "INFO",
        "interpretation_guide": "standard" if variable_kind == "continuous" else "review_required",
        "summary": "",
        "linked_issue_ids": [],
        "role_summary": role_summary,
        "_reference_level": ref,
        "terms": [],
    }


def _term_row(row: dict[str, Any], variable: str, reference_level: str, model_id: str) -> dict[str, Any]:
    raw_term = str(row.get("variable") or variable)
    level = str(row.get("level") or _level_from_term(raw_term) or "")
    display = f"{variable} = {level}" if level else variable
    return {
        "term": raw_term,
        "display_term": display,
        "level": level,
        "reference_level": reference_level,
        "estimate": row.get("estimate"),
        "p_value": row.get("p_value"),
        "source_id": f"model_results.{model_id}.coefficients.{raw_term}",
    }


def _issue_by_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    diagnostics = summary.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        return result
    for bucket in ("blockers", "warnings", "cautions", "info"):
        for issue in _issue_list(diagnostics.get(bucket)):
            issue_id = issue.get("issue_id")
            if isinstance(issue_id, str) and issue_id:
                result[issue_id] = issue
    return result


def _highest_severity(current: str, linked_issue_ids: list[str], issue_by_id: dict[str, dict[str, Any]]) -> str:
    winner = current
    for issue_id in linked_issue_ids:
        sev = str(issue_by_id.get(issue_id, {}).get("severity") or "INFO")
        if SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(winner, 0):
            winner = sev
    return winner


def _encoded_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    encoded = summary.get("preprocessing", {}).get("categorical_encoded", [])
    result: dict[str, dict[str, Any]] = {}
    if isinstance(encoded, list):
        for item in encoded:
            if isinstance(item, dict) and isinstance(item.get("variable"), str):
                result[item["variable"]] = item
    return result


def _role_summary(summary: dict[str, Any], variable: str) -> dict[str, Any]:
    roles = summary.get("preprocessing", {}).get("variable_roles", {})
    role_entries = roles.get(variable, {}).get("roles", []) if isinstance(roles, dict) else []
    if isinstance(role_entries, list) and role_entries:
        # Pick the first non-rejected role; rejected roles carry no signal.
        for role in role_entries:
            if role.get("status") not in ("rejected",):
                return {
                    "role": role.get("role", "unknown"),
                    "status": role.get("status", "unknown"),
                    "confidence": role.get("confidence"),
                    "needs_user_confirmation": bool(role.get("needs_user_confirmation", False)),
                }
        # All roles rejected → report the first one but mark status clearly.
        role = role_entries[0]
        return {
            "role": role.get("role", "unknown"),
            "status": "rejected",
            "confidence": None,
            "needs_user_confirmation": False,
        }
    return {"role": "unknown", "status": "unknown", "confidence": None, "needs_user_confirmation": False}


def _variable_kind(role_summary: dict[str, Any]) -> str:
    role = role_summary.get("role")
    status = role_summary.get("status")
    if role == "categorical" and status == "confirmed_by_rules":
        return "categorical_confirmed"
    if role == "categorical" and status == "candidate":
        return "categorical_candidate"
    if role == "treatment":
        return "treatment"
    if role == "proxy":
        return "proxy"
    if role == "id":
        return "id_like"
    if role == "time":
        return "time_like"
    return "continuous"


def _original_variable(term: str) -> str:
    if term.startswith("C(") and ")[T." in term:
        inner = term[2:term.find(")[T.")]
        if inner.startswith("Q('") and inner.endswith("')"):
            return inner[3:-2]
        if inner.startswith('Q("') and inner.endswith('")'):
            return inner[3:-2]
    return term


def _level_from_term(term: str) -> str | None:
    if "[T." not in term:
        return None
    start = term.rfind("[T.") + 3
    end = term.find("]", start)
    return term[start:end] if end > start else None


def _interpretation_restrictions(summary: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    constraints = summary.get("narrative_contract", {}).get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    result: list[dict[str, Any]] = []
    if constraints.get("causal_language_allowed") is False:
        result.append({
            "restriction_id": "restriction_causal_001",
            "restriction_type": "causal",
            "scope": "run",
            "severity": "CAUTION",
            "message": "Do not use causal language unless the research design justifies causal interpretation.",
            "forbidden_language": ["causes", "causal effect", "treatment improves"],
            "affected_variables": [],
            "affected_terms": [],
            "linked_issue_ids": [],
            "source": "narrative_contract",
        })
    if constraints.get("must_not_interpret_treatment_independently"):
        sev = "WARNING" if _has_issue_code(issues, "TREATMENT_PROXY_CORRELATION") else "CAUTION"
        result.append({
            "restriction_id": "restriction_treatment_proxy_001",
            "restriction_type": "treatment_proxy",
            "scope": "variable",
            "severity": sev,
            "message": "Do not interpret treatment-like coefficients independently when proxy or overlapping variables are flagged.",
            "forbidden_language": ["standalone treatment effect", "independent treatment effect"],
            "affected_variables": _variables_for_code(issues, "TREATMENT_PROXY_CORRELATION"),
            "affected_terms": [],
            "linked_issue_ids": _issue_ids_for_code(issues, "TREATMENT_PROXY_CORRELATION"),
            "source": "narrative_contract",
        })
    for issue in issues:
        if issue.get("code") == "CATEGORICAL_CANDIDATE":
            var = _issue_variable(issue)
            result.append({
                "restriction_id": f"restriction_categorical_{len(result) + 1:03d}",
                "restriction_type": "categorical",
                "scope": "variable",
                "severity": str(issue.get("severity") or "CAUTION"),
                "message": "Do not interpret categorical codes as continuous one-unit numeric effects.",
                "forbidden_language": ["one-unit increase", "per unit", "linear increase"],
                "affected_variables": [var] if var else [],
                "affected_terms": [],
                "linked_issue_ids": [issue["issue_id"]] if issue.get("issue_id") else [],
                "source": "issue",
            })
    return result


def _recommended_actions(trust_status: str, summary: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if trust_status == "blocked":
        actions.append(_action("action_global_blocked_001", "run", "BLOCKER", "DO_NOT_INTERPRET_UNTIL_BLOCKERS_RESOLVED", "Do not interpret the model results until blocking issues are resolved.", []))
    if trust_status == "usable_with_caution":
        actions.append(_action("action_global_caution_001", "run", "CAUTION", "REVIEW_CAUTIONS_BEFORE_INTERPRETING", "Review warnings and interpretation cautions before using coefficient-level conclusions.", []))
    counters: dict[str, int] = {}
    for issue in issues:
        code = str(issue.get("code") or "")
        if code == "TREATMENT_PROXY_CORRELATION":
            counters[code] = counters.get(code, 0) + 1
            actions.append(_action(f"action_issue_treatment_proxy_{counters[code]:03d}", "issue", str(issue.get("severity") or "CAUTION"), "INTERPRET_TREATMENT_PROXY_JOINTLY", "Interpret treatment and proxy variables jointly rather than as independent effects.", _issue_ids(issue), list(issue.get("variables") or [])))
        elif code == "CATEGORICAL_CANDIDATE":
            counters[code] = counters.get(code, 0) + 1
            actions.append(_action(f"action_issue_categorical_{counters[code]:03d}", "issue", str(issue.get("severity") or "CAUTION"), "REVIEW_CATEGORICAL_ENCODING", "Review categorical encoding before interpreting this variable.", _issue_ids(issue), [_issue_variable(issue)] if _issue_variable(issue) else []))
        elif code == "EXPOSURE_VARIABLE_DETECTED_BUT_NOT_USED":
            counters[code] = counters.get(code, 0) + 1
            actions.append(_action(f"action_issue_exposure_{counters[code]:03d}", "issue", str(issue.get("severity") or "WARNING"), "REVIEW_EXPOSURE_OFFSET_HANDLING", "Review exposure or offset handling before interpreting count-model coefficients.", _issue_ids(issue), list(issue.get("variables") or [])))
    return actions[:6]


def _action(action_id: str, scope: str, severity: str, key: str, message: str, linked_issue_ids: list[str], linked_variables: list[str] | None = None) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "scope": scope,
        "severity": severity,
        "action_key": key,
        "message": message,
        "linked_issue_ids": linked_issue_ids,
        "linked_variables": linked_variables or [],
    }


def _has_issue_code(issues: list[dict[str, Any]], code: str) -> bool:
    return any(issue.get("code") == code for issue in issues)


def _variables_for_code(issues: list[dict[str, Any]], code: str) -> list[str]:
    result: list[str] = []
    for issue in issues:
        if issue.get("code") == code:
            result.extend(str(v) for v in issue.get("variables", []) if v)
    return sorted(set(result))


def _issue_ids_for_code(issues: list[dict[str, Any]], code: str) -> list[str]:
    return [str(issue["issue_id"]) for issue in issues if issue.get("code") == code and issue.get("issue_id")]


def _issue_ids(issue: dict[str, Any]) -> list[str]:
    return [str(issue["issue_id"])] if issue.get("issue_id") else []


def _issue_variable(issue: dict[str, Any]) -> str:
    variables = issue.get("variables")
    if isinstance(variables, list) and variables:
        return str(variables[0])
    evidence = issue.get("evidence")
    if isinstance(evidence, dict) and evidence.get("column"):
        return str(evidence["column"])
    return ""
