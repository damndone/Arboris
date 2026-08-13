"""Typed contract for bounded GLM extensions outside the existing model family."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from workbench.contracts.common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json
from workbench.contracts.model.p7_extension import P7ScopeMetadata


GLM_EXTENSION_CONTRACT = "glm_extensions.result"
GLM_EXTENSION_CONTRACT_VERSION = "1.0"
GLM_EXTENSION_OPERATION_IDS = {
    "glm.zero_inflated_poisson",
    "glm.zero_inflated_negative_binomial",
    "glm.hurdle_poisson",
    "glm.hurdle_negative_binomial",
    "glm.beta",
}
GLM_EXTENSION_REASON_CODES = {
    "ANALYSIS_COMPLETED",
    "GLM_EXTENSION_REJECTED",
    "GLM_EXTENSION_FAILED",
    "GLM_BAD_INPUT",
    "GLM_NONCONVERGENCE",
    "GLM_NUMERICAL_FAILURE",
}
_INPUT_FIELDS = {
    "operation_id", "predictor_columns", "zero_predictor_columns",
    "positive_predictor_columns", "precision_predictor_columns", "matrix_semantics",
    "response_semantics", "zero_process_semantics", "count_link", "zero_link",
    "positive_count_link", "mean_link", "precision_link", "intercept",
    "missing_policy", "offset_policy", "optimizer", "maxiter", "tolerance",
    "max_abs_linear_predictor",
}
_RESULT_FIELDS = {"contract", "contract_version", "operation_id", "result"}
_RAW_KEYS = frozenset({"data", "raw_data", "raw_rows", "raw_values", "response", "design", "matrix"})


def _columns(value: Any, field: str, *, allow_none: bool = True) -> tuple[str, ...] | None:
    if value is None and allow_none:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{field} must be an array of predictor names or null")
    columns = tuple(value)
    if not columns or any(type(item) is not str or not item for item in columns):
        raise ContractError(f"{field} must contain non-empty strings")
    if len(set(columns)) != len(columns):
        raise ContractError(f"{field} must not contain duplicates")
    return columns


def _choice(value: Any, expected: str, field: str) -> None:
    if type(value) is not str or value != expected:
        raise ContractError(f"{field} must be {expected}")


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a positive finite number")
    number = float(value)
    if not number > 0.0 or number != number or number in {float("inf"), float("-inf")}:
        raise ContractError(f"{field} must be a positive finite number")
    return number


@dataclass(frozen=True)
class GLMExtensionRequest:
    operation_id: str
    predictor_columns: tuple[str, ...]
    zero_predictor_columns: tuple[str, ...] | None
    positive_predictor_columns: tuple[str, ...] | None
    precision_predictor_columns: tuple[str, ...] | None
    matrix_semantics: str
    response_semantics: str
    zero_process_semantics: str
    count_link: str
    zero_link: str
    positive_count_link: str
    mean_link: str
    precision_link: str
    intercept: bool
    missing_policy: str
    offset_policy: str
    optimizer: str
    maxiter: int
    tolerance: float
    max_abs_linear_predictor: float

    def __post_init__(self) -> None:
        if self.operation_id not in GLM_EXTENSION_OPERATION_IDS:
            raise ContractError("operation_id is not a declared GLM extension")
        predictor = _columns(self.predictor_columns, "predictor_columns", allow_none=False)
        assert predictor is not None
        for field, value in (
            ("zero_predictor_columns", self.zero_predictor_columns),
            ("positive_predictor_columns", self.positive_predictor_columns),
            ("precision_predictor_columns", self.precision_predictor_columns),
        ):
            columns = _columns(value, field)
            if columns is not None and any(item not in predictor for item in columns):
                raise ContractError(f"{field} must be a subset of predictor_columns")
        if self.operation_id == "glm.beta":
            _choice(self.response_semantics, "strict_unit_interval_v1", "response_semantics")
            _choice(self.zero_process_semantics, "not_applicable_v1", "zero_process_semantics")
            _choice(self.count_link, "not_applicable", "count_link")
            _choice(self.zero_link, "not_applicable", "zero_link")
            _choice(self.positive_count_link, "not_applicable", "positive_count_link")
            _choice(self.mean_link, "logit", "mean_link")
            _choice(self.precision_link, "log", "precision_link")
            if self.precision_predictor_columns is not None:
                raise ContractError("precision_predictor_columns is not supported by glm.beta in this version")
        elif self.operation_id.startswith("glm.zero_inflated"):
            _choice(self.response_semantics, "nonnegative_integer_count_v1", "response_semantics")
            _choice(self.zero_process_semantics, "mixture_structural_zero_v1", "zero_process_semantics")
            _choice(self.count_link, "log", "count_link")
            _choice(self.zero_link, "logit", "zero_link")
            _choice(self.positive_count_link, "not_applicable", "positive_count_link")
            _choice(self.mean_link, "not_applicable", "mean_link")
            _choice(self.precision_link, "not_applicable", "precision_link")
        else:
            _choice(self.response_semantics, "nonnegative_integer_count_v1", "response_semantics")
            _choice(self.zero_process_semantics, "separate_zero_gate_truncated_count_v1", "zero_process_semantics")
            _choice(self.count_link, "not_applicable", "count_link")
            _choice(self.zero_link, "logit", "zero_link")
            _choice(self.positive_count_link, "log", "positive_count_link")
            _choice(self.mean_link, "not_applicable", "mean_link")
            _choice(self.precision_link, "not_applicable", "precision_link")
        _choice(self.matrix_semantics, "rows_are_observations_columns_are_predictors_v1", "matrix_semantics")
        _choice(self.missing_policy, "reject_nonfinite_v1", "missing_policy")
        _choice(self.offset_policy, "none_v1", "offset_policy")
        _choice(self.optimizer, "bfgs", "optimizer")
        if type(self.intercept) is not bool:
            raise ContractError("intercept must be boolean")
        if type(self.maxiter) is not int or self.maxiter < 1 or self.maxiter > 10_000:
            raise ContractError("maxiter must be a positive bounded integer")
        _positive_number(self.tolerance, "tolerance")
        _positive_number(self.max_abs_linear_predictor, "max_abs_linear_predictor")
        object.__setattr__(self, "predictor_columns", predictor)
        for field in ("zero_predictor_columns", "positive_predictor_columns", "precision_predictor_columns"):
            object.__setattr__(self, field, _columns(getattr(self, field), field))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GLMExtensionRequest":
        require_exact_keys(value, _INPUT_FIELDS, "glm extension request")
        return cls(
            operation_id=value["operation_id"],
            predictor_columns=_columns(value["predictor_columns"], "predictor_columns", allow_none=False) or (),
            zero_predictor_columns=_columns(value["zero_predictor_columns"], "zero_predictor_columns"),
            positive_predictor_columns=_columns(value["positive_predictor_columns"], "positive_predictor_columns"),
            precision_predictor_columns=_columns(value["precision_predictor_columns"], "precision_predictor_columns"),
            matrix_semantics=value["matrix_semantics"], response_semantics=value["response_semantics"],
            zero_process_semantics=value["zero_process_semantics"], count_link=value["count_link"],
            zero_link=value["zero_link"], positive_count_link=value["positive_count_link"],
            mean_link=value["mean_link"], precision_link=value["precision_link"],
            intercept=value["intercept"], missing_policy=value["missing_policy"],
            offset_policy=value["offset_policy"], optimizer=value["optimizer"],
            maxiter=value["maxiter"], tolerance=value["tolerance"],
            max_abs_linear_predictor=value["max_abs_linear_predictor"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "predictor_columns": list(self.predictor_columns),
            "zero_predictor_columns": None if self.zero_predictor_columns is None else list(self.zero_predictor_columns),
            "positive_predictor_columns": None if self.positive_predictor_columns is None else list(self.positive_predictor_columns),
            "precision_predictor_columns": None if self.precision_predictor_columns is None else list(self.precision_predictor_columns),
            "matrix_semantics": self.matrix_semantics, "response_semantics": self.response_semantics,
            "zero_process_semantics": self.zero_process_semantics, "count_link": self.count_link,
            "zero_link": self.zero_link, "positive_count_link": self.positive_count_link,
            "mean_link": self.mean_link, "precision_link": self.precision_link,
            "intercept": self.intercept, "missing_policy": self.missing_policy,
            "offset_policy": self.offset_policy, "optimizer": self.optimizer,
            "maxiter": self.maxiter, "tolerance": self.tolerance,
            "max_abs_linear_predictor": self.max_abs_linear_predictor,
        }


def _reject_raw(value: Any, path: str = "result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _RAW_KEYS:
                raise ContractError(f"{path}.{key} must not expose raw GLM inputs")
            _reject_raw(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw(item, f"{path}[{index}]")


def _status_reason(status: Any, reason: Any) -> None:
    allowed = {
        "completed": {"ANALYSIS_COMPLETED"},
        "rejected": {"GLM_EXTENSION_REJECTED", "GLM_BAD_INPUT"},
        "failed": {"GLM_EXTENSION_FAILED", "GLM_NONCONVERGENCE", "GLM_NUMERICAL_FAILURE"},
    }.get(status)
    if allowed is None or reason not in allowed:
        raise ContractError("reason_code must match status")


def _validate_hurdle_inference(result: Mapping[str, Any]) -> None:
    inference = result.get("inference")
    positive = inference.get("positive_count") if isinstance(inference, Mapping) else None
    expected = {
        "standard_error_method": "bfgs_inverse_hessian_approximation",
        "p_value_method": "normal_wald_approximation",
        "p_value_status": "approximate",
    }
    if not isinstance(positive, Mapping) or dict(positive) != expected:
        raise ContractError(
            "hurdle positive-count inference metadata must declare its approximation"
        )


@dataclass(frozen=True)
class GLMExtensionResultEnvelope:
    operation_id: str
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.operation_id not in GLM_EXTENSION_OPERATION_IDS:
            raise ContractError("operation_id is not a declared GLM extension")
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        frozen = freeze_json(self.result, "result")
        _reject_raw(frozen)
        if "status" not in frozen or "reason_code" not in frozen:
            raise ContractError("GLM result requires status and reason_code")
        _status_reason(frozen["status"], frozen["reason_code"])
        if frozen["status"] == "completed":
            for field in ("model_family", "n_observations", "predictor_columns", "policy", "fit", "coefficient_estimands", "mean_estimands", "zero_probability_estimands", "scope", "diagnostics"):
                if field not in frozen:
                    raise ContractError(f"completed GLM result requires {field}")
            P7ScopeMetadata.from_dict(frozen["scope"])
            if self.operation_id.startswith("glm.hurdle_"):
                _validate_hurdle_inference(frozen)
        object.__setattr__(self, "result", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {"contract": GLM_EXTENSION_CONTRACT, "contract_version": GLM_EXTENSION_CONTRACT_VERSION, "operation_id": self.operation_id, "result": thaw_json(self.result)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GLMExtensionResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "glm extension result envelope")
        if value["contract"] != GLM_EXTENSION_CONTRACT or value["contract_version"] != GLM_EXTENSION_CONTRACT_VERSION:
            raise ContractError("GLM extension contract or version is not declared")
        return cls(operation_id=value["operation_id"], result=value["result"])


__all__ = ["GLM_EXTENSION_CONTRACT", "GLM_EXTENSION_CONTRACT_VERSION", "GLM_EXTENSION_OPERATION_IDS", "GLM_EXTENSION_REASON_CODES", "GLMExtensionRequest", "GLMExtensionResultEnvelope"]
