"""Provider-independent operation discovery contracts."""

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from .common import JsonSchema


class OperationAvailability(TypedDict):
    status: Literal["available", "needs_target", "needs_parameters", "unavailable"]
    reason_code: str
    message: str


class OperationFieldHint(TypedDict):
    control: Literal["text", "number", "checkbox", "select", "list", "object"]
    required: bool


class OperationExecution(TypedDict):
    kind: Literal["workflow", "dedicated", "unavailable"]
    method: str | None
    path: str | None
    confirmation_path: NotRequired[str]
    request_schema: NotRequired[JsonSchema]


class OperationCatalogEntry(TypedDict):
    id: str
    version: str
    category: str
    name: str
    summary: str
    spec_schema: JsonSchema
    field_hints: dict[str, OperationFieldHint]
    target_requirements: list[str]
    confirmation_policy: str
    risk_level: str
    output_schema_ref: str | None
    declaration_source: str
    capability_ids: list[str]
    column_resolver: str | None
    execution: OperationExecution
    availability: OperationAvailability


class OperationCatalog(TypedDict):
    catalog_version: Literal["workbench.operations/v1"]
    total: int
    operations: list[OperationCatalogEntry]


class ManualArtifactRef(TypedDict):
    run_id: str
    artifact_id: str


class ManualNodeRef(TypedDict):
    run_id: str
    node_id: str


class ManualStepStatus(TypedDict):
    step_id: str
    operation_id: str
    spec: dict[str, Any]
    status: str
    artifact_refs: list[ManualArtifactRef]
    node_refs: list[ManualNodeRef]
    row_counts: dict[str, int]
    error: str | None


class ManualOperationResponse(TypedDict):
    request_id: str
    preview_id: str
    fingerprint: str
    revision: int
    status: str
    confirmation_required: bool
    workflow_id: str | None
    operation_record_id: str | None
    target: dict[str, str]
    expected_effect: list[str]
    risks: list[str]
    steps: list[ManualStepStatus]
    error: dict[str, object] | None
