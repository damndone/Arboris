"""Typed contracts for standalone OLS-shaped model diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import numbers
from typing import Any

from workbench.contracts.common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json
from workbench.contracts.model.p7_extension import P7ScopeMetadata


MODEL_DIAGNOSTICS_CONTRACT = "model_diagnostics.result"
MODEL_DIAGNOSTICS_CONTRACT_VERSION = "1.0"
MODEL_DIAGNOSTICS_OPERATION_IDS = frozenset(
    {
        "diagnostics.vif",
        "diagnostics.breusch_pagan",
        "diagnostics.white",
        "diagnostics.breusch_godfrey",
        "diagnostics.reset",
        "diagnostics.influence",
    }
)
MODEL_DIAGNOSTICS_STATUSES = frozenset({"completed", "failed", "rejected"})
MODEL_DIAGNOSTICS_REASON_CODES = frozenset(
    {
        "DIAGNOSTICS_COMPLETED",
        "DIAGNOSTICS_FAILED",
        "DIAGNOSTICS_INVALID_INPUT",
        "DIAGNOSTICS_NON_FINITE_INPUT",
        "DIAGNOSTICS_FITTED_RESIDUAL_MISMATCH",
        "DIAGNOSTICS_NUMERIC_FAILURE",
        "DIAGNOSTICS_INSUFFICIENT_DF",
        "DIAGNOSTICS_SINGULAR_DESIGN",
        "DIAGNOSTICS_OUTPUT_TOO_LARGE",
    }
)
_INPUT_FIELDS = {
    "operation_id", "response", "design", "design_columns", "residuals", "fitted_values",
    "intercept", "intercept_column", "model_metadata", "time_order", "time_values", "lag",
    "reset_powers", "max_output_rows",
}
_RESULT_FIELDS = {
    "contract", "contract_version", "operation_id", "status", "reason_code",
    "n_observations", "design_columns", "result",
}


def _sequence(value: Any, name: str, *, min_len: int = 1) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{name} must be an array")
    output = tuple(value)
    if len(output) < min_len:
        raise ContractError(f"{name} must contain at least {min_len} values")
    return output


def _strings(value: Any, name: str, *, min_len: int = 1) -> tuple[str, ...]:
    output = _sequence(value, name, min_len=min_len)
    if any(type(item) is not str or not item for item in output):
        raise ContractError(f"{name} must contain non-empty strings")
    if len(set(output)) != len(output):
        raise ContractError(f"{name} must not contain duplicates")
    return output


def _numeric_sequence(value: Any, name: str, *, allow_none: bool = True) -> tuple[float, ...] | None:
    if value is None and allow_none:
        return None
    output = _sequence(value, name)
    if any(not isinstance(item, numbers.Real) or isinstance(item, bool) for item in output):
        raise ContractError(f"{name} must contain numeric values")
    normalized = tuple(float(item) for item in output)
    if any(not math.isfinite(item) for item in normalized):
        raise ContractError(f"{name} must contain finite values")
    return normalized


def _matrix(value: Any, name: str) -> tuple[tuple[float, ...], ...]:
    rows = _sequence(value, name)
    normalized: list[tuple[float, ...]] = []
    width: int | None = None
    for row in rows:
        values = _numeric_sequence(row, f"{name} row", allow_none=False)
        assert values is not None
        if width is None:
            width = len(values)
        if len(values) != width:
            raise ContractError(f"{name} must be rectangular")
        normalized.append(values)
    if width is None or width < 1:
        raise ContractError(f"{name} must not be empty")
    return tuple(normalized)


def _metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("model_metadata must be a mapping")
    required = {"model_type", "parameter_count", "residual_df", "residual_variance", "covariance", "parameter_names"}
    require_exact_keys(value, required, "model_metadata")
    if value["model_type"] != "ols" or value["covariance"] != "unadjusted":
        raise ContractError("model_metadata must describe an unadjusted OLS fit")
    if type(value["parameter_count"]) is not int or value["parameter_count"] < 1:
        raise ContractError("parameter_count must be positive")
    if type(value["residual_df"]) is not int or value["residual_df"] < 1:
        raise ContractError("residual_df must be positive")
    if type(value["residual_variance"]) not in {int, float} or isinstance(value["residual_variance"], bool) or float(value["residual_variance"]) < 0:
        raise ContractError("residual_variance must be non-negative")
    names = _strings(value["parameter_names"], "parameter_names")
    if len(names) != value["parameter_count"]:
        raise ContractError("parameter_names must match parameter_count")
    return dict(value)


@dataclass(frozen=True)
class ModelDiagnosticsInput:
    operation_id: str
    response: tuple[float, ...]
    design: tuple[tuple[float, ...], ...]
    design_columns: tuple[str, ...]
    residuals: tuple[float, ...]
    fitted_values: tuple[float, ...] | None
    intercept: bool
    intercept_column: str | None
    model_metadata: Mapping[str, Any]
    time_order: str | None
    time_values: tuple[float, ...] | None
    lag: int | None
    reset_powers: tuple[int, ...] | None
    max_output_rows: int | None

    def __post_init__(self) -> None:
        if self.operation_id not in MODEL_DIAGNOSTICS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared diagnostics operation")
        response = _numeric_sequence(self.response, "response", allow_none=False)
        residuals = _numeric_sequence(self.residuals, "residuals", allow_none=False)
        assert response is not None and residuals is not None
        design = _matrix(self.design, "design")
        columns = _strings(self.design_columns, "design_columns")
        if len(design) != len(response) or len(residuals) != len(response) or len(design[0]) != len(columns):
            raise ContractError("response, residuals, design, and design_columns shapes must agree")
        if len(columns) != len(set(columns)):
            raise ContractError("design_columns must not contain duplicates")
        if type(self.intercept) is not bool:
            raise ContractError("intercept must be boolean")
        if self.intercept and (self.intercept_column is None or self.intercept_column not in columns):
            raise ContractError("intercept_column is required when intercept is included")
        if not self.intercept and self.intercept_column is not None:
            raise ContractError("intercept_column must be absent when intercept is false")
        fitted = _numeric_sequence(self.fitted_values, "fitted_values")
        if fitted is not None and len(fitted) != len(response):
            raise ContractError("fitted_values must match response length")
        metadata = _metadata(self.model_metadata)
        if metadata["parameter_count"] != len(columns) or metadata["residual_df"] != len(response) - len(columns):
            raise ContractError("model_metadata does not match design degrees of freedom")
        if self.time_order is not None and self.time_order not in {"declared_monotonic", "declared_order"}:
            raise ContractError("time_order is not declared")
        times = _numeric_sequence(self.time_values, "time_values")
        if times is not None and len(times) != len(response):
            raise ContractError("time_values must match response length")
        if self.lag is not None and (type(self.lag) is not int or not 1 <= self.lag < len(response)):
            raise ContractError("lag must be a positive integer below the observation count")
        powers = None
        if self.reset_powers is not None:
            raw_powers = _sequence(self.reset_powers, "reset_powers")
            if any(type(power) is not int or power < 2 or power > 5 for power in raw_powers):
                raise ContractError("reset_powers must contain integers in [2, 5]")
            powers = tuple(raw_powers)
        if self.max_output_rows is not None and (type(self.max_output_rows) is not int or self.max_output_rows < 1):
            raise ContractError("max_output_rows must be positive")
        if self.operation_id == "diagnostics.breusch_godfrey" and (self.time_order is None or self.lag is None):
            raise ContractError("Breusch-Godfrey requires time_order and lag")
        if self.operation_id == "diagnostics.reset" and powers is None:
            raise ContractError("RESET requires reset_powers")
        if self.operation_id == "diagnostics.influence" and fitted is None:
            raise ContractError("influence requires fitted_values")
        object.__setattr__(self, "response", response)
        object.__setattr__(self, "residuals", residuals)
        object.__setattr__(self, "design", design)
        object.__setattr__(self, "design_columns", columns)
        object.__setattr__(self, "fitted_values", fitted)
        object.__setattr__(self, "model_metadata", metadata)
        object.__setattr__(self, "time_values", times)
        object.__setattr__(self, "reset_powers", powers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "response": list(self.response), "design": [list(row) for row in self.design],
            "design_columns": list(self.design_columns), "residuals": list(self.residuals),
            "fitted_values": None if self.fitted_values is None else list(self.fitted_values),
            "intercept": self.intercept, "intercept_column": self.intercept_column,
            "model_metadata": dict(self.model_metadata), "time_order": self.time_order,
            "time_values": None if self.time_values is None else list(self.time_values), "lag": self.lag,
            "reset_powers": None if self.reset_powers is None else list(self.reset_powers),
            "max_output_rows": self.max_output_rows,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelDiagnosticsInput":
        require_exact_keys(value, _INPUT_FIELDS, "model diagnostics input")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ModelDiagnosticsResultEnvelope:
    operation_id: str
    status: str
    reason_code: str
    n_observations: int
    design_columns: tuple[str, ...]
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.operation_id not in MODEL_DIAGNOSTICS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared diagnostics operation")
        if self.status not in MODEL_DIAGNOSTICS_STATUSES or self.reason_code not in MODEL_DIAGNOSTICS_REASON_CODES:
            raise ContractError("status or reason_code is not declared")
        if type(self.n_observations) is not int or self.n_observations < 0:
            raise ContractError("n_observations must be non-negative")
        columns = _strings(self.design_columns, "design_columns")
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        frozen = freeze_json(self.result, "result")
        if self.status == "completed":
            if "scope" not in frozen or "model_valid" in frozen:
                raise ContractError("completed diagnostics result must have scope and no model-validity verdict")
            P7ScopeMetadata.from_dict(frozen["scope"])
        else:
            require_exact_keys(frozen, {"error_code", "message"}, "failed diagnostics result")
        object.__setattr__(self, "design_columns", columns)
        object.__setattr__(self, "result", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": MODEL_DIAGNOSTICS_CONTRACT, "contract_version": MODEL_DIAGNOSTICS_CONTRACT_VERSION,
            "operation_id": self.operation_id, "status": self.status, "reason_code": self.reason_code,
            "n_observations": self.n_observations, "design_columns": list(self.design_columns),
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelDiagnosticsResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "model diagnostics result")
        if value["contract"] != MODEL_DIAGNOSTICS_CONTRACT or value["contract_version"] != MODEL_DIAGNOSTICS_CONTRACT_VERSION:
            raise ContractError("diagnostics contract/version is not declared")
        return cls(
            operation_id=value["operation_id"], status=value["status"], reason_code=value["reason_code"],
            n_observations=value["n_observations"], design_columns=tuple(value["design_columns"]), result=value["result"],
        )


def make_model_diagnostics_result(**kwargs: Any) -> dict[str, Any]:
    return ModelDiagnosticsResultEnvelope(**kwargs).to_dict()


__all__ = [
    "MODEL_DIAGNOSTICS_CONTRACT", "MODEL_DIAGNOSTICS_CONTRACT_VERSION", "MODEL_DIAGNOSTICS_OPERATION_IDS",
    "MODEL_DIAGNOSTICS_REASON_CODES", "ModelDiagnosticsInput", "ModelDiagnosticsResultEnvelope",
    "make_model_diagnostics_result",
]
