"""Project + capabilities + standalone-upload routes.

``GET /capabilities`` · ``POST /projects`` · ``POST /uploads``.

Extracted from ``api.py`` in v1.6.10 (D1 decomposition, Phase 4).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from ..api_errors import ERROR_INVALID_PATH, WorkbenchAPIError
from ..config import load_config
from ..engine.capabilities import build_capabilities
from ..lineage.upload_store import store_upload_bytes
from ..projects import create_project
from ..repository.run_repository import _resolve_project_runs_dir
from ..services.run_service import _read_upload_bytes
from ..services.system_appearance import detect_system_appearance
from ._deps import BYTES_PER_GB
from .responses.projects import ProjectCreated, StatisticalUploadPreview, UploadStored
from .responses.system import Capabilities, SystemAppearance
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


class ProjectRequest(BaseModel):
    parent: str
    name: str


@router.get("/capabilities")
def capabilities_endpoint() -> Capabilities:
    return build_capabilities()


@router.get("/system/appearance")
def system_appearance_endpoint() -> SystemAppearance:
    """Expose only the local host's light/dark preference.

    The frontend consumes this endpoint only on loopback hosts. Remote clients
    continue to use their own browser ``prefers-color-scheme`` signal.
    """

    return detect_system_appearance()


@router.post("/projects")
def create_project_endpoint(request: ProjectRequest) -> ProjectCreated:
    parent_raw = request.parent.strip()
    name = request.name.strip()
    if not parent_raw:
        raise WorkbenchAPIError(
            status_code=422,
            code=ERROR_INVALID_PATH,
            message="Project parent path is required.",
            details={"field": "parent"},
        )
    if not name:
        raise WorkbenchAPIError(
            status_code=422,
            code=ERROR_INVALID_PATH,
            message="Project name is required.",
            details={"field": "name"},
        )
    if "/" in name or "\\" in name:
        raise WorkbenchAPIError(
            status_code=422,
            code=ERROR_INVALID_PATH,
            message="Project name must not contain path separators.",
            details={"field": "name"},
        )
    if name in {".", ".."}:
        # `parent / ".."` escapes the parent: create_project mkdirs with
        # exist_ok=True and writes project.yaml/config.yml unconditionally,
        # so it would scaffold project files into an arbitrary existing dir.
        raise WorkbenchAPIError(
            status_code=422,
            code=ERROR_INVALID_PATH,
            message="Project name must be a real directory name.",
            details={"field": "name"},
        )
    parent = Path(parent_raw).expanduser()
    if not parent.is_absolute():
        raise WorkbenchAPIError(
            status_code=422,
            code=ERROR_INVALID_PATH,
            message="Project parent path must be absolute.",
            details={"field": "parent", "parent": parent_raw},
        )
    try:
        project = create_project(parent, name)
    except OSError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=ERROR_INVALID_PATH,
            message="Cannot create project at parent path.",
            details={"parent": str(parent), "reason": str(exc)},
        ) from exc
    return {"project_root": str(project.root)}


@router.post("/uploads")
async def upload_dataset_endpoint(
    project_root: str = Form(...),
    file: UploadFile = File(...),
) -> UploadStored:
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


PREVIEW_ROW_LIMIT = 5000


@router.post("/uploads/preview")
async def preview_statistical_upload(
    project_root: str = Form(...),
    file: UploadFile = File(...),
) -> StatisticalUploadPreview:
    """Preview rows of an SPSS/Stata file the browser cannot parse itself.

    CSV and Excel are previewed client-side; this returns the same row shape
    (first rows as JSON records, codes as stored) plus the file's labels and
    total row count, so the form can suggest roles the same way.
    """

    import math
    import tempfile

    import pandas as pd

    from ..tabular_io import (
        StatisticalFileError,
        read_statistical_labels,
        read_table,
        statistical_format,
        statistical_row_count,
    )

    _resolve_project_runs_dir(project_root)
    filename = Path(file.filename or "").name
    fmt = statistical_format(filename)
    if fmt is None:
        raise WorkbenchAPIError(
            status_code=422,
            code="UPLOAD_PREVIEW_UNSUPPORTED",
            message="Server preview is only for .sav, .zsav and .dta files.",
            details={"filename": filename},
        )
    config = load_config(Path(project_root) / "config.yml")
    try:
        data = await _read_upload_bytes(file, int(config.max_single_file_gb * BYTES_PER_GB))
    finally:
        await file.close()
    with tempfile.TemporaryDirectory(prefix="workbench-preview-") as directory:
        path = Path(directory) / f"upload{Path(filename).suffix.lower()}"
        path.write_bytes(data)
        try:
            header = read_table(path, nrows=0)
            frame = read_table(path, nrows=PREVIEW_ROW_LIMIT)
            labels = read_statistical_labels(path, fmt)
            total_rows = statistical_row_count(path, fmt) or len(frame)
        except StatisticalFileError as exc:
            raise WorkbenchAPIError(
                status_code=422,
                code="UPLOAD_PREVIEW_UNREADABLE",
                message=str(exc),
                details={"filename": filename},
            ) from exc

    def cell(value: object) -> object:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if hasattr(value, "item"):
            return value.item()
        return value

    rows = [
        {str(column): cell(value) for column, value in record.items()}
        for record in frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
    ]
    return {
        "columns": [str(column) for column in header.columns],
        "rows": rows,
        "total_rows": total_rows,
        "labels": labels,
    }
