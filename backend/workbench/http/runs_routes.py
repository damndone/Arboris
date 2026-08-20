"""Run submission, listing, detail, artifacts, report, and SSE event stream.

``POST /runs`` · ``POST /runs/batch`` · ``GET /runs`` · ``GET /runs/{id}`` ·
``GET /runs/{id}/artifacts`` · ``GET /runs/{id}/artifacts/{artifact_id}`` ·
``GET /runs/{id}/report`` · ``GET /runs/{id}/events``.

Thin: parse the request, delegate to services (dispatch / results) and repository
(fs reads), shape the response. Extracted from ``api.py`` in v1.6.10 (Phase 4).
"""
from __future__ import annotations

import asyncio
import json
import string
import queue
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..api_errors import (
    ERROR_ARTIFACT_NOT_FOUND,
    WorkbenchAPIError,
)
from ..artifacts import read_json, sha256_file
from ..config import load_config
from ..diagnostic_preview import build_diagnostic_summary_preview
from ..events import get_event_manager
from ..exports import render_typed_xlsx
from ..ingestion import _read_frame
from ..model_options import ModelOptionsError, parse_model_options
from ..orchestrator import run_batch_y_workflow
from ..repository.run_repository import (
    _artifact_counts,
    _group_artifacts,
    _read_artifact_records,
    _read_manifest,
    _resolve_artifact_path,
    _resolve_project_runs_dir,
    _resolve_run_root,
    _summarize_manifest,
)
from ..report_export import EvidenceProjectionV1, ReportExportError, export_report
from ..report_contract import ReportContractError, validate_report_packet
from ..report_quality import validate_report_response_quality
from ..report_view_model import (
    _unavailable_report_evidence,
    build_indexed_report_evidence,
    build_report_evidence_bundle,
)
from ..report_store import list_ai_reports, save_ai_report
from ..services.results_service import (
    _normalize_issue_stream,
    EvidenceProjectionError,
    ReportEvidenceRequestIdentityV1,
    ServerOwnedReportEvidencePersistenceV1,
    current_report_evidence_persistence,
)
from ..predictive_research.consumer_projection import (
    read_prediction_evidence_from_run_root,
)
from ..predictive_research.schema import PayloadContractError
from ..services.run_deletion import RunDeletionConfirmationError, RunDeletionService
from ..services.run_service import (
    _mark_interrupted_if_dead,
    _normalize_labels,
    _parse_json_str_array,
    _read_upload_bytes,
    _sse_frame,
    _submit_run,
    _write_upload,
    parse_column_selector,
)
from ._deps import BYTES_PER_GB

router = APIRouter()


