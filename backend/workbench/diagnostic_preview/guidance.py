"""Recommended actions, interpretation restrictions, primary-reasons, highlights.

Renders the preview's "what should the user do" surface.
"""
from __future__ import annotations

from typing import Any

from ._shared import SEVERITY_ORDER, issue_list


def primary_reasons(issues: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    sorted_issues = sorted(
        issues,
        key=lambda issue: SEVERITY_ORDER.get(str(issue.get("severity")), 0),
        reverse=True,
    )
    return [_reason_from_issue(issue, index) for index, issue in enumerate(sorted_issues[:limit], start=1)]


def diagnostic_highlights(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def interpretation_restrictions(summary: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def recommended_actions(trust_status: str, summary: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
