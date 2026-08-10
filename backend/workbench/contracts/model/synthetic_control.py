"""Typed contract for bounded simplex synthetic-control summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json
from workbench.contracts.model.p7_extension import P7ScopeMetadata


SYNTHETIC_CONTROL_CONTRACT = "synthetic_control.result"
SYNTHETIC_CONTROL_CONTRACT_VERSION = "1.0"
SYNTHETIC_CONTROL_OPERATION_IDS = frozenset({"synthetic_control.fit", "synthetic_control.placebo"})
_INPUT_FIELDS = {
    "operation_id", "treated_unit", "donor_pool", "periods", "pre_periods", "post_periods",
    "predictor_policy", "weight_policy", "solver_policy", "tolerance_policy", "placebo_policy",
}
_RESULT_FIELDS = {"contract", "contract_version", "operation_id", "status", "reason_code", "n_units", "n_periods", "result", "evidence_digest"}
_RAW_KEYS = frozenset({"raw_matrix", "raw_rows", "outcome_matrix", "predictor_matrix", "data"})


def _unit(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{field} must be a non-empty unit identifier")
    return value


def _periods(value: Any, field: str) -> tuple[int | float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{field} must be an ordered period array")
    result: list[int | float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ContractError(f"{field} must contain finite numeric periods")
        result.append(item)
    if not result or len(set(result)) != len(result) or result != sorted(result):
        raise ContractError(f"{field} must be sorted and unique")
    return tuple(result)


def _policy(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"solver", "max_iter", "tolerance", "constraint_tolerance"}
    require_exact_keys(value, expected, "solver policy")
    if value["solver"] != "scipy_slsqp":
        raise ContractError("solver must be scipy_slsqp")
    if type(value["max_iter"]) is not int or not 1 <= value["max_iter"] <= 10_000:
        raise ContractError("solver max_iter is outside the supported bound")
    for field in ("tolerance", "constraint_tolerance"):
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)) or float(number) <= 0.0:
            raise ContractError(f"solver {field} must be positive and finite")
    return dict(value)


def _tolerances(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"weight_sum", "constraint", "finite"}
    require_exact_keys(value, expected, "tolerance policy")
    normalized: dict[str, Any] = {}
    for field in expected:
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)) or float(number) < 0.0:
            raise ContractError(f"tolerance {field} must be finite and non-negative")
        normalized[field] = number
    return normalized


def _placebo(value: Mapping[str, Any] | None, *, operation_id: str, donor_pool: Sequence[str], treated_unit: str) -> dict[str, Any] | None:
    if operation_id == "synthetic_control.fit":
        if value is not None:
            raise ContractError("fit operation does not accept placebo_policy")
        return None
    if not isinstance(value, Mapping):
        raise ContractError("placebo operation requires an explicit placebo_policy")
    expected = {"unit_policy", "placebo_units", "max_placebos", "donor_policy", "failure_policy"}
    require_exact_keys(value, expected, "placebo policy")
    units = value["placebo_units"]
    if value["unit_policy"] != "explicit" or value["donor_policy"] != "exclude_original_treated" or value["failure_policy"] != "reject":
        raise ContractError("placebo policy contains an undeclared policy")
    if isinstance(units, (str, bytes)) or not isinstance(units, Sequence) or not units or any(_unit(item, "placebo_units[]") == treated_unit for item in units):
        raise ContractError("placebo_units must be explicit and exclude the treated unit")
    if len(set(units)) != len(units) or any(item not in donor_pool for item in units):
        raise ContractError("placebo_units must be unique members of the donor pool")
    if type(value["max_placebos"]) is not int or not 1 <= value["max_placebos"] <= 100:
        raise ContractError("max_placebos is outside the supported bound")
    if len(units) > value["max_placebos"]:
        raise ContractError("placebo_units exceed max_placebos")
    return dict(value)


@dataclass(frozen=True)
class SyntheticControlInput:
    operation_id: str
    treated_unit: str
    donor_pool: tuple[str, ...]
    periods: tuple[int | float, ...]
    pre_periods: tuple[int | float, ...]
    post_periods: tuple[int | float, ...]
    predictor_policy: str
    weight_policy: str
    solver_policy: Mapping[str, Any]
    tolerance_policy: Mapping[str, Any]
    placebo_policy: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        if self.operation_id not in SYNTHETIC_CONTROL_OPERATION_IDS:
            raise ContractError("operation_id is not a declared synthetic-control operation")
        treated = _unit(self.treated_unit, "treated_unit")
        if isinstance(self.donor_pool, (str, bytes)) or not isinstance(self.donor_pool, Sequence) or not self.donor_pool:
            raise ContractError("donor_pool must be a non-empty array")
        donor_pool = tuple(_unit(item, "donor_pool[]") for item in self.donor_pool)
        if len(set(donor_pool)) != len(donor_pool) or treated in donor_pool:
            raise ContractError("donor_pool must be unique and exclude treated_unit")
        periods = _periods(self.periods, "periods")
        pre = _periods(self.pre_periods, "pre_periods")
        post = _periods(self.post_periods, "post_periods")
        if len(periods) < 3:
            raise ContractError("periods must contain at least three periods")
        if len(pre) < 2:
            raise ContractError("pre_periods must contain at least two periods")
        if set(pre) & set(post) or not set(pre).issubset(periods) or not set(post).issubset(periods) or not set(pre) | set(post) <= set(periods):
            raise ContractError("pre_periods and post_periods must be disjoint members of periods")
        if self.predictor_policy != "pre_outcome_v1":
            raise ContractError("predictor_policy is not declared")
        if self.weight_policy != "simplex_nonnegative_v1":
            raise ContractError("weight_policy is not declared")
        solver = _policy(self.solver_policy)
        tolerances = _tolerances(self.tolerance_policy)
        placebo = _placebo(self.placebo_policy, operation_id=self.operation_id, donor_pool=donor_pool, treated_unit=treated)
        object.__setattr__(self, "treated_unit", treated)
        object.__setattr__(self, "donor_pool", donor_pool)
        object.__setattr__(self, "periods", periods)
        object.__setattr__(self, "pre_periods", pre)
        object.__setattr__(self, "post_periods", post)
        object.__setattr__(self, "solver_policy", freeze_json(solver, "solver_policy"))
        object.__setattr__(self, "tolerance_policy", freeze_json(tolerances, "tolerance_policy"))
        # Preserve the explicit list shape for agent-facing round trips.  The
        # values were fully validated above; result envelopes still freeze
        # their published evidence.
        object.__setattr__(self, "placebo_policy", None if placebo is None else dict(placebo))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SyntheticControlInput":
        require_exact_keys(value, _INPUT_FIELDS, "synthetic-control input")
        return cls(
            operation_id=value["operation_id"], treated_unit=value["treated_unit"], donor_pool=tuple(value["donor_pool"]),
            periods=tuple(value["periods"]), pre_periods=tuple(value["pre_periods"]), post_periods=tuple(value["post_periods"]),
            predictor_policy=value["predictor_policy"], weight_policy=value["weight_policy"], solver_policy=value["solver_policy"],
            tolerance_policy=value["tolerance_policy"], placebo_policy=value["placebo_policy"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "treated_unit": self.treated_unit, "donor_pool": list(self.donor_pool),
            "periods": list(self.periods), "pre_periods": list(self.pre_periods), "post_periods": list(self.post_periods),
            "predictor_policy": self.predictor_policy, "weight_policy": self.weight_policy,
            "solver_policy": thaw_json(self.solver_policy), "tolerance_policy": thaw_json(self.tolerance_policy),
            "placebo_policy": None if self.placebo_policy is None else thaw_json(self.placebo_policy),
        }


def _reject_raw(value: Any, path: str = "result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _RAW_KEYS:
                raise ContractError(f"{path}.{key} must not expose raw synthetic-control arrays")
            _reject_raw(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw(item, f"{path}[{index}]")


def validate_synthetic_control_result(value: Mapping[str, Any]) -> None:
    require_exact_keys(value, _RESULT_FIELDS, "synthetic-control result envelope")
    if value["contract"] != SYNTHETIC_CONTROL_CONTRACT or value["contract_version"] != SYNTHETIC_CONTROL_CONTRACT_VERSION:
        raise ContractError("synthetic-control contract or version is not declared")
    if value["operation_id"] not in SYNTHETIC_CONTROL_OPERATION_IDS:
        raise ContractError("synthetic-control operation_id is not declared")
    expected = {"completed": "SYNTHETIC_CONTROL_COMPLETED", "rejected": "SYNTHETIC_CONTROL_REJECTED", "failed": "SYNTHETIC_CONTROL_FAILED"}.get(value["status"])
    if expected is None or value["reason_code"] != expected:
        raise ContractError("synthetic-control status and reason_code are inconsistent")
    if type(value["n_units"]) is not int or value["n_units"] < 0 or type(value["n_periods"]) is not int or value["n_periods"] < 0:
        raise ContractError("n_units and n_periods must be non-negative integers")
    if not isinstance(value["result"], Mapping):
        raise ContractError("synthetic-control result must be a mapping")
    _reject_raw(value["result"])
    if value["status"] == "completed":
        if "scope" not in value["result"]:
            raise ContractError("completed synthetic-control result requires scope")
        P7ScopeMetadata.from_dict(value["result"]["scope"])
        expected_digest = sha256_canonical({"operation_id": value["operation_id"], "result": value["result"]})
        if value["evidence_digest"] != expected_digest:
            raise ContractError("synthetic-control evidence_digest does not match result")
    elif value["evidence_digest"] is not None:
        raise ContractError("non-completed synthetic-control result cannot publish evidence_digest")
    freeze_json(value["result"], "result")


def make_synthetic_control_result(*, operation_id: str, status: str, reason_code: str, n_units: int, n_periods: int, result: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "contract": SYNTHETIC_CONTROL_CONTRACT, "contract_version": SYNTHETIC_CONTROL_CONTRACT_VERSION,
        "operation_id": operation_id, "status": status, "reason_code": reason_code,
        "n_units": n_units, "n_periods": n_periods, "result": result,
        "evidence_digest": sha256_canonical({"operation_id": operation_id, "result": result}) if status == "completed" else None,
    }
    validate_synthetic_control_result(payload)
    return payload


__all__ = ["SYNTHETIC_CONTROL_CONTRACT", "SYNTHETIC_CONTROL_CONTRACT_VERSION", "SYNTHETIC_CONTROL_OPERATION_IDS", "SyntheticControlInput", "make_synthetic_control_result", "validate_synthetic_control_result"]
