from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

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
        "exploration": data.get("exploration"),
        "statistical_tests": data.get("statistical_tests"),
        "statistical_evidence": data.get("statistical_evidence"),
        "regression_table": data.get("regression_table"),
        "model_family_evidence": data.get("model_family_evidence"),
        "model_diagnostics": data.get("diagnostics", {}),
        "model_quality": None,
    }


def render_html_report(
    view_model: dict[str, Any],
    run_root: Path,
    *,
    filename: str = "report.html",
    artifact_id: str = "report_html",
    inputs: list[str] | tuple[str, ...] = (),
    evidence_port: Any = None,
    admission_receipt: Any = None,
) -> Path:
    from .agent.workflow_runtime import (
        prepare_formal_workflow_output,
        record_formal_workflow_artifact,
    )

    output = prepare_formal_workflow_output(
        evidence_port,
        admission_receipt,
        run_root=run_root,
        directory_name="reports",
        filename=filename,
    )

    try:
        environment = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "templates"),
            autoescape=True,
        )
        if view_model.get("report_kind") == "arma_garch":
            template = environment.get_template("arma_garch_report.html.j2")
            rendered_view_model = view_model
        else:
            template = environment.get_template("report.html.j2")
            rendered_view_model = _normalize_to_view_model(view_model)
        with output.open_binary() as stream:
            stream.write(template.render(view_model=rendered_view_model).encode("utf-8"))
            stream.flush()
        html_path = output.commit()
    except Exception:
        output.abort()
        raise
    try:
        record_formal_workflow_artifact(
            evidence_port,
            admission_receipt,
            run_root=run_root,
            artifact_id=artifact_id,
            path=html_path,
            artifact_type="report",
            producer_step="reporting",
            inputs=inputs,
            output_target=output,
        )
    finally:
        output.close()
    return html_path
