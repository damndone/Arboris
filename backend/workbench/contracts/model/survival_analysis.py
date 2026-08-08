"""Versioned contracts for the standalone non-parametric survival pack."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


SURVIVAL_ANALYSIS_CONTRACT = "survival_analysis.result"
SURVIVAL_ANALYSIS_CONTRACT_VERSION = "1.0"
SURVIVAL_ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS = "SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS"
SURVIVAL_NON_EXACT_TIME = "SURVIVAL_NON_EXACT_TIME"
SURVIVAL_NUMERIC_UNDERFLOW = "SURVIVAL_NUMERIC_UNDERFLOW"
SURVIVAL_RMST_NON_EXACT = "SURVIVAL_RMST_NON_EXACT"
SURVIVAL_ENTRY_AT_DURATION = "SURVIVAL_ENTRY_AT_DURATION"
SURVIVAL_REQUIRED_FIELD = "SURVIVAL_REQUIRED_FIELD"
SURVIVAL_ANALYSIS_OPERATION_IDS = frozenset(
    {"survival.kaplan_meier", "survival.log_rank", "survival.rmst"}
)
SURVIVAL_ANALYSIS_CI_METHODS = frozenset({"plain", "log_log"})
SURVIVAL_ANALYSIS_TIE_POLICIES = frozenset({"hypergeometric", "breslow"})
SURVIVAL_ANALYSIS_STATUSES = frozenset({"completed"})
SURVIVAL_ANALYSIS_REASON_CODES = frozenset(
    {
        "ANALYSIS_COMPLETED",
        "SURVIVAL_BAD_INPUT",
        "SURVIVAL_EMPTY_INPUT",
        "SURVIVAL_MISSING_COLUMN",
        "SURVIVAL_DUPLICATE_COLUMN",
        "SURVIVAL_NON_NUMERIC_INPUT",
        "SURVIVAL_NONFINITE_INPUT",
        SURVIVAL_NON_EXACT_TIME,
        SURVIVAL_NUMERIC_UNDERFLOW,
        SURVIVAL_RMST_NON_EXACT,
        "SURVIVAL_DURATION_NEGATIVE",
        "SURVIVAL_EVENT_NOT_BINARY",
        "SURVIVAL_ENTRY_NEGATIVE",
        "SURVIVAL_ENTRY_AFTER_DURATION",
        SURVIVAL_ENTRY_AT_DURATION,
        "SURVIVAL_GROUP_MISSING",
        "SURVIVAL_GROUP_INVALID",
        "SURVIVAL_GROUP_REQUIRED",
        "SURVIVAL_GROUP_DEGENERATE",
        "SURVIVAL_TOO_MANY_ROWS",
        "SURVIVAL_TOO_MANY_GROUPS",
        "SURVIVAL_TOO_MANY_TIME_POINTS",
        "SURVIVAL_INVALID_OPTION",
        SURVIVAL_REQUIRED_FIELD,
        "SURVIVAL_CONFIDENCE_INVALID",
        "SURVIVAL_TAU_REQUIRED",
        "SURVIVAL_TAU_INVALID",
        "SURVIVAL_TAU_NONFINITE",
        "SURVIVAL_TAU_NEGATIVE",
        "SURVIVAL_TAU_OUT_OF_SUPPORT",
        "SURVIVAL_NO_EVENTS",
        "SURVIVAL_NUMERIC_DEGENERACY",
        SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS,
    }
)

_REQUEST_FIELDS = {
    "duration_column",
    "event_column",
    "entry_column",
    "group_column",
    "ci_method",
    "confidence_level",
    "tie_policy",
    "tau",
}

_COMMON_RESULT_FIELDS = frozenset(
    {"status", "reason_code", "estimator", "nobs", "event_count", "groups", "policy", "provenance"}
)
_OPERATION_RESULT_FIELDS = {
    "survival.kaplan_meier": _COMMON_RESULT_FIELDS | {"curves"},
    "survival.log_rank": _COMMON_RESULT_FIELDS
    | {"groups", "observed", "expected", "covariance", "chi_square", "degrees_of_freedom", "p_value", "tie_policy"},
    "survival.rmst": _COMMON_RESULT_FIELDS | {"groups", "group_results", "tau"},
}


def _require_non_empty_string(value: Any, field_name: str) -> None:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")


def _require_finite_probability(value: Any, field_name: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ContractError(f"{field_name} must be a finite number strictly between 0 and 1")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be a finite number strictly between 0 and 1") from exc
    if not math.isfinite(normalized) or not 0.0 < normalized < 1.0:
        raise ContractError(f"{field_name} must be a finite number strictly between 0 and 1")
    return normalized


def _require_optional_tau(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ContractError("tau must be a finite non-negative number")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ContractError("tau must be a finite non-negative number") from exc
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ContractError("tau must be a finite non-negative number")
    return normalized


@dataclass(frozen=True)
class SurvivalAnalysisRequest:
    """Closed input options shared by the three standalone operations."""

    duration_column: str
    event_column: str
    entry_column: str | None = None
    group_column: str | None = None
    ci_method: Literal["plain", "log_log"] = "log_log"
    confidence_level: float = 0.95
    tie_policy: Literal["hypergeometric", "breslow"] = "hypergeometric"
    tau: float | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.duration_column, "duration_column")
        _require_non_empty_string(self.event_column, "event_column")
        if self.duration_column == self.event_column:
            raise ContractError("duration_column and event_column must be distinct")
        for field_name in ("entry_column", "group_column"):
            value = getattr(self, field_name)
            if value is not None:
                _require_non_empty_string(value, field_name)
        if type(self.ci_method) is not str or self.ci_method not in SURVIVAL_ANALYSIS_CI_METHODS:
            raise ContractError("ci_method must be plain or log_log")
        _require_finite_probability(self.confidence_level, "confidence_level")
        if type(self.tie_policy) is not str or self.tie_policy not in SURVIVAL_ANALYSIS_TIE_POLICIES:
            raise ContractError("tie_policy must be hypergeometric or breslow")
        _require_optional_tau(self.tau)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SurvivalAnalysisRequest":
        if not isinstance(value, Mapping):
            raise ContractError("survival analysis request must be a mapping")
        if any(type(key) is not str for key in value):
            raise ContractError("survival analysis request mapping keys must be strings")
        unknown = sorted(set(value) - _REQUEST_FIELDS)
        if unknown:
            raise ContractError(
                "survival analysis request has unknown field(s): " + ", ".join(unknown)
            )
        if "duration_column" not in value or "event_column" not in value:
            raise ContractError("survival analysis request requires duration_column and event_column")
        return cls(
            duration_column=value["duration_column"],
            event_column=value["event_column"],
            entry_column=value.get("entry_column"),
            group_column=value.get("group_column"),
            ci_method=value.get("ci_method", "log_log"),
            confidence_level=value.get("confidence_level", 0.95),
            tie_policy=value.get("tie_policy", "hypergeometric"),
            tau=value.get("tau"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_column": self.duration_column,
            "event_column": self.event_column,
            "entry_column": self.entry_column,
            "group_column": self.group_column,
            "ci_method": self.ci_method,
            "confidence_level": self.confidence_level,
            "tie_policy": self.tie_policy,
            "tau": self.tau,
        }


def _require_result_fields(value: Mapping[str, Any], required: frozenset[str], label: str) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be a mapping")
    missing = required - set(value)
    if missing:
        raise ContractError(f"missing {label} field(s): {', '.join(sorted(missing))}")


@dataclass(frozen=True)
class SurvivalAnalysisResultEnvelope:
    """Immutable, JSON-safe envelope for one closed survival operation."""

    operation_id: str
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or self.operation_id not in SURVIVAL_ANALYSIS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared survival operation")
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        frozen_result = freeze_json(self.result, "result")
        _require_result_fields(
            frozen_result,
            _OPERATION_RESULT_FIELDS[self.operation_id],
            f"{self.operation_id} result",
        )
        if frozen_result["status"] not in SURVIVAL_ANALYSIS_STATUSES:
            raise ContractError("status is not a declared survival status")
        if frozen_result["reason_code"] not in SURVIVAL_ANALYSIS_REASON_CODES:
            raise ContractError("reason_code is not a declared survival reason")
        if frozen_result["status"] == "completed" and frozen_result["reason_code"] != SURVIVAL_ANALYSIS_COMPLETED:
            raise ContractError("reason_code must match completed status")
        object.__setattr__(self, "result", frozen_result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": SURVIVAL_ANALYSIS_CONTRACT,
            "contract_version": SURVIVAL_ANALYSIS_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurvivalAnalysisResultEnvelope":
        require_exact_keys(value, {"contract", "contract_version", "operation_id", "result"}, "survival result")
        if value["contract"] != SURVIVAL_ANALYSIS_CONTRACT:
            raise ContractError("contract is not the declared survival result contract")
        if value["contract_version"] != SURVIVAL_ANALYSIS_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared survival version")
        return cls(operation_id=value["operation_id"], result=value["result"])


def make_result_envelope(*, operation_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a mutable JSON-shaped survival result envelope."""

    return SurvivalAnalysisResultEnvelope(operation_id=operation_id, result=result).to_dict()


__all__ = [
    "SURVIVAL_ANALYSIS_CI_METHODS",
    "SURVIVAL_ANALYSIS_COMPLETED",
    "SURVIVAL_ANALYSIS_CONTRACT",
    "SURVIVAL_ANALYSIS_CONTRACT_VERSION",
    "SURVIVAL_ANALYSIS_OPERATION_IDS",
    "SURVIVAL_ANALYSIS_REASON_CODES",
    "SURVIVAL_ANALYSIS_STATUSES",
    "SURVIVAL_ANALYSIS_TIE_POLICIES",
    "SURVIVAL_ENTRY_AT_DURATION",
    "SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS",
    "SURVIVAL_NON_EXACT_TIME",
    "SURVIVAL_NUMERIC_UNDERFLOW",
    "SURVIVAL_RMST_NON_EXACT",
    "SURVIVAL_REQUIRED_FIELD",
    "SurvivalAnalysisRequest",
    "SurvivalAnalysisResultEnvelope",
    "make_result_envelope",
]
