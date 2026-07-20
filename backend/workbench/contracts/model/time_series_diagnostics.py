"""Strict contract-only types for Time Series Diagnostics C1.

This module intentionally defines portable input/output contracts only.  It
does not load data, execute statistics, register a model, or expose a runtime
capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from workbench.contracts.common.envelope import ContractError, require_exact_keys


TIME_SERIES_DIAGNOSTICS_CONTRACT_VERSION = "1.0"
OPERATION_REASONS_BY_STATUS = {
    "completed": frozenset({"ASSESSMENT_COMPLETED", "HARD_DATA_INPUT"}),
    "rejected": frozenset({"USER_REJECTED"}),
    "failed": frozenset(
        {
            "EXECUTOR_TIMEOUT",
            "EXECUTOR_OOM",
            "TERMINATED_EXECUTOR",
            "CORRUPT_PACK_OUTPUT",
        }
    ),
    "cancelled": frozenset({"USER_CANCELLED"}),
}
OPERATION_STATUSES = frozenset(OPERATION_REASONS_BY_STATUS)
OPERATION_REASON_CODES = frozenset().union(*OPERATION_REASONS_BY_STATUS.values())

_OPERATION_EXECUTION_ENVELOPE_FIELDS = {
    "operation_status",
    "reason_code",
    "facts_packet_ref",
    "assessment_packet_ref",
}
_TIME_SERIES_DIAGNOSTIC_FACT_FIELDS = {
    "has_hard_input_violation",
    "required_component_unavailable",
    "adf_outcome",
    "kpss_outcome",
    "trend_status",
    "trend_evidence",
    "trend_advisory_preconditions",
}

TIME_SERIES_DIAGNOSTIC_CONCLUSIONS = frozenset(
    {"suitable_with_caveats", "not_suitable", "inconclusive"}
)
NULL_TEST_OUTCOMES = frozenset({"reject", "fail_to_reject", "undetermined"})
TREND_STATUSES = frozenset({"completed", "unavailable", "unknown"})
TREND_EVIDENCE_VALUES = frozenset(
    {"absent", "present", "undetermined", "unavailable"}
)
TREND_ADVISORY_PRECONDITIONS = frozenset({"true", "false", "unknown"})
TIME_SERIES_ADVISORY_CODES = frozenset(
    {"CONSIDER_DIFFERENCING", "REVIEW_TREND_HANDLING"}
)


def _require_packet_ref_or_none(value: Any, field_name: str) -> None:
    if value is not None and (type(value) is not str or not value):
        raise ContractError(f"{field_name} must be a non-empty string or null")


def _require_closed_string(value: Any, allowed: frozenset[str], field_name: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ContractError(f"{field_name} must be a declared value")


@dataclass(frozen=True)
class OperationExecutionEnvelope:
    """A terminal execution fact with completed-only assessment references."""

    operation_status: Literal["rejected", "completed", "failed", "cancelled"]
    reason_code: str
    facts_packet_ref: str | None
    assessment_packet_ref: str | None

    def __post_init__(self) -> None:
        if (
            type(self.operation_status) is not str
            or self.operation_status not in OPERATION_STATUSES
        ):
            raise ContractError(
                "operation_status must be rejected, completed, failed, or cancelled"
            )
        if (
            type(self.reason_code) is not str
            or self.reason_code not in OPERATION_REASON_CODES
        ):
            raise ContractError("reason_code must be a declared operation reason")
        if self.reason_code not in OPERATION_REASONS_BY_STATUS[self.operation_status]:
            raise ContractError("reason_code is not allowed for operation_status")
        _require_packet_ref_or_none(self.facts_packet_ref, "facts_packet_ref")
        _require_packet_ref_or_none(self.assessment_packet_ref, "assessment_packet_ref")

        refs_present = (
            self.facts_packet_ref is not None or self.assessment_packet_ref is not None
        )
        if self.operation_status == "completed":
            if self.facts_packet_ref is None or self.assessment_packet_ref is None:
                raise ContractError("completed requires both packet refs")
        elif refs_present:
            raise ContractError("packet refs require completed")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_status": self.operation_status,
            "reason_code": self.reason_code,
            "facts_packet_ref": self.facts_packet_ref,
            "assessment_packet_ref": self.assessment_packet_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "OperationExecutionEnvelope":
        require_exact_keys(
            value,
            _OPERATION_EXECUTION_ENVELOPE_FIELDS,
            "operation execution envelope",
        )
        return cls(
            operation_status=value["operation_status"],
            reason_code=value["reason_code"],
            facts_packet_ref=value["facts_packet_ref"],
            assessment_packet_ref=value["assessment_packet_ref"],
        )


@dataclass(frozen=True)
class TimeSeriesDiagnosticFacts:
    """Already-normalized D02/D05 facts; never raw data or a runtime request."""

    has_hard_input_violation: bool
    required_component_unavailable: bool
    adf_outcome: Literal["reject", "fail_to_reject", "undetermined"]
    kpss_outcome: Literal["reject", "fail_to_reject", "undetermined"]
    trend_status: Literal["completed", "unavailable", "unknown"]
    trend_evidence: Literal["absent", "present", "undetermined", "unavailable"]
    trend_advisory_preconditions: Literal["true", "false", "unknown"]

    def __post_init__(self) -> None:
        for field_name in (
            "has_hard_input_violation",
            "required_component_unavailable",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ContractError(f"{field_name} must be a bool")
        _require_closed_string(self.adf_outcome, NULL_TEST_OUTCOMES, "adf_outcome")
        _require_closed_string(self.kpss_outcome, NULL_TEST_OUTCOMES, "kpss_outcome")
        _require_closed_string(self.trend_status, TREND_STATUSES, "trend_status")
        _require_closed_string(
            self.trend_evidence,
            TREND_EVIDENCE_VALUES,
            "trend_evidence",
        )
        _require_closed_string(
            self.trend_advisory_preconditions,
            TREND_ADVISORY_PRECONDITIONS,
            "trend_advisory_preconditions",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "has_hard_input_violation": self.has_hard_input_violation,
            "required_component_unavailable": self.required_component_unavailable,
            "adf_outcome": self.adf_outcome,
            "kpss_outcome": self.kpss_outcome,
            "trend_status": self.trend_status,
            "trend_evidence": self.trend_evidence,
            "trend_advisory_preconditions": self.trend_advisory_preconditions,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TimeSeriesDiagnosticFacts":
        require_exact_keys(
            value,
            _TIME_SERIES_DIAGNOSTIC_FACT_FIELDS,
            "time-series diagnostic facts",
        )
        return cls(
            has_hard_input_violation=value["has_hard_input_violation"],
            required_component_unavailable=value["required_component_unavailable"],
            adf_outcome=value["adf_outcome"],
            kpss_outcome=value["kpss_outcome"],
            trend_status=value["trend_status"],
            trend_evidence=value["trend_evidence"],
            trend_advisory_preconditions=value["trend_advisory_preconditions"],
        )


@dataclass(frozen=True)
class TimeSeriesDiagnosticAdvisory:
    """An immutable presentation fact that cannot issue or execute an operation."""

    code: Literal["CONSIDER_DIFFERENCING", "REVIEW_TREND_HANDLING"]
    effect: Literal["advisory_only"]
    execution_available: Literal[False]

    def __post_init__(self) -> None:
        _require_closed_string(self.code, TIME_SERIES_ADVISORY_CODES, "advisory code")
        if self.effect != "advisory_only":
            raise ContractError("advisory effect must be advisory_only")
        if self.execution_available is not False:
            raise ContractError("advisory execution_available must be false")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "effect": self.effect,
            "execution_available": self.execution_available,
        }


@dataclass(frozen=True)
class TimeSeriesDiagnosticAssessment:
    """One conclusion plus advisory-only presentation facts."""

    conclusion: Literal["suitable_with_caveats", "not_suitable", "inconclusive"]
    advisories: tuple[TimeSeriesDiagnosticAdvisory, ...]

    def __post_init__(self) -> None:
        _require_closed_string(
            self.conclusion,
            TIME_SERIES_DIAGNOSTIC_CONCLUSIONS,
            "conclusion",
        )
        if any(
            not isinstance(advisory, TimeSeriesDiagnosticAdvisory)
            for advisory in self.advisories
        ):
            raise ContractError("advisories must contain declared advisory objects")


def _advisory(
    code: Literal["CONSIDER_DIFFERENCING", "REVIEW_TREND_HANDLING"],
) -> TimeSeriesDiagnosticAdvisory:
    return TimeSeriesDiagnosticAdvisory(
        code=code,
        effect="advisory_only",
        execution_available=False,
    )


def derive_assessment(facts: TimeSeriesDiagnosticFacts) -> TimeSeriesDiagnosticAssessment:
    """Derive the D02 conclusion and D05 advice from normalized facts only."""

    if not isinstance(facts, TimeSeriesDiagnosticFacts):
        raise ContractError("facts must be TimeSeriesDiagnosticFacts")
    if facts.has_hard_input_violation:
        return TimeSeriesDiagnosticAssessment("not_suitable", ())
    if (
        facts.required_component_unavailable
        or facts.adf_outcome == "undetermined"
        or facts.kpss_outcome == "undetermined"
    ):
        return TimeSeriesDiagnosticAssessment("inconclusive", ())

    pair = (facts.adf_outcome, facts.kpss_outcome)
    if pair in {
        ("reject", "reject"),
        ("fail_to_reject", "fail_to_reject"),
    }:
        return TimeSeriesDiagnosticAssessment("inconclusive", ())

    advisories: tuple[TimeSeriesDiagnosticAdvisory, ...] = ()
    if (
        pair == ("fail_to_reject", "reject")
        and facts.trend_status == "completed"
        and facts.trend_evidence == "absent"
    ):
        advisories = (_advisory("CONSIDER_DIFFERENCING"),)
    elif (
        facts.trend_status == "completed"
        and facts.trend_evidence in {"present", "undetermined"}
        and facts.trend_advisory_preconditions == "true"
    ):
        advisories = (_advisory("REVIEW_TREND_HANDLING"),)
    return TimeSeriesDiagnosticAssessment("suitable_with_caveats", advisories)
