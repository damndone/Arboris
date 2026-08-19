from __future__ import annotations

from pathlib import Path
from typing import Any
from collections.abc import Mapping
from dataclasses import dataclass

from jinja2 import Environment, FileSystemLoader

from .artifacts import register_artifact, write_bytes_durable
from .report_export import EvidenceProjectionV1


@dataclass(frozen=True, slots=True)
class ReportDocumentWriterV1:
    """Typed HTML/PDF document writer capability."""

    view_model: dict[str, Any]
    projection: EvidenceProjectionV1
    canonical_run_root: Path

    @classmethod
    def from_view_model(
        cls,
        view_model: Mapping[str, Any],
        projection: EvidenceProjectionV1,
        *,
        canonical_run_root: Path,
    ) -> "ReportDocumentWriterV1":
        if not isinstance(view_model, Mapping):
            raise TypeError("ReportDocumentWriterV1 requires a report view model")
        if type(projection) is not EvidenceProjectionV1:
            raise TypeError("ReportDocumentWriterV1 requires EvidenceProjectionV1")
        return cls(
            view_model=dict(view_model),
            projection=projection,
            canonical_run_root=canonical_run_root.expanduser().resolve(strict=False),
        )

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
    writer: ReportDocumentWriterV1,
    run_root: Path,
    *,
    filename: str = "report.html",
    artifact_id: str = "report_html",
    inputs: list[str] | tuple[str, ...] = (),
    evidence_port: Any = None,
    admission_receipt: Any = None,
) -> Path:
    if type(writer) is not ReportDocumentWriterV1:
        raise TypeError("render_html_report requires ReportDocumentWriterV1")
    if writer.canonical_run_root != run_root.expanduser().resolve(strict=False):
        raise ValueError("REPORT_WRITER_RUN_ROOT_MISMATCH")
    view_model = writer.view_model
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
    html_path = run_root / "reports" / filename
    write_bytes_durable(html_path, template.render(view_model=rendered_view_model).encode("utf-8"))
    register_artifact(run_root, artifact_id, html_path, "report", "reporting", list(inputs))
    return html_path
