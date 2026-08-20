from __future__ import annotations

from pathlib import Path
from typing import Any
from collections.abc import Mapping
from dataclasses import dataclass, field

from jinja2 import Environment, FileSystemLoader

from .artifacts import register_artifact, write_bytes_durable
from .report_export import (
    EvidenceProjectionV1,
    _validate_owner_bound_projection,
    _freeze_wire_value,
)


@dataclass(frozen=True, slots=True)
class ReportDocumentWriterV1:
    """Typed HTML/PDF document writer capability."""

    view_model: dict[str, Any]
    projection: EvidenceProjectionV1
    canonical_run_root: Path
    _owner: object | None = field(init=False, repr=False, compare=False, default=None)

    def __init__(
        self,
        view_model: dict[str, Any],
        projection: EvidenceProjectionV1,
        canonical_run_root: Path,
        *,
        _factory_token: object | None = None,
        _owner: object | None = None,
    ) -> None:
        del view_model, projection, canonical_run_root, _factory_token, _owner
        raise TypeError("ReportDocumentWriterV1 is server-owned; use the owner capability factory")

    @classmethod
    def from_view_model(
        cls,
        view_model: Mapping[str, Any],
        projection: EvidenceProjectionV1,
        *,
        canonical_run_root: Path,
    ) -> "ReportDocumentWriterV1":
        raise TypeError("ReportDocumentWriterV1.from_view_model is not a public trust boundary; use the owner capability factory")

    @classmethod
    def _from_server_view_model(
        cls,
        view_model: Mapping[str, Any],
        projection: EvidenceProjectionV1,
        *,
        owner: object,
        canonical_run_root: Path,
    ) -> "ReportDocumentWriterV1":
        _validate_owner_bound_projection(projection, owner)
        if not isinstance(view_model, Mapping):
            raise TypeError("ReportDocumentWriterV1 requires a bound typed report payload")
        _validate_bound_report_view_model(view_model, projection)
        instance = object.__new__(cls)
        object.__setattr__(instance, "view_model", _freeze_wire_value(dict(view_model)))
        object.__setattr__(instance, "projection", projection)
        object.__setattr__(instance, "canonical_run_root", canonical_run_root.expanduser().resolve(strict=False))
        object.__setattr__(instance, "_owner", owner)
        return instance

    def _assert_server_owned(self) -> None:
        _validate_owner_bound_projection(self.projection, getattr(self, "_owner", None))


def _validate_bound_report_view_model(
    view_model: Mapping[str, Any],
    projection: EvidenceProjectionV1,
) -> None:
    """Require citable report fields to be an exact owner-issued projection."""

    wire = projection.wire
    for key in (
        "schemaVersion",
        "projectionId",
        "consumerId",
        "consumerVersion",
        "artifactRef",
        "commitId",
        "envelopeDigest",
        "status",
        "validationStatus",
        "projectionDigest",
    ):
        if view_model.get(key) != wire.get(key):
            raise TypeError("Report document payload is not bound to the owner-issued projection")
    if view_model.get("facts") != list(wire.get("facts", ())):
        raise TypeError("Report document facts are not bound to the owner-issued projection")
    provenance = view_model.get("provenance")
    if not isinstance(provenance, Mapping):
        raise TypeError("Report document provenance is required")
    for key in ("artifactRef", "commitId", "envelopeRef"):
        if provenance.get(key) != wire.get(key):
            raise TypeError("Report document provenance is not bound to the owner-issued projection")
    for key in (
        "actorRef",
        "projectRef",
        "sessionRef",
        "scopeRef",
        "runId",
        "modelRunId",
        "confirmationRef",
    ):
        if view_model.get(key) != wire.get(key):
            raise TypeError("Report document identity is not bound to the owner-issued projection")

def _normalize_to_view_model(data: dict[str, Any]) -> dict[str, Any]:
    if "critical_errors" in data:
        return data
    return {
        "title": data.get("title", "Econometrics Report"),
        "facts": data.get("presentation_facts", data.get("facts", [])),
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


def _assert_report_output_path(run_root: Path, output_path: Path) -> None:
    """Reject traversal and symlinked report parents before any write."""

    root = run_root.expanduser().resolve(strict=False)
    path = output_path.expanduser()
    try:
        relative_parent = path.parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("REPORT_OUTPUT_PATH_OUTSIDE_RUN_ROOT") from exc
    current = root
    for component in relative_parent.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("REPORT_OUTPUT_PARENT_SYMLINK")
        if current.exists() and not current.is_dir():
            raise ValueError("REPORT_OUTPUT_PARENT_NOT_DIRECTORY")
    if path.is_symlink():
        raise ValueError("REPORT_OUTPUT_SYMLINK")


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
    writer._assert_server_owned()
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
    _assert_report_output_path(run_root, html_path)
    write_bytes_durable(html_path, template.render(view_model=rendered_view_model).encode("utf-8"))
    register_artifact(run_root, artifact_id, html_path, "report", "reporting", list(inputs))
    return html_path


def render_legacy_html_report(
    view_model: Mapping[str, Any],
    run_root: Path,
    *,
    filename: str = "report.html",
    artifact_id: str = "report_html",
    inputs: list[str] | tuple[str, ...] = (),
    owner: object | None = None,
    projection: EvidenceProjectionV1 | None = None,
) -> Path:
    """Render a legacy-shaped view only through the server-owned writer seam.

    The historical function name is retained for callers, but a Mapping alone
    is never an authority.  The owner-issued projection and canonical run root
    are validated before templates, bytes, registration, or filesystem IO.
    """

    if not isinstance(view_model, Mapping):
        raise TypeError("legacy report view must be a mapping")
    if type(projection) is not EvidenceProjectionV1:
        raise TypeError("legacy report render requires an owner-issued projection")
    if owner is None:
        raise TypeError("legacy report render requires a server-owned owner capability")
    _validate_owner_bound_projection(projection, owner)
    writer = owner.issue_report_document_writer(  # type: ignore[attr-defined]
        view_model,
        projection,
        canonical_run_root=run_root,
    )
    return render_html_report(
        writer,
        run_root,
        filename=filename,
        artifact_id=artifact_id,
        inputs=inputs,
    )
