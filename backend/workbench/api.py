from __future__ import annotations

import asyncio
import json
import queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from .api_errors import (
    ERROR_ARTIFACT_NOT_FOUND,
    ERROR_INVALID_PATH,
    ERROR_PROJECT_NOT_FOUND,
    ERROR_REGISTRY_VERSION_INVALID,
    ERROR_REGISTRY_VERSION_UNSUPPORTED,
    ERROR_REPORT_NOT_FOUND,
    ERROR_RUN_NOT_FOUND,
    WorkbenchAPIError,
    register_error_handlers,
)
from .artifacts import read_json, write_json
from .config import load_config
from .engine.capabilities import build_capabilities
from .graph_store import GraphDeserializationError, GraphStore, graph_to_json
from .diagnostic_preview import build_diagnostic_summary_preview
from .term_parser import parse_term, is_q_quoted_dummy
from .domain import GuardrailIssue, Severity
from .events import get_event_manager
from .orchestrator import (
    _lineage,
    _run_workflow,
    _write_manifest,
    parse_imputation_request,
    run_batch_y_workflow,
    run_workflow,
)
from .projects import create_project, create_run
from . import flags
from .lineage.family import scan_family
from .lineage.hashing import dag_hash, override_hash
from .lineage.headset import build_headset
from .lineage.node_index import NODE_INDEX_FILENAME
from .lineage.node_write_validation import (
    AcceptedContext,
    NodeWriteOperationRequestV1,
    accepted_context_from,
    validate_rerun_operation_target,
)
from .lineage.op_contract import (
    OpOverrideError,
    resolve_operation_contract,
    resolve_overrides_target,
    validate_overrides,
)
from .lineage.run_inputs import read_run_inputs, write_run_inputs
from .lineage.upload_store import resolve_upload, store_upload_bytes, verify_upload

# A parent run must be in one of these (non-running) states to be rerun-from.
_TERMINAL_RUN_STATUSES = {
    "completed", "failed", "cancelled", "interrupted", "partial", "blocked",
}

app = FastAPI(title="Local Econometrics Workbench")
register_error_handlers(app)

