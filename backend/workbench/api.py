from __future__ import annotations

import asyncio
import json
import queue
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError

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
from .lineage.manual_patch_validation import (
    ManualPatchValidationError,
    ManualRerunPatch,
    validate_manual_patch,
)
from .lineage.op_contract import (
    OpOverrideError,
    resolve_operation_contract,
    resolve_overrides_target,
    validate_overrides,
)
from .lineage.pipeline_drafts import (
    DraftHashConflict,
    DraftLockedForExecution,
    DraftNodeNotFound,
    DraftNodePatchConflict,
    DraftNotFound,
    DraftValidationFailure,
    PipelineDraftStore,
    compute_executable_draft_hash,
    new_draft_id,
    schema_hash,
    utc_now,
    validate_draft_for_execution,
)
from .lineage.rerun_provenance import (
    pending_produced_lineage,
    run_rerun_from_from_context,
)
from .lineage.run_inputs import read_run_inputs, write_run_inputs
from .lineage.role_layer import canonicalize_focal_x
from .lineage.upload_store import resolve_upload, store_upload_bytes, verify_upload

# Estimator families whose focal/treatment variable is structural (not user-declared
# via focal_x). For these, persisted focal_x MUST be empty (spec §5).
_STRUCTURAL_FOCAL_FAMILIES = {"iv_2sls", "did", "cs_did", "sa_did", "dcdh"}


def _parse_focal_x(raw: str, x_columns: list[str]) -> list[str]:
    """Canonicalize the form's focal_x against the run's x columns."""
    return canonicalize_focal_x(raw, x_columns)


def _inject_focal_x_control(
    editable_schema: list[dict[str, Any]],
    form: dict[str, Any],
    model_type: str,
) -> list[dict[str, Any]]:
    """v1.6.5 — add a `focal_x` multiselect to a model node's editable_schema so
    the draft inspector can re-declare the focal explanatory variable(s).

    Omitted for structural-focal families (IV/DID/CS/SA/dCDH), where
    focal/treatment is structural — mirrors the run-POST clear (spec §5). The
    options are the run's x columns; the value is the run's canonicalized
    focal_x. No-op when there are no x columns or the control already exists."""
    if model_type in _STRUCTURAL_FOCAL_FAMILIES:
        return editable_schema
    if any(item.get("key") == "focal_x" for item in editable_schema):
        return editable_schema
    x_columns = [part.strip() for part in form.get("x", "").split(",") if part.strip()]
    if not x_columns:
        return editable_schema
    value = _parse_focal_x(form.get("focal_x", ""), x_columns)
    control = {
        "key": "focal_x",
        "kind": "multiselect",
        "label": "Focal explanatory variable(s)",
        "options": list(x_columns),
        "value": value,
    }
    return [*editable_schema, control]

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


