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
from .http.projects_routes import router as projects_router
from .http.runs_routes import router as runs_router

app = FastAPI(title="Local Econometrics Workbench")
register_error_handlers(app)

app.include_router(projects_router)
app.include_router(runs_router)