UPLOAD_CHUNK_BYTES = 1024 * 1024
BYTES_PER_GB = 1024**3


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_json_str_array(raw: str, label: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {label} JSON: {exc}")
    if not isinstance(parsed, list) or not all(isinstance(c, str) for c in parsed):
        raise HTTPException(status_code=422, detail=f"{label} must be a JSON array of column-name strings.")
    return parsed


class ProjectRequest(BaseModel):
    parent: str
    name: str


@app.get("/capabilities")
def capabilities_endpoint() -> dict:
    return build_capabilities()


@app.post("/projects")
def create_project_endpoint(request: ProjectRequest) -> dict[str, str]:
    project = create_project(Path(request.parent), request.name)
    return {"project_root": str(project.root)}


async def _read_upload_bytes(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload fully into memory, enforcing the project size cap."""
    buf = bytearray()
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Uploaded file exceeds project size limit.",
            )
    return bytes(buf)


def _submit_run(
    root: Path,
    *,
    form: dict[str, str],
    upload_bytes: bytes,
    upload_filename: str,
    started_at: str,
    rerun_of: str | None = None,
    from_node: str | None = None,
    rerun_reason: str = "initial",
    op_overrides: dict | None = None,
) -> dict[str, str]:
    """Single dispatch path shared by POST /runs and POST /runs/{id}/rerun.

    Stores the upload content-addressably, writes run_inputs.json, materializes the
    blob into the run dir for the engine (which reads a path), and dispatches the full
    pipeline via _bg_run. The caller MUST already hold the run slot. Input parsing that
    can fail (imputation / iv arrays) happens BEFORE any run is created, so a bad request
    raises without leaving a junk run behind."""
    x_columns = [part.strip() for part in form.get("x", "").split(",") if part.strip()]
    imputation_request = parse_imputation_request(form.get("imputation", ""))
    iv_endog_list = _parse_json_str_array(form.get("iv_endog", ""), "iv_endog")
    iv_instruments_list = _parse_json_str_array(form.get("iv_instruments", ""), "iv_instruments")

    sha = store_upload_bytes(root, upload_bytes, filename=upload_filename)
    run = create_run(root, mode=form.get("mode", "auto"))

    write_run_inputs(
        run.root,
        form=form,
        upload={"sha256": sha, "filename": upload_filename},
        rerun_of=rerun_of, from_node=from_node, rerun_reason=rerun_reason,
        override_hash=override_hash(op_overrides) if op_overrides else None,
        dag_hash=dag_hash(sha, form),
    )

    uploads_dir = run.root / "_uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved_path = uploads_dir / Path(upload_filename or "upload.csv").name
    saved_path.write_bytes(resolve_upload(root, sha).read_bytes())

    _write_manifest(
        run.root, run.run_id, form.get("mode", "auto"), "running",
        _lineage([saved_path]), started_at=started_at,
        y=form.get("y", ""), x=x_columns,
        requested_model_type=form.get("model_type", "auto"),
        rerun_of=rerun_of,
    )

    events = get_event_manager()
    events.register_run(run.run_id)
    events.mark_active(run.run_id)
    events.executor.submit(
        _bg_run, run.root, run.run_id, saved_path,
        form.get("mode", "auto"), form.get("y", ""), x_columns, started_at,
        form.get("model_type", "auto"),
        (form.get("sheet_name") or None), form.get("transpose") == "true",
        imputation_request,
        form.get("entity_col", ""), form.get("time_col", ""), form.get("covariance", ""),
        form.get("prediction_model_type", ""), _safe_int(form.get("prediction_cv_folds", "0")),
        form.get("prediction_sampling_method", ""),
        iv_endog_list, iv_instruments_list,
        form.get("did_mode", ""), form.get("did_cohort_col", ""), form.get("did_treat_col", ""),
        form.get("did_post_col", ""), form.get("did_status_col", ""), form.get("did_treatment_path", ""),
        form.get("cs_control_group", ""), form.get("cs_est_method", ""), form.get("cs_base_period", ""),
        form.get("cs_cluster_var", ""), _safe_int(str(form.get("cs_anticipation", "0"))),
        str(form.get("honest_did", "false")).lower() == "true",
    )
    return {"run_id": run.run_id, "status": "running"}


@app.post("/runs")
async def run_endpoint(
    project_root: str = Form(...),
    mode: str = Form("auto"),
    model_type: str = Form("auto"),
    y: str = Form(...),
    x: str = Form(...),
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
) -> dict[str, str]:
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(
            status_code=429,
            detail="A run is already in progress.",
        )

    run_id_for_cleanup: str | None = None
    try:
        data = await _read_upload_bytes(file, max_upload_bytes)
        form: dict[str, str] = {
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
        }
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = _submit_run(
                root, form=form, upload_bytes=data,
                upload_filename=Path(file.filename or "upload.csv").name,
                started_at=started_at, rerun_reason="initial",
            )
        except ValueError as exc:  # bad imputation / iv request — no run created yet
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        run_id_for_cleanup = result["run_id"]
        return result
    except Exception:
        events.release_slot(run_id_for_cleanup)
        raise
    finally:
        await file.close()


@app.post("/runs/batch")
async def batch_run_endpoint(
    project_root: str = Form(...),
    mode: str = Form("auto"),
    y_list: str = Form(...),
    x: str = Form(...),
    file: UploadFile = File(...),
    sheet_name: str = Form(""),
    transpose: str = Form("false"),
) -> dict:
    if sheet_name or transpose == "true":
        raise HTTPException(
            status_code=400,
            detail="Batch runs currently support raw CSV/Excel orientation only.",
        )
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    y_columns = [part.strip() for part in y_list.split(",") if part.strip()]
    x_columns = [part.strip() for part in x.split(",") if part.strip()]
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


async def _write_upload(file: UploadFile, target: Path, max_bytes: int) -> None:
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="Uploaded file exceeds project size limit.",
                )
            handle.write(chunk)


def _resolve_project_root(run_root: Path) -> Path:
    return run_root.parent.parent


def _bg_run(
    run_root: Path,
    run_id: str,
    saved_path: Path,
    mode: str,
    y: str,
    x_columns: list[str],
    started_at: str,
    model_type: str = "auto",
    sheet_name: str | None = None,
    transpose: bool = False,
    imputation: dict | None = None,
    entity_col: str = "",
    time_col: str = "",
    covariance: str = "",
    prediction_model_type: str = "",
    prediction_cv_folds: int = 0,
    prediction_sampling_method: str = "",
    iv_endog: list[str] | None = None,
    iv_instruments: list[str] | None = None,
    did_mode: str = "",
    did_cohort_col: str = "",
    did_treat_col: str = "",
    did_post_col: str = "",
    did_status_col: str = "",
    did_treatment_path: str = "",
    cs_control_group: str = "",
    cs_est_method: str = "",
    cs_base_period: str = "",
    cs_cluster_var: str = "",
    cs_anticipation: int = 0,
    honest_did: bool = False,
) -> None:
    events = get_event_manager()
    config = load_config(_resolve_project_root(run_root) / "config.yml")

    def _on_step(step: str, status: str, message: str) -> None:
        if status == "blocked":
            event_name = "step_blocked"
        elif status in ("start", "complete"):
            event_name = f"step_{status}"
        else:
            event_name = f"step_{status}"
        events.emit(run_id, {
            "event": event_name,
            "step": step,
            "message": message,
            "status": status if status not in ("start", "complete") else None,
        })

    try:
        result = _run_workflow(
            run_root, run_id, [saved_path],
            mode, y, x_columns, config, started_at,
            on_step=_on_step,
            model_type=model_type,
            sheet_name=sheet_name,
            transpose=transpose,
            imputation=imputation,
            entity_col=entity_col,
            time_col=time_col,
            covariance=covariance,
            prediction_model_type=prediction_model_type,
            prediction_cv_folds=prediction_cv_folds,
            prediction_sampling_method=prediction_sampling_method,
            iv_endog=iv_endog,
            iv_instruments=iv_instruments,
            did_mode=did_mode,
            did_cohort_col=did_cohort_col,
            did_treat_col=did_treat_col,
            did_post_col=did_post_col,
            did_status_col=did_status_col,
            did_treatment_path=did_treatment_path,
            cs_control_group=cs_control_group,
            cs_est_method=cs_est_method,
            cs_base_period=cs_base_period,
            cs_cluster_var=cs_cluster_var,
            cs_anticipation=cs_anticipation,
            honest_did=honest_did,
        )
        status = result["status"]
        events.emit_terminal(run_id, status, f"Workflow {status}")
    except Exception as exc:
        _write_manifest(
            run_root, run_id, mode, "failed",
            _lineage([saved_path]),
            started_at=started_at, y=y, x=x_columns,
            requested_model_type=model_type,
        )
        write_json(run_root / "errors.json", {
            "issues": [GuardrailIssue(
                Severity.BLOCKER, "WORKFLOW_FAILED",
                str(exc), {},
            ).to_dict()],
        })
        events.emit_terminal(run_id, "failed", f"Workflow failed: {exc}")
    finally:
        events.release_slot(run_id)


def _mark_interrupted_if_dead(run_root: Path, manifest: dict) -> str | None:
    run_id = manifest.get("run_id")
    if manifest.get("status") != "running":
        return None
    events = get_event_manager()
    if events.is_active(run_id):
        return None
    issue = GuardrailIssue(
        Severity.BLOCKER, "WORKFLOW_INTERRUPTED",
        "Workflow interrupted because the server process stopped before completion.",
        {},
    )
    write_json(run_root / "errors.json", {"issues": [issue.to_dict()]})
    _write_manifest(
        run_root, run_id,
        manifest.get("mode", "auto"), "interrupted",
        manifest.get("lineage", []),
        started_at=manifest.get("started_at"),
        y=manifest.get("y"),
        x=manifest.get("x") or [],
        requested_model_type=manifest.get("requested_model_type"),
    )
    manifest["status"] = "interrupted"
    return "interrupted"


def _sse_frame(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _resolve_project_runs_dir(project_root: str) -> Path:
    project = Path(project_root).resolve()
    runs_dir = project / "runs"
    if not runs_dir.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_PROJECT_NOT_FOUND,
            message=f"Project not found: {project}",
            details={"project_root": str(project)},
        )
    return runs_dir


def _resolve_run_root(project_root: str, run_id: str) -> Path:
    runs_dir = _resolve_project_runs_dir(project_root)
    candidate = (runs_dir / run_id).resolve()
    try:
        candidate.relative_to(runs_dir.resolve())
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=400,
            code=ERROR_INVALID_PATH,
            message="run_id must resolve inside the project's runs directory",
            details={"run_id": run_id},
        ) from exc
    if not candidate.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message=f"Run not found: {run_id}",
            details={"run_id": run_id, "project_root": str(runs_dir.parent)},
        )
    return candidate


def _read_manifest(run_root: Path) -> dict:
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message=f"run_manifest.json missing for run: {run_root.name}",
            details={"run_id": run_root.name},
        )
    return read_json(manifest_path)


def _summarize_manifest(manifest: dict) -> dict:
    return {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "mode": manifest.get("mode"),
        "started_at": manifest.get("started_at"),
        "y": manifest.get("y"),
        "x": manifest.get("x"),
    }


def _artifact_counts(run_root: Path) -> dict[str, int]:
    index = _read_artifacts_index(run_root)
    counts: dict[str, int] = {}
    for record in index.get("artifacts", []):
        artifact_type = record.get("artifact_type", "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1
    return counts


def _model_results(run_root: Path) -> list[dict]:
    model_dir = run_root / "model_results"
    if not model_dir.is_dir():
        return []
    results: list[dict] = []
    for path in sorted(model_dir.glob("*.json")):
        data = read_json(path)
        if isinstance(data, dict) and isinstance(data.get("coefficients"), dict):
            results.append(data)
    return results


def _normalize_issue_stream(errors: dict, model_results: list[dict]) -> dict:
    """Align legacy/stored issues with the final model preprocessing state."""
    issues = errors.get("issues", [])
    if not isinstance(issues, list):
        return {"issues": []}
    dummy_coded = _dummy_coded_columns(model_results)
    if not dummy_coded:
        return {"issues": issues}

    normalized: list[dict] = []
    emitted_auto: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            normalized.append(issue)
            continue
        evidence = issue.get("evidence", {})
        column = evidence.get("column") if isinstance(evidence, dict) else None
        if issue.get("code") == "CATEGORICAL_CANDIDATE" and column in dummy_coded:
            if column not in emitted_auto:
                normalized.append(_auto_dummy_coded_issue(column))
                emitted_auto.add(column)
            continue
        normalized.append(issue)

    existing_auto = {
        issue.get("evidence", {}).get("column")
        for issue in normalized
        if isinstance(issue, dict)
        and issue.get("code") == "CATEGORICAL_AUTO_DUMMY_CODED"
        and isinstance(issue.get("evidence"), dict)
    }
    for column in sorted(dummy_coded - existing_auto - emitted_auto):
        normalized.append(_auto_dummy_coded_issue(column))
    return {"issues": normalized}


def _dummy_coded_columns(model_results: list[dict]) -> set[str]:
    columns: set[str] = set()
    for result in model_results:
        coefficients = result.get("coefficients", {})
        if not isinstance(coefficients, dict):
            continue
        for term in coefficients:
            if not isinstance(term, str):
                continue
            if is_q_quoted_dummy(term):
                columns.add(parse_term(term).source_id)
    return columns


def _auto_dummy_coded_issue(column: str) -> dict:
    return GuardrailIssue(
        Severity.INFO,
        "CATEGORICAL_AUTO_DUMMY_CODED",
        f"Column '{column}' was detected as categorical and automatically dummy-coded.",
        evidence={"column": column, "preprocessing": "dummy_coded"},
        affected_stage="data_cleaning",
        variables=[column],
        template_key="categorical_auto_dummy",
    ).to_dict()


SUPPORTED_REGISTRY_VERSION = 1


def _read_artifacts_index(run_root: Path) -> dict:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return {"artifacts": []}
    data = read_json(index_path)
    raw = data.get("schema_version", 1)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message="artifacts_index.json schema_version is not an integer",
            details={"found": raw, "type": type(raw).__name__},
        )
    if raw < 1:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message=f"artifacts_index.json schema_version must be >= 1, got {raw}",
            details={"found": raw},
        )
    if raw > SUPPORTED_REGISTRY_VERSION:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_UNSUPPORTED,
            message=f"artifacts_index.json schema_version {raw} not supported",
            details={"found": raw, "supported": SUPPORTED_REGISTRY_VERSION},
        )
    return data


def _read_artifact_records(run_root: Path) -> list[dict]:
    return list(_read_artifacts_index(run_root).get("artifacts", []))


def _group_artifacts(records: list[dict]) -> list[dict]:
    by_type: dict[str, list[dict]] = {}
    for record in records:
        artifact_type = record.get("artifact_type", "unknown")
        by_type.setdefault(artifact_type, []).append(
            {
                "artifact_id": record.get("artifact_id"),
                "path": record.get("path"),
                "artifact_type": artifact_type,
                "step": record.get("step"),
                "sha256": record.get("sha256"),
            }
        )
    return [
        {"artifact_type": artifact_type, "items": items}
        for artifact_type, items in sorted(by_type.items())
    ]


def _resolve_artifact_path(run_root: Path, record: dict) -> Path:
    relative = record.get("path")
    if not isinstance(relative, str) or relative == "":
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message="Artifact has no path",
            details={"artifact_id": record.get("artifact_id")},
        )
    candidate = (run_root / relative).resolve()
    try:
        candidate.relative_to(run_root.resolve())
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=400,
            code=ERROR_INVALID_PATH,
            message="Artifact path resolved outside run root",
            details={"artifact_id": record.get("artifact_id")},
        ) from exc
    if not candidate.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Artifact file missing on disk: {relative}",
            details={"artifact_id": record.get("artifact_id")},
        )
    return candidate


@app.get("/runs")
def list_runs_endpoint(project_root: str) -> dict:
    runs_dir = _resolve_project_runs_dir(project_root)
    summaries: list[dict] = []
    for entry in sorted(runs_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        manifest_path = entry / "run_manifest.json"
        if not manifest_path.is_file():
            continue
        summaries.append(_summarize_manifest(read_json(manifest_path)))
    return {"runs": summaries}


@app.get("/runs/{run_id}")
def get_run_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    _mark_interrupted_if_dead(run_root, manifest)
    summary = _summarize_manifest(manifest)
    errors_path = run_root / "errors.json"
    errors = read_json(errors_path) if errors_path.is_file() else {"issues": []}
    model_results = _model_results(run_root)
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


@app.get("/runs/{run_id}/artifacts")
def list_artifacts_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    records = _read_artifact_records(run_root)
    return {"groups": _group_artifacts(records)}


@app.get("/runs/{run_id}/artifacts/{artifact_id}")
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


@app.get("/runs/{run_id}/report")
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


def _list_existing_artifacts(run_root: Path) -> list[str]:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return []
    try:
        index = read_json(index_path)
        return [a.get("artifact_id", "?") for a in index.get("artifacts", [])]
    except Exception:
        return []


def _read_errors(run_root: Path) -> list[dict[str, Any]] | None:
    errors_path = run_root / "errors.json"
    if not errors_path.is_file():
        return None
    try:
        return read_json(errors_path).get("issues", [])
    except Exception:
        return None


def _detect_failed_stage(run_root: Path, existing: list[str]) -> str:
    if "report_html" in existing:
        return "report_registered_but_file_missing"
    if "poisson_1" in existing or "logit_1" in existing or "ols_1" in existing:
        return "model_fit_succeeded_report_build_failed"
    if "cleaned_dataset" in existing:
        return "data_cleaned_model_fit_failed_or_report_not_built"
    if "data_profile" in existing:
        return "data_profiled_cleaning_or_later_failed"
    return "early_failure"


_TERMINAL_EVENTS = {
    "workflow_completed", "workflow_blocked",
    "workflow_failed", "workflow_interrupted",
}


def _backfill_schema_values(editable_schema: list, form: dict) -> list:
    """2B.4: overlay the run's real form values onto editable_schema[i].value (by key).
    Copies (never mutates the shared capabilities list); missing/empty keys keep the
    capabilities default."""
    out = []
    for param in editable_schema:
        copy = dict(param)
        key = copy.get("key")
        if key in form and form[key] not in (None, ""):
            copy["value"] = form[key]
        out.append(copy)
    return out


def _annotate_editable_node(node: dict, manifest: dict, form: dict | None = None) -> None:
    """Guardrail #7: RESPONSE-TIME decoration only — never persisted to graph.json.
    If `form` is given (head-set view), backfill each control's current value from the
    run's run_inputs.form; otherwise keep capabilities defaults (legacy per-run shape)."""
    contract = resolve_operation_contract(stage=node.get("stage"), manifest=manifest)
    if contract is None:
        return
    node["editable"] = True
    node["op_type"] = contract.op_type
    node["schema_id"] = contract.schema_id
    if form:
        node["editable_schema"] = _backfill_schema_values(contract.editable_schema, form)
        node["editable_schema_source"] = "run_inputs"
    else:
        node["editable_schema"] = contract.editable_schema
        node["editable_schema_source"] = "capabilities"


def _annotate_editable_nodes(body: dict, manifest: dict) -> None:
    for node in body.get("nodes", {}).values():
        _annotate_editable_node(node, manifest)


@app.get("/runs/{run_id}/graph")
def get_run_graph(run_id: str, project_root: str, view: str | None = None):
    runs_root = _resolve_project_runs_dir(project_root)
    run_root = _resolve_run_root(project_root, run_id)  # 404 if run dir missing
    store = GraphStore(runs_root=runs_root)
    try:
        graph = store.read(run_id)
    except GraphDeserializationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="GRAPH_CORRUPT",
            message=f"graph.json for run {run_id} is corrupt or unreadable: {exc}",
            details={"run_id": run_id},
        ) from exc

    # 2B.2 — head-set family view (flag- or query-gated, non-breaking by default).
    headset_requested = view == "headset" or flags.graph_headset()
    target_legacy = not (run_root / NODE_INDEX_FILENAME).is_file()
    if headset_requested and not target_legacy:
        family = scan_family(runs_root, run_id)
        body = build_headset(runs_root, family, annotate=_annotate_editable_node)
        return body

    body = graph_to_json(graph)
    try:
        _annotate_editable_nodes(body, _read_manifest(run_root))
    except Exception:
        pass  # legacy / manifest-less runs stay non-editable (defensive)
    if headset_requested and target_legacy:
        body["legacy"] = True  # R5: opaque/legacy head, degrade to per-run shape
    sources = {edge.source_id for edge in graph.edges.values()}
    body["stats"] = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "leaf_count": sum(1 for node_id in graph.nodes if node_id not in sources),
        "has_dp_count": sum(1 for node in graph.nodes.values() if node.decision_points),
    }
    return body


