"""Coefficient-risk aggregation grouped by original variable.

V1.3.2: uses workbench.term_parser for all term parsing. The previous local
helpers (_original_variable, _level_from_term) are gone.
"""
from __future__ import annotations

from typing import Any

from ..term_parser import parse_term
from ._shared import issue_list, SEVERITY_ORDER


def build_coefficient_risk(
    summary: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
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
        parsed = parse_term(raw_term)
        variable = str(row.get("display_name") or parsed.source_id)
        if variable == "Intercept":
            continue
        group = grouped.setdefault(variable, _new_risk_group(variable, summary))
        linked = [item for item in row.get("linked_issues", []) if isinstance(item, str)]
        group["linked_issue_ids"] = sorted(set(group["linked_issue_ids"]) | set(linked))
        group["risk_level"] = _highest_severity(group["risk_level"], linked, issue_by_id)
        ref = group.pop("_reference_level", "1")
        group["terms"].append(_term_row(row, parsed, variable, ref, model_id))
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


def _term_row(
    row: dict[str, Any],
    parsed,  # ParsedTerm
    variable: str,
    reference_level: str,
    model_id: str,
) -> dict[str, Any]:
    raw_term = str(row.get("variable") or variable)
    level = str(row.get("level") or _level_from_parsed(parsed) or "")
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


def _level_from_parsed(parsed) -> str | None:
    """Extract the dummy-level label from a parsed term, or None for non-dummy."""
    if not parsed.is_dummy:
        return None
    if " = " in parsed.display_term:
        return parsed.display_term.split(" = ", 1)[1]
    return None


def _issue_by_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    diagnostics = summary.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        return result
    for bucket in ("blockers", "warnings", "cautions", "info"):
        for issue in issue_list(diagnostics.get(bucket)):
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
        role = role_entries[0]
        return {
            "role": role.get("role", "unknown"),
            "status": role.get("status", "unknown"),
            "confidence": role.get("confidence"),
            "needs_user_confirmation": bool(role.get("needs_user_confirmation", False)),
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