class ReportExportFigure(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    artifact_id: str = Field(min_length=1, max_length=200)
    chart_type: str | None = Field(default=None, max_length=300)


class ReportExportRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    markdown: str = Field(min_length=1, max_length=2_000_000)
    figures: list[ReportExportFigure] = Field(default_factory=list)
    report_id: str | None = Field(default=None, pattern=r"^rpt_[A-Za-z0-9_-]{3,100}$")


_RESULT_TABLE_SECTIONS = frozenset(
    {
        "coefficients",
        "regression_table",
        "table_1",
        "statistical_evidence",
        "model_family_evidence",
    }
)

_REPORT_EVIDENCE_ARTIFACT_TYPES = frozenset(
    {"post_estimation", "statistical_test", "p7_analysis", "workflow_capability_result"}
)


def _report_evidence_for_run(
    run_root: Path,
    post_estimation_results: list[dict[str, Any]],
    request_identity: ReportEvidenceRequestIdentityV1 | None = None,
    project_root: Path | str | None = None,
) -> dict[str, object]:
    """Build the typed Report contribution from indexed artifacts only."""

    authoritative_persistence = _admit_report_owner_for_run(
        run_root,
        request_identity,
        project_root,
    )
    if type(authoritative_persistence) is not ServerOwnedReportEvidencePersistenceV1:
        del post_estimation_results
        return _unavailable_report_evidence(
            artifact_id=f"run:{run_root.name}",
            artifact_type="report",
            reason_code="EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
            request_identity=request_identity,
        )

    views: list[dict[str, object]] = []
    try:
        indexed_records = _read_artifact_records(run_root)
    except (OSError, TypeError, ValueError, WorkbenchAPIError):
        indexed_records = []
    for record in indexed_records:
        if not isinstance(record, dict):
            continue
        if record.get("artifact_type") not in _REPORT_EVIDENCE_ARTIFACT_TYPES:
            continue
        if record.get("artifact_id") != authoritative_persistence.artifact_id:
            continue
        artifact_content_sha256: str | None = None
        artifact_path: Path | None = None
        try:
            artifact_path = _resolve_artifact_path(run_root, record)
        except (OSError, TypeError, ValueError, WorkbenchAPIError):
            artifact_path = None
        if artifact_path is not None:
            try:
                artifact_content_sha256 = sha256_file(artifact_path)
            except (OSError, TypeError, ValueError):
                artifact_content_sha256 = None

        views.append(
            build_indexed_report_evidence(
                record,
                artifact_content_sha256=artifact_content_sha256,
                authoritative_persistence=authoritative_persistence,
                request_identity=request_identity,
            )
        )

    # ``post_estimation_results`` is a legacy response field.  It is
    # intentionally not a Report evidence fallback: raw result entries cannot
    # create a typed projection or citable facts.
    del post_estimation_results

    bundle = build_report_evidence_bundle(views)
    if bundle is not None:
        return bundle
    return build_indexed_report_evidence(
        {
            "artifact_id": f"run:{run_root.name}",
            "artifact_type": "report",
        },
    )


def _report_evidence_server_receipt(
    view: dict[str, object],
) -> dict[str, object] | None:
    """Expose an independent server transport anchor for available evidence."""

    digest = view.get("projectionDigest")
    provenance = view.get("provenance")
    if (
        view.get("status") != "available"
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or not isinstance(provenance, dict)
    ):
        return None
    identity_keys = (
        "actorRef",
        "projectRef",
        "sessionRef",
        "scopeRef",
        "runId",
        "modelRunId",
        "artifactRef",
        "commitId",
        "confirmationRef",
    )
    identity = {key: view.get(key) for key in identity_keys}
    if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        return None
    return {
        "schemaVersion": 1,
        "kind": "evidence.report.server-receipt.v1",
        "projectionDigest": digest,
        "identity": identity,
        "provenance": dict(provenance),
    }


def _report_identity_for_request(
    request: Request,
    run_id: str,
) -> ReportEvidenceRequestIdentityV1 | None:
    """Resolve identity from the server owner seam, never from query fields."""

    resolver = getattr(request.app.state, "report_evidence_identity_resolver", None)
    if resolver is not None:
        if not callable(resolver):
            return None
        try:
            identity = resolver(request, run_id)
        except Exception:
            return None
        return identity if type(identity) is ReportEvidenceRequestIdentityV1 else None

    persistence = getattr(request.app.state, "report_evidence_persistence", None)
    if type(persistence) is not ServerOwnedReportEvidencePersistenceV1:
        return None
    if persistence.run_id != run_id:
        return None
    try:
        return persistence._require_report_request_identity(None)
    except (AttributeError, TypeError, ValueError, RuntimeError, EvidenceProjectionError):
        return None


def _admit_report_owner_for_run(
    run_root: Path,
    request_identity: ReportEvidenceRequestIdentityV1 | None,
    project_root: Path | str | None,
) -> ServerOwnedReportEvidencePersistenceV1 | None:
    """Admit the server owner before opening an artifact index or file."""

    owner = current_report_evidence_persistence(
        actor_ref=(request_identity.actor_ref if request_identity else None),
        run_id=run_root.name,
        project_ref=(request_identity.project_ref if request_identity else None),
        session_ref=(request_identity.session_ref if request_identity else None),
        scope_ref=(request_identity.scope_ref if request_identity else None),
        model_run_id=(request_identity.model_run_id if request_identity else None),
        artifact_id=None,
        commit_id=None,
        confirmation_ref=(request_identity.confirmation_ref if request_identity else None),
        artifact_file_sha256=None,
        project_root=project_root,
    )
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        return None
    try:
        owner._require_report_authority()
        owner._require_report_request_identity(request_identity)
        owner._canonical_report_artifact()
        owner._canonical_report_wire()
        if project_root is not None and not owner.accepts_project_root(project_root):
            return None
    except (AttributeError, TypeError, ValueError, RuntimeError, EvidenceProjectionError):
        return None
    return owner


def _report_owner_for_export(
    run_root: Path,
    projection: dict[str, object],
    request_identity: ReportEvidenceRequestIdentityV1 | None,
    *,
    project_root: Path | str,
) -> ServerOwnedReportEvidencePersistenceV1:
    """Resolve the owner bound to the indexed artifact before any export."""

    owner = _admit_report_owner_for_run(run_root, request_identity, project_root)
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        raise ReportExportError("REPORT_EVIDENCE_OWNER_UNAVAILABLE")

    artifact_id = projection.get("artifactRef")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise ReportExportError("REPORT_EVIDENCE_ARTIFACT_REQUIRED")
    if artifact_id != owner.artifact_id:
        raise ReportExportError("REPORT_EVIDENCE_OWNER_CONTEXT_MISMATCH")
    try:
        records = _read_artifact_records(run_root)
    except (OSError, TypeError, ValueError, WorkbenchAPIError) as exc:
        raise ReportExportError("REPORT_EVIDENCE_ARTIFACT_INDEX_UNAVAILABLE") from exc
    record = next(
        (item for item in records if isinstance(item, dict) and item.get("artifact_id") == artifact_id),
        None,
    )
    if record is None:
        raise ReportExportError("REPORT_EVIDENCE_ARTIFACT_NOT_INDEXED")
    try:
        artifact_path = _resolve_artifact_path(run_root, record)
        artifact_file_sha256 = sha256_file(artifact_path)
    except (OSError, TypeError, ValueError, WorkbenchAPIError) as exc:
        raise ReportExportError("REPORT_EVIDENCE_ARTIFACT_INTEGRITY_UNAVAILABLE") from exc
    if artifact_file_sha256 != owner.artifact_file_sha256:
        raise ReportExportError("REPORT_EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH")
    return owner


def _issue_report_projection_for_export(
    run_root: Path,
    projection: dict[str, object],
    request_identity: ReportEvidenceRequestIdentityV1 | None,
    *,
    project_root: Path | str,
) -> EvidenceProjectionV1:
    owner = _report_owner_for_export(
        run_root,
        projection,
        request_identity,
        project_root=project_root,
    )
    return owner.issue_report_projection(projection)


class ResultTableExportRequest(BaseModel):
    """Presentation-section selection; numeric values are always server-read."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    sections: list[str] = Field(default_factory=list, max_length=20)


class AiReportRecordRequest(BaseModel):
    """The immutable evidence snapshot produced by the browser report flow."""

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid")

    id: str = Field(pattern=r"^rpt_[A-Za-z0-9_-]{3,100}$")
    generatedAt: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=300)
    instruction: str = Field(min_length=1, max_length=20_000)
    text: str = Field(min_length=1, max_length=2_000_000)
    generatedText: str | None = Field(default=None, max_length=2_000_000)
    scope: dict[str, Any]
    context_fingerprints: list[str] = Field(default_factory=list, max_length=100)
    facts: list[dict[str, Any]]
    excluded_fact_ids: list[str] = Field(default_factory=list)
    figures: list[dict[str, Any]] = Field(default_factory=list)
    excluded_figure_ids: list[str] = Field(default_factory=list)
    capability_manifest: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    report_standard: str | None = Field(default=None, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=50)
    report_quality: dict[str, Any] | None = None
    revision: dict[str, Any] | None = None


class RunDeletionConfirmationRequest(BaseModel):
    """Second, explicit confirmation for permanent leaf-run deletion."""

    model_config = ConfigDict(hide_input_in_errors=True)

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_run_id: str = Field(min_length=1, max_length=200)

_TERMINAL_EVENTS = {
    "workflow_completed", "workflow_blocked",
    "workflow_failed", "workflow_interrupted",
}


@router.post("/runs/arma-garch/transform-preflight")
async def arma_garch_transform_preflight(
    project_root: str = Form(...),
    time_column: str = Form(...),
    value_column: str = Form(...),
    time_index_semantics: str = Form("business_or_trading_observations"),
    missing_value_policy: str = Form("block"),
    file: UploadFile = File(...),
    sheet_name: str = Form(""),
    transpose: str = Form("false"),
) -> dict[str, Any]:
    """Profile all supported transforms on the same full analysis view as a run."""

    # ARMA/GARCH imports transitively load the optional ``arch`` plotting stack.
    # Keep that pack behind its route so importing the general runs router does
    # not block legacy graph startup on Matplotlib font-cache initialization.
    from ..contracts.model.arma_garch import ArmaGarchAnalysisContract
    from ..engine.packs.arma_garch.errors import ArmaGarchInputError
    from ..engine.packs.arma_garch.input import audit_time_value_input
    from ..engine.packs.arma_garch.transforms import build_transform_profiles

    _resolve_project_runs_dir(project_root)
    config = load_config(Path(project_root) / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    filename = Path(file.filename or "upload.csv").name
    try:
        data = await _read_upload_bytes(file, max_upload_bytes)
        with tempfile.TemporaryDirectory(prefix="workbench-ts-preflight-") as tmp:
            source_path = Path(tmp) / filename
            source_path.write_bytes(data)
            frame = _read_frame(
                source_path,
                config,
                sheet_name or None,
                transpose == "true",
            )
        contract = ArmaGarchAnalysisContract.from_dict(
            {
                "dataset_ref": f"preflight:upload:{filename}",
                "time_column": time_column,
                "value_column": value_column,
                "time_index_semantics": time_index_semantics,
                "transform": "level",
                "transform_confirmed": True,
                "missing_value_policy": missing_value_policy,
                "validation": {},
            }
        )
        audited = audit_time_value_input(frame, contract)
        blocking = next(
            (item for item in audited.diagnostics if item.severity == "blocking"),
            None,
        )
        if blocking is not None:
            raise ArmaGarchInputError(blocking)
        profiles = build_transform_profiles(audited.analysis_view)
        eligible = [profile for profile in profiles.values() if profile.eligible]
        recommended = max(eligible, key=lambda item: item.recommendation_score)
        return {
            "schema_version": 1,
            "source_row_count": len(frame),
            "analysis_row_count": len(audited.analysis_view),
            "diagnostics": [item.to_dict() for item in audited.diagnostics],
            "transform_profiles": {
                transform_id: profile.to_dict()
                for transform_id, profile in profiles.items()
            },
            "recommendation": {
                "transform_id": recommended.transform_id,
                "score": recommended.recommendation_score,
                "reason": recommended.recommendation_reason,
            },
            "transform_confirmation_required": True,
        }
    except (ArmaGarchInputError, KeyError, TypeError, ValueError) as exc:
        detail = exc.to_dict() if isinstance(exc, ArmaGarchInputError) else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc
    finally:
        await file.close()


@router.post("/runs")
async def run_endpoint(
    project_root: str = Form(...),
    mode: str = Form("auto"),
    model_type: str = Form("auto"),
    y: str = Form(...),
    # Optional: an omitted/empty x is a legal empty selector (zero-covariate
    # DID/CS families). Accepts comma-separated names or a JSON string array.
    x: str = Form(""),
    file: UploadFile = File(...),
    sheet_name: str = Form(""),
    transpose: str = Form("false"),
    imputation: str = Form(""),
    entity_col: str = Form(""),
    time_col: str = Form(""),
    covariance: str = Form(""),
    prediction_model_type: str = Form(""),
    prediction_cv_folds: str = Form("0"),
    prediction_sampling_method: str = Form(""),
    prediction_data_structure: str | None = Form(None),
    prediction_entity_column: str = Form(""),
    prediction_group_column: str = Form(""),
    prediction_time_column: str = Form(""),
    prediction_final_holdout_fraction: str | None = Form(None),
    prediction_shuffle: str | None = Form(None),
    frequency_weight: str = Form(""),
    analysis_weight: str = Form(""),
    sampling_weight: str = Form(""),
    survey_strata_col: str = Form(""),
    survey_psu_col: str = Form(""),
    survey_fpc_col: str = Form(""),
    survey_replicate_weights: str = Form(""),   # JSON array of column names
    survey_replicate_type: str = Form(""),      # brr | jackknife | bootstrap | provided
    survey_lonely_psu: str = Form(""),          # fail | remove | adjust | average | certainty
    survey_weight_frame: str = Form(""),        # cross_sectional | longitudinal
    survey_subpop: str = Form(""),
    iv_endog: str = Form(""),          # JSON array of column names, e.g. ["educ"]
    iv_instruments: str = Form(""),    # JSON array of column names
    did_mode: str = Form(""),
    did_cohort_col: str = Form(""),
    did_treat_col: str = Form(""),
    did_post_col: str = Form(""),
    did_status_col: str = Form(""),
    did_treatment_path: str = Form(""),
    cs_control_group: str = Form(""),
    cs_est_method: str = Form(""),
    cs_base_period: str = Form(""),
    cs_cluster_var: str = Form(""),
    cs_anticipation: int = Form(0),
    honest_did: bool = Form(False),
    focal_x: str = Form(""),  # v1.6.5 role layer: comma-joined focal columns
    model_options: str = Form("{}"),
    labels: str = Form("{}"),
    statistical_tests: str = Form("{}"),
) -> dict[str, str]:
    _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND for bogus roots
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    try:
        parsed_model_options = parse_model_options(model_options)
    except ModelOptionsError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    try:
        parsed_labels = _normalize_labels(parse_model_options(labels))
    except (ModelOptionsError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"INVALID_LABELS: {exc}") from exc
    try:
        parsed_statistical_tests = parse_model_options(statistical_tests)
    except ModelOptionsError as exc:
        raise HTTPException(
            status_code=422, detail=f"INVALID_STATISTICAL_TESTS: {exc.code}"
        ) from exc

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(
            status_code=429,
            detail="A run is already in progress.",
        )

    run_id_for_cleanup: str | None = None
    try:
        data = await _read_upload_bytes(file, max_upload_bytes)
        form: dict[str, Any] = {
            "mode": mode, "model_type": model_type, "y": y, "x": x,
            "sheet_name": sheet_name, "transpose": transpose, "imputation": imputation,
            "entity_col": entity_col, "time_col": time_col, "covariance": covariance,
            "prediction_model_type": prediction_model_type,
            "prediction_cv_folds": prediction_cv_folds,
            "prediction_sampling_method": prediction_sampling_method,
            "prediction_data_structure": prediction_data_structure,
            "prediction_entity_column": prediction_entity_column,
            "prediction_group_column": prediction_group_column,
            "prediction_time_column": prediction_time_column,
            "prediction_final_holdout_fraction": prediction_final_holdout_fraction,
            "prediction_shuffle": prediction_shuffle,
            "frequency_weight": frequency_weight,
            "analysis_weight": analysis_weight,
            "sampling_weight": sampling_weight,
            "survey_strata_col": survey_strata_col,
            "survey_psu_col": survey_psu_col,
            "survey_fpc_col": survey_fpc_col,
            "survey_replicate_weights": survey_replicate_weights,
            "survey_replicate_type": survey_replicate_type,
            "survey_lonely_psu": survey_lonely_psu,
            "survey_weight_frame": survey_weight_frame,
            "survey_subpop": survey_subpop,
            "iv_endog": iv_endog, "iv_instruments": iv_instruments,
            "did_mode": did_mode, "did_cohort_col": did_cohort_col,
            "did_treat_col": did_treat_col, "did_post_col": did_post_col,
            "did_status_col": did_status_col, "did_treatment_path": did_treatment_path,
            "cs_control_group": cs_control_group, "cs_est_method": cs_est_method,
            "cs_base_period": cs_base_period, "cs_cluster_var": cs_cluster_var,
            "cs_anticipation": str(cs_anticipation), "honest_did": str(honest_did).lower(),
            "focal_x": focal_x,
            "model_options": parsed_model_options,
        }
        if parsed_labels:
            form["labels"] = parsed_labels
        if parsed_statistical_tests:
            form["statistical_tests"] = parsed_statistical_tests
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = _submit_run(
                root, form=form, upload_bytes=data,
                upload_filename=Path(file.filename or "upload.csv").name,
                started_at=started_at, rerun_reason="initial",
            )
        except ModelOptionsError as exc:
            raise HTTPException(status_code=422, detail=exc.code) from exc
        except ValueError as exc:  # bad imputation / iv request — no run created yet
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        run_id_for_cleanup = result["run_id"]
        return result
    except Exception:
        events.release_slot(run_id_for_cleanup)
        raise
    finally:
        await file.close()


@router.post("/runs/batch")
async def batch_run_endpoint(
    project_root: str = Form(...),
    mode: str = Form("auto"),
    y_list: str = Form(...),
    x: str = Form(...),
    file: UploadFile = File(...),
    sheet_name: str = Form(""),
    transpose: str = Form("false"),
    # v1.8.7 block 1.  Batch used to forward only mode/y/x, so anything else a
    # caller declared was dropped by FastAPI without a word -- a batch with a
    # declared strata/PSU design came back computed as a simple random sample
    # with no indication.  The design travels with the batch now, and
    # sampling_weight comes with it because a design without its weight is only
    # half a declaration.
    sampling_weight: str = Form(""),
    survey_strata_col: str = Form(""),
    survey_psu_col: str = Form(""),
    survey_fpc_col: str = Form(""),
    survey_replicate_weights: str = Form(""),
    survey_replicate_type: str = Form(""),
    survey_lonely_psu: str = Form(""),
    survey_weight_frame: str = Form(""),
    survey_subpop: str = Form(""),
) -> dict:
    _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND for bogus roots
    if sheet_name or transpose == "true":
        raise HTTPException(
            status_code=400,
            detail="Batch runs currently support raw CSV/Excel orientation only.",
        )
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    y_columns = [part.strip() for part in y_list.split(",") if part.strip()]
    try:
        x_columns = parse_column_selector(x, "x")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not y_columns:
        raise HTTPException(
            status_code=422,
            detail="y_list must include at least one column.",
        )
    if not x_columns:
        raise HTTPException(
            status_code=422,
            detail="x must include at least one column.",
        )

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(
            status_code=429,
            detail="A run is already in progress.",
        )

    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        uploads_dir = root / "data" / "raw" / "_batch_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        upload_name = Path(file.filename or "upload.csv").name
        saved_path = uploads_dir / f"{timestamp}_{upload_name}"
        await _write_upload(file, saved_path, max_upload_bytes)
        return run_batch_y_workflow(
            root,
            [saved_path],
            mode=mode,
            y_list=y_columns,
            x=x_columns,
            sampling_weight=sampling_weight,
            survey_strata_col=survey_strata_col,
            survey_psu_col=survey_psu_col,
            survey_fpc_col=survey_fpc_col,
            survey_replicate_weights=_parse_json_str_array(
                survey_replicate_weights, "survey_replicate_weights"
            ),
            survey_replicate_type=survey_replicate_type,
            survey_lonely_psu=survey_lonely_psu,
            survey_weight_frame=survey_weight_frame,
            survey_subpop=survey_subpop,
        )
    finally:
        events.release_slot(None)
        await file.close()


@router.get("/runs")
def list_runs_endpoint(project_root: str) -> dict:
    runs_dir = _resolve_project_runs_dir(project_root)
    summaries: list[dict] = []
    for entry in sorted(runs_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        manifest_path = entry / "run_manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = read_json(manifest_path)
        # A server restart can leave a manifest in ``running`` while the worker
        # no longer exists. The list is the run rail's primary source, so it
        # must perform the same cheap dead-worker reconciliation as detail/SSE.
        if manifest.get("status") == "running":
            _mark_interrupted_if_dead(entry, manifest)
        summaries.append(_summarize_manifest(manifest, run_id=entry.name))
    return {"runs": summaries}


@router.get("/runs/{run_id}")
def get_run_endpoint(run_id: str, project_root: str, request: Request) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    _mark_interrupted_if_dead(run_root, manifest)
    summary = _summarize_manifest(manifest, run_id=run_id)
    errors_path = run_root / "errors.json"
    errors = read_json(errors_path) if errors_path.is_file() else {"issues": []}
    # Raw model-result packets are never a Report or consumer input.  Keep the
    # compatibility fields empty and build all evidence from the typed index.
    model_results: list[dict[str, Any]] = []
    errors = _normalize_issue_stream(errors, model_results)
    preview = build_diagnostic_summary_preview(run_root, manifest, model_results)
    model_family_evidence = None
    prediction_evidence = None
    if (run_root / "prediction_results").is_dir():
        try:
            prediction_evidence = read_prediction_evidence_from_run_root(
                run_root, consumer="table"
            )
        except (PayloadContractError, OSError, ValueError):
            prediction_evidence = {"status": "unavailable"}
    post_estimation_results: list[dict[str, Any]] = []
    report_evidence = _report_evidence_for_run(
        run_root,
        post_estimation_results,
        _report_identity_for_request(request, run_id),
        project_root=project_root,
    )
    try:
        artifact_counts = _artifact_counts(run_root)
    except (OSError, TypeError, ValueError, WorkbenchAPIError):
        artifact_counts = {}
    return {
        **summary,
        "lineage": manifest.get("lineage", []),
        "artifact_counts": artifact_counts,
        "errors": errors,
        "model_results": model_results,
        "model_results_authority": "non-authoritative",
        "model_results_status": "unavailable",
        "diagnostic_summary_preview": preview,
        "table_1": [],
        "statistical_evidence": None,
        "labels": {"variable_labels": {}, "value_labels": {}},
        "model_family_evidence": model_family_evidence,
        "model_family_evidence_authority": "non-authoritative",
        "prediction_evidence": prediction_evidence,
        # Serve-time projection of already-durable evidence: a declared
        # post-estimation step answers a question, and this is what lets the
        # run surface show that answer instead of leaving it in an artifact.
        "post_estimation_results": post_estimation_results,
        "report_evidence": report_evidence,
        "report_evidence_receipt": _report_evidence_server_receipt(report_evidence),
    }


@router.get("/runs/{run_id}/deletion-preview")
def get_run_deletion_preview(run_id: str, project_root: str) -> dict[str, Any]:
    """Return an immutable summary of exactly what a confirmed deletion removes."""

    service = RunDeletionService(project_root)
    return {"preview": service.preview(run_id).to_dict()}


@router.post("/runs/{run_id}/deletion-confirmation")
def confirm_run_deletion(
    run_id: str,
    project_root: str,
    request: RunDeletionConfirmationRequest,
) -> dict[str, Any]:
    """Permanently remove a previously previewed terminal leaf run."""

    service = RunDeletionService(project_root)
    try:
        receipt = service.delete(
            run_id,
            expected_fingerprint=request.fingerprint,
            confirmation_run_id=request.confirmation_run_id,
        )
    except RunDeletionConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RUN_DELETION_CONFIRMATION_REQUIRED",
            message=str(exc),
            details={"run_id": run_id},
        ) from exc
    return {"deletion": receipt.to_dict()}


@router.post("/runs/{run_id}/cancel")
def cancel_run_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    if manifest.get("status") != "running":
        return {"run_id": run_id, "status": manifest.get("status")}
    status = _mark_interrupted_if_dead(run_root, manifest)
    if status == "interrupted":
        return {"run_id": run_id, "status": "interrupted"}

    events = get_event_manager()
    if not events.request_cancel(run_id):
        # A running manifest without an active worker is a dead run; reconcile
        # it instead of claiming that cancellation was accepted.
        _mark_interrupted_if_dead(run_root, manifest)
        return {"run_id": run_id, "status": manifest.get("status", "interrupted")}
    events.emit(
        run_id,
        {
            "event": "workflow_cancel_requested",
            "step": None,
            "message": "Cancellation requested; the worker will stop at its next checkpoint.",
            "status": "cancelling",
        },
    )
    return {"run_id": run_id, "status": "cancelling"}


@router.post("/runs/{run_id}/report/export")
def export_report_endpoint(
    run_id: str,
    project_root: str,
    format: str,
    payload: ReportExportRequest,
    http_request: Request,
) -> Response:
    run_root = _resolve_run_root(project_root, run_id)
    projection = _report_evidence_for_run(
        run_root,
        [],
        _report_identity_for_request(http_request, run_id),
        project_root=project_root,
    )
    if projection.get("status") != "available":
        raise WorkbenchAPIError(
            status_code=409,
            code="REPORT_EVIDENCE_UNAVAILABLE",
            message="The report export requires a committed typed evidence projection.",
            details={"run_id": run_id, "projection": projection},
        )
    markdown = payload.markdown
    figures = [figure.model_dump() for figure in payload.figures]
    if payload.report_id is not None:
        stored = next(
            (record for record in list_ai_reports(run_root) if record.get("id") == payload.report_id),
            None,
        )
        if stored is None:
            raise WorkbenchAPIError(
                status_code=404,
                code="AI_REPORT_NOT_FOUND",
                message="The selected report revision is not stored for this run.",
                details={"report_id": payload.report_id, "run_id": run_id},
            )
        stored_facts = stored.get("facts") or []
        stored_figures = stored.get("figures") or []
        included_facts, included_figures = _included_report_snapshot(
            facts=stored_facts,
            figures=stored_figures,
            excluded_fact_ids=stored.get("excluded_fact_ids") or [],
            excluded_figure_ids=stored.get("excluded_figure_ids") or [],
        )
        requested_figure_identity = [
            {"artifact_id": figure.get("artifact_id"), "chart_type": figure.get("chart_type")}
            for figure in figures
        ]
        stored_figure_identity = [
            {"artifact_id": figure.get("artifact_id"), "chart_type": figure.get("chart_type")}
            for figure in stored_figures
            if isinstance(figure, dict)
        ]
        # The request carries only the stable export identity. Paths and
        # figure-source previews are server-owned provenance fields and may be
        # omitted by the lightweight export request model; the actual bytes
        # below are always read from the persisted report snapshot.
        if payload.markdown != stored.get("text") or requested_figure_identity != stored_figure_identity:
            raise WorkbenchAPIError(
                status_code=409,
                code="AI_REPORT_SOURCE_MISMATCH",
                message="Export must use the persisted report revision and evidence snapshot.",
                details={"report_id": payload.report_id},
            )
        try:
            contract = validate_report_packet(
                {
                    "fact_table": included_facts,
                    "figures": included_figures,
                    "report_standard": stored.get("report_standard"),
                    "required_capabilities": stored.get("required_capabilities") or [],
                    "capability_manifest": stored.get("capability_manifest") or [],
                    "excluded_fact_ids": stored.get("excluded_fact_ids") or [],
                }
            )
            quality = validate_report_response_quality(str(stored.get("text", "")), contract)
        except ReportContractError as exc:
            raise WorkbenchAPIError(
                status_code=422,
                code="REPORT_EXPORT_NOT_ALLOWED",
                message="The stored report revision has an invalid evidence contract.",
                details={"report_id": payload.report_id, "violations": list(exc.violations)},
            ) from exc
        if not quality.is_exportable:
            details = quality.to_dict()
            details.pop("normalized_text", None)
            raise WorkbenchAPIError(
                status_code=422,
                code="REPORT_EXPORT_NOT_ALLOWED",
                message="The report revision is not exportable until its quality issues are fixed.",
                details={"report_id": payload.report_id, "quality": details},
            )
        markdown = str(stored["text"])
        figures = list(included_figures)
    try:
        payload, media_type, filename = export_report(
            run_root,
            markdown=markdown,
            figures=figures,
            format=format,
            evidence_projection=_issue_report_projection_for_export(
                run_root,
                projection,
                _report_identity_for_request(http_request, run_id),
                project_root=project_root,
            ),
        )
    except ReportExportError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="REPORT_EXPORT_INVALID",
            message=str(exc),
            details={"format": format},
        ) from exc
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/runs/{run_id}/report/result-table-export")
def export_result_table_endpoint(
    run_id: str,
    project_root: str,
    request: ResultTableExportRequest,
    http_request: Request,
) -> Response:
    """Export selected result tables from the bounded typed evidence view."""

    run_root = _resolve_run_root(project_root, run_id)
    sections = request.sections or ["regression_table", "table_1", "statistical_evidence", "model_family_evidence"]
    unknown = sorted(set(sections) - _RESULT_TABLE_SECTIONS)
    if unknown:
        raise WorkbenchAPIError(
            status_code=422,
            code="RESULT_TABLE_EXPORT_INVALID",
            message="Unknown result-table export section.",
            details={"sections": unknown},
        )
    if len(set(sections)) != len(sections):
        raise WorkbenchAPIError(
            status_code=422,
            code="RESULT_TABLE_EXPORT_INVALID",
            message="Result-table export sections must be unique.",
            details={"sections": sections},
        )

    projection = _report_evidence_for_run(
        run_root,
        [],
        _report_identity_for_request(http_request, run_id),
        project_root=project_root,
    )
    if projection.get("status") != "available":
        raise WorkbenchAPIError(
            status_code=409,
            code="RESULT_TABLE_EXPORT_UNAVAILABLE",
            message="The selected result tables require committed typed evidence.",
            details={"run_id": run_id, "projection": projection},
        )

    typed_facts = projection.get("facts")
    if not isinstance(typed_facts, list) or not typed_facts:
        unavailable = dict(projection)
        unavailable.update({"status": "unavailable", "facts": [], "reasonCode": "EVIDENCE_FACTS_UNAVAILABLE"})
        raise WorkbenchAPIError(
            status_code=409,
            code="RESULT_TABLE_EXPORT_UNAVAILABLE",
            message="The committed projection contains no bounded facts for export.",
            details={"run_id": run_id, "projection": unavailable},
        )

    slug = "-".join(sections)
    filename = f"result-table-{slug}.xlsx"
    try:
        owner = _report_owner_for_export(
            run_root,
            projection,
            _report_identity_for_request(http_request, run_id),
            project_root=project_root,
        )
        typed_projection = owner.issue_report_projection(projection)
        writer = owner.issue_report_evidence_writer(
            typed_projection,
            sections=tuple(sections),
        )
        xlsx_payload = render_typed_xlsx(writer)
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        unavailable = dict(projection)
        unavailable.update({"status": "blocked", "facts": [], "reasonCode": "RESULT_TABLE_EXPORT_FAILED"})
        raise WorkbenchAPIError(
            status_code=409,
            code="RESULT_TABLE_EXPORT_FAILED",
            message="The typed result table could not be downloaded or exported.",
            details={"run_id": run_id, "projection": unavailable},
        ) from exc
    return Response(
        content=xlsx_payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _figure_ids_for_report_fact(fact: dict[str, Any]) -> set[str]:
    owners: set[str] = set()
    artifact_ids = fact.get("artifact_ids")
    if isinstance(artifact_ids, list):
        owners.update(item for item in artifact_ids if isinstance(item, str))
    for key in ("field", "node_key"):
        value = fact.get(key)
        if not isinstance(value, str) or not value.startswith("figure:"):
            continue
        source = value.removeprefix("figure:")
        if source:
            owners.add(source.split(":", 1)[0])
    return owners


def _included_report_snapshot(
    *,
    facts: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    excluded_fact_ids: list[str] | tuple[str, ...],
    excluded_figure_ids: list[str] | tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the writer's curation boundary to a full persisted snapshot."""

    excluded_figures = set(excluded_figure_ids)
    excluded_facts = set(excluded_fact_ids)
    figures = [
        figure
        for figure in figures
        if figure.get("artifact_id") not in excluded_figures
    ]
    facts = [
        fact
        for fact in facts
        if fact.get("id") not in excluded_facts
        and not (_figure_ids_for_report_fact(fact) & excluded_figures)
    ]
    return facts, figures


@router.post("/runs/{run_id}/ai-reports")
def save_ai_report_endpoint(
    run_id: str,
    project_root: str,
    request: AiReportRecordRequest,
) -> dict[str, Any]:
    run_root = _resolve_run_root(project_root, run_id)
    if request.scope.get("run_id") != run_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AI_REPORT_SCOPE_MISMATCH",
            message="AI report scope must match the target run.",
            details={"scope_run_id": request.scope.get("run_id"), "run_id": run_id},
        )
    try:
        validation_facts, validation_figures = _included_report_snapshot(
            facts=request.facts,
            figures=request.figures,
            excluded_fact_ids=request.excluded_fact_ids,
            excluded_figure_ids=request.excluded_figure_ids,
        )
        contract = validate_report_packet(
            {
                "fact_table": validation_facts,
                "figures": validation_figures,
                "report_standard": request.report_standard,
                "required_capabilities": request.required_capabilities,
                "capability_manifest": request.capability_manifest,
                "excluded_fact_ids": [],
            }
        )
        quality = validate_report_response_quality(request.text, contract)
        if not quality.is_exportable:
            quality_details = quality.to_dict()
            quality_details.pop("normalized_text", None)
            raise WorkbenchAPIError(
                status_code=422,
                code="AI_REPORT_QUALITY_INVALID",
                message="The report revision does not satisfy its evidence and quality contract.",
                details={"quality": quality_details},
            )
        return save_ai_report(
            run_root,
            request.model_dump(),
            validation_status=quality.status,
        )
    except ReportContractError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="AI_REPORT_INVALID",
            message=str(exc),
            details={"run_id": run_id, "violations": list(exc.violations)},
        ) from exc
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="AI_REPORT_INVALID",
            message=str(exc),
            details={"run_id": run_id},
        ) from exc


