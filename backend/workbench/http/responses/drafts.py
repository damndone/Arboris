"""Pipeline drafts: the editable chain a run is (re)built from.

The stored draft document is validated on write by
``lineage.pipeline_drafts.PipelineDraftV1``; its ``graph`` is declared here,
per node type, because the frontend reads the nodes. A test
keeps the envelope's fields aligned with PipelineDraftV1
(tests/test_response_contracts.py).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired

from pydantic import Field
from typing_extensions import TypedDict

from .system import EditableControlSpec


class UploadRef(TypedDict):
    sha256: str
    filename: str


class UploadDraftNode(TypedDict):
    node_id: str
    node_type: Literal["input.upload"]
    upload: UploadRef
    sheet_names: list[str]
    status: str


class InputDatasetDraftNode(TypedDict):
    node_id: str
    node_type: Literal["input.dataset"]
    source_type: Literal["run_input", "upload"]
    run_input_id: NotRequired[str | None]
    upload_sha: NotRequired[str | None]
    dataset_snapshot_id: NotRequired[str | None]
    schema_fingerprint: str
    input_fingerprint: str
    row_count: NotRequired[int | None]
    column_count: NotRequired[int | None]
    columns_summary: list[dict[str, Any]]
    status: Literal["bound", "missing", "invalid"]


class TableDraftNode(TypedDict):
    node_id: str
    node_type: Literal["table"]
    params: dict[str, Any]
    columns: list[str]
    status: str


class DraftSourceRef(TypedDict):
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str


class ModelDraftNode(TypedDict):
    node_id: str
    node_type: Literal["model"]
    model_family: str
    model_type: str
    schema_id: str
    editable_schema: list[EditableControlSpec]
    editable_schema_hash: NotRequired[str]
    params: dict[str, Any]
    source_ref: NotRequired[DraftSourceRef]
    source_params: NotRequired[dict[str, Any]]
    status: NotRequired[str]


DraftNode = Annotated[
    UploadDraftNode | InputDatasetDraftNode | TableDraftNode | ModelDraftNode,
    Field(discriminator="node_type"),
]


# "from" is a Python keyword, so the edge uses the functional TypedDict form.
DraftEdge = TypedDict("DraftEdge", {"from": str, "to": str})


class DraftGraph(TypedDict):
    nodes: list[DraftNode]
    edges: list[DraftEdge]


class RunCreatedFrom(TypedDict):
    source_type: Literal["run"]
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str
    source_input_fingerprint: str


class GenesisCreatedFrom(TypedDict):
    source_type: Literal["genesis"]
    source_input_fingerprint: str


class PipelineDraft(TypedDict):
    draft_id: str
    schema_version: Literal["pipeline_draft.v1"]
    created_at: str
    updated_at: str
    status: str
    created_from: Annotated[RunCreatedFrom | GenesisCreatedFrom, Field(discriminator="source_type")] | None
    graph: DraftGraph
    default_execution_mode: Literal["rerun_child", "new_run", "genesis"]
    notebook_provenance: NotRequired[dict[str, str] | None]
    exploration_context: NotRequired[dict[str, Any]]


class StoredPipelineDraft(TypedDict):
    draft: PipelineDraft
    draft_hash: str


class PipelineDraftSummary(TypedDict):
    draft_id: str
    status: str
    model_type: str | None
    source_run_id: str | None
    source_model_node_id: str | None
    source_op_node_id: str | None
    source_node_hash: str | None
    draft_hash: str
    updated_at: str | None


class PipelineDraftList(TypedDict):
    drafts: list[PipelineDraftSummary]


class PipelineDraftDeleted(TypedDict):
    ok: Literal[True]
    draft_id: str
    upload_reclaimed: bool


class DraftCheck(TypedDict):
    code: str
    level: Literal["error", "warning", "info"]
    message: str
    blocking: bool
    node_id: NotRequired[str]


class ResolvedExecution(TypedDict):
    execution_mode: NotRequired[Literal["rerun_child", "new_run", "genesis"]]
    compare_source_available: NotRequired[bool]
    genesis: NotRequired[bool]
    rerun_from_run_id: NotRequired[str | None]
    rerun_from_model_node_id: NotRequired[str | None]
    rerun_from_op_node_id: NotRequired[str | None]


class DraftValidation(TypedDict):
    ok: bool
    status: Literal["valid", "invalid", "blocked"]
    executable: bool
    checks: list[DraftCheck]
    resolved_execution: ResolvedExecution
    validated_at: str
    validated_execution_mode: NotRequired[Literal["rerun_child", "new_run", "genesis"]]
    validated_draft_hash: NotRequired[str]


class ExecutionFocus(TypedDict):
    status: str
    run_id: str
    poll: ResolvedExecution


class DraftExecution(TypedDict):
    ok: Literal[True]
    run_id: str
    draft_id: str
    executed_draft_hash: str
    execution_mode: Literal["genesis", "rerun_child"]
    produced_lineage: ResolvedExecution
    focus: ExecutionFocus
    deduped: NotRequired[bool]
