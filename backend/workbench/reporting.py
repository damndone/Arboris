from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
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


_REPORT_DOCUMENT_WRITER_ADMISSIONS: dict[int, tuple[object, object, object]] = {}
_REPORT_DOCUMENT_WRITER_ADMISSIONS_LOCK = RLock()
_WORKFLOW_REPORT_WRITER_FACTORY_TOKEN = object()
_WORKFLOW_REPORT_WRITER_ADMISSIONS: dict[int, tuple[object, object, object]] = {}
_WORKFLOW_REPORT_WRITER_ADMISSIONS_LOCK = RLock()


@dataclass(frozen=True, slots=True)
class WorkflowReportStepV1:
    """One server-projected completed workflow step."""

    step_id: str
    status: str
    artifact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.step_id) is not str or not self.step_id.strip():
            raise TypeError("workflow report step_id must be a non-empty string")
        if self.status != "completed":
            raise ValueError("workflow report steps must be completed")
        if type(self.artifact_ids) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.artifact_ids
        ):
            raise TypeError("workflow report artifact_ids must be a tuple of strings")


@dataclass(frozen=True, slots=True)
class WorkflowReportPayloadV1:
    """Typed, server-built report projection; raw mappings are not accepted."""

    workflow_id: str
    workflow_plan_fingerprint: str
    steps: tuple[WorkflowReportStepV1, ...]
    exploration_log: tuple[str, ...] = ()
    source_rows: int = 0

    def __post_init__(self) -> None:
        for field_name in ("workflow_id", "workflow_plan_fingerprint"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise TypeError(f"workflow report {field_name} is required")
        if type(self.steps) is not tuple or not self.steps or any(
            type(item) is not WorkflowReportStepV1 for item in self.steps
        ):
            raise TypeError("workflow report steps must be typed")
        if type(self.exploration_log) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.exploration_log
        ):
            raise TypeError("workflow report exploration_log must contain JSON strings")
        for item in self.exploration_log:
            try:
                json.loads(item)
            except json.JSONDecodeError as exc:
                raise TypeError("workflow report exploration_log contains invalid JSON") from exc
        if isinstance(self.source_rows, bool) or type(self.source_rows) is not int or self.source_rows < 0:
            raise TypeError("workflow report source_rows must be a non-negative integer")

    def view_model(self) -> dict[str, Any]:
        collection = {
            "schema_version": "workflow-report-collection.v1",
            "workflow_id": self.workflow_id,
            "workflow_plan_fingerprint": self.workflow_plan_fingerprint,
            "status": "completed",
            "steps": {
                step.step_id: {
                    "status": step.status,
                    "artifact_ids": list(step.artifact_ids),
                }
                for step in self.steps
            },
            "exploration_log": [json.loads(item) for item in self.exploration_log],
        }
        return {
            "title": "Statistical workflow report",
            "facts": [
                f"Workflow steps completed: {len(self.steps)}.",
                f"Workflow id: {self.workflow_id}",
                f"Source rows: {self.source_rows}",
            ],
            "claims": [],
            "warnings": [],
            "descriptive_stats": [],
            "exploration": collection,
        }


