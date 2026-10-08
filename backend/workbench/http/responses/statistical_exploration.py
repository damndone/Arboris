"""Typed statistical explorations (descriptives, tests) and their OLS context.

An exploration result is a versioned contract (``SCHEMA_VERSION``): every
operation shares its header, and each operation adds its own fields; the
fields the Workbench reads are named here and the rest stay open.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from pydantic import ConfigDict
from typing_extensions import TypedDict

from ...statistical_exploration import ExplorationOperation, FilterOperator
from .drafts import PipelineDraft


class ExplorationFilter(TypedDict):
    column: str
    operator: FilterOperator
    value: Any


class ExplorationSpecView(TypedDict):
    schema_version: str
    operation: ExplorationOperation
    selected_columns: list[str]
    filters: list[ExplorationFilter]
    options: dict[str, Any]
    derived_definitions: list[dict[str, Any]]


class CorrelationPair(TypedDict):
    a: str
    b: str
    r: float | None
    n: int


class ScatterSummary(TypedDict):
    x_column: str
    y_column: str
    plotted_row_count: int


class ExplorationResult(TypedDict):
    """One operation's result: the shared header plus that operation's fields."""

    __pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[misc]
    schema_version: str
    operation: ExplorationOperation
    filters: list[ExplorationFilter]
    source_row_count: int
    filtered_row_count: int
    missing_policy: NotRequired[str]
    group_by: NotRequired[str]
    groups: NotRequired[list[dict[str, Any]]]
    empty_group_values: NotRequired[list[Any]]
    variables: NotRequired[dict[str, Any] | list[str]]
    non_numeric_columns: NotRequired[list[str]]
    quantile_method: NotRequired[str]
    correlation_n: NotRequired[int]
    matrix: NotRequired[list[list[float | None]]]
    pairs: NotRequired[list[CorrelationPair]]
    derived: NotRequired[dict[str, Any]]
    plot: NotRequired[ScatterSummary]


class ExplorationExport(TypedDict):
    format: Literal["html", "pdf", "xlsx"]
    artifact_id: str
    path: str


class DerivedVariable(TypedDict):
    """The dataset a derive_boolean exploration added as a child node."""

    child_node_id: str
    artifact_id: str
    artifact_path: str
    recipe_artifact_id: str
    recipe_path: str
    threshold: float
    output_name: str


class ScatterPlot(TypedDict):
    artifact_id: str
    path: str
    x_column: str
    y_column: str
    plotted_row_count: int
    fingerprint: str


class ExplorationRecord(TypedDict):
    """The durable artifacts one confirmed exploration wrote."""

    artifact_id: str
    path: str
    transcript_artifact_id: str
    transcript_path: str
    fingerprint: str
    source_sha256: str
    exports: list[ExplorationExport]
    derived: NotRequired[DerivedVariable]
    plot: NotRequired[ScatterPlot]


class ExplorationPreviewState(TypedDict):
    status: Literal["ready"]
    fingerprint: str
    source_sha256: str
    source_artifact_id: str
    result: ExplorationResult


class ExplorationPreview(TypedDict):
    spec: ExplorationSpecView
    preview: ExplorationPreviewState


class ExplorationConfirmed(TypedDict):
    status: Literal["completed"]
    exploration: ExplorationRecord
    result: ExplorationResult
    exports: NotRequired[list[ExplorationExport]]
    derived: NotRequired[DerivedVariable]
    plot: NotRequired[ScatterPlot]


class ExplorationOlsContext(TypedDict):
    status: Literal["draft_created"]
    draft: PipelineDraft
    draft_hash: str
    exploration: ExplorationRecord
