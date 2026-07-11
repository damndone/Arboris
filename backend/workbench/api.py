"""Backward-compat facade for ``workbench.api``.

The FastAPI app now lives in ``workbench.app`` and route clusters in
``workbench.http.*_routes``. This module re-exports ``app`` (uvicorn target
``workbench.api:app``) plus the handful of private symbols tests import directly
(kept as a stable seam). v1.6.10 D1 decomposition, Phase 4 completion.
"""
from __future__ import annotations

from .app import app
from .http.drafts_routes import _inject_focal_x_control
from .repository.run_repository import (
    _read_artifacts_index,
    _resolve_artifact_path,
    _resolve_run_root,
)
from .services.run_service import (
    _STRUCTURAL_FOCAL_FAMILIES,
    _parse_focal_x,
    _parse_json_str_array,
)

__all__ = [
    "app",
    "_inject_focal_x_control",
    "_read_artifacts_index",
    "_resolve_artifact_path",
    "_resolve_run_root",
    "_STRUCTURAL_FOCAL_FAMILIES",
    "_parse_focal_x",
    "_parse_json_str_array",
]
