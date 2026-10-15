"""Manual operation discovery; execution uses the shared operation service."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ..services.operation_catalog import operation_catalog
from .responses.operations import ManualOperationResponse, OperationCatalog
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


class DatasetNodeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["dataset_node"]
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)


class ModelNodeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["model_node"]
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)


class UploadTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["upload"]
    upload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    filename: str = Field(min_length=1)
    sheet_names: list[str] = Field(default_factory=list)


class ManualOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    mode: Literal["preview", "execute", "confirm"] = "preview"
    target: Annotated[DatasetNodeTarget | ModelNodeTarget | UploadTarget, Field(discriminator="kind")] | None = None
    steps: list[dict[str, Any]] | None = None
    preview_id: str | None = None
    fingerprint: str | None = None

    @model_validator(mode="after")
    def check_mode(self):
        if self.mode == "confirm":
            if not self.preview_id or not self.fingerprint or self.target is not None or self.steps is not None:
                raise ValueError("confirm requires preview_id and fingerprint; target and steps come from the server preview")
        elif self.target is None or not self.steps or self.preview_id is not None or self.fingerprint is not None:
            raise ValueError("preview/execute require target and steps; confirmation references are not accepted")
        return self

# Bind existing route declarations, never duplicate their parameter tables.
# Tuple: identity, route module, path, confirmation path, target requirements,
# surface. The surface is where a person operates it in the workbench:
# "graph" (the step's own detail), "data", "table", "notebook",
# "new_analysis" (the new-analysis wizard), "analyze" (the manual operation
# builder) or "agent" (a proposal confirmed in the Agent).
_DEDICATED = (
    ("model.custom", "notebook_routes", "/notebooks/{notebook_id}/options/{option_id}/confirm-and-execute", None,
     ("notebook_option", "admitted_capability_binding", "trusted_execution_gateway"), "notebook"),
    ("graph.fork", "agent_routes", "/agent/fork-proposals", "/agent/sessions/{session_id}/proposals/{proposal_id}/confirm", ("graph_node",), "agent"),
    ("operation.multi_step", "operation_routes", "/operations/run", "/operations/run", ("dataset_or_model_or_upload",), "analyze"),
    ("data.column.cast", "data_operation_routes", "/data-operations/column-cast/preview", "/data-operations/column-cast/confirm", ("dataset_node",), "graph"),
    ("data.columns.cast", "data_operation_routes", "/data-operations/columns-cast/preview", "/data-operations/columns-cast/confirm", ("dataset_node",), "graph"),
    ("code.execute", "data_operation_routes", "/data-operations/code-execute/preview", "/data-operations/code-execute/confirm", ("dataset_node", "risk_authorization"), "graph"),
    ("model.rerun", "rerun_routes", "/runs/{run_id}/rerun", None, ("run", "editable_node",), "graph"),
    ("metadata.edit", "rerun_routes", "/runs/{run_id}/rerun", None, ("run", "editable_node",), "data"),
    ("data.import", "projects_routes", "/uploads", None, ("project",), "new_analysis"),
    ("model.draft", "drafts_routes", "/pipeline-drafts/genesis", None, ("verified_upload",), "new_analysis"),
    ("model.compare", "graph_routes", "/compare-nodes", None, ("model_nodes",), "graph"),
    ("table.export", "runs_routes", "/runs/{run_id}/report/result-table-export", None, ("run",), "table"),
    ("data.export", "runs_routes", "/runs/{run_id}/datasets/export/preview", "/runs/{run_id}/datasets/export", ("dataset_node",), "data"),
    ("script.export", "script_export_routes", "/runs/{run_id}/script-export", None, ("run",), "graph"),
)


def _local_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _local_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_local_refs(item) for item in value]
    if isinstance(value, str) and value.startswith("#/components/schemas/"):
        return value.replace("#/components/schemas/", "#/$defs/", 1)
    return value


@lru_cache(maxsize=1)
def _dedicated_operations() -> tuple[dict[str, Any], ...]:
    declarations = []
    for identity, module_name, path, confirmation_path, targets, surface in _DEDICATED:
        module = import_module(f"workbench.http.{module_name}")
        route = next(item for item in module.router.routes if item.path == path and "POST" in item.methods)
        document = get_openapi(title="Operation", version="1", routes=[route])
        operation = document["paths"][path]["post"]
        content = operation.get("requestBody", {}).get("content", {})
        body_schema = next(iter(content.values()), {}).get("schema", {"type": "object"})
        properties = {"body": _local_refs(body_schema)} if content else {}
        required = ["body"] if operation.get("requestBody", {}).get("required") else []
        for parameter in operation.get("parameters", []):
            key = parameter["name"]
            properties[key] = _local_refs(parameter["schema"])
            if parameter.get("required"):
                required.append(key)
        schema = {"type": "object", "properties": properties, "required": required,
                  "$defs": _local_refs(document.get("components", {}).get("schemas", {}))}
        execution = {"kind": "dedicated", "method": "POST", "path": path, "request_schema": schema, "surface": surface}
        if confirmation_path:
            execution["confirmation_path"] = confirmation_path
        declarations.append({"id": identity, "name": operation.get("summary", identity),
                             "summary": operation.get("description", operation.get("summary", identity)),
                             "execution": execution, "target_requirements": list(targets),
                             "confirmation_policy": "required" if confirmation_path else "endpoint_validation",
                             "declaration_source": f"workbench.http.{module_name}:{route.endpoint.__name__}"})
    return tuple(declarations)


@router.get("/operations")
def get_operations(
    project_root: str | None = None, source_run_id: str | None = None,
    source_node_id: str | None = None, source_artifact_id: str | None = None,
    target: str | None = None,
) -> OperationCatalog:
    """Discover operations; target is the JSON target used by POST /operations/run."""
    requested = None
    if target is not None:
        if any(value is not None for value in (source_run_id, source_node_id, source_artifact_id)):
            raise HTTPException(422, "Use target or source_* fields, not both")
        try:
            requested = TypeAdapter(Annotated[DatasetNodeTarget | ModelNodeTarget | UploadTarget, Field(discriminator="kind")]).validate_json(target).model_dump()
        except ValidationError as exc:
            raise HTTPException(422, "target must be a valid operation target JSON object") from exc
    return operation_catalog(
        project_root=project_root, source_run_id=source_run_id,
        source_node_id=source_node_id, source_artifact_id=source_artifact_id,
        dedicated_operations=_dedicated_operations(), target=requested,
    )


@router.post("/operations/run")
def run_operations(project_root: str, body: ManualOperationRequest) -> ManualOperationResponse:
    from ..services.manual_operations import run_manual_operation

    return run_manual_operation(project_root, body.model_dump())
