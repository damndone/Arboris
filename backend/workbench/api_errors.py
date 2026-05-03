from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ERROR_PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
ERROR_RUN_NOT_FOUND = "RUN_NOT_FOUND"
ERROR_ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
ERROR_REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
ERROR_INVALID_PATH = "INVALID_PATH"
ERROR_REGISTRY_VERSION_UNSUPPORTED = "REGISTRY_VERSION_UNSUPPORTED"
ERROR_REGISTRY_VERSION_INVALID = "REGISTRY_VERSION_INVALID"


class WorkbenchAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(WorkbenchAPIError)
    async def _handle_workbench_error(
        _request: Request, exc: WorkbenchAPIError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
