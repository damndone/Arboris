"""Orthogonal public status vocabularies for v1 evidence contracts."""

from __future__ import annotations

from enum import Enum


class ExecutionStatusV1(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class AvailabilityStatusV1(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    NOT_APPLICABLE = "not_applicable"


class CompletenessStatusV1(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    INSUFFICIENT = "insufficient"
    NOT_APPLICABLE = "not_applicable"


class NumericalMethodV1(str, Enum):
    CLOSED_FORM = "closed_form"
    DETERMINISTIC_NUMERIC = "deterministic_numeric"
    SIMULATION = "simulation"
    APPROXIMATE_ALGORITHM = "approximate_algorithm"


class InferenceBasisV1(str, Enum):
    EXACT_DISTRIBUTION = "exact_distribution"
    ASYMPTOTIC = "asymptotic"
    BOOTSTRAP = "bootstrap"
    DESCRIPTIVE = "descriptive"
    NOT_APPLICABLE = "not_applicable"


class EvaluationDesignV1(str, Enum):
    IN_SAMPLE = "in_sample"
    HOLDOUT = "holdout"
    CROSS_VALIDATION = "cross_validation"
    NESTED_CROSS_VALIDATION = "nested_cross_validation"
    CROSS_FITTING = "cross_fitting"
    BOOTSTRAP = "bootstrap"
    NOT_APPLICABLE = "not_applicable"


class ValidationLevelV1(str, Enum):
    NONE = "none"
    SAME_LIBRARY_REGRESSION = "same_library_regression"
    KNOWN_ANSWER = "known_answer"
    INDEPENDENT_IMPLEMENTATION = "independent_implementation"
    REFERENCE_SOFTWARE = "reference_software"


class ValidationRequirementStatusV1(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    NOT_APPLICABLE = "not_applicable"


class TransactionStatusV1(str, Enum):
    COMMITTED = "committed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


_VALIDATION_LEVEL_RANK = {
    ValidationLevelV1.NONE: 0,
    ValidationLevelV1.SAME_LIBRARY_REGRESSION: 1,
    ValidationLevelV1.KNOWN_ANSWER: 2,
    ValidationLevelV1.INDEPENDENT_IMPLEMENTATION: 3,
    ValidationLevelV1.REFERENCE_SOFTWARE: 4,
}


def validation_level_rank(level: ValidationLevelV1) -> int:
    """Return the locked weakest-to-strongest validation rank."""

    if type(level) is not ValidationLevelV1:
        raise TypeError("level must be ValidationLevelV1")
    return _VALIDATION_LEVEL_RANK[level]


__all__ = [
    "AvailabilityStatusV1",
    "CompletenessStatusV1",
    "EvaluationDesignV1",
    "ExecutionStatusV1",
    "InferenceBasisV1",
    "NumericalMethodV1",
    "TransactionStatusV1",
    "ValidationLevelV1",
    "ValidationRequirementStatusV1",
    "validation_level_rank",
]
