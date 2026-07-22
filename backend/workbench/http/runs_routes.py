"""Run submission, listing, detail, artifacts, report, and SSE event stream.

``POST /runs`` · ``POST /runs/batch`` · ``GET /runs`` · ``GET /runs/{id}`` ·
``GET /runs/{id}/artifacts`` · ``GET /runs/{id}/artifacts/{artifact_id}`` ·
``GET /runs/{id}/report`` · ``GET /runs/{id}/events``.

Thin: parse the request, delegate to services (dispatch / results) and repository
(fs reads), shape the response. Extracted from ``api.py`` in v1.6.10 (Phase 4).
"""
from __future__ import annotations

import asyncio
import queue
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..api_errors import (
    ERROR_ARTIFACT_NOT_FOUND,
    ERROR_REPORT_NOT_FOUND,
    WorkbenchAPIError,
)
from ..artifacts import read_json
from ..config import load_config
from ..diagnostic_preview import build_diagnostic_summary_preview
from ..events import get_event_manager
from ..contracts.model.arma_garch import ArmaGarchAnalysisContract
from ..engine.packs.arma_garch.errors import ArmaGarchInputError
from ..engine.packs.arma_garch.input import audit_time_value_input
from ..engine.packs.arma_garch.transforms import build_transform_profiles
from ..ingestion import _read_frame
from ..model_options import ModelOptionsError, parse_model_options
from ..orchestrator import run_batch_y_workflow
from ..repository.run_repository import (
    _artifact_counts,
    _detect_failed_stage,
    _group_artifacts,
    _list_existing_artifacts,
    _read_artifact_records,
    _read_errors,
    _read_manifest,
    _resolve_artifact_path,
    _resolve_project_runs_dir,
    _resolve_run_root,
    _summarize_manifest,
)
from ..report_export import ReportExportError, export_report
from ..report_store import list_ai_reports, save_ai_report
from ..services.lmm_result_adapter import VersionedResultReadError
from ..services.results_service import _model_results, _normalize_issue_stream
from ..services.run_service import (
    _mark_interrupted_if_dead,
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


class AiReportRecordRequest(BaseModel):
    """The immutable evidence snapshot produced by the browser report flow."""

    model_config = ConfigDict(hide_input_in_errors=True)

    id: str = Field(pattern=r"^rpt_[A-Za-z0-9_-]{3,100}$")
    generatedAt: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=300)
    instruction: str = Field(min_length=1, max_length=20_000)
    text: str = Field(min_length=1, max_length=2_000_000)
    scope: dict[str, Any]
    facts: list[dict[str, Any]]
    excluded_fact_ids: list[str] = Field(default_factory=list)
    figures: list[dict[str, Any]] = Field(default_factory=list)

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
) -> dict[str, str]:
    _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND for bogus roots
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    try:
        parsed_model_options = parse_model_options(model_options)
    except ModelOptionsError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc

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
def get_run_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    _mark_interrupted_if_dead(run_root, manifest)
    summary = _summarize_manifest(manifest, run_id=run_id)
    errors_path = run_root / "errors.json"
    errors = read_json(errors_path) if errors_path.is_file() else {"issues": []}
    try:
        model_results = _model_results(run_root)
    except VersionedResultReadError as exc:
        details = (
            {"artifact_path": exc.artifact_path}
            if exc.artifact_path is not None
            else {}
        )
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message="The versioned model result cannot be read.",
            details=details,
        ) from exc
    errors = _normalize_issue_stream(errors, model_results)
    preview = build_diagnostic_summary_preview(run_root, manifest, model_results)
    return {
        **summary,
        "lineage": manifest.get("lineage", []),
        "artifact_counts": _artifact_counts(run_root),
        "errors": errors,
        "model_results": model_results,
        "diagnostic_summary_preview": preview,
    }


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
    request: ReportExportRequest,
) -> Response:
    run_root = _resolve_run_root(project_root, run_id)
    try:
        payload, media_type, filename = export_report(
            run_root,
            markdown=request.markdown,
            figures=[figure.model_dump() for figure in request.figures],
            format=format,
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
        return save_ai_report(run_root, request.model_dump())
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
    return FileResponse(
        path,
        filename=path.name,
        media_type=None,
    )


@router.get("/runs/{run_id}/report")
def get_report_endpoint(run_id: str, project_root: str) -> FileResponse:
    run_root = _resolve_run_root(project_root, run_id)
    report_path = run_root / "reports" / "report.html"
    if not report_path.is_file():
        existing_artifacts = _list_existing_artifacts(run_root)
        errors = _read_errors(run_root)
        failed_stage = _detect_failed_stage(run_root, existing_artifacts)
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_REPORT_NOT_FOUND,
            message="report.html not found for this run",
            details={
                "run_id": run_id,
                "failed_stage": failed_stage,
                "existing_artifacts": existing_artifacts,
                "errors": errors,
            },
        )
    return FileResponse(report_path, media_type="text/html")


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