@app.post("/uploads")
async def upload_dataset_endpoint(
    project_root: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    """v1.6.8 genesis: standalone content-addressable upload.

    Files persist server-side from wizard step 1 so genesis draft chains
    fully rehydrate after reload (same store POST /runs uses internally).
    """
    _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND for bogus roots
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    try:
        data = await _read_upload_bytes(file, max_upload_bytes)
    finally:
        await file.close()
    filename = Path(file.filename or "upload.csv").name
    sha = store_upload_bytes(root, data, filename=filename)
    return {"sha256": sha, "filename": filename}


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
    rerun_from: dict[str, Any] | None = None,
    before_dispatch: Callable[[str], None] | None = None,
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

    # focal_x: canonicalize against x; clear for families whose focal/treatment is
    # structural. Persist into run_inputs (the engine reads it back at recording).
    # Only mutate the form when there is something to set/clear, so runs that never
    # declare a focal keep byte-identical run_inputs (spec §5 backward compat).
    focal_x = _parse_focal_x(form.get("focal_x", ""), x_columns)
    if form.get("model_type", "auto") in _STRUCTURAL_FOCAL_FAMILIES:
        focal_x = []
    form_for_persist = form
    if focal_x:
        form_for_persist = {**form, "focal_x": ",".join(focal_x)}
    elif form.get("focal_x"):
        form_for_persist = {**form, "focal_x": ""}

    sha = store_upload_bytes(root, upload_bytes, filename=upload_filename)
    run = create_run(root, mode=form.get("mode", "auto"))

    write_run_inputs(
        run.root,
        form=form_for_persist,
        upload={"sha256": sha, "filename": upload_filename},
        rerun_of=rerun_of, from_node=from_node, rerun_reason=rerun_reason,
        override_hash=override_hash(op_overrides) if op_overrides else None,
        dag_hash=dag_hash(sha, form_for_persist),
        rerun_from=rerun_from,
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
    if before_dispatch is not None:
        before_dispatch(run.run_id)

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
    focal_x: str = Form(""),  # v1.6.5 role layer: comma-joined focal columns
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
            "focal_x": focal_x,
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
    model_config = ConfigDict(extra="forbid")

    from_node: str | None = None
    op_overrides: dict = {}
    rerun_reason: str = "manual_override"
    manual_patch: dict[str, Any] | None = None

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


class PipelineDraftFromNodeRequest(BaseModel):
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_forest_node_key: str | None = None
    source_context_fingerprint: str


class PipelineDraftPatchRequest(BaseModel):
    model_node_id: str
    base_draft_hash: str
    params: dict[str, Any]


class PipelineDraftValidateRequest(BaseModel):
    execution_mode: Literal["rerun_child", "new_run", "genesis"] | None = None


class PipelineDraftExecuteRequest(BaseModel):
    validated_draft_hash: str
    execution_mode: Literal["rerun_child", "new_run", "genesis"]
    idempotency_key: str | None = None


def _pipeline_draft_store(project_root: str) -> PipelineDraftStore:
    return PipelineDraftStore(Path(project_root))


def _draft_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DraftNotFound):
        return HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
    if isinstance(exc, DraftNodeNotFound):
        return HTTPException(status_code=404, detail=f"DRAFT_NODE_NOT_FOUND: {exc}")
    if isinstance(exc, DraftNodePatchConflict):
        return HTTPException(status_code=409, detail=f"{DraftNodePatchConflict.code}: {exc}")
    if isinstance(exc, DraftHashConflict):
        return HTTPException(status_code=409, detail="DRAFT_HASH_CONFLICT")
    if isinstance(exc, DraftLockedForExecution):
        return HTTPException(status_code=409, detail="DRAFT_LOCKED_FOR_EXECUTION")
    if isinstance(exc, DraftValidationFailure):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _read_indexed_node_hash(run_root: Path, node_id: str) -> str | None:
    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return None
    index = read_json(index_path)
    entry = index.get(node_id)
    if not isinstance(entry, dict):
        return None
    node_hash = entry.get("node_hash")
    return str(node_hash) if node_hash else None


def _source_params_from_schema(editable_schema: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        item["key"]: item.get("value")
        for item in editable_schema
        if item.get("key")
    }


@app.post("/pipeline-drafts/from-node")
def create_pipeline_draft_from_node(
    project_root: str,
    body: PipelineDraftFromNodeRequest,
) -> dict[str, Any]:
    runs_root = _resolve_project_runs_dir(project_root)
    run_root = _resolve_run_root(project_root, body.source_run_id)
    manifest = _read_manifest(run_root)
    if manifest.get("status") not in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Source run not terminal (status={manifest.get('status')}).",
        )

    graph = GraphStore(runs_root=runs_root).read(body.source_run_id)
    node = graph.nodes.get(body.source_op_node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="SOURCE_MODEL_NODE_NOT_FOUND")
    if body.source_model_node_id != body.source_op_node_id:
        raise HTTPException(status_code=409, detail="SOURCE_MODEL_NODE_MISMATCH")

    indexed_hash = _read_indexed_node_hash(run_root, body.source_op_node_id)
    if indexed_hash is None:
        raise HTTPException(status_code=422, detail="SOURCE_NODE_HASH_UNAVAILABLE")
    if indexed_hash != body.source_node_hash:
        raise HTTPException(status_code=409, detail="SOURCE_NODE_HASH_MISMATCH")

    try:
        request = NodeWriteOperationRequestV1(
            request_id="pipeline_draft_from_node",
            operation="rerun",
            context_version="node-operation-context/v1",
            context_fingerprint=body.source_context_fingerprint,
            owner_run_id=body.source_run_id,
            op_node_id=body.source_op_node_id,
            node_hash=body.source_node_hash,
            forest_node_key=body.source_forest_node_key or body.source_node_hash,
            owner_resolution="single_candidate",
            active_head_run_id=body.source_run_id,
        )
        validate_rerun_operation_target(runs_root, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"SOURCE_CONTEXT_MISMATCH: {exc}") from exc

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise HTTPException(status_code=422, detail="MODEL_NODE_NOT_ELIGIBLE")

    try:
        inputs = read_run_inputs(run_root)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail="SOURCE_RUN_INPUTS_UNAVAILABLE") from exc
    upload = inputs.get("upload") or {}
    source_input_fingerprint = upload.get("sha256")
    if not source_input_fingerprint:
        raise HTTPException(status_code=422, detail="SOURCE_INPUT_FINGERPRINT_UNAVAILABLE")

    now = utc_now()
    draft_id = new_draft_id()
    _draft_form = inputs.get("form") or {}
    editable_schema = _backfill_schema_values(contract.editable_schema, _draft_form)
    editable_schema = _inject_focal_x_control(editable_schema, _draft_form, contract.op_type)
    source_params = _source_params_from_schema(editable_schema)
    draft = {
        "draft_id": draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": body.source_run_id,
            "source_model_node_id": body.source_model_node_id,
            "source_op_node_id": body.source_op_node_id,
            "source_node_hash": body.source_node_hash,
            "source_context_fingerprint": body.source_context_fingerprint,
            "source_input_fingerprint": source_input_fingerprint,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": body.source_run_id,
                    "schema_fingerprint": inputs.get("dag_hash") or source_input_fingerprint,
                    "input_fingerprint": source_input_fingerprint,
                    "columns_summary": [
                        {"name": key}
                        for key in sorted((inputs.get("form") or {}).keys())
                    ],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": contract.op_type,
                    "schema_id": contract.schema_id,
                    "editable_schema": editable_schema,
                    "editable_schema_hash": schema_hash(editable_schema),
                    "source_ref": {
                        "source_run_id": body.source_run_id,
                        "source_model_node_id": body.source_model_node_id,
                        "source_op_node_id": body.source_op_node_id,
                        "source_node_hash": body.source_node_hash,
                        "source_context_fingerprint": body.source_context_fingerprint,
                    },
                    "source_params": source_params,
                    "params": source_params,
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }
    try:
        stored = _pipeline_draft_store(project_root).create(draft)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


class PipelineDraftGenesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_sha256: str
    filename: str
    sheet_names: list[str] = []
    columns: list[str] = []  # client-side SheetJS-parsed column names


@app.post("/pipeline-drafts/genesis")
def create_pipeline_draft_genesis(
    project_root: str,
    body: PipelineDraftGenesisRequest,
) -> dict[str, Any]:
    """v1.6.8: parentless genesis draft chain (source -> table -> model).

    Same store + lifecycle as from-node drafts; created_from.source_type
    distinguishes the branch everywhere downstream (validate / execute).

    Design note: the genesis model node is params-only, NO editable_schema —
    the wizard reuses capabilities-driven RunForm controls (which don't need
    editable_schema); validate stays structural; column checks belong to
    execute (spec F3/F4).
    """
    _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND for bogus roots
    root = Path(project_root)
    if not re.fullmatch(r"[0-9a-f]{64}", body.upload_sha256):
        # Reject before touching the filesystem; do NOT reflect the raw value.
        raise HTTPException(status_code=422, detail="UPLOAD_NOT_FOUND: invalid sha256")
    try:
        verify_upload(root, body.upload_sha256)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"UPLOAD_NOT_FOUND: {exc}") from exc

    now = utc_now()
    draft = {
        "draft_id": new_draft_id(),
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "genesis",
            "source_input_fingerprint": body.upload_sha256,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "source_1",
                    "node_type": "input.upload",
                    "upload": {"sha256": body.upload_sha256, "filename": body.filename},
                    "sheet_names": body.sheet_names,
                    "status": "bound",
                },
                {
                    "node_id": "table_1",
                    "node_type": "table",
                    "params": {"sheet_name": None, "transpose": False},
                    "columns": body.columns,
                    "status": "pending",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": None,
                    "params": {},
                    "status": "pending",
                },
            ],
            "edges": [
                {"from": "source_1", "to": "table_1"},
                {"from": "table_1", "to": "model_1"},
            ],
        },
        "default_execution_mode": "genesis",
    }
    try:
        stored = _pipeline_draft_store(project_root).create(draft)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@app.get("/pipeline-drafts")
