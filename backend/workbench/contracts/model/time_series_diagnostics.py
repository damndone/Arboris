"""Strict contract-only types for Time Series Diagnostics C1.

This module intentionally defines portable input/output contracts only.  It
does not load data, execute statistics, register a model, or expose a runtime
capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


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

GRID_REGULARITIES = frozenset({"exact_regular", "irregular", "undetermined"})
GRID_BASES = frozenset(
    {
        "contiguous_integer_step",
        "exact_fixed_duration_step",
        "declared_calendar_frequency",
        "none",
    }
)
SEMANTIC_FREQUENCY_SOURCES = frozenset(
    {"user_confirmed", "artifact_metadata", "none"}
)
SEASONAL_CANDIDATE_PERIOD_SOURCES = SEMANTIC_FREQUENCY_SOURCES
SEASONAL_CANDIDATE_PERIOD_UNITS = frozenset({"lag_steps"})
ADF_P_VALUE_STATUSES = frozenset({"approximate", "unavailable"})
KPSS_P_VALUE_STATUSES = frozenset(
    {"approximate", "lower_bound", "upper_bound", "unavailable"}
)
LAG_ZERO_POLICIES = frozenset({"included"})
ACF_METHODS = frozenset({"standard"})
PACF_METHODS = frozenset({"ywm"})

_TIME_SERIES_DIAGNOSTIC_PROPOSAL_FIELDS = {
    "grid_regularity",
    "grid_basis",
    "semantic_frequency_source",
    "usable_observation_count",
    "seasonal_candidate_period",
}
_SEASONAL_CANDIDATE_PERIOD_FIELDS = {"value", "unit", "source"}
_ADF_FACT_FIELDS = {"p_value_status"}
_KPSS_FACT_FIELDS = {"p_value_status"}
_ACF_POLICY_FIELDS = {"method", "lag_zero", "confidence_level"}
_PACF_POLICY_FIELDS = {"method", "lag_zero", "confidence_level"}


def _require_packet_ref_or_none(value: Any, field_name: str) -> None:
    if value is not None and (type(value) is not str or not value):
        raise ContractError(f"{field_name} must be a non-empty string or null")


def _require_closed_string(value: Any, allowed: frozenset[str], field_name: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ContractError(f"{field_name} must be a declared value")


def _require_positive_int(value: Any, field_name: str) -> None:
    if type(value) is not int or value < 1:
        raise ContractError(f"{field_name} must be a positive integer")


def _require_confidence_level(value: Any) -> None:
    if type(value) is not float or not 0.0 < value < 1.0:
        raise ContractError("confidence_level must be a float between 0 and 1")


def _parse_seasonal_candidate_period(
    value: Any, usable_observation_count: int
) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContractError("seasonal_candidate_period must be a mapping or null")
    require_exact_keys(
        value,
        _SEASONAL_CANDIDATE_PERIOD_FIELDS,
        "seasonal candidate period",
    )
    period_value = value["value"]
    if (
        type(period_value) is not int
        or period_value < 2
        or period_value >= usable_observation_count
    ):
        raise ContractError(
            "seasonal_candidate_period.value must be an integer >= 2 and "
            "less than usable_observation_count"
        )
    _require_closed_string(
        value["unit"], SEASONAL_CANDIDATE_PERIOD_UNITS, "seasonal_candidate_period.unit"
    )
    _require_closed_string(
        value["source"],
        SEASONAL_CANDIDATE_PERIOD_SOURCES,
        "seasonal_candidate_period.source",
    )
    return freeze_json(dict(value), "seasonal_candidate_period")


@dataclass(frozen=True)
class TimeSeriesDiagnosticProposal:
    """Normalized time-grid and user/artifact seasonal declarations only."""

    grid_regularity: Literal["exact_regular", "irregular", "undetermined"]
    grid_basis: Literal[
        "contiguous_integer_step",
        "exact_fixed_duration_step",
        "declared_calendar_frequency",
        "none",
    ]
    semantic_frequency_source: Literal["user_confirmed", "artifact_metadata", "none"]
    usable_observation_count: int
    seasonal_candidate_period: Mapping[str, object] | None

    def __post_init__(self) -> None:
        _require_closed_string(
            self.grid_regularity, GRID_REGULARITIES, "grid_regularity"
        )
        _require_closed_string(self.grid_basis, GRID_BASES, "grid_basis")
        _require_closed_string(
            self.semantic_frequency_source,
            SEMANTIC_FREQUENCY_SOURCES,
            "semantic_frequency_source",
        )
        _require_positive_int(
            self.usable_observation_count, "usable_observation_count"
        )
        candidate = _parse_seasonal_candidate_period(
            self.seasonal_candidate_period, self.usable_observation_count
        )
        object.__setattr__(self, "seasonal_candidate_period", candidate)

    def to_dict(self) -> dict[str, object]:
        return {
            "grid_regularity": self.grid_regularity,
            "grid_basis": self.grid_basis,
            "semantic_frequency_source": self.semantic_frequency_source,
            "usable_observation_count": self.usable_observation_count,
            "seasonal_candidate_period": thaw_json(self.seasonal_candidate_period),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TimeSeriesDiagnosticProposal":
        require_exact_keys(
            value,
            _TIME_SERIES_DIAGNOSTIC_PROPOSAL_FIELDS,
            "time-series diagnostic proposal",
        )
        return cls(
            grid_regularity=value["grid_regularity"],
            grid_basis=value["grid_basis"],
            semantic_frequency_source=value["semantic_frequency_source"],
            usable_observation_count=value["usable_observation_count"],
            seasonal_candidate_period=value["seasonal_candidate_period"],
        )


@dataclass(frozen=True)
class AdfFact:
    """Normalized ADF p-value provenance; no ADF calculation is performed."""

    p_value_status: Literal["approximate", "unavailable"]

    def __post_init__(self) -> None:
        _require_closed_string(
            self.p_value_status, ADF_P_VALUE_STATUSES, "ADF p_value_status"
        )

    def to_dict(self) -> dict[str, object]:
        return {"p_value_status": self.p_value_status}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AdfFact":
        require_exact_keys(value, _ADF_FACT_FIELDS, "ADF fact")
        return cls(p_value_status=value["p_value_status"])


@dataclass(frozen=True)
class KpssFact:
    """Normalized KPSS p-value provenance; no KPSS calculation is performed."""

    p_value_status: Literal[
        "approximate", "lower_bound", "upper_bound", "unavailable"
    ]

    def __post_init__(self) -> None:
        _require_closed_string(
            self.p_value_status, KPSS_P_VALUE_STATUSES, "KPSS p_value_status"
        )

    def to_dict(self) -> dict[str, object]:
        return {"p_value_status": self.p_value_status}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "KpssFact":
        require_exact_keys(value, _KPSS_FACT_FIELDS, "KPSS fact")
        return cls(p_value_status=value["p_value_status"])


@dataclass(frozen=True)
class AcfPolicy:
    """Declared ACF presentation policy, not an autocorrelation calculator."""

    method: Literal["standard"]
    lag_zero: Literal["included"]
    confidence_level: float

    def __post_init__(self) -> None:
        _require_closed_string(self.method, ACF_METHODS, "ACF method")
        _require_closed_string(self.lag_zero, LAG_ZERO_POLICIES, "ACF lag_zero")
        _require_confidence_level(self.confidence_level)

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "lag_zero": self.lag_zero,
            "confidence_level": self.confidence_level,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AcfPolicy":
        require_exact_keys(value, _ACF_POLICY_FIELDS, "ACF policy")
        return cls(
            method=value["method"],
            lag_zero=value["lag_zero"],
            confidence_level=value["confidence_level"],
        )


@dataclass(frozen=True)
class PacfPolicy:
    """Declared PACF presentation policy, not a partial-autocorrelation calculator."""

    method: Literal["ywm"]
    lag_zero: Literal["included"]
    confidence_level: float

    def __post_init__(self) -> None:
        _require_closed_string(self.method, PACF_METHODS, "PACF method")
        _require_closed_string(self.lag_zero, LAG_ZERO_POLICIES, "PACF lag_zero")
        _require_confidence_level(self.confidence_level)

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "lag_zero": self.lag_zero,
            "confidence_level": self.confidence_level,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PacfPolicy":
        require_exact_keys(value, _PACF_POLICY_FIELDS, "PACF policy")
        return cls(
            method=value["method"],
            lag_zero=value["lag_zero"],
            confidence_level=value["confidence_level"],
        )


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
