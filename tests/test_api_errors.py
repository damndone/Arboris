from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api_errors import (
    ERROR_RUN_NOT_FOUND,
    WorkbenchAPIError,
    register_error_handlers,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message="Run abc not found",
            details={"run_id": "abc"},
        )

    return app


def test_workbench_api_error_returns_envelope_with_code_message_details():
    client = TestClient(_build_app())

    response = client.get("/boom")

    assert response.status_code == 404
    payload = response.json()
    assert payload == {
        "error": {
            "code": "RUN_NOT_FOUND",
            "message": "Run abc not found",
            "details": {"run_id": "abc"},
        }
    }


def test_workbench_api_error_default_details_is_empty_dict():
    err = WorkbenchAPIError(404, ERROR_RUN_NOT_FOUND, "missing")

    assert err.details == {}
    assert err.code == "RUN_NOT_FOUND"
    assert err.status_code == 404


def test_registry_version_unsupported_has_correct_code():
    from workbench.api_errors import ERROR_REGISTRY_VERSION_UNSUPPORTED

    assert ERROR_REGISTRY_VERSION_UNSUPPORTED == "REGISTRY_VERSION_UNSUPPORTED"