def list_pipeline_drafts(project_root: str) -> dict[str, Any]:
    try:
        drafts = _pipeline_draft_store(project_root).list()
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"drafts": drafts}


@app.get("/pipeline-drafts/{draft_id}")
def get_pipeline_draft(draft_id: str, project_root: str) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@app.patch("/pipeline-drafts/{draft_id}")
def patch_pipeline_draft(
    draft_id: str,
    project_root: str,
    body: PipelineDraftPatchRequest,
) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).update_params(
            draft_id,
            model_node_id=body.model_node_id,
            base_draft_hash=body.base_draft_hash,
            params=body.params,
        )
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


class DraftNodePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any]
    columns: list[str] | None = None


@app.patch("/pipeline-drafts/{draft_id}/nodes/{node_id}")
def patch_pipeline_draft_node(
    draft_id: str,
    node_id: str,
    project_root: str,
    body: DraftNodePatchRequest,
) -> dict[str, Any]:
    """v1.6.8 genesis wizard step: configure table_1 / model_1 in place.

    Genesis-only (409 otherwise); the bound source node is immutable —
    changing the file means discard the draft and restart genesis.
    `columns` applies to table nodes only and is silently dropped on a
    model-node PATCH.
    """
    store = _pipeline_draft_store(project_root)
    try:
        stored = store.update_node_params(draft_id, node_id, body.params, columns=body.columns)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@app.delete("/pipeline-drafts/{draft_id}")
def delete_pipeline_draft(draft_id: str, project_root: str) -> dict[str, Any]:
    try:
        _pipeline_draft_store(project_root).delete(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"ok": True, "draft_id": draft_id}


@app.post("/pipeline-drafts/{draft_id}/validate")
def validate_pipeline_draft(
    draft_id: str,
    project_root: str,
    body: PipelineDraftValidateRequest,
) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return validate_draft_for_execution(stored.draft, execution_mode=body.execution_mode)