@router.get("/runs/{run_id}/ai-reports")
def list_ai_reports_endpoint(run_id: str, project_root: str) -> dict[str, Any]:
    return {"reports": list_ai_reports(_resolve_run_root(project_root, run_id))}


@router.get("/runs/{run_id}/artifacts")
def list_artifacts_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    records = _read_artifact_records(run_root)
    return {"groups": _group_artifacts(records)}


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact_endpoint(
    run_id: str, artifact_id: str, project_root: str
) -> FileResponse:
    run_root = _resolve_run_root(project_root, run_id)
    records = _read_artifact_records(run_root)
    matched = next(
        (record for record in records if record.get("artifact_id") == artifact_id),
        None,
    )
    if matched is None:
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Artifact not found: {artifact_id}",
            details={"artifact_id": artifact_id, "run_id": run_id},
        )
    path = _resolve_artifact_path(run_root, matched)
    expected_sha256 = matched.get("sha256")
    is_valid_sha256 = (
        isinstance(expected_sha256, str)
        and len(expected_sha256) == 64
        and all(character in string.hexdigits for character in expected_sha256)
    )
    artifact_type = matched.get("artifact_type")
    is_classification_evidence = (
        artifact_type in {"classification_evidence", "classification_artifacts"}
        or artifact_id in {"classification_evidence", "classification_artifacts"}
        or (
            isinstance(matched.get("payload_contract"), dict)
            and matched["payload_contract"].get("payload_schema")
            in {
                "workbench.prediction.classification-evidence",
                "workbench.prediction.classification-artifacts",
            }
        )
    )
    # Legacy non-evidence indexes occasionally contain placeholder digests;
    # preserve their read compatibility, but never expose a typed
    # classification packet without a verifiable content hash.
    if not is_valid_sha256 and is_classification_evidence:
        raise WorkbenchAPIError(
            status_code=409,
            code="ARTIFACT_INTEGRITY_UNVERIFIED",
            message="The typed evidence artifact has no valid sha256 digest.",
            details={"artifact_id": artifact_id, "run_id": run_id},
        )
    if is_valid_sha256:
        try:
            actual_sha256 = sha256_file(path)
        except OSError as exc:
            raise WorkbenchAPIError(
                status_code=409,
                code="ARTIFACT_INTEGRITY_UNAVAILABLE",
                message="The artifact could not be hashed for integrity verification.",
                details={"artifact_id": artifact_id, "run_id": run_id},
            ) from exc
        if actual_sha256.lower() != expected_sha256.lower():
            raise WorkbenchAPIError(
                status_code=409,
                code="ARTIFACT_INTEGRITY_MISMATCH",
                message="The artifact bytes do not match the indexed sha256 digest.",
                details={"artifact_id": artifact_id, "run_id": run_id},
            )
    return FileResponse(
        path,
        filename=path.name,
        media_type=None,
    )


