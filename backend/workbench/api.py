from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .api_errors import register_error_handlers
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
