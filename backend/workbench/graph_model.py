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
from enum import Enum
from typing import Any, Literal


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
    """
    is_contestable: bool = True
    assumption_checks_needed: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    review_status: ReviewStatus | None = None

    def __post_init__(self) -> None:
        if self.review_status is None:
            object.__setattr__(
                self, "review_status",
                _derive_review_status(self.assumption_checks_needed),
            )
        _check_contestability_consistency(
            self.assumption_checks_needed,
            self.review_status,  # type: ignore[arg-type]
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
