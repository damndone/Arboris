"""Typed data operations: column casts, recipes, transforms, code execution.

Specs, previews, effects, proposals, risk grants and operation records are
derived from their domain dataclasses (their JSON form is their fields, with
the adjustments named here: previews flatten their spec in, some records add
a fixed ``record_type``).
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from ...agent.operations import OperationRecord
from ...agent.proposals import ProposalRevision
from ...agent.risk import RiskAuthorization
from ...code_execution import CodeExecutePreview, CodeExecuteSpecV1
from ...data_operations import (
    DataColumnCastPreview,
    DataColumnCastSpecV1,
    DataColumnsCastPreview,
    DataColumnsCastSpecV1,
    DataTransformPreview,
    DataTransformSpecV1,
    FeatureRecipeEffect,
    FeatureRecipeOperationSpecV1,
    FeatureRecipePreview,
)
from ...predictive_research.contracts import FeatureRecipeV1
from .common import view_of

OperationRecordView = view_of(OperationRecord, "OperationRecordView", record_type=Literal["state"])
ProposalRevisionView = view_of(ProposalRevision, "ProposalRevisionView", record_type=Literal["revision"])
RiskAuthorizationView = view_of(
    RiskAuthorization,
    "RiskAuthorizationView",
    omit=("token",),
    record_type=Literal["risk_authorization"],
    token=NotRequired[str],
)

ColumnCastSpecView = view_of(DataColumnCastSpecV1, "ColumnCastSpecView")
ColumnsCastSpecView = view_of(DataColumnsCastSpecV1, "ColumnsCastSpecView")
FeatureRecipeView = view_of(
    FeatureRecipeV1,
    "FeatureRecipeView",
    payload_schema=Literal["workbench.prediction.feature-recipe"],
    schema_version=Literal[1],
)
FeatureRecipeSpecView = view_of(FeatureRecipeOperationSpecV1, "FeatureRecipeSpecView", recipe=FeatureRecipeView)
DataTransformSpecView = view_of(DataTransformSpecV1, "DataTransformSpecView", omit=("operation",), operation_id=str)
CodeExecuteSpecView = view_of(CodeExecuteSpecV1, "CodeExecuteSpecView", code_sha256=str)

ColumnCastPreviewView = view_of(DataColumnCastPreview, "ColumnCastPreviewView", omit=("spec",), inline=(ColumnCastSpecView,))
ColumnsCastPreviewView = view_of(
    DataColumnsCastPreview, "ColumnsCastPreviewView", omit=("spec", "output_format"), inline=(ColumnsCastSpecView,)
)
FeatureRecipePreviewView = view_of(FeatureRecipePreview, "FeatureRecipePreviewView", omit=("spec",), inline=(FeatureRecipeSpecView,))
DataTransformPreviewView = view_of(DataTransformPreview, "DataTransformPreviewView", omit=("spec",), inline=(DataTransformSpecView,))
CodeExecutePreviewView = view_of(CodeExecutePreview, "CodeExecutePreviewView", omit=("spec",), inline=(CodeExecuteSpecView,))
FeatureRecipeEffectView = view_of(FeatureRecipeEffect, "FeatureRecipeEffectView")


class ColumnCastPreviewed(TypedDict):
    spec: ColumnCastSpecView
    preview: ColumnCastPreviewView


class ColumnsCastPreviewed(TypedDict):
    spec: ColumnsCastSpecView
    preview: ColumnsCastPreviewView


class FeatureRecipePreviewed(TypedDict):
    spec: FeatureRecipeSpecView
    preview: FeatureRecipePreviewView


class DataTransformPreviewed(TypedDict):
    spec: DataTransformSpecView
    preview: DataTransformPreviewView


class CodeExecutePreviewed(TypedDict):
    spec: CodeExecuteSpecView
    preview: CodeExecutePreviewView


class OperationConfirmed(TypedDict):
    """A proposal-backed operation: the latest proposal revision, the durable
    operation record, and its status."""

    proposal: ProposalRevisionView
    operation: OperationRecordView
    status: str


class FeatureRecipeApplied(TypedDict):
    status: Literal["completed"]
    effect: FeatureRecipeEffectView
    preview: FeatureRecipePreviewView


class DataTransformApplied(TypedDict):
    status: Literal["completed"]
    effect: FeatureRecipeEffectView
    preview: DataTransformPreviewView


class RiskAuthorized(TypedDict):
    proposal: ProposalRevisionView
    risk_authorization: RiskAuthorizationView
    status: Literal["risk_authorized"]


class ModelRunSourceLineage(TypedDict):
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    source_node_hash: str | None


class ModelRunStarted(TypedDict):
    status: str
    run_id: str
    model_type: str
    source_lineage: ModelRunSourceLineage


class FigureRef(TypedDict):
    artifact_id: str
    path: str | None
    chart_type: str
    sha256: str | None


class FigureSource(TypedDict):
    """The data the figure was drawn from, as a bounded JSON preview."""

    artifact_id: str | None
    path: str | None
    kind: str
    sha256: str | None
    preview_json: str
    preview_truncated: bool


class FigureVisibilityNotice(TypedDict):
    artifact_policy: Literal["metadata_and_safe_preview_only"]
    binary_artifacts_included: Literal[False]
    image_pixels_included: Literal[False]
    max_source_preview_chars: int


class FigureGuardrails(TypedDict):
    advisory_text_only: Literal[True]
    executable_actions_allowed: Literal[False]
    graph_mutations_allowed: Literal[False]
    must_interpret_from_numeric_source: Literal[True]


class FigureAiContext(TypedDict):
    """What the Agent may know about a figure: its numeric source, never pixels.

    ``source`` is null when the figure's source artifact is not available."""

    figure_context_version: Literal["figure-ai-context/v1"]
    run_id: str
    figure: FigureRef
    source: FigureSource | None
    guidance: str
    context_visibility_notice: FigureVisibilityNotice
    response_guardrails: FigureGuardrails


class ColumnDtype(TypedDict):
    name: str
    dtype: str


class ColumnCastContext(TypedDict):
    operation_id: str
    operation_version: str
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    source_artifact_path: str
    source_sha256: str
    row_count: int
    columns: list[ColumnDtype]
    downstream_invalidation: list[str]


class OperationLookup(TypedDict):
    operation: OperationRecordView
