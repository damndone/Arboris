from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import read_json
from .narrative.render import render_template


def build_report_view_model(summary: dict[str, Any], run_root: Path) -> dict[str, Any]:
    diagnostics = summary.get("diagnostics", {})

    def _render_issues(issues: list[dict]) -> list[dict]:
        result: list[dict] = []
        for issue in issues:
            tk = issue.get("template_key", "")
            params = issue.get("template_params", {})
            if tk:
                try:
                    text = render_template(tk, params)
                except (KeyError, ValueError):
                    text = issue.get("message", "")
            else:
                text = issue.get("message", "")
            result.append({
                "text": text,
                "code": issue.get("code", ""),
                "severity": issue.get("severity", ""),
                "variables": issue.get("variables", []),
            })
        return result

    coeff_rows = summary.get("coefficients_summary", {}).get("rows", [])
    coeff_views: list[dict] = []
    for row in coeff_rows:
        tk = row.get("template_key", "")
        if tk:
            try:
                text = render_template(tk, {
                    "variable": row.get("display_name", row.get("variable", "")),
                    "estimate": _format_estimate(row.get("estimate")),
                    "p_label": row.get("significance_label", "not reported"),
                    "y": summary.get("model_identity", {}).get("y_variable", "y"),
                    "level": "",
                    "reference": "1",
                })
            except (KeyError, ValueError):
                text = ""
        else:
            text = ""
        coeff_views.append({
            "text": text,
            "variable": row.get("variable", ""),
            "interpretation_guide": row.get("interpretation_guide", "standard"),
        })

    nc = summary.get("narrative_contract", {})
    has_treatment = nc.get("constraints", {}).get("must_not_interpret_treatment_independently", False)
    if has_treatment:
        try:
            causal_text = render_template("causal_caution_with_treatment", {})
        except (KeyError, ValueError):
            causal_text = ""
    else:
        try:
            causal_text = render_template("causal_caution_default", {})
        except (KeyError, ValueError):
            causal_text = ""

    descriptive_stats = _load_if_exists(run_root / "staged" / "data_profile.json")
    stat_tests = _load_if_exists(run_root / "staged" / "statistical_test_summaries.json")

    model_diag: dict[str, Any] = {}
    diag_dir = run_root / "model_results"
    if diag_dir.is_dir():
        for path in sorted(diag_dir.glob("diagnostics_*.json")):
            try:
                data = read_json(path)
                if isinstance(data, dict):
                    model_diag[path.stem] = data
            except Exception:
                pass

    return {
        "title": summary.get("model_identity", {}).get("model_label", "Econometrics Report"),
        "facts": _build_facts_list(summary),
        "critical_errors": _render_issues(diagnostics.get("blockers", [])),
        "warnings": _render_issues(diagnostics.get("warnings", [])),
        "cautions": _render_issues(diagnostics.get("cautions", [])),
        "system_notes": _render_issues(diagnostics.get("info", [])),
        "coefficient_interpretations": coeff_views,
        "causal_caution": causal_text,
        "descriptive_stats": descriptive_stats,
        "statistical_tests": stat_tests,
        "model_diagnostics": model_diag,
        "model_quality": summary.get("model_quality"),
    }


def _build_facts_list(summary: dict[str, Any]) -> list[str]:
    mi = summary.get("model_identity", {})
    pp = summary.get("preprocessing", {})
    facts = [
        f"Model: {mi.get('model_label', '')}",
        f"y = {mi.get('y_variable', '')};  X = {', '.join(mi.get('x_variables', []))}",
        f"Rows used: {mi.get('n_observations', 0)} · Columns: {pp.get('column_count_after_encoding', mi.get('n_predictors_after_encoding', 0) + 1)}",
        f"Dataset kind: {mi.get('dataset_kind', 'unknown')}",
    ]
    encoded = pp.get("categorical_encoded", [])
    if encoded:
        names = ", ".join(e["variable"] for e in encoded)
        facts.append(f"Categorical variable(s): {names} (dummy-coded in model)")
    return facts


def _format_estimate(estimate: Any) -> str:
    if estimate is None:
        return "N/A"
    try:
        return f"{float(estimate):+.4f}"
    except (ValueError, TypeError):
        return str(estimate)


def _load_if_exists(path: Path) -> Any | None:
    if path.is_file():
        try:
            return read_json(path)
        except Exception:
            return None
    return None