def _execute_genesis_draft(
    draft_id: str,
    root: Path,
    store: PipelineDraftStore,
    first: Any,
    body: PipelineDraftExecuteRequest,
) -> dict[str, Any]:
    """v1.6.8 genesis execute: parentless draft chain -> FIRST run of a project.

    PARALLEL implementation to the from-node branch (same skeleton: hash check
    outside lock -> dedupe -> execution_lock -> re-check + re-validate -> submit),
    but genesis is NOT a rerun: no parent run_inputs to merge, no rerun_of /
    from_node / op_overrides / rerun_from — the full form is synthesized from the
    draft chain and dispatched via _submit_run(rerun_reason='initial')."""
    if first.draft_hash != body.validated_draft_hash:
        raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

    dedupe_key = (
        body.idempotency_key
        or f"{draft_id}:{body.validated_draft_hash}:{body.execution_mode}"
    )
    existing = store.get_dedupe(draft_id, dedupe_key)
    if existing is not None:
        validation = validate_draft_for_execution(first.draft, execution_mode="genesis")
        return {
            "ok": True,
            "run_id": existing.run_id,
            "draft_id": draft_id,
            "executed_draft_hash": existing.executed_draft_hash,
            "execution_mode": "genesis",
            "deduped": True,
            "produced_lineage": validation["resolved_execution"],
            "focus": {
                "status": "pending_index",
                "run_id": existing.run_id,
                "poll": validation["resolved_execution"],
            },
        }

    with store.execution_lock(draft_id):
        current = store.get(draft_id)
        if current.draft_hash != body.validated_draft_hash:
            raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

        validation = validate_draft_for_execution(current.draft, execution_mode="genesis")
        if not validation.get("executable"):
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")
        if validation.get("validated_execution_mode") != "genesis":
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")

        existing = store.get_dedupe(draft_id, dedupe_key)
        if existing is not None:
            return {
                "ok": True,
                "run_id": existing.run_id,
                "draft_id": draft_id,
                "executed_draft_hash": existing.executed_draft_hash,
                "execution_mode": "genesis",
                "deduped": True,
                "produced_lineage": validation["resolved_execution"],
                "focus": {
                    "status": "pending_index",
                    "run_id": existing.run_id,
                    "poll": validation["resolved_execution"],
                },
            }

        draft = current.draft
        # --- genesis: synthesize the full form (no parent run to merge) ---
        nodes = {n["node_id"]: n for n in draft["graph"]["nodes"]}
        sha = nodes["source_1"]["upload"]["sha256"]
        filename = nodes["source_1"]["upload"].get("filename") or "upload.csv"
        try:
            upload_bytes = verify_upload(root, sha).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"GENESIS_UPLOAD_UNUSABLE: {exc}"
            ) from exc

        tp = nodes["table_1"].get("params") or {}
        mp = dict(nodes["model_1"].get("params") or {})
        x_val = mp.pop("x", "")
        focal = mp.pop("focal_x", "")
        merged_form = {
            "mode": "auto",
            "model_type": str(mp.pop("model_type", "") or "auto"),
            "y": str(mp.pop("y", "")),
            # x / focal_x wire format is a comma-joined column list (the
            # dispatch comma-splits; see the v1.6.5 note in the from-node branch)
            "x": ",".join(x_val) if isinstance(x_val, list) else str(x_val),
            "sheet_name": str(tp.get("sheet_name") or ""),
            "transpose": "true" if tp.get("transpose") else "false",
            "focal_x": ",".join(focal) if isinstance(focal, list) else str(focal),
            # remaining model params share POST /runs' form field names — pass through:
            **{
                k: (json.dumps(v) if isinstance(v, (list, dict)) else str(v))
                for k, v in mp.items()
            },
        }

        executed_hash = compute_executable_draft_hash(draft)

        def _record_snapshot_before_dispatch(new_run_id: str) -> None:
            run_dir = root / "runs" / new_run_id
            (run_dir / "executed_pipeline_draft.json").write_text(
                json.dumps(
                    {
                        "executed_at": utc_now(),
                        "source_draft_id": draft_id,
                        "executed_draft_hash": executed_hash,
                        "execution_request": {
                            "execution_mode": "genesis",
                            "validated_draft_hash": body.validated_draft_hash,
                        },
                        "draft": draft,
                    },
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            store.record_dedupe(
                draft_id,
                dedupe_key,
                run_id=new_run_id,
                executed_draft_hash=executed_hash,
            )

        events = get_event_manager()
        if not events.try_acquire_slot():
            raise HTTPException(status_code=429, detail="A run is already in progress.")
        try:
            result = _submit_run(
                root,
                form=merged_form,
                upload_bytes=upload_bytes,
                upload_filename=filename,
                started_at=datetime.now(timezone.utc).isoformat(),
                rerun_reason="initial",
                before_dispatch=_record_snapshot_before_dispatch,
            )
        except Exception:
            events.release_slot(None)
            raise

        return {
            "ok": True,
            "run_id": result["run_id"],
            "draft_id": draft_id,
            "executed_draft_hash": executed_hash,
            "execution_mode": "genesis",
            "produced_lineage": {"genesis": True},
            "focus": {
                "status": "pending_index",
                "run_id": result["run_id"],
                "poll": {"genesis": True},
            },
        }


@app.post("/pipeline-drafts/{draft_id}/execute")
def execute_pipeline_draft(
    draft_id: str,
    project_root: str,
    body: PipelineDraftExecuteRequest,
) -> dict[str, Any]:
    if body.execution_mode == "new_run":
        raise HTTPException(status_code=409, detail="NEW_RUN_EXECUTION_NOT_ENABLED")

    root = Path(project_root)
    store = _pipeline_draft_store(project_root)
    try:
        first = store.get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc

    # v1.6.8 genesis drafts dispatch to a PARALLEL branch before any from-node
    # semantics (hash check included, so the cross-mode guard always wins).
    is_genesis = (first.draft.get("created_from") or {}).get("source_type") == "genesis"
    if is_genesis and body.execution_mode != "genesis":
        raise HTTPException(status_code=409, detail="GENESIS_MODE_REQUIRED")
    if not is_genesis and body.execution_mode == "genesis":
        raise HTTPException(status_code=409, detail="GENESIS_ONLY_FOR_GENESIS_DRAFTS")
    if is_genesis:
        return _execute_genesis_draft(draft_id, root, store, first, body)

    if first.draft_hash != body.validated_draft_hash:
        raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

    dedupe_key = (
        body.idempotency_key
        or f"{draft_id}:{body.validated_draft_hash}:{body.execution_mode}"
    )
    existing = store.get_dedupe(draft_id, dedupe_key)
    if existing is not None:
        validation = validate_draft_for_execution(first.draft, execution_mode=body.execution_mode)
        return {
            "ok": True,
            "run_id": existing.run_id,
            "draft_id": draft_id,
            "executed_draft_hash": existing.executed_draft_hash,
            "execution_mode": "rerun_child",
            "deduped": True,
            "produced_lineage": validation["resolved_execution"],
            "focus": {
                "status": "pending_index",
                "run_id": existing.run_id,
                "poll": validation["resolved_execution"],
            },
        }

    with store.execution_lock(draft_id):
        current = store.get(draft_id)
        if current.draft_hash != body.validated_draft_hash:
            raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

        validation = validate_draft_for_execution(current.draft, execution_mode=body.execution_mode)
        if not validation.get("executable"):
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")
        if validation.get("validated_execution_mode") != body.execution_mode:
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")

        existing = store.get_dedupe(draft_id, dedupe_key)
        if existing is not None:
            return {
                "ok": True,
                "run_id": existing.run_id,
                "draft_id": draft_id,
                "executed_draft_hash": existing.executed_draft_hash,
                "execution_mode": "rerun_child",
                "deduped": True,
                "produced_lineage": validation["resolved_execution"],
                "focus": {
                    "status": "pending_index",
                    "run_id": existing.run_id,
                    "poll": validation["resolved_execution"],
                },
            }

        draft = current.draft
        source = draft["created_from"]
        model = next(node for node in draft["graph"]["nodes"] if node.get("node_type") == "model")
        run_root = _resolve_run_root(project_root, source["source_run_id"])
        try:
            inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(status_code=422, detail="SOURCE_RUN_INPUTS_UNAVAILABLE") from exc
        parent_sha = (inputs.get("upload") or {}).get("sha256")
        if not parent_sha:
            raise HTTPException(status_code=422, detail="SOURCE_INPUT_FINGERPRINT_UNAVAILABLE")
        try:
            upload_bytes = verify_upload(root, parent_sha).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Parent upload unusable: {exc}") from exc

        op_overrides = {
            key: value
            for key, value in model["params"].items()
            if model.get("source_params", {}).get(key) != value
        }

        def _encode_override(value: object) -> str:
            return json.dumps(value) if isinstance(value, (list, dict)) else str(value)

        merged_form = {
            **inputs["form"],
            **{key: _encode_override(value) for key, value in op_overrides.items()},
        }
        # v1.6.5: focal_x is a run-form field carrying a comma-joined column
        # list, NOT a JSON-encoded override. _encode_override would emit
        # ["x"], which the dispatch's comma-split parser cannot read — coerce
        # it back to the form wire format so the role layer sees the picks.
        if "focal_x" in op_overrides:
            _focal = op_overrides["focal_x"]
            merged_form["focal_x"] = (
                ",".join(_focal) if isinstance(_focal, list) else str(_focal)
            )
        run_level_rerun_from = run_rerun_from_from_context(
            request_id=f"draft:{draft_id}",
            owner_run_id=source["source_run_id"],
            op_node_id=source["source_op_node_id"],
            node_hash=source["source_node_hash"],
            context_fingerprint=source["source_context_fingerprint"],
        )
        executed_hash = compute_executable_draft_hash(draft)

        def _record_snapshot_before_dispatch(new_run_id: str) -> None:
            run_dir = root / "runs" / new_run_id
            (run_dir / "executed_pipeline_draft.json").write_text(
                json.dumps(
                    {
                        "executed_at": utc_now(),
                        "source_draft_id": draft_id,
                        "executed_draft_hash": executed_hash,
                        "execution_request": {
                            "execution_mode": "rerun_child",
                            "validated_draft_hash": body.validated_draft_hash,
                        },
                        "draft": draft,
                    },
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            store.record_dedupe(
                draft_id,
                dedupe_key,
                run_id=new_run_id,
                executed_draft_hash=executed_hash,
            )

        events = get_event_manager()
        if not events.try_acquire_slot():
            raise HTTPException(status_code=429, detail="A run is already in progress.")
        try:
            result = _submit_run(
                root,
                form=merged_form,
                upload_bytes=upload_bytes,
                upload_filename=inputs["upload"].get("filename") or "upload.csv",
                started_at=datetime.now(timezone.utc).isoformat(),
                rerun_of=source["source_run_id"],
                from_node=source["source_op_node_id"],
                rerun_reason="pipeline_draft",
                op_overrides=op_overrides,
                rerun_from=run_level_rerun_from,
                before_dispatch=_record_snapshot_before_dispatch,
            )
        except Exception:
            events.release_slot(None)
            raise

        return {
            "ok": True,
            "run_id": result["run_id"],
            "draft_id": draft_id,
            "executed_draft_hash": executed_hash,
            "execution_mode": "rerun_child",
            "produced_lineage": {
                "rerun_from_run_id": source["source_run_id"],
                "rerun_from_model_node_id": source["source_model_node_id"],
                "rerun_from_op_node_id": source["source_op_node_id"],
            },
            "focus": {
                "status": "pending_index",
                "run_id": result["run_id"],
                "poll": {
                    "rerun_from_run_id": source["source_run_id"],
                    "rerun_from_model_node_id": source["source_model_node_id"],
                    "rerun_from_op_node_id": source["source_op_node_id"],
                },
            },
        }


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
    run_level_rerun_from: dict[str, Any] | None = None
    manual_patch: ManualRerunPatch | None = None
    effective_op_overrides = body.op_overrides

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
        run_level_rerun_from = run_rerun_from_from_context(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            node_hash=request.node_hash,
            context_fingerprint=request.context_fingerprint,
        )
        if body.manual_patch is not None:
            if body.op_overrides:
                raise HTTPException(status_code=400, detail="MANUAL_PATCH_WITH_OP_OVERRIDES")
            try:
                manual_patch = ManualRerunPatch(**body.manual_patch)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail="INVALID_MANUAL_PATCH") from exc
            if manual_patch.source_context_fingerprint != request.context_fingerprint:
                raise HTTPException(status_code=409, detail="SOURCE_CONTEXT_MISMATCH")
            if (
                manual_patch.target.owner_run_id != request.owner_run_id
                or manual_patch.target.op_node_id != request.op_node_id
                or manual_patch.target.node_hash != request.node_hash
            ):
                raise HTTPException(status_code=409, detail="PATCH_TARGET_MISMATCH")
            run_level_rerun_from["patch_id"] = manual_patch.patch_id
        effective_run_id = request.owner_run_id
        effective_from_node = request.op_node_id
        focus_target = None
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

    manual_patch_result: dict[str, Any] | None = None
    if manual_patch is not None:
        editable_schema = _backfill_schema_values(contract.editable_schema, inputs["form"])
        current_values = {
            item["key"]: item.get("value")
            for item in editable_schema
            if item.get("key")
        }
        try:
            patch_overrides = validate_manual_patch(
                patch=manual_patch,
                current_values=current_values,
                editable_schema=editable_schema,
                editable_schema_version="run_inputs",
            )
        except ManualPatchValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        merged_form = {
            **inputs["form"],
            **{k: _encode_override(v) for k, v in patch_overrides.items()},
        }
        effective_op_overrides = patch_overrides
        manual_patch_result = _manual_patch_idempotency_result(
            root=root,
            owner_run_id=effective_run_id,
            patch=manual_patch,
        )
        if manual_patch_result is not None:
            return manual_patch_result

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(status_code=429, detail="A run is already in progress.")
    child_id: str | None = None
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        def _response_for(new_child_id: str) -> dict[str, Any]:
            return {
                "run_id": new_child_id,
                "new_run_id": new_child_id,
                "new_active_head_id": new_child_id,
                "focus": focus_target,
                "produced_lineage": (
                    pending_produced_lineage(
                        produced_owner_run_id=new_child_id,
                        rerun_from=run_level_rerun_from,
                    )
                    if run_level_rerun_from is not None
                    else None
                ),
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

        def _record_idempotency_before_dispatch(new_child_id: str) -> None:
            if manual_patch is not None:
                _record_manual_patch_idempotency(
                    root=root,
                    owner_run_id=effective_run_id,
                    patch=manual_patch,
                    response=_response_for(new_child_id),
                )

        result = _submit_run(
            root, form=merged_form, upload_bytes=upload_bytes,
            upload_filename=inputs["upload"].get("filename") or "upload.csv",
            started_at=started_at, rerun_of=effective_run_id, from_node=effective_from_node,
            rerun_reason=body.rerun_reason, op_overrides=effective_op_overrides,
            rerun_from=run_level_rerun_from,
            before_dispatch=_record_idempotency_before_dispatch,
        )
        child_id = result["run_id"]
        return _response_for(child_id)
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
            body.manual_patch,
        )
    )


def _manual_patch_idempotency_path(root: Path, owner_run_id: str) -> Path:
    return root / "runs" / owner_run_id / "manual_patch_idempotency.json"


def _manual_patch_idempotency_payload(patch: ManualRerunPatch) -> str:
    return json.dumps(patch.model_dump(), sort_keys=True, separators=(",", ":"))


def _manual_patch_idempotency_result(
    *,
    root: Path,
    owner_run_id: str,
    patch: ManualRerunPatch,
) -> dict[str, Any] | None:
    path = _manual_patch_idempotency_path(root, owner_run_id)
    if not path.is_file():
        return None
    try:
        index = read_json(path)
    except (OSError, ValueError):
        return None
    entry = (index.get("patches") or {}).get(patch.patch_id)
    if entry is None:
        return None
    if entry.get("payload") != _manual_patch_idempotency_payload(patch):
        raise HTTPException(status_code=409, detail="PATCH_ID_CONFLICT")
    response = entry.get("response")
    if not isinstance(response, dict):
        return None
    return response


def _record_manual_patch_idempotency(
    *,
    root: Path,
    owner_run_id: str,
    patch: ManualRerunPatch,
    response: dict[str, Any],
) -> None:
    path = _manual_patch_idempotency_path(root, owner_run_id)
    try:
        index = read_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        index = {}
    patches = dict(index.get("patches") or {})
    patches[patch.patch_id] = {
        "payload": _manual_patch_idempotency_payload(patch),
        "response": response,
    }
    write_json(path, {"patches": patches})


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
