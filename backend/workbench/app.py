"""FastAPI application assembly.

Owns the single ``app`` instance and error-handler registration. Route clusters
live in ``http/*_routes.py`` as ``APIRouter``s and are mounted here via
``include_router``. ``api.py`` re-exports this ``app`` (uvicorn target
``workbench.api:app``) and, during the v1.6.10 D1 router migration, still attaches
the not-yet-migrated routes onto it.

Extracted from ``api.py`` in v1.6.10 (D1 decomposition, Phase 4).
"""
from __future__ import annotations

from fastapi import FastAPI

from .api_errors import register_error_handlers
from .control_plane import control_plane_capability, validate_control_plane
from .http.agent_routes import router as agent_router
from .http.drafts_routes import router as drafts_router
from .http.data_operation_routes import router as data_operation_router
from .http.graph_routes import router as graph_router
from .http.llm_routes import router as llm_router
from .http.projects_routes import router as projects_router
from .http.rerun_routes import router as rerun_router
from .http.runs_routes import router as runs_router

app = FastAPI(title="Local Econometrics Workbench")
register_error_handlers(app)


@app.on_event("startup")
def _validate_supported_deployment() -> None:
    validate_control_plane()


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", **control_plane_capability()}

app.include_router(projects_router)
app.include_router(runs_router)
app.include_router(graph_router)
app.include_router(drafts_router)
app.include_router(data_operation_router)
app.include_router(agent_router)
app.include_router(rerun_router)
app.include_router(llm_router)
