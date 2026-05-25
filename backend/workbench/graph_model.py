"""V1.4 lineage graph data model.

DESIGN INVARIANTS (do not violate without a major-version bump):
- All fields are JSON-serializable (str / int / float / bool / None / list / dict / tuple).
- `decision_id` is permanent. To rename: keep old + add to `decision_id_alias`.
- `candidates` may only grow over versions. Deprecated values stay in the tuple.
- `DecisionSource`, `ReasonType`, `ReviewStatus` enums may only grow.
- `chosen_params_schema` version numbers strictly increase; never reused.

Migration anticipated: post-V1.5, types here may move to Pydantic BaseModel.
Validation/derivation logic lives in module-level pure functions so they can
be reused as Pydantic @model_validator callbacks. See §3.1 of the V1.4 spec.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Literal


SCHEMA_VERSION = 3


class NodeKind(str, Enum):
    DATASET_STAGE = "dataset_stage"
    VARIABLE = "variable"
    OPERATION = "operation"
    MODEL = "model"
    TEST = "test"
    PLOT = "plot"
    REPORT = "report"


class Trust(str, Enum):
    OK = "ok"
    CAUTION = "caution"
    WARNING = "warning"
    BLOCKER = "blocker"


class Stage(StrEnum):
    SOURCE = "source"
    EDA = "eda"
    CLEAN = "clean"
    TRANSFORM = "transform"
    MODEL = "model"
    DIAG = "diag"
    VIZ = "viz"
    REPORT = "report"


DecisionSource = Literal[
    "user_explicit",
    "system_default",
    "data_driven_default",
    "fallback",
    "compatibility_constraint",
]

ReasonType = Literal[
    "system_default",
    "data_driven_default",
    "user_config",
    "fallback",
    "compatibility_constraint",
]

ReviewStatus = Literal[
    "not_needed",
    "needed",
    "passed",
    "failed",
    "waived",
    "unknown",
]


def _derive_review_status(checks_needed: tuple[str, ...]) -> ReviewStatus:
    """Pure function — reusable when migrating to Pydantic @model_validator."""
    return "needed" if checks_needed else "not_needed"


def _check_contestability_consistency(
    checks_needed: tuple[str, ...],
    review_status: ReviewStatus,
) -> None:
    """Warn (don't raise) on suspicious combinations."""
    if not checks_needed and review_status == "needed":
        warnings.warn(
            "Contestability: review_status='needed' but assumption_checks_needed is empty. "
            "Did you mean 'not_needed'?",
            UserWarning,
            stacklevel=3,
        )
    if checks_needed and review_status == "not_needed":
        warnings.warn(
            f"Contestability: review_status='not_needed' but assumption_checks_needed={checks_needed!r}. "
            "Did you mean 'needed'? (If a human waived, use 'waived' instead.)",
            UserWarning,
            stacklevel=3,
        )


@dataclass(frozen=True)
class Contestability:
    """Whether and how a decision can be challenged later.

    `assumption_checks_needed` semantics: lists checks that, if implemented and
    passed, would justify this default. Does NOT mean checks have been run —
    see `review_status` for that.

    Construction: prefer `Contestability.derive(...)` for the common case where
    `review_status` follows from `assumption_checks_needed`. Direct construction
    requires an explicit `review_status` value.
    """
    is_contestable: bool = True
    assumption_checks_needed: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    review_status: ReviewStatus = "not_needed"

    def __post_init__(self) -> None:
        _check_contestability_consistency(
            self.assumption_checks_needed,
            self.review_status,
        )

    @classmethod
    def derive(
        cls,
        *,
        is_contestable: bool = True,
        assumption_checks_needed: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        review_status: ReviewStatus | None = None,
    ) -> "Contestability":
        """Construct with `review_status` derived from `assumption_checks_needed`
        when not given explicitly."""
        if review_status is None:
            review_status = _derive_review_status(assumption_checks_needed)
        return cls(
            is_contestable=is_contestable,
            assumption_checks_needed=assumption_checks_needed,
            warnings=warnings,
            review_status=review_status,
        )


@dataclass(frozen=True)
class AutoChosenReason:
    """Why an auto choice was made + its parameters.

    `chosen_params` values must be JSON-serializable; GraphStore enforces this
    at write time. Do NOT embed DataFrames, fitted model objects, callables,
    or class instances.

    `chosen_params_schema`: when a params shape stabilizes, the versioned
    schema name (e.g. "MissingValueStrategy.v1") is recorded so consumers
    can dispatch on it. None means free-form params.
    """
    reason_type: ReasonType
    explanation: str | None = None
    chosen_params_schema: str | None = None
    chosen_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionPoint:
    """Audit trail entry on a graph node. Records what was selected from what set.

    See module docstring for schema evolution rules.
    """
    decision_id: str
    decision_id_alias: tuple[str, ...] = ()
    selected: Any = None
    candidates: tuple[Any, ...] = ()
    source: DecisionSource = "system_default"
    contestability: Contestability = field(default_factory=Contestability)
    reason: AutoChosenReason | None = None


@dataclass(frozen=True)
class Node:
    """A vertex in the lineage graph."""
    id: str
    kind: NodeKind
    display_label: str
    created_at: str  # ISO 8601 UTC
    parent_stage_id: str | None
    branch_id: str
    trust: Trust = Trust.OK
    trust_reason: str | None = None
    archived: bool = False
    payload_ref: str | None = None  # path relative to run root
    decision_points: tuple[DecisionPoint, ...] = ()
    summary: str | None = None
    annotations: tuple = ()  # reserved for V1.6 AI; tuple of Annotation
    stage: Stage | None = None


@dataclass(frozen=True)
class Edge:
    """A directed edge in the lineage graph."""
    id: str
    source_id: str
    target_id: str
    op: str
    params: dict[str, Any] = field(default_factory=dict)
    reversible: bool = False
    inverse_op: str | None = None


@dataclass(frozen=True)
class BranchRef:
    """A named branch within a run's lineage graph."""
    id: str
    forked_from_node_id: str | None
    head_node_ids: tuple[str, ...] = ()
    archived: bool = False


@dataclass(frozen=True)
class Graph:
    """The full lineage graph for one run."""
    schema_version: int
    run_id: str
    nodes: dict[str, Node]
    edges: dict[str, Edge]
    branches: dict[str, BranchRef]
    legacy: bool = False


def resolve_decision_id(graph: Graph, id_or_alias: str) -> str | None:
    """Return the canonical decision_id for a given id or alias.

    Honors the rename invariant: when a decision_id is renamed, the old name
    is added to `decision_id_alias`. Consumers should resolve through this
    function rather than matching `decision_id` directly.

    V1.4.1: iterates the decision_points tuple per node.
    """
    for node in graph.nodes.values():
        for dp in node.decision_points:
            if dp.decision_id == id_or_alias or id_or_alias in dp.decision_id_alias:
                return dp.decision_id
    return None


__all__ = [
    "AutoChosenReason",
    "BranchRef",
    "Contestability",
    "DecisionPoint",
    "DecisionSource",
    "Edge",
    "Graph",
    "Node",
    "NodeKind",
    "ReasonType",
    "ReviewStatus",
    "SCHEMA_VERSION",
    "Stage",
    "Trust",
    "resolve_decision_id",
]
