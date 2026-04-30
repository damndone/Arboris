from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

from .orchestrator import run_workflow
from .projects import create_project

app = FastAPI(title="Local Econometrics Workbench")


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
    temp_dir = Path(tempfile.mkdtemp(prefix="workbench_upload_"))
    filename = Path(file.filename or "upload.csv").name
    target = temp_dir / filename
    target.write_bytes(await file.read())
    x_columns = [part.strip() for part in x.split(",") if part.strip()]
    result = run_workflow(Path(project_root), [target], mode=mode, y=y, x=x_columns)
    return {"run_id": result["run_id"], "status": result["status"]}
