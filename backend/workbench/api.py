from __future__ import annotations

import asyncio
import json
import queue
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

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

app = FastAPI(title="Local Econometrics Workbench")
register_error_handlers(app)

UPLOAD_CHUNK_BYTES = 1024 * 1024
BYTES_PER_GB = 1024**3


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
) -> dict[str, str]:
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    x_columns = [part.strip() for part in x.split(",") if part.strip()]
    try:
        imputation_request = parse_imputation_request(imputation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(
            status_code=429,
            detail="A run is already in progress.",
        )

    run_id_for_cleanup: str | None = None
    try:
        run = create_run(root, mode=mode)
        run_id_for_cleanup = run.run_id
        started_at = datetime.now(timezone.utc).isoformat()

        uploads_dir = run.root / "_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        saved_path = uploads_dir / Path(file.filename or "upload.csv").name
        await _write_upload(file, saved_path, max_upload_bytes)

        _write_manifest(
            run.root, run.run_id, mode, "running",
            _lineage([saved_path]),
            started_at=started_at, y=y, x=x_columns,
            requested_model_type=model_type,
        )

        events.register_run(run.run_id)
        events.mark_active(run.run_id)
        events.executor.submit(
            _bg_run, run.root, run.run_id, saved_path,
            mode, y, x_columns, started_at, model_type,
            sheet_name or None, transpose == "true", imputation_request,
            entity_col, time_col, covariance,
            prediction_model_type, _safe_int(prediction_cv_folds),
            prediction_sampling_method,
        )

        return {"run_id": run.run_id, "status": "running"}
    except Exception:
        events.release_slot(run_id_for_cleanup)
        if run_id_for_cleanup is not None:
            write_json(
                run.root / "errors.json",
                {"issues": [GuardrailIssue(
                    Severity.BLOCKER, "WORKFLOW_FAILED",
                    "Workflow submission failed: the background worker could not be started.",
                    {},
                ).to_dict()]},
            )
            _write_manifest(
                run.root, run.run_id, mode, "failed",
                _lineage([saved_path]),
                started_at=started_at, y=y, x=x_columns,
                requested_model_type=model_type,
            )
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


@app.get("/runs/{run_id}/graph")
def get_run_graph(run_id: str, project_root: str):
    runs_root = _resolve_project_runs_dir(project_root)
    _resolve_run_root(project_root, run_id)  # 404 if run dir missing
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
    body = graph_to_json(graph)
    sources = {edge.source_id for edge in graph.edges.values()}
    body["stats"] = {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "leaf_count": sum(1 for node_id in graph.nodes if node_id not in sources),
        "has_dp_count": sum(1 for node in graph.nodes.values() if node.decision_points),
    }
    return body


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
