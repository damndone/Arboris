from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_diagnostic_summary(
    issue_dicts: list[dict[str, Any]],
    model_results: list[dict[str, Any]],
    routing: dict[str, Any],
    normalized_y: str,
    normalized_x: list[str],
    profile: dict[str, Any],
    categorical_vars: set[str],
    y_type: str,
    primary_type: str,
    variable_roles: dict[str, Any],
    run_id: str = "",
    exposure_col: str | None = None,
    dropped_vars: list[dict[str, str]] | list[str] | None = None,
    coercions: list[dict[str, Any]] | None = None,
    imputation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict] = []
    warnings: list[dict] = []
    cautions: list[dict] = []
    infos: list[dict] = []

    for issue in issue_dicts:
        sev = issue.get("severity", "INFO")
        if sev == "BLOCKER":
            blockers.append(issue)
        elif sev == "WARNING":
            warnings.append(issue)
        elif sev == "CAUTION":
            cautions.append(issue)
        else:
            infos.append(issue)

    primary_result = model_results[0] if model_results else {}
    coefficients = primary_result.get("coefficients", {})
    if not isinstance(coefficients, Mapping):
        coefficients = {}

    coeff_rows: list[dict] = []
    treatment_roles = _get_confirmed_roles(variable_roles, "treatment")
    proxy_vars = _get_candidate_roles(variable_roles, "proxy")

    for term, coef in coefficients.items():
        if term == "Intercept" or not isinstance(coef, Mapping):
            continue
        est = coef.get("estimate")
        p = coef.get("p_value")
        if est is None:
            continue
        std_err = coef.get("std_error")
        p_label = _significance_label(p)
        interpretation_guide = "standard"
        template_key = "coef_continuous_association"
        linked_issues: list[str] = []

        term_base = _term_base_name(term)
        cat_level = _cat_level(term)

        if cat_level is not None and term_base in categorical_vars:
            interpretation_guide = "categorical_level"
            template_key = "coef_categorical"
        elif term in treatment_roles or term_base in treatment_roles or term_base in _get_candidate_roles(variable_roles, "treatment"):
            if _has_proxy_correlation(term_base, proxy_vars, issue_dicts):
                interpretation_guide = "warn_joint"
                template_key = "coef_warn_joint"
                linked_issues = [i.get("issue_id", "") for i in issue_dicts
                                 if i.get("code") == "TREATMENT_PROXY_CORRELATION" and term_base in i.get("variables", [])]
            else:
                interpretation_guide = "treatment_direct"
                template_key = "coef_binary_association"

        coeff_rows.append({
            "variable": term,
            "display_name": term_base,
            "level": cat_level or "",
            "estimate": round(float(est), 4),
            "std_error": round(float(std_err), 4) if std_err is not None else None,
            "p_value": round(float(p), 4) if p is not None else None,
            "significance_label": p_label,
            "interpretation_guide": interpretation_guide,
            "linked_issues": linked_issues,
            "template_key": template_key,
        })

    encoded_cat = [
        {"variable": v, "n_levels": _n_levels(v, coefficients), "reference": "1", "method": "treatment_dummy"}
        for v in sorted(categorical_vars)
    ]

    has_treatment = len(treatment_roles) > 0
    has_treatment_proxy = any(
        i.get("code") == "TREATMENT_PROXY_CORRELATION" for i in issue_dicts
    )
    has_categorical = len(encoded_cat) > 0

    required_mentions: list[str] = []
    forbidden_claims: list[str] = [
        "causal effect of treatment",
        "one-hot encoding required",
        "X causes Y",
        "treatment improves Y",
    ]
    if has_treatment_proxy:
        required_mentions.append("treatment-proxy correlation")
    if has_categorical:
        required_mentions.append("categorical auto-encoding")

    narrative_contract = {
        "summary": f"{_model_label(primary_type)} with {'categorical auto-encoding and ' if has_categorical else ''}{'treatment-proxy correlation detected.' if has_treatment_proxy else 'no major diagnostic concerns.'}",
        "constraints": {
            "causal_language_allowed": False,
            "allowed_effect_language": "association_only",
            "must_not_claim_policy_effect": True,
            "must_not_interpret_treatment_independently": has_treatment,
            "must_acknowledge_treatment_proxy_correlation": has_treatment_proxy,
            "must_note_categorical_encoded": has_categorical,
            "must_not_hide_blockers": True,
            "must_not_change_severity": True,
            "must_not_add_uncomputed_statistics": True,
        },
        "required_mentions": required_mentions,
        "forbidden_claims": forbidden_claims,
    }

    drop = dropped_vars or []
    coerc = coercions or []
    encoded_count = sum(
        _count_dummy_coefs(v, coefficients) for v in categorical_vars
    )
    n_original = len(normalized_x)
    n_after = n_original - len(drop) + encoded_count

    metrics: dict[str, Any] = {}
    for key in ("r_squared", "f_statistic", "f_p_value", "aic", "bic", "pseudo_r2", "llf"):
        val = primary_result.get(key)
        if val is not None:
            metrics[key] = val
    primary_keys = _primary_metric_keys(y_type, metrics)

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "run_status": {
            "model_fit_status": "success",
            "report_render_status": "pending",
            "has_blockers": len(blockers) > 0,
            "has_warnings": len(warnings) > 0,
            "model_results_available": len(model_results) > 0,
            "report_available": False,
            "safe_to_generate_report": len(blockers) == 0,
        },
        "model_identity": {
            "model_family": primary_type,
            "model_label": _model_label(primary_type),
            "y_variable": normalized_y,
            "x_variables": normalized_x,
            "n_observations": profile.get("row_count", 0),
            "n_predictors_original": n_original,
            "n_predictors_after_encoding": n_after,
            "dataset_kind": routing.get("kind", "unknown"),
            "interpretation_mode": "associational",
        },
        "preprocessing": {
            "variable_roles": variable_roles,
            "categorical_encoded": encoded_cat,
            "exposure_variable": exposure_col,
            "variables_dropped": drop,
            "coercions_applied": coerc,
            "imputation": imputation or {},
            "column_count_after_encoding": profile.get("column_count", 0) + encoded_count,
        },
        "diagnostics": {
            "blockers": blockers,
            "warnings": warnings,
            "cautions": cautions,
            "info": infos,
        },
        "coefficients_summary": {
            "interpretation_mode": "associational",
            "rows": coeff_rows,
            "full_table_ref": f"model_results/{primary_result.get('model_id', 'model')}.json",
        },
        "model_quality": {
            "metrics": metrics,
            "primary_metric_keys": primary_keys,
            "metric_notes": [],
        },
        "narrative_contract": narrative_contract,
    }