@router.get("/runs/{run_id}/report")
def get_report_endpoint(run_id: str, project_root: str, request: Request) -> Response:
    run_root = _resolve_run_root(project_root, run_id)
    projection = _report_evidence_for_run(
        run_root,
        [],
        _report_identity_for_request(request, run_id),
        project_root=project_root,
    )
    if projection.get("status") != "available":
        raise WorkbenchAPIError(
            status_code=409,
            code="REPORT_EVIDENCE_UNAVAILABLE",
            message="The HTML report requires a committed typed evidence projection.",
            details={"run_id": run_id, "projection": projection},
        )
    facts = projection.get("facts", [])
    lines = [
        "# Persisted report evidence",
        f"Status: {projection.get('status')}",
        f"Validation: {projection.get('validationStatus')}",
        f"Commit: {projection.get('commitId')}",
        f"Digest: {projection.get('envelopeDigest')}",
    ]
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            lines.append(
                f"- {fact.get('statisticId', 'fact')}: {fact.get('value')}"
                + (f" ({fact.get('unit')})" if fact.get('unit') else "")
            )
    try:
        payload, media_type, _filename = export_report(
            run_root,
            markdown="\n".join(lines),
            figures=[],
            format="html",
            evidence_projection=_issue_report_projection_for_export(
                run_root,
                projection,
                _report_identity_for_request(request, run_id),
                project_root=project_root,
            ),
        )
    except ReportExportError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="REPORT_EXPORT_FAILED",
            message=str(exc),
            details={"run_id": run_id, "projection": projection},
        ) from exc
    return Response(content=payload, media_type=media_type)


@router.get("/runs/{run_id}/events")
async def run_events_endpoint(run_id: str, project_root: str):
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    events = get_event_manager()
    # Rehydrate durable history for every run, not only interrupted runs. The
    # in-memory event window is intentionally short-lived; Logs must still be
    # useful after a completed run has aged out of that window.
    events.register_run(run_id, run_root / "workflow_log.jsonl")

    status = _mark_interrupted_if_dead(run_root, manifest)
    if status == "interrupted":
        events.emit_terminal(run_id, "interrupted", "Server stopped before completion.")

    sub_queue, snapshot = events.subscribe(run_id)

    async def _generator():
        loop = asyncio.get_running_loop()
        try:
            for event in snapshot:
                yield _sse_frame(event)
                if event["event"] in _TERMINAL_EVENTS:
                    return
                await asyncio.sleep(0)

            while True:
                try:
                    event = await loop.run_in_executor(
                        None, sub_queue.get, True, 30)
                except queue.Empty:
                    yield ":\n\n"
                    continue
                if event is None:
                    break
                yield _sse_frame(event)
        finally:
            events.unsubscribe(run_id, sub_queue)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
