"""Notebook: options planned from a compiled context, their materialization,
authorization, dispatch and results.

Notebooks, option revisions (every contract version), materializations,
executions, the planning context, dispatches and execution authorizations are
derived from their dataclasses. The option revision versions read their wire
format with exact keys, so each version's fields are its wire format; the
adjustments (extra contract metadata, datetimes as text, omitted defaults)
are named here. Trace events and per-option execution records keep their own
versioned shapes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired

from pydantic import Field
from typing_extensions import TypedDict

from ...agent.context_compiler import NotebookPlanningContextV1
from ...agent.notebook.service import ExecutionOutcome
from ...agent.notebook.store import Notebook, WorkflowSource
from ...capability_factory.notebook_bridge import NotebookExecutionDispatch
from ...contracts.agent.notebook_option import (
    ArtifactContract,
    NotebookOptionRevision,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV12,
    NotebookOptionRevisionV13,
    NotebookOptionRevisionV14,
    OptionExecution,
    OptionExecutionV11,
    OptionMaterialization,
    OptionMaterializationV11,
)
from .common import define_view, view_of
from .drafts import PipelineDraft


# to_dict omits source_kind for the default run_artifact.
WorkflowSourceView = define_view(WorkflowSource, source_kind=NotRequired[Literal["dataset_upload"]])


class RunProjectionSource(TypedDict):
    kind: Literal["run"]
    run_id: str | None


class DatasetProjectionSource(TypedDict):
    kind: Literal["dataset"]
    upload_sha256: str | None
    filename: str | None
    sheet_names: list[str]
    workflow_source: NotRequired[WorkflowSourceView]


NotebookView = view_of(
    Notebook,
    "NotebookView",
    omit=("trace_id",),
    record_type=Literal["notebook"],
    projection_source=Annotated[RunProjectionSource | DatasetProjectionSource, Field(discriminator="kind")] | None,
)

ArtifactContractView = view_of(
    ArtifactContract, "ArtifactContractView", checked_dimensions=list[str], not_evaluated_dimensions=list[str]
)
OptionRevisionV10 = view_of(NotebookOptionRevision, "OptionRevisionV10", artifact_contract=ArtifactContractView)
OptionRevisionV11 = view_of(NotebookOptionRevisionV11, "OptionRevisionV11", artifact_contract=ArtifactContractView)
OptionRevisionV12 = view_of(NotebookOptionRevisionV12, "OptionRevisionV12", artifact_contract=ArtifactContractView)
OptionRevisionV13 = view_of(NotebookOptionRevisionV13, "OptionRevisionV13", artifact_contract=ArtifactContractView)
OptionRevisionV14 = view_of(NotebookOptionRevisionV14, "OptionRevisionV14", artifact_contract=ArtifactContractView)
OptionRevision = OptionRevisionV10 | OptionRevisionV11 | OptionRevisionV12 | OptionRevisionV13 | OptionRevisionV14

MaterializationView = view_of(OptionMaterialization, "MaterializationView") | view_of(
    OptionMaterializationV11, "MaterializationV11View"
)
ExecutionView = view_of(OptionExecution, "ExecutionView") | view_of(OptionExecutionV11, "ExecutionV11View")
ExecutionOutcomeView = view_of(ExecutionOutcome, "ExecutionOutcomeView")
DispatchView = view_of(NotebookExecutionDispatch, "DispatchView")
PlanningContextView = view_of(
    NotebookPlanningContextV1,
    "PlanningContextView",
    domain_memory_projection=NotRequired[dict[str, Any]],
    generation_context_hash=str,
    freshness_dependency_fingerprint=str,
    planning_deadline_s=NotRequired[float],
)


class NotebookOptions(TypedDict):
    context: PlanningContextView
    options: list[OptionRevision]
    materializations: dict[str, MaterializationView]
    execution_results: dict[str, dict[str, Any]]
    trace_id: str


class OptionRevalidated(TypedDict):
    context: PlanningContextView
    option: OptionRevision
    trace_id: str


class PlanningCancelled(TypedDict):
    attempt_id: str
    status: Literal["cancelled", "not_active"]


class NotebookTrace(TypedDict):
    trace_id: str
    events: list[dict[str, Any]]


class Materialized(TypedDict):
    materialization: MaterializationView
    draft: PipelineDraft
    draft_hash: str
    trace_id: str


class ExecutionConfirmed(TypedDict):
    execution: ExecutionView
    trace_id: str


class WorkflowConfirmed(TypedDict):
    """A workflow option confirmed and executed in one step."""

    execution: NotRequired[ExecutionView]
    outcome: NotRequired[ExecutionOutcomeView]
    workflow_execution: NotRequired[dict[str, Any]]
    trace_id: str


OptionConfirmed = Materialized | ExecutionConfirmed | WorkflowConfirmed


class Dispatched(TypedDict):
    dispatch: DispatchView
    trace_id: str


OptionDecisionRecorded = OptionRevision


class ExecutionCompleted(ExecutionOutcomeView):  # type: ignore[valid-type,misc]
    trace_id: str


class NotebookProjection(NotebookView):  # type: ignore[valid-type,misc]
    current_family_head_run_id: str | None