@dataclass(frozen=True, slots=True)
class ReportDocumentWriterV1:
    """Typed HTML/PDF document writer capability."""

    view_model: dict[str, Any]
    projection: EvidenceProjectionV1
    canonical_run_root: Path
    _owner: object | None = field(init=False, repr=False, compare=False, default=None)
    _issuer_token: object | None = field(init=False, repr=False, compare=False, default=None)

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
        issuer_token = object()
        object.__setattr__(instance, "_issuer_token", issuer_token)
        with _REPORT_DOCUMENT_WRITER_ADMISSIONS_LOCK:
            _REPORT_DOCUMENT_WRITER_ADMISSIONS[id(instance)] = (
                instance,
                owner,
                issuer_token,
            )
        return instance

    def _assert_server_owned(self) -> None:
        issuer_token = getattr(self, "_issuer_token", None)
        with _REPORT_DOCUMENT_WRITER_ADMISSIONS_LOCK:
            admission = _REPORT_DOCUMENT_WRITER_ADMISSIONS.get(id(self))
        if (
            admission is None
            or admission[0] is not self
            or admission[1] is not getattr(self, "_owner", None)
            or admission[2] is not issuer_token
            or type(issuer_token) is not object
        ):
            raise TypeError("ReportDocumentWriterV1 lacks the server-owned exact issuer identity")
        _validate_owner_bound_projection(self.projection, getattr(self, "_owner", None))

    def __copy__(self):
        raise TypeError("server-issued Report document writers cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("server-issued Report document writers cannot be copied")

    def __reduce__(self):
        raise TypeError("server-issued Report document writers cannot be serialized")


@dataclass(frozen=True, slots=True)
class WorkflowReportWriterV1:
    """Receipt-bound workflow report capability, separate from the C0 writer."""

    view_model: Mapping[str, Any]
    evidence_port: object
    admission_receipt: object
    canonical_run_root: Path
    producer_step: str
    input_collection: tuple[str, ...]
    artifact_bindings: Mapping[str, tuple[str, str, str, str]]
    _issuer_token: object | None = field(init=False, repr=False, compare=False, default=None)

    def __init__(
        self,
        view_model: Mapping[str, Any],
        evidence_port: object,
        admission_receipt: object,
        canonical_run_root: Path,
        producer_step: str,
        input_collection: tuple[str, ...],
        artifact_bindings: Mapping[str, tuple[str, str, str, str]],
        *,
        _factory_token: object | None = None,
    ) -> None:
        del (
            view_model,
            evidence_port,
            admission_receipt,
            canonical_run_root,
            producer_step,
            input_collection,
            artifact_bindings,
            _factory_token,
        )
        raise TypeError("WorkflowReportWriterV1 is server-owned; use the workflow runtime factory")

    @classmethod
    def _from_runtime(
        cls,
        payload: WorkflowReportPayloadV1,
        evidence_port: object,
        admission_receipt: object,
        canonical_run_root: Path,
        producer_step: str,
        input_collection: tuple[str, ...],
        artifact_bindings: Mapping[str, tuple[str, str, str, str]],
        *,
        _factory_token: object | None = None,
    ) -> "WorkflowReportWriterV1":
        from .agent.workflow_runtime import (
            WorkflowExecutionError,
            _require_active_write_context,
        )

        if _factory_token is not _WORKFLOW_REPORT_WRITER_FACTORY_TOKEN:
            raise TypeError("WorkflowReportWriterV1 requires the workflow runtime factory")
        if type(payload) is not WorkflowReportPayloadV1:
            raise TypeError("Workflow report payload must be WorkflowReportPayloadV1")
        context = _require_active_write_context()
        if context[0] is not evidence_port or context[1] is not admission_receipt:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: workflow report payload is not bound to the active receipt"
            )
        draft = context[2]
        if (
            payload.workflow_id != draft.workflow_id
            or payload.workflow_plan_fingerprint != draft.plan_fingerprint
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_REPORT_IDENTITY_MISMATCH: report payload is not bound to the active workflow plan"
            )
        if producer_step != "report.compose":
            raise WorkflowExecutionError(
                "WORKFLOW_REPORT_PRODUCER_INVALID: workflow reports must be produced by report.compose"
            )
        collection_id = f"workflow_report_collection_{payload.workflow_id}"
        if input_collection != (collection_id,):
            raise WorkflowExecutionError(
                "WORKFLOW_REPORT_INPUT_INVALID: report must consume its admitted collection artifact"
            )
        expected_bindings = {
            "html": (
                "reports",
                f"{payload.workflow_id}.html",
                f"workflow_report_{payload.workflow_id}_html",
                "report",
            ),
            "pdf": (
                "reports",
                f"{payload.workflow_id}.pdf",
                f"workflow_report_{payload.workflow_id}_pdf",
                "report",
            ),
            "xlsx": (
                "exports",
                f"{payload.workflow_id}.xlsx",
                f"workflow_report_{payload.workflow_id}_xlsx",
                "table_export",
            ),
        }
        if dict(artifact_bindings) != expected_bindings:
            raise WorkflowExecutionError(
                "WORKFLOW_REPORT_BINDING_INVALID: report output bindings are not server-derived"
            )
        instance = object.__new__(cls)
        object.__setattr__(instance, "view_model", _freeze_wire_value(payload.view_model()))
        object.__setattr__(instance, "evidence_port", evidence_port)
        object.__setattr__(instance, "admission_receipt", admission_receipt)
        object.__setattr__(
            instance,
            "canonical_run_root",
            Path(canonical_run_root).expanduser().resolve(strict=False),
        )
        object.__setattr__(instance, "producer_step", producer_step)
        object.__setattr__(instance, "input_collection", input_collection)
        object.__setattr__(instance, "artifact_bindings", _freeze_wire_value(dict(artifact_bindings)))
        issuer_token = object()
        object.__setattr__(instance, "_issuer_token", issuer_token)
        with _WORKFLOW_REPORT_WRITER_ADMISSIONS_LOCK:
            _WORKFLOW_REPORT_WRITER_ADMISSIONS[id(instance)] = (
                instance,
                evidence_port,
                issuer_token,
            )
        instance._assert_server_owned()
        return instance

    def _assert_server_owned(self) -> None:
        from .agent.workflow_runtime import (
            EvidencePersistencePort,
            WorkflowExecutionError,
            WorkflowAdmissionReceipt,
            _require_active_write_context,
            _require_workflow_opaque_ref,
        )

        issuer_token = getattr(self, "_issuer_token", None)
        with _WORKFLOW_REPORT_WRITER_ADMISSIONS_LOCK:
            admission = _WORKFLOW_REPORT_WRITER_ADMISSIONS.get(id(self))
        if (
            admission is None
            or admission[0] is not self
            or admission[1] is not getattr(self, "evidence_port", None)
            or admission[2] is not issuer_token
            or type(issuer_token) is not object
            or type(self.evidence_port) is not EvidencePersistencePort
            or type(self.admission_receipt) is not WorkflowAdmissionReceipt
        ):
            raise TypeError("Workflow report writer lacks the server-owned exact issuer identity")
        context = _require_active_write_context()
        if context[0] is not self.evidence_port or context[1] is not self.admission_receipt:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: workflow report writer is not bound to the active receipt"
            )
        self.evidence_port.require_receipt(self.admission_receipt)
        run_id = _require_workflow_opaque_ref(
            context[2].target.get("run_id"), "workflow report run_id"
        )
        expected_root = self.evidence_port.project_root / "runs" / run_id
        if self.canonical_run_root != expected_root:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: workflow report writer run root changed"
            )

    def __copy__(self):
        raise TypeError("server-issued workflow report writers cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("server-issued workflow report writers cannot be copied")

    def __reduce__(self):
        raise TypeError("server-issued workflow report writers cannot be serialized")

    def _write_formal_output(
        self,
        format_name: str,
        *,
        directory_name: str,
        filename: str,
        artifact_id: str,
        artifact_type: str,
        content: bytes,
    ) -> Path:
        self._assert_server_owned()
        expected = self.artifact_bindings.get(format_name)
        if expected != (directory_name, filename, artifact_id, artifact_type):
            from .agent.workflow_runtime import WorkflowExecutionError

            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: workflow report output binding changed"
            )
        from .agent.workflow_runtime import (
            WorkflowExecutionError,
            prepare_formal_workflow_output,
            record_formal_workflow_artifact,
        )

        output = prepare_formal_workflow_output(
            self.evidence_port,
            self.admission_receipt,
            run_root=self.canonical_run_root,
            directory_name=directory_name,
            filename=filename,
        )
        try:
            existing = output.read_bytes()
            if existing is not None:
                if existing != content:
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: workflow report output is occupied"
                    )
            else:
                output.write_bytes(content)
            record_formal_workflow_artifact(
                self.evidence_port,
                self.admission_receipt,
                run_root=self.canonical_run_root,
                artifact_id=artifact_id,
                path=output.path,
                artifact_type=artifact_type,
                producer_step=self.producer_step,
                inputs=self.input_collection,
                output_target=output,
            )
            return output.path
        except Exception:
            output.abort()
            raise
        finally:
            output.close()


