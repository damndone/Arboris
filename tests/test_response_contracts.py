"""The response-type mechanism itself (V1812-OPENAPI-TYPES).

A handler declares its response by return annotation; TypedAPIRoute documents
it in OpenAPI and serves the return value exactly as an untyped route would,
and the test-suite validator rejects missing, mistyped and undeclared fields.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, NotRequired

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient
from typing_extensions import TypedDict

import response_contracts
from response_contracts import ResponseContracts, violations
from workbench.http.typed_routes import MediaType, TypedAPIRoute


class Coefficient(TypedDict):
    term: str
    estimate: float | None


class Model(TypedDict):
    model_id: str
    coefficients: list[Coefficient]
    labels: dict[str, str]
    note: NotRequired[str]


def test_a_complete_body_passes():
    body = {"model_id": "m", "coefficients": [{"term": "x", "estimate": 1.5}], "labels": {"any key": "v"}}
    assert violations(Model, body) == []


def test_missing_mistyped_and_undeclared_fields_are_reported_with_their_paths():
    body = {"coefficients": [{"term": "x", "estimate": "high", "extra": 1}], "labels": {}, "surprise": True}
    found = violations(Model, body)
    assert any(item.startswith("(root):") and "'model_id' is a required property" in item for item in found), found
    assert any(item.startswith("(root):") and "surprise" in item for item in found), found
    assert any(item.startswith("coefficients/0/estimate:") for item in found), found
    assert any(item.startswith("coefficients/0:") and "extra" in item for item in found), found


def test_nan_is_served_as_null_and_must_be_declared_nullable():
    assert violations(Coefficient, {"term": "x", "estimate": None}) == []

    class Strict(TypedDict):
        estimate: float

    assert violations(Strict, {"estimate": None})


def _app() -> FastAPI:
    router = APIRouter(route_class=TypedAPIRoute)

    @router.get("/model")
    def model() -> Model:
        return {"model_id": "m", "coefficients": [{"term": "x", "estimate": math.nan}], "labels": {}, "undeclared": 1}

    @router.get("/untyped")
    def untyped() -> dict[str, Any]:
        return {"p": math.nan, "pair": (1, 2)}

    @router.get("/text")
    def text() -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ResponseContracts)
    return app


def test_a_declared_route_is_documented_but_served_unchanged():
    app = _app()
    client = TestClient(app)
    response_contracts.VIOLATIONS.clear()
    body = client.get("/model").json()
    assert body == {"model_id": "m", "coefficients": [{"term": "x", "estimate": None}], "labels": {}, "undeclared": 1}
    assert any("undeclared" in item for item in response_contracts.VIOLATIONS)
    response_contracts.VIOLATIONS.clear()
    schema = app.openapi()["paths"]["/model"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/Model"
    assert "Coefficient" in app.openapi()["components"]["schemas"]


def test_untyped_and_non_json_routes_are_untouched():
    client = TestClient(_app())
    assert client.get("/untyped").json() == {"p": None, "pair": [1, 2]}
    assert client.get("/text").text == "ok"
    assert response_contracts.VIOLATIONS == []


def test_file_and_stream_responses_document_their_media_type():
    router = APIRouter(route_class=TypedAPIRoute)

    @router.get("/report")
    def report() -> Annotated[FileResponse, MediaType("text/html")]:
        raise AssertionError("not called")

    @router.get("/download")
    def download() -> FileResponse:
        raise AssertionError("not called")

    @router.get("/events")
    def events() -> Annotated[StreamingResponse, MediaType("text/event-stream")]:
        raise AssertionError("not called")

    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]
    assert set(paths["/report"]["get"]["responses"]["200"]["content"]) == {"text/html"}
    download_content = paths["/download"]["get"]["responses"]["200"]["content"]
    assert download_content == {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
    assert set(paths["/events"]["get"]["responses"]["200"]["content"]) == {"text/event-stream"}


def test_the_draft_response_keeps_every_field_the_draft_model_validates():
    # The stored draft is validated on write by PipelineDraftV1; the response
    # type declares its graph in detail, so the two are kept aligned here.
    from workbench.http.responses.drafts import PipelineDraft
    from workbench.lineage.pipeline_drafts import PipelineDraftV1

    assert set(PipelineDraftV1.model_fields) <= set(PipelineDraft.__annotations__)