def _model_label(primary_type: str) -> str:
    labels = {
        "ols": "OLS",
        "ols_robust": "OLS with robust standard errors",
        "logit": "Logistic regression",
        "poisson": "Poisson regression",
        "poisson_rate": "Poisson rate model",
    }
    return labels.get(primary_type, primary_type)


def _significance_label(p: float | None) -> str:
    if p is None:
        return "not reported"
    if p < 0.01:
        return "significant at the 1% level"
    if p < 0.05:
        return "significant at the 5% level"
    if p < 0.10:
        return "marginally significant"
    return "not statistically significant at conventional levels"


def _get_confirmed_roles(roles: dict, role_name: str) -> set[str]:
    result: set[str] = set()
    for var, info in roles.items():
        for r in info.get("roles", []):
            if r.get("role") == role_name and r.get("status") == "confirmed_by_rules":
                result.add(var)
    return result


def _get_candidate_roles(roles: dict, role_name: str) -> set[str]:
    result: set[str] = set()
    for var, info in roles.items():
        for r in info.get("roles", []):
            if r.get("role") == role_name and r.get("status") != "rejected":
                result.add(var)
    return result


def _has_proxy_correlation(term: str, proxy_vars: set[str], issues: list[dict]) -> bool:
    for issue in issues:
        if issue.get("code") == "TREATMENT_PROXY_CORRELATION":
            vars_in = set(issue.get("variables", []))
            if term in vars_in and any(p in vars_in for p in proxy_vars):
                return True
    return False


def _term_base_name(term: str) -> str:
    if "[T." in term and term.startswith("C("):
        end = term.find(")[T.")
        if end > 2:
            inner = term[2:end]
            if inner.startswith("Q('") and inner.endswith("')"):
                return inner[3:-2]
            if inner.startswith('Q("') and inner.endswith('")'):
                return inner[3:-2]
    return term


def _n_levels(var: str, coefficients: Mapping) -> int:
    count = 0
    for term in coefficients:
        base = _term_base_name(term)
        if base == var and "[T." in term:
            count += 1
    return max(count, 2)


def _count_dummy_coefs(var: str, coefficients: Mapping) -> int:
    count = 0
    for term in coefficients:
        base = _term_base_name(term)
        if base == var and "[T." in term:
            count += 1
    return count


def _cat_level(term: str) -> str | None:
    if "[T." in term:
        start = term.rfind("[T.") + 3
        end = term.find("]", start)
        if end > start:
            return term[start:end]
    return None


def _primary_metric_keys(y_type: str, metrics: dict) -> list[str]:
    if y_type == "binary":
        return [k for k in ["pseudo_r2", "aic", "bic"] if k in metrics]
    if y_type == "count":
        return [k for k in ["aic", "bic"] if k in metrics]
    return [k for k in ["r_squared", "aic", "bic"] if k in metrics]
