"""Human-only extension admission. No configuration tool is exposed to the model."""
from typing import Any, Literal
from typing_extensions import TypedDict
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..agent.extensions import ExtensionStore, ExtensionError, validate_manifest
from ..canonical import sha256_canonical
from ..api_errors import WorkbenchAPIError
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


class ExtensionToolView(TypedDict):
    id: str
    version: str
    origin: str
    endpoint: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class ExtensionHookView(TypedDict):
    id: str
    version: str
    origin: str
    event: Literal["before_operation", "after_operation", "turn_end", "plan_approved"]
    operation_ids: list[str]
    action: Literal["record", "deny"]
    reason: str


class ExtensionManifestView(TypedDict):
    schema: Literal["arboris.extensions.v1"]
    tools: list[ExtensionToolView]
    hooks: list[ExtensionHookView]


class ExtensionCatalogView(TypedDict):
    manifest: ExtensionManifestView
    sha256: str | None
    disabled: list[str]


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]


class Admission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]
    expected_sha256: str = Field(max_length=80)
    previous_sha256: str | None = Field(default=None, max_length=80)


class Disable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(max_length=64)
    disabled: bool
    expected_sha256: str = Field(max_length=80)


def _apply(root, function):
    try:
        return function(ExtensionStore(root))
    except (ExtensionError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(status_code=422, code="AGENT_EXTENSION_REFUSED", message=str(exc)[:500]) from exc


@router.get("/projects/agent-extensions")
def view(project_root: str) -> ExtensionCatalogView:
    return _apply(project_root, lambda store: store.view())


@router.put("/projects/agent-extensions")
def admit(project_root: str, body: Admission) -> ExtensionCatalogView:
    return _apply(project_root, lambda store: store.admit(body.manifest, expected_sha256=body.expected_sha256, previous_sha256=body.previous_sha256))


@router.post("/projects/agent-extensions/disable")
def disable(project_root: str, body: Disable) -> ExtensionCatalogView:
    return _apply(project_root, lambda store: store.disable(body.id, body.disabled, expected_sha256=body.expected_sha256))


@router.post("/projects/agent-extensions/review")
def review(project_root: str, body: Review) -> ExtensionCatalogView:
    def inspect(store):
        doc = validate_manifest(body.manifest)
        return {"manifest": doc, "sha256": sha256_canonical(doc), "disabled": []}
    return _apply(project_root, inspect)