class RerunRequest(BaseModel):
    from_node: str | None = None
    op_overrides: dict = {}
    rerun_reason: str = "manual_override"

    request_id: str | None = None
    operation: str | None = None
    context_version: str | None = None
    context_fingerprint: str | None = None
    owner_run_id: str | None = None
    op_node_id: str | None = None
    node_hash: str | None = None
    forest_node_key: str | None = None
    owner_resolution: str | None = None
    active_head_run_id: str | None = None


@app.post("/runs/{run_id}/rerun")
def rerun_endpoint(run_id: str, project_root: str, body: RerunRequest) -> dict[str, Any]:
    """Create a new immutable run from a parent run's editable node, applying
    structurally-validated overrides. Full-pipeline re-execution; lineage preserved."""
    root = Path(project_root)
    runs_root = _resolve_project_runs_dir(project_root)
    effective_run_id = run_id
    effective_from_node = body.from_node
    accepted_context: AcceptedContext | None = None
    focus_target: dict[str, str] | None = None

    if body.context_version is not None:
        try:
            request = NodeWriteOperationRequestV1(
                request_id=body.request_id,
                operation=body.operation,
                context_version=body.context_version,
                context_fingerprint=body.context_fingerprint,
                owner_run_id=body.owner_run_id,
                op_node_id=body.op_node_id,
                node_hash=body.node_hash,
                forest_node_key=body.forest_node_key,
                owner_resolution=body.owner_resolution,
                active_head_run_id=body.active_head_run_id,
            )
            validate_rerun_operation_target(runs_root, request)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="invalid_operation_target") from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=_node_write_validation_status(str(exc)),
                detail=str(exc),
            ) from exc
        accepted_context = accepted_context_from(request)
        effective_run_id = request.owner_run_id
        effective_from_node = request.op_node_id
        focus_target = {
            "forest_node_key": request.forest_node_key,
            "op_node_id": request.op_node_id,
            "node_hash": request.node_hash,
        }
    elif _has_context_target_fields(body):
        raise HTTPException(
            status_code=400,
            detail="context_version is required for context target fields.",
        )

    if effective_from_node is None:
        raise HTTPException(status_code=422, detail="from_node is required.")

    run_root = _resolve_run_root(project_root, effective_run_id)
    manifest = _read_manifest(run_root)

    # Guardrail #8: parent must be terminal (else 409). Distinct from slot-busy 429.
    status = manifest.get("status")
    if status not in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Parent run not terminal (status={status})."
        )

    # Guardrail #6: from_node must exist in the parent graph.
    graph = GraphStore(runs_root=runs_root).read(effective_run_id)
    node = graph.nodes.get(effective_from_node)
    if node is None:
        raise HTTPException(
            status_code=422, detail=f"from_node not in run graph: {effective_from_node}"
        )

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise HTTPException(
            status_code=422, detail=f"Node {effective_from_node} is not editable."
        )

    # Guardrails #3 + #4: structural validation against the switch-resolved schema.
    try:
        target = resolve_overrides_target(contract, body.op_overrides)
        validate_overrides(target, body.op_overrides)
    except OpOverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        inputs = read_run_inputs(run_root)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Parent run has no run_inputs.json (not rerunnable).",
        ) from exc
    parent_sha = (inputs.get("upload") or {}).get("sha256")
    if not parent_sha:
        raise HTTPException(status_code=422, detail="Parent run_inputs.json has no upload sha256.")
    # Guardrails #2 + #5: reuse parent upload by sha256 only; re-verify content hash.
    try:
        upload_bytes = verify_upload(root, parent_sha).read_bytes()
    except (OSError, ValueError) as exc:  # UploadBlobMissing / UploadHashMismatch
        raise HTTPException(
            status_code=422, detail=f"Parent upload unusable: {exc}"
        ) from exc

    # Form params are strings; JSON-encode list/dict overrides (e.g. iv_endog ["x"])
    # so the pipeline's JSON-array parsers accept them. override_hash uses raw values.
    def _encode_override(value: object) -> str:
        return json.dumps(value) if isinstance(value, (list, dict)) else str(value)

    merged_form = {
        **inputs["form"],
        **{k: _encode_override(v) for k, v in body.op_overrides.items()},
    }

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(status_code=429, detail="A run is already in progress.")
    child_id: str | None = None
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        result = _submit_run(
            root, form=merged_form, upload_bytes=upload_bytes,
            upload_filename=inputs["upload"].get("filename") or "upload.csv",
            started_at=started_at, rerun_of=effective_run_id, from_node=effective_from_node,
            rerun_reason=body.rerun_reason, op_overrides=body.op_overrides,
        )
        child_id = result["run_id"]
        return {
            "run_id": child_id,
            "new_run_id": child_id,
            "new_active_head_id": child_id,
            "focus": focus_target,
            "rerun_from": {
                "owner_run_id": effective_run_id,
                "op_node_id": effective_from_node,
                "node_hash": body.node_hash,
                "forest_node_key": body.forest_node_key,
            },
            "accepted_context": (
                accepted_context.model_dump() if accepted_context is not None else None
            ),
        }
    except ValueError as exc:
        events.release_slot(child_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        events.release_slot(child_id)
        raise


def _node_write_validation_status(message: str) -> int:
    if message.startswith(("unsupported_context_version", "invalid_operation_target")):
        return 400
    if message.startswith(("context_mismatch", "context_stale")):
        return 409
    if message.startswith("operation_not_allowed"):
        return 403
    return 400


def _has_context_target_fields(body: RerunRequest) -> bool:
    return any(
        value is not None
        for value in (
            body.request_id,
            body.operation,
            body.context_fingerprint,
            body.owner_run_id,
            body.op_node_id,
            body.node_hash,
            body.forest_node_key,
            body.owner_resolution,
            body.active_head_run_id,
        )
    )


@app.get("/runs/{run_id}/events")
async def run_events_endpoint(run_id: str, project_root: str):
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    events = get_event_manager()

    status = _mark_interrupted_if_dead(run_root, manifest)
    if status == "interrupted":
        events.register_run(run_id)
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
