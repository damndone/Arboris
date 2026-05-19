from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .artifacts import register_artifact, write_text_durable


def _normalize_to_view_model(data: dict[str, Any]) -> dict[str, Any]:
    if "critical_errors" in data:
        return data
    return {
        "title": data.get("title", "Econometrics Report"),
        "facts": data.get("facts", []),
        "critical_errors": [
            {"text": i.get("message", str(i)), "code": i.get("code", ""), "severity": i.get("severity", "")}
            for i in data.get("warnings", []) if isinstance(i, dict) and i.get("severity") == "BLOCKER"
        ],
        "warnings": [
            {"text": i.get("message", str(i)), "code": i.get("code", ""), "severity": i.get("severity", "")}
            for i in data.get("warnings", []) if isinstance(i, dict) and i.get("severity") == "WARNING"
        ],
        "cautions": [
            {"text": i.get("message", str(i)), "code": i.get("code", ""), "severity": i.get("severity", "")}
            for i in data.get("warnings", []) if isinstance(i, dict) and i.get("severity") == "CAUTION"
        ],
        "system_notes": [
            {"text": i.get("message", str(i)), "code": i.get("code", ""), "severity": i.get("severity", "")}
            for i in data.get("warnings", []) if isinstance(i, dict) and i.get("severity") == "INFO"
        ],
        "coefficient_interpretations": [
            {"text": c.get("claim", ""), "variable": "", "interpretation_guide": "standard"}
            for c in data.get("claims", [])
        ],
        "causal_caution": "",
        "descriptive_stats": data.get("descriptive_stats"),
        "statistical_tests": data.get("statistical_tests"),
        "model_diagnostics": data.get("diagnostics", {}),
        "model_quality": None,
    }


def render_html_report(view_model: dict[str, Any], run_root: Path) -> Path:
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_path = reports_dir / "report.html"

    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True,
    )
    template = environment.get_template("report.html.j2")
    write_text_durable(html_path, template.render(view_model=_normalize_to_view_model(view_model)))
    register_artifact(run_root, "report_html", html_path, "report", "reporting", [])
    return html_path
