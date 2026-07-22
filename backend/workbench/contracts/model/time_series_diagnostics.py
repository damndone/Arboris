"""Strict contract-only types for Time Series Diagnostics C1.

This module intentionally defines portable input/output contracts only.  It
does not load data, execute statistics, register a model, or expose a runtime
capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal

from workbench.canonical import CanonicalJSONError, sha256_canonical
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

FACTS_PACKET_CONTRACT = "time_series_diagnostics.facts"
ASSESSMENT_PACKET_CONTRACT = "time_series_diagnostics.assessment"
ASSESSMENT_SCOPE = "first_slice_diagnostic_evidence"

TIME_SERIES_CAVEAT_CODES = frozenset(
    {
        "RAW_LEVEL_CORRELATION_ONLY",
        "NO_MODEL_ORDER_INFERENCE",
        "LEVEL_STATIONARITY_ONLY",
        "NO_FORECAST_ELIGIBILITY",
        "NO_MODEL_SELECTION",
        "STRUCTURAL_BREAKS_NOT_ASSESSED",
    }
)
TIME_SERIES_PACKET_REASON_CODES = frozenset(
    {
        "TIME_VALUE_MISSING",
        "TIME_PARSE_FAILED",
        "IRREGULAR_SPACING",
        "EXPECTED_TIME_POINT_ABSENT",
        "FREQUENCY_DECLARATION_MISMATCH",
        "TREND_NOT_ASSESSED",
        "NO_DECLARED_CANDIDATE_PERIOD",
        *TIME_SERIES_CAVEAT_CODES,
        *TIME_SERIES_ADVISORY_CODES,
        *OPERATION_REASON_CODES,
        "UNSUPPORTED_DEPENDENCY_MANIFEST",
    }
)

_FACTS_PACKET_FIELDS = {
    "contract",
    "contract_version",
    "packet_id",
    "producer_version",
    "policy_version",
    "run_id",
    "execution_timestamp",
    "input_identity",
    "configuration",
    "numeric_runtime_manifest_digest",
    "facts",
    "facts_content_digest",
}
_ASSESSMENT_PACKET_FIELDS = {
    "contract",
    "contract_version",
    "packet_id",
    "producer_version",
    "run_id",
    "execution_timestamp",
    "facts_packet_id",
    "facts_content_digest",
    "decision_policy_version",
    "assessment_scope",
    "conclusion",
    "caveat_codes",
    "caveat_fact_refs",
    "advisories",
    "assessment_content_digest",
}
_ADVISORY_FIELDS = {
    "advisory_code",
    "advisory_version",
    "evidence_fact_refs",
    "precondition_results",
    "source_facts_content_digest",
    "decision_policy_version",
    "effects_summary",
    "incompatibility_codes",
    "input_identity",
    "effect",
    "execution_available",
}
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FACT_PATH_PATTERN = re.compile(r"^facts(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)

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


def _require_non_empty_packet_string(value: Any, field_name: str) -> None:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")


def _require_digest(value: Any, field_name: str) -> None:
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_utc_timestamp(value: Any) -> None:
    if type(value) is not str or _UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ContractError(
            "execution_timestamp must be an RFC 3339 UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError("execution_timestamp must be a valid UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ContractError("execution_timestamp must be a UTC timestamp")


def _freeze_required_mapping(value: Any, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field_name} must be a mapping")
    frozen = freeze_json(value, field_name)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded above
        raise ContractError(f"{field_name} must be a mapping")
    return frozen


def _normalize_fact_refs(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{field_name} must be an array")
    refs: list[str] = []
    for ref in value:
        if type(ref) is not str or _FACT_PATH_PATTERN.fullmatch(ref) is None:
            raise ContractError(f"{field_name} contains a malformed fact reference")
        refs.append(ref)
    return tuple(sorted(refs))


def _normalize_closed_codes(
    value: Any, allowed: frozenset[str], field_name: str
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{field_name} must be an array")
    codes: list[str] = []
    for code in value:
        _require_closed_string(code, allowed, field_name)
        codes.append(code)
    if len(set(codes)) != len(codes):
        raise ContractError(f"{field_name} must not contain duplicates")
    return tuple(sorted(codes))


def _normalize_advisory(
    value: Any, *, facts_content_digest_value: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError("advisory must be a mapping")
    require_exact_keys(value, _ADVISORY_FIELDS, "advisory")
    _require_closed_string(value["advisory_code"], TIME_SERIES_ADVISORY_CODES, "advisory_code")
    _require_non_empty_packet_string(value["advisory_version"], "advisory_version")
    evidence_refs = _normalize_fact_refs(value["evidence_fact_refs"], "evidence_fact_refs")
    preconditions = _freeze_required_mapping(
        value["precondition_results"], "precondition_results"
    )
    for name, result in preconditions.items():
        if (
            type(name) is not str
            or type(result) is not str
            or result not in TREND_ADVISORY_PRECONDITIONS
        ):
            raise ContractError("precondition_results values must be true, false, or unknown")
    if any(result != "true" for result in preconditions.values()):
        raise ContractError("advisory preconditions must all be true")
    _require_digest(value["source_facts_content_digest"], "source_facts_content_digest")
    if value["source_facts_content_digest"] != facts_content_digest_value:
        raise ContractError("advisory source_facts_content_digest does not match Facts")
    _require_non_empty_packet_string(
        value["decision_policy_version"], "decision_policy_version"
    )
    effects_summary = freeze_json(value["effects_summary"], "effects_summary")
    incompatibility_codes = _normalize_closed_codes(
        value["incompatibility_codes"],
        TIME_SERIES_PACKET_REASON_CODES,
        "incompatibility_codes",
    )
    input_identity = _freeze_required_mapping(value["input_identity"], "input_identity")
    if value["effect"] != "advisory_only":
        raise ContractError("advisory effect must be advisory_only")
    if value["execution_available"] is not False:
        raise ContractError("advisory execution_available must be false")
    return freeze_json(
        {
            "advisory_code": value["advisory_code"],
            "advisory_version": value["advisory_version"],
            "evidence_fact_refs": list(evidence_refs),
            "precondition_results": preconditions,
            "source_facts_content_digest": value["source_facts_content_digest"],
            "decision_policy_version": value["decision_policy_version"],
            "effects_summary": effects_summary,
            "incompatibility_codes": list(incompatibility_codes),
            "input_identity": input_identity,
            "effect": value["effect"],
            "execution_available": value["execution_available"],
        },
        "advisory",
    )


def _facts_projection_from_normalized(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: thaw_json(value[key])
        for key in (
            "contract",
            "contract_version",
            "producer_version",
            "policy_version",
            "input_identity",
            "configuration",
            "numeric_runtime_manifest_digest",
            "facts",
        )
    }


def _packet_canonical_digest(value: Any, packet_name: str) -> str:
    try:
        return sha256_canonical(value)
    except CanonicalJSONError as exc:
        raise ContractError(f"{packet_name} contains invalid canonical JSON") from exc


def _normalize_facts_packet(
    value: Mapping[str, object], *, verify_digest: bool
) -> dict[str, object]:
    require_exact_keys(value, _FACTS_PACKET_FIELDS, "facts packet")
    if value["contract"] != FACTS_PACKET_CONTRACT:
        raise ContractError("facts packet contract is not declared")
    if value["contract_version"] != TIME_SERIES_DIAGNOSTICS_CONTRACT_VERSION:
        raise ContractError("facts packet contract_version is not declared")
    for field_name in ("packet_id", "producer_version", "policy_version", "run_id"):
        _require_non_empty_packet_string(value[field_name], field_name)
    _require_utc_timestamp(value["execution_timestamp"])
    input_identity = _freeze_required_mapping(value["input_identity"], "input_identity")
    configuration = _freeze_required_mapping(value["configuration"], "configuration")
    facts = _freeze_required_mapping(value["facts"], "facts")
    _require_digest(
        value["numeric_runtime_manifest_digest"],
        "numeric_runtime_manifest_digest",
    )
    _require_digest(value["facts_content_digest"], "facts_content_digest")
    normalized = {
        "contract": value["contract"],
        "contract_version": value["contract_version"],
        "packet_id": value["packet_id"],
        "producer_version": value["producer_version"],
        "policy_version": value["policy_version"],
        "run_id": value["run_id"],
        "execution_timestamp": value["execution_timestamp"],
        "input_identity": input_identity,
        "configuration": configuration,
        "numeric_runtime_manifest_digest": value["numeric_runtime_manifest_digest"],
        "facts": facts,
        "facts_content_digest": value["facts_content_digest"],
    }
    if verify_digest:
        expected_digest = _packet_canonical_digest(
            _facts_projection_from_normalized(normalized), "facts packet"
        )
        if value["facts_content_digest"] != expected_digest:
            raise ContractError("facts_content_digest does not match Facts content")
    return normalized


@dataclass(frozen=True)
class TimeSeriesDiagnosticFactsPacket:
    """Strict, immutable D06 Facts packet; this type performs no diagnostics."""

    contract: str
    contract_version: str
    packet_id: str
    producer_version: str
    policy_version: str
    run_id: str
    execution_timestamp: str
    input_identity: Mapping[str, object]
    configuration: Mapping[str, object]
    numeric_runtime_manifest_digest: str
    facts: Mapping[str, object]
    facts_content_digest: str

    def __post_init__(self) -> None:
        normalized = _normalize_facts_packet(self.to_dict(), verify_digest=True)
        for field_name, field_value in normalized.items():
            object.__setattr__(self, field_name, field_value)

    def to_dict(self) -> dict[str, object]:
        return {
            field_name: thaw_json(getattr(self, field_name))
            for field_name in _FACTS_PACKET_FIELDS
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TimeSeriesDiagnosticFactsPacket":
        normalized = _normalize_facts_packet(value, verify_digest=False)
        return cls(**normalized)


def facts_content_projection(packet: Mapping[str, object] | TimeSeriesDiagnosticFactsPacket) -> dict[str, object]:
    value = packet.to_dict() if isinstance(packet, TimeSeriesDiagnosticFactsPacket) else packet
    normalized = _normalize_facts_packet(value, verify_digest=False)
    return _facts_projection_from_normalized(normalized)


def facts_content_digest(packet: Mapping[str, object] | TimeSeriesDiagnosticFactsPacket) -> str:
    return _packet_canonical_digest(facts_content_projection(packet), "facts packet")


def _assessment_projection_from_normalized(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: thaw_json(value[key])
        for key in (
            "facts_content_digest",
            "decision_policy_version",
            "assessment_scope",
            "conclusion",
            "caveat_codes",
            "caveat_fact_refs",
            "advisories",
        )
    }


def _normalize_assessment_packet(
    value: Mapping[str, object], *, verify_digest: bool
) -> dict[str, object]:
    require_exact_keys(value, _ASSESSMENT_PACKET_FIELDS, "assessment packet")
    if value["contract"] != ASSESSMENT_PACKET_CONTRACT:
        raise ContractError("assessment packet contract is not declared")
    if value["contract_version"] != TIME_SERIES_DIAGNOSTICS_CONTRACT_VERSION:
        raise ContractError("assessment packet contract_version is not declared")
    for field_name in (
        "packet_id",
        "producer_version",
        "run_id",
        "facts_packet_id",
        "decision_policy_version",
    ):
        _require_non_empty_packet_string(value[field_name], field_name)
    _require_utc_timestamp(value["execution_timestamp"])
    _require_digest(value["facts_content_digest"], "facts_content_digest")
    if value["assessment_scope"] != ASSESSMENT_SCOPE:
        raise ContractError("assessment_scope is not declared")
    _require_closed_string(value["conclusion"], TIME_SERIES_DIAGNOSTIC_CONCLUSIONS, "conclusion")
    caveat_codes = _normalize_closed_codes(
        value["caveat_codes"], TIME_SERIES_CAVEAT_CODES, "caveat_codes"
    )
    caveat_fact_refs = _normalize_fact_refs(value["caveat_fact_refs"], "caveat_fact_refs")
    if not isinstance(value["advisories"], (list, tuple)):
        raise ContractError("advisories must be an array")
    advisories = tuple(
        _normalize_advisory(
            advisory,
            facts_content_digest_value=value["facts_content_digest"],
        )
        for advisory in value["advisories"]
    )
    advisory_keys = [
        (advisory["advisory_code"], advisory["advisory_version"])
        for advisory in advisories
    ]
    if len(set(advisory_keys)) != len(advisory_keys):
        raise ContractError("advisories must not contain duplicate identities")
    advisories = tuple(sorted(advisories, key=lambda item: (item["advisory_code"], item["advisory_version"])))
    _require_digest(value["assessment_content_digest"], "assessment_content_digest")
    normalized = {
        "contract": value["contract"],
        "contract_version": value["contract_version"],
        "packet_id": value["packet_id"],
        "producer_version": value["producer_version"],
        "run_id": value["run_id"],
        "execution_timestamp": value["execution_timestamp"],
        "facts_packet_id": value["facts_packet_id"],
        "facts_content_digest": value["facts_content_digest"],
        "decision_policy_version": value["decision_policy_version"],
        "assessment_scope": value["assessment_scope"],
        "conclusion": value["conclusion"],
        "caveat_codes": list(caveat_codes),
        "caveat_fact_refs": list(caveat_fact_refs),
        "advisories": list(advisories),
        "assessment_content_digest": value["assessment_content_digest"],
    }
    normalized = dict(freeze_json(normalized, "assessment packet"))
    if verify_digest:
        expected_digest = _packet_canonical_digest(
            _assessment_projection_from_normalized(normalized), "assessment packet"
        )
        if value["assessment_content_digest"] != expected_digest:
            raise ContractError("assessment_content_digest does not match Assessment content")
    return normalized


@dataclass(frozen=True)
class TimeSeriesDiagnosticAssessmentPacket:
    """Strict, immutable D06 Assessment packet derived from Facts identity."""

    contract: str
    contract_version: str
    packet_id: str
    producer_version: str
    run_id: str
    execution_timestamp: str
    facts_packet_id: str
    facts_content_digest: str
    decision_policy_version: str
    assessment_scope: str
    conclusion: str
    caveat_codes: tuple[str, ...]
    caveat_fact_refs: tuple[str, ...]
    advisories: tuple[Mapping[str, object], ...]
    assessment_content_digest: str
    facts_packet: TimeSeriesDiagnosticFactsPacket

    def __post_init__(self) -> None:
        if not isinstance(self.facts_packet, TimeSeriesDiagnosticFactsPacket):
            raise ContractError("facts_packet must be a TimeSeriesDiagnosticFactsPacket")
        if (
            self.facts_packet_id != self.facts_packet.packet_id
            or self.facts_content_digest != self.facts_packet.facts_content_digest
        ):
            raise ContractError("assessment facts_content_digest does not match Facts packet")
        normalized = _normalize_assessment_packet(self.to_dict(), verify_digest=True)
        for field_name, field_value in normalized.items():
            object.__setattr__(self, field_name, field_value)

    def to_dict(self) -> dict[str, object]:
        return {
            field_name: thaw_json(getattr(self, field_name))
            for field_name in _ASSESSMENT_PACKET_FIELDS
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
        *,
        facts_packet: Mapping[str, object] | TimeSeriesDiagnosticFactsPacket | None = None,
    ) -> "TimeSeriesDiagnosticAssessmentPacket":
        if facts_packet is None:
            raise ContractError("assessment packet requires a bound Facts packet")
        facts = (
            facts_packet
            if isinstance(facts_packet, TimeSeriesDiagnosticFactsPacket)
            else TimeSeriesDiagnosticFactsPacket.from_dict(facts_packet)
        )
        normalized = _normalize_assessment_packet(value, verify_digest=False)
        return cls(**normalized, facts_packet=facts)


def assessment_content_projection(
    packet: Mapping[str, object] | TimeSeriesDiagnosticAssessmentPacket,
) -> dict[str, object]:
    value = packet.to_dict() if isinstance(packet, TimeSeriesDiagnosticAssessmentPacket) else packet
    normalized = _normalize_assessment_packet(value, verify_digest=False)
    return _assessment_projection_from_normalized(normalized)


def assessment_content_digest(
    packet: Mapping[str, object] | TimeSeriesDiagnosticAssessmentPacket,
) -> str:
    return _packet_canonical_digest(
        assessment_content_projection(packet), "assessment packet"
    )


def envelope_digest(packet: Mapping[str, object]) -> str:
    """Hash every envelope field except the non-self-referential digest field."""

    if not isinstance(packet, Mapping):
        raise ContractError("execution envelope must be a mapping")
    try:
        return sha256_canonical(
            {key: value for key, value in packet.items() if key != "envelope_digest"}
        )
    except (TypeError, ValueError) as exc:
        raise ContractError("execution envelope contains invalid canonical JSON") from exc


def parse_time_series_diagnostic_facts_packet(
    value: Mapping[str, object],
) -> TimeSeriesDiagnosticFactsPacket:
    return TimeSeriesDiagnosticFactsPacket.from_dict(value)


def parse_time_series_diagnostic_assessment_packet(
    value: Mapping[str, object],
    *,
    facts_packet: Mapping[str, object] | TimeSeriesDiagnosticFactsPacket | None = None,
) -> TimeSeriesDiagnosticAssessmentPacket:
    return TimeSeriesDiagnosticAssessmentPacket.from_dict(value, facts_packet=facts_packet)
