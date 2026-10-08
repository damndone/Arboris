"""Dataset nodes of a run: listing, rows, variables, metadata edits, reruns."""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from ...egress import SensitivityLevel
from ...lineage.node_write_validation import AcceptedContext
from .common import MissingRange


class DatasetNode(TypedDict):
    node_id: str
    label: str
    stage: str | None
    parent_stage_id: str | None


class DatasetNodes(TypedDict):
    run_id: str
    datasets: list[DatasetNode]


class DatasetPage(TypedDict):
    run_id: str
    node_id: str
    artifact_id: str
    columns: list[str]
    total_rows: int
    offset: int
    row_numbers: list[int]
    rows: list[dict[str, Any]]


class ValueCount(TypedDict):
    value: Any
    count: int


class DatasetVariable(TypedDict):
    position: int
    name: str
    type: Literal["boolean", "numeric", "date", "string"]
    dtype: str
    missing: int
    declared_missing_matches: int
    unique: int
    variable_label: str | None
    value_labels: dict[str, str]
    measurement_level: str | None
    user_missing_values: list[str | int | float | MissingRange]
    # Present when the project's sharing policy is readable.
    sensitivity: NotRequired[SensitivityLevel]
    sensitivity_source: NotRequired[Literal["project", "suggested"]]
    sensitivity_suggested: NotRequired[SensitivityLevel]
    # Numeric variables only.
    min: NotRequired[int | float | None]
    max: NotRequired[int | float | None]
    mean: NotRequired[float | None]
    # Variables with few distinct values.
    values: NotRequired[list[ValueCount]]


class DatasetVariables(TypedDict):
    run_id: str
    node_id: str
    artifact_id: str
    total_rows: int
    variables: list[DatasetVariable]
    sensitivity_error: str | None


class MetadataRerunSubmitted(TypedDict):
    source_run_id: str
    run_id: str
    status: str


class RerunFrom(TypedDict):
    owner_run_id: str
    op_node_id: str
    node_hash: str | None
    forest_node_key: str | None


class ProducedLineage(TypedDict):
    """Where a rerun's result lands: pending until the child run is indexed."""

    produced_owner_run_id: str
    produced_op_node_id: str | None
    produced_node_hash: str | None
    rerun_request_id: str
    rerun_from: dict[str, Any]
    status: Literal["pending_index", "indexed"]


class RerunSubmitted(TypedDict):
    run_id: str
    new_run_id: str
    new_active_head_id: str
    focus: None  # reserved; no rerun path sets a focus target today
    produced_lineage: ProducedLineage | None
    rerun_from: RerunFrom
    accepted_context: AcceptedContext | None