def issue_workflow_report_writer(
    payload: WorkflowReportPayloadV1,
    evidence_port: object,
    admission_receipt: object,
    *,
    canonical_run_root: Path,
    producer_step: str,
    input_collection: tuple[str, ...],
    artifact_bindings: Mapping[str, tuple[str, str, str, str]],
) -> WorkflowReportWriterV1:
    """Issue the report capability only from the admitted workflow runtime."""

    return WorkflowReportWriterV1._from_runtime(
        payload,
        evidence_port,
        admission_receipt,
        canonical_run_root,
        producer_step,
        input_collection,
        dict(artifact_bindings),
        _factory_token=_WORKFLOW_REPORT_WRITER_FACTORY_TOKEN,
    )


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
    writer: ReportDocumentWriterV1 | WorkflowReportWriterV1,
    run_root: Path,
    *,
    filename: str = "report.html",
    artifact_id: str = "report_html",
    inputs: list[str] | tuple[str, ...] = (),
    evidence_port: Any = None,
    admission_receipt: Any = None,
) -> Path:
    if type(writer) is WorkflowReportWriterV1:
        writer._assert_server_owned()
        if writer.canonical_run_root != run_root.expanduser().resolve(strict=False):
            from .agent.workflow_runtime import WorkflowExecutionError

            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: workflow report run root changed"
            )
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
        return writer._write_formal_output(
            "html",
            directory_name="reports",
            filename=filename,
            artifact_id=artifact_id,
            artifact_type="report",
            content=template.render(view_model=rendered_view_model).encode("utf-8"),
        )
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
