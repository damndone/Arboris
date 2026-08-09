"""Typed contract for bounded propensity-score nearest-neighbour matching."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json
from workbench.contracts.model.p7_extension import P7ScopeMetadata


MATCHING_CONTRACT = "matching.result"
MATCHING_CONTRACT_VERSION = "1.0"
MATCHING_OPERATION_IDS = frozenset({"matching.att", "matching.balance"})
_INPUT_FIELDS = {
    "operation_id", "treatment_column", "outcome_column", "covariate_columns", "id_column",
    "estimand", "propensity_policy", "distance_policy", "ratio", "caliper", "replacement",
    "tie_policy", "common_support_policy", "unmatched_policy", "balance_threshold", "missing_policy",
}
_RESULT_FIELDS = {"contract", "contract_version", "operation_id", "status", "reason_code", "n_observations", "result", "evidence_digest"}
_RAW_KEYS = frozenset({"raw_rows", "raw_data", "data", "outcomes"})


def _name(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value:
        raise ContractError(f"{field} must be a non-empty column name")
    return value


def _columns(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError("covariate_columns must be an array of column names")
    columns = tuple(value)
    if not columns or any(type(column) is not str or not column for column in columns):
        raise ContractError("covariate_columns must contain non-empty names")
    if len(set(columns)) != len(columns):
        raise ContractError("covariate_columns must not contain duplicates")
    return columns


def _finite(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        raise ContractError(f"{field} is outside the supported range")
    return number


def _propensity(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"model", "solver", "max_iter", "tolerance", "min_probability", "max_probability"}
    require_exact_keys(value, expected, "propensity policy")
    if value["model"] != "logit" or value["solver"] != "newton":
        raise ContractError("propensity policy must explicitly select logit/newton")
    if type(value["max_iter"]) is not int or not 1 <= value["max_iter"] <= 10_000:
        raise ContractError("propensity max_iter is outside the supported range")
    tolerance = _finite(value["tolerance"], "propensity tolerance", minimum=1e-15)
    minimum = _finite(value["min_probability"], "propensity min_probability", minimum=0.0, maximum=1.0)
    maximum = _finite(value["max_probability"], "propensity max_probability", minimum=0.0, maximum=1.0)
    if not minimum < maximum:
        raise ContractError("propensity probability bounds must be ordered")
    return {"model": "logit", "solver": "newton", "max_iter": value["max_iter"], "tolerance": tolerance, "min_probability": minimum, "max_probability": maximum}


@dataclass(frozen=True)
class MatchingInput:
    operation_id: str
    treatment_column: str
    outcome_column: str | None
    covariate_columns: tuple[str, ...]
    id_column: str
    estimand: str
    propensity_policy: Mapping[str, Any]
    distance_policy: str
    ratio: int
    caliper: float | None
    replacement: bool
    tie_policy: str
    common_support_policy: str
    unmatched_policy: str
    balance_threshold: float | None
    missing_policy: str

    def __post_init__(self) -> None:
        if self.operation_id not in MATCHING_OPERATION_IDS:
            raise ContractError("operation_id is not a declared matching operation")
        treatment = _name(self.treatment_column, "treatment_column")
        outcome = _name(self.outcome_column, "outcome_column", optional=True)
        identifier = _name(self.id_column, "id_column")
        columns = _columns(self.covariate_columns)
        if len({treatment, identifier, *columns, *([] if outcome is None else [outcome])}) != len(columns) + 2 + (0 if outcome is None else 1):
            raise ContractError("matching column names must be distinct")
        if self.operation_id == "matching.att":
            if outcome is None or self.estimand != "ATT":
                raise ContractError("matching.att requires estimand ATT and an outcome column")
        elif outcome is not None or self.estimand != "covariate_balance":
            raise ContractError("matching.balance requires covariate_balance and no outcome column")
        if not isinstance(self.propensity_policy, Mapping):
            raise ContractError("propensity_policy must be explicit")
        policy = _propensity(self.propensity_policy)
        if self.distance_policy != "logit":
            raise ContractError("distance_policy must be logit")
        if type(self.ratio) is not int or not 1 <= self.ratio <= 10:
            raise ContractError("ratio must be a bounded positive integer")
        if self.caliper is not None:
            _finite(self.caliper, "caliper", minimum=0.0)
        if type(self.replacement) is not bool:
            raise ContractError("replacement must be boolean")
        if self.tie_policy != "stable_first":
            raise ContractError("tie_policy must be stable_first")
        if self.common_support_policy != "trim":
            raise ContractError("common_support_policy must be trim")
        if self.unmatched_policy != "reject":
            raise ContractError("unmatched_policy must be reject")
        if self.balance_threshold is not None:
            _finite(self.balance_threshold, "balance_threshold", minimum=0.0)
        if self.missing_policy != "reject":
            raise ContractError("missing_policy must be reject")
        object.__setattr__(self, "treatment_column", treatment)
        object.__setattr__(self, "outcome_column", outcome)
        object.__setattr__(self, "id_column", identifier)
        object.__setattr__(self, "covariate_columns", columns)
        object.__setattr__(self, "propensity_policy", freeze_json(policy, "propensity_policy"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatchingInput":
        require_exact_keys(value, _INPUT_FIELDS, "matching input")
        return cls(
            operation_id=value["operation_id"], treatment_column=value["treatment_column"],
            outcome_column=value["outcome_column"], covariate_columns=tuple(value["covariate_columns"]),
            id_column=value["id_column"], estimand=value["estimand"], propensity_policy=value["propensity_policy"],
            distance_policy=value["distance_policy"], ratio=value["ratio"], caliper=value["caliper"],
            replacement=value["replacement"], tie_policy=value["tie_policy"],
            common_support_policy=value["common_support_policy"], unmatched_policy=value["unmatched_policy"],
            balance_threshold=value["balance_threshold"], missing_policy=value["missing_policy"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "treatment_column": self.treatment_column,
            "outcome_column": self.outcome_column, "covariate_columns": list(self.covariate_columns),
            "id_column": self.id_column, "estimand": self.estimand,
            "propensity_policy": thaw_json(self.propensity_policy), "distance_policy": self.distance_policy,
            "ratio": self.ratio, "caliper": self.caliper, "replacement": self.replacement,
            "tie_policy": self.tie_policy, "common_support_policy": self.common_support_policy,
            "unmatched_policy": self.unmatched_policy, "balance_threshold": self.balance_threshold,
            "missing_policy": self.missing_policy,
        }


def _reject_raw(value: Any, path: str = "result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _RAW_KEYS:
                raise ContractError(f"{path}.{key} must not expose raw matching rows")
            _reject_raw(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw(item, f"{path}[{index}]")


def validate_matching_result(value: Mapping[str, Any]) -> None:
    require_exact_keys(value, _RESULT_FIELDS, "matching result envelope")
    if value["contract"] != MATCHING_CONTRACT or value["contract_version"] != MATCHING_CONTRACT_VERSION:
        raise ContractError("matching contract or version is not declared")
    if value["operation_id"] not in MATCHING_OPERATION_IDS:
        raise ContractError("matching operation_id is not declared")
    expected = {"completed": "MATCHING_COMPLETED", "rejected": "MATCHING_REJECTED", "failed": "MATCHING_FAILED"}.get(value["status"])
    if expected is None or value["reason_code"] != expected:
        raise ContractError("matching status and reason_code are inconsistent")
    if type(value["n_observations"]) is not int or value["n_observations"] < 0:
        raise ContractError("n_observations must be non-negative")
    if not isinstance(value["result"], Mapping):
        raise ContractError("matching result must be a mapping")
    _reject_raw(value["result"])
    if value["status"] == "completed":
        if "scope" not in value["result"]:
            raise ContractError("completed matching result requires scope")
        P7ScopeMetadata.from_dict(value["result"]["scope"])
        expected_digest = sha256_canonical({"operation_id": value["operation_id"], "result": value["result"]})
        if value["evidence_digest"] != expected_digest:
            raise ContractError("matching evidence_digest does not match result")
    elif value["evidence_digest"] is not None:
        raise ContractError("non-completed matching result cannot publish evidence_digest")
    freeze_json(value["result"], "result")


def make_matching_result(*, operation_id: str, status: str, reason_code: str, n_observations: int, result: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "contract": MATCHING_CONTRACT, "contract_version": MATCHING_CONTRACT_VERSION,
        "operation_id": operation_id, "status": status, "reason_code": reason_code,
        "n_observations": n_observations, "result": result,
        "evidence_digest": sha256_canonical({"operation_id": operation_id, "result": result}) if status == "completed" else None,
    }
    validate_matching_result(payload)
    return payload


__all__ = ["MATCHING_CONTRACT", "MATCHING_CONTRACT_VERSION", "MATCHING_OPERATION_IDS", "MatchingInput", "make_matching_result", "validate_matching_result"]
