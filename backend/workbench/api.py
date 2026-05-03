from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
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
from .artifacts import read_json
from .config import load_config
from .orchestrator import run_workflow
from .projects import create_project

app = FastAPI(title="Local Econometrics Workbench")
register_error_handlers(app)

UPLOAD_CHUNK_BYTES = 1024 * 1024
BYTES_PER_GB = 1024**3


class ProjectRequest(BaseModel):
    parent: str
    name: str


@app.post("/projects")
def create_project_endpoint(request: ProjectRequest) -> dict[str, str]:
    project = create_project(Path(request.parent), request.name)
    return {"project_root": str(project.root)}


@app.post("/runs")
async def run_endpoint(
    project_root: str = Form(...),
    mode: str = Form("auto"),
    y: str = Form(...),
    x: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    root = Path(project_root)
    config = load_config(root / "config.yml")
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    x_columns = [part.strip() for part in x.split(",") if part.strip()]
    try:
        with tempfile.TemporaryDirectory(prefix="workbench_upload_") as temp_dir:
            target = Path(temp_dir) / Path(file.filename or "upload.csv").name
            await _write_upload(file, target, max_upload_bytes)
            result = run_workflow(root, [target], mode=mode, y=y, x=x_columns)
    finally:
        await file.close()
    return {"run_id": result["run_id"], "status": result["status"]}


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
    summary = _summarize_manifest(manifest)
    errors_path = run_root / "errors.json"
    errors = read_json(errors_path) if errors_path.is_file() else {"issues": []}
    return {
        **summary,
        "lineage": manifest.get("lineage", []),
        "artifact_counts": _artifact_counts(run_root),
        "errors": errors,
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
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_REPORT_NOT_FOUND,
            message="report.html not found for this run",
            details={"run_id": run_id},
        )
    return FileResponse(report_path, media_type="text/html")
