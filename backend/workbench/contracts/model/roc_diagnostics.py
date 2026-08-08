"""Versioned contracts for the standalone score-only ROC diagnostics pack."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from typing import Any

from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


ROC_DIAGNOSTICS_CONTRACT = "roc_diagnostics.result"
ROC_DIAGNOSTICS_CONTRACT_VERSION = "1.0"
ROC_DIAGNOSTICS_OPERATION_IDS = frozenset({"roc.curve", "roc.calibration"})
ROC_DIAGNOSTICS_STATUSES = frozenset({"completed", "rejected", "failed"})
ROC_DIAGNOSTICS_COMPLETED = "ROC_DIAGNOSTICS_COMPLETED"
ROC_DIAGNOSTICS_REJECTED = "ROC_DIAGNOSTICS_REJECTED"
ROC_DIAGNOSTICS_FAILED = "ROC_DIAGNOSTICS_FAILED"
ROC_DIAGNOSTICS_REASON_CODES = frozenset(
    {
        ROC_DIAGNOSTICS_COMPLETED,
        ROC_DIAGNOSTICS_REJECTED,
        ROC_DIAGNOSTICS_FAILED,
    }
)
ROC_SCORE_SEMANTICS = frozenset({"score", "probability"})
ROC_THRESHOLD_POLICIES = frozenset({"unique_scores", "quantile_grid"})
ROC_MISSING_POLICIES = frozenset({"reject", "drop_explicit"})
ROC_CALIBRATION_METHODS = frozenset({"equal_width", "quantile"})

ROC_CURVE_RESULT_FIELDS = frozenset(
    {
        "score_semantics",
        "positive_label",
        "negative_label",
        "n_observations",
        "missing_metadata",
        "threshold_policy",
        "tie_policy",
        "auc_method",
        "auc",
        "auc_alias_of",
        "auc_semantics",
        "exact_auc",
        "exact_auc_method",
        "sampled_roc_auc",
        "sampled_roc_auc_method",
        "sampled_roc_auc_semantics",
        "roc_points",
        "pr_points",
        "pr_auc",
        "pr_auc_alias_of",
        "pr_auc_method",
        "pr_auc_semantics",
        "sampled_pr_auc",
        "sampled_pr_auc_method",
        "sampled_pr_auc_semantics",
        "threshold_evidence",
        "brier_score",
        "log_loss",
        "log_loss_defined",
        "probability_metrics",
        "decision_evidence",
    }
)
ROC_CALIBRATION_RESULT_FIELDS = frozenset(
    {
        "score_semantics",
        "positive_label",
        "negative_label",
        "n_observations",
        "missing_metadata",
        "calibration_method",
        "requested_bins",
        "bins",
        "brier_score",
        "log_loss",
        "log_loss_defined",
        "probability_metrics",
    }
)
ROC_OPERATION_RESULT_FIELDS = {
    "roc.curve": ROC_CURVE_RESULT_FIELDS,
    "roc.calibration": ROC_CALIBRATION_RESULT_FIELDS,
}
ROC_ERROR_RESULT_FIELDS = frozenset({"error_code", "message"})
_PROTECTED_PROVENANCE_FIELDS = {
    "pack": "roc_diagnostics",
    "runtime": "score_only",
    "implementation": "numpy",
    "contract_version": ROC_DIAGNOSTICS_CONTRACT_VERSION,
}

_RESULT_FIELDS = {
    "contract",
    "contract_version",
    "operation_id",
    "status",
    "reason_code",
    "result",
    "provenance",
}


def _require_fields(
    value: Mapping[str, Any], required: frozenset[str], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be a mapping")
    missing = required - set(value)
    if missing:
        raise ContractError(f"missing {label} field(s): {', '.join(sorted(missing))}")


def _validate_error_result(value: Mapping[str, Any]) -> None:
    _require_fields(value, ROC_ERROR_RESULT_FIELDS, "ROC diagnostics error result")
    if type(value["error_code"]) is not str or not value["error_code"]:
        raise ContractError("ROC diagnostics error_code must be a non-empty string")
    if type(value["message"]) is not str or not value["message"]:
        raise ContractError("ROC diagnostics error message must be a non-empty string")


def _validate_provenance(value: Mapping[str, Any]) -> None:
    for key, expected in _PROTECTED_PROVENANCE_FIELDS.items():
        if key in value and (
            type(value[key]) is not str or value[key] != expected
        ):
            raise ContractError(f"provenance field {key} is reserved")


def _validate_curve_auc_aliases(value: Mapping[str, Any]) -> None:
    for field_name, alias_name in (
        ("auc", "exact_auc"),
        ("pr_auc", "sampled_pr_auc"),
    ):
        field_value = value[field_name]
        alias_value = value[alias_name]
        if type(field_value) not in {int, float} or not math.isfinite(field_value):
            raise ContractError(f"{field_name} must be a finite number")
        if type(alias_value) not in {int, float} or not math.isfinite(alias_value):
            raise ContractError(f"{alias_name} must be a finite number")
        if field_value != alias_value:
            raise ContractError(f"{field_name} must equal {alias_name}")


def _validate_metric_semantics(
    operation_id: str,
    status: str,
    result: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    if status == "completed" and operation_id == "roc.curve":
        _validate_curve_auc_aliases(result)

    metric_semantics = provenance.get("metric_semantics")
    if metric_semantics is None:
        return
    if type(metric_semantics) is not str:
        raise ContractError("provenance metric_semantics must be a declared string")

    if status == "completed" and operation_id == "roc.curve":
        threshold_policy = result["threshold_policy"]
        if not isinstance(threshold_policy, Mapping):
            raise ContractError("roc.curve threshold_policy must be a mapping")
        policy_name = threshold_policy.get("name")
        expected = {
            "unique_scores": "exact_rank_auc_and_unique_threshold_sampled_areas",
            "quantile_grid": "exact_rank_auc_and_grid_based_sampled_areas",
        }.get(policy_name)
        if expected is None:
            raise ContractError(
                "roc.curve metric_semantics is inconsistent with threshold_policy"
            )
    elif status == "completed" and operation_id == "roc.calibration":
        expected = "probability_calibration"
    else:
        expected = {
            "rejected": "dispatcher_rejection",
            "failed": "dispatcher_failure",
        }[status]

    if metric_semantics != expected:
        raise ContractError(
            "provenance metric_semantics is inconsistent with the ROC operation"
        )


def _validate_status_reason(status: Any, reason_code: Any) -> None:
    if type(status) is not str or status not in ROC_DIAGNOSTICS_STATUSES:
        raise ContractError("status is not a declared ROC diagnostics status")
    if type(reason_code) is not str or reason_code not in ROC_DIAGNOSTICS_REASON_CODES:
        raise ContractError("reason_code is not a declared ROC diagnostics reason")
    expected = {
        "completed": ROC_DIAGNOSTICS_COMPLETED,
        "rejected": ROC_DIAGNOSTICS_REJECTED,
        "failed": ROC_DIAGNOSTICS_FAILED,
    }[status]
    if reason_code != expected:
        raise ContractError("status and reason_code are inconsistent")


@dataclass(frozen=True)
class RocDiagnosticsInput:
    """JSON-shaped policy input for either closed diagnostics operation."""

    operation_id: str
    positive_label: Any
    score_semantics: str = "score"
    threshold_policy: str = "unique_scores"
    missing_policy: str = "reject"
    calibration_method: str | None = None
    n_bins: int | None = None
    quantile_grid_size: int | None = None

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or self.operation_id not in ROC_DIAGNOSTICS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared ROC diagnostics operation")
        if type(self.score_semantics) is not str or self.score_semantics not in ROC_SCORE_SEMANTICS:
            raise ContractError("score_semantics is not declared")
        if type(self.threshold_policy) is not str or self.threshold_policy not in ROC_THRESHOLD_POLICIES:
            raise ContractError("threshold_policy is not declared")
        if type(self.missing_policy) is not str or self.missing_policy not in ROC_MISSING_POLICIES:
            raise ContractError("missing_policy is not declared")
        if self.calibration_method is not None and (
            type(self.calibration_method) is not str
            or self.calibration_method not in ROC_CALIBRATION_METHODS
        ):
            raise ContractError("calibration_method is not declared")
        for field_name, value in (("n_bins", self.n_bins), ("quantile_grid_size", self.quantile_grid_size)):
            if value is not None and (type(value) is not int or value < 1):
                raise ContractError(f"{field_name} must be a positive integer or null")
        if self.operation_id == "roc.calibration":
            if self.score_semantics != "probability":
                raise ContractError("roc.calibration score_semantics must be probability")
            if self.calibration_method is None:
                raise ContractError("roc.calibration calibration_method must be explicit")
            if self.n_bins is None:
                raise ContractError("roc.calibration n_bins must be explicit")
        freeze_json(self.positive_label, "positive_label")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "positive_label": thaw_json(freeze_json(self.positive_label, "positive_label")),
            "score_semantics": self.score_semantics,
            "threshold_policy": self.threshold_policy,
            "missing_policy": self.missing_policy,
            "calibration_method": self.calibration_method,
            "n_bins": self.n_bins,
            "quantile_grid_size": self.quantile_grid_size,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RocDiagnosticsInput":
        require_exact_keys(
            value,
            {
                "operation_id",
                "positive_label",
                "score_semantics",
                "threshold_policy",
                "missing_policy",
                "calibration_method",
                "n_bins",
                "quantile_grid_size",
            },
            "ROC diagnostics input",
        )
        return cls(**dict(value))


@dataclass(frozen=True)
class RocDiagnosticsResultEnvelope:
    """Immutable, JSON-safe result envelope shared by both ROC operations."""

    operation_id: str
    result: Mapping[str, Any]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    status: str = "completed"
    reason_code: str = ROC_DIAGNOSTICS_COMPLETED

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or self.operation_id not in ROC_DIAGNOSTICS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared ROC diagnostics operation")
        _validate_status_reason(self.status, self.reason_code)
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        if not isinstance(self.provenance, Mapping):
            raise ContractError("provenance must be a mapping")
        frozen_result = freeze_json(self.result, "result")
        frozen_provenance = freeze_json(self.provenance, "provenance")
        _validate_provenance(frozen_provenance)
        if self.status == "completed":
            _require_fields(
                frozen_result,
                ROC_OPERATION_RESULT_FIELDS[self.operation_id],
                f"{self.operation_id} result",
            )
        else:
            _validate_error_result(frozen_result)
        _validate_metric_semantics(
            self.operation_id,
            self.status,
            frozen_result,
            frozen_provenance,
        )
        object.__setattr__(self, "result", frozen_result)
        object.__setattr__(self, "provenance", frozen_provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": ROC_DIAGNOSTICS_CONTRACT,
            "contract_version": ROC_DIAGNOSTICS_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "result": thaw_json(self.result),
            "provenance": thaw_json(self.provenance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RocDiagnosticsResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "ROC diagnostics result")
        if value["contract"] != ROC_DIAGNOSTICS_CONTRACT:
            raise ContractError("contract is not the declared ROC diagnostics contract")
        if value["contract_version"] != ROC_DIAGNOSTICS_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared ROC diagnostics version")
        return cls(
            operation_id=value["operation_id"],
            status=value["status"],
            reason_code=value["reason_code"],
            result=value["result"],
            provenance=value["provenance"],
        )


def make_result_envelope(
    *,
    operation_id: str,
    result: Mapping[str, Any],
    provenance: Mapping[str, Any],
    status: str = "completed",
    reason_code: str = ROC_DIAGNOSTICS_COMPLETED,
) -> dict[str, Any]:
    return RocDiagnosticsResultEnvelope(
        operation_id=operation_id,
        result=result,
        provenance=provenance,
        status=status,
        reason_code=reason_code,
    ).to_dict()


def make_error_envelope(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    error_code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if type(status) is not str or status not in {"rejected", "failed"}:
        raise ContractError("error envelope status must be rejected or failed")
    result: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
    }
    if details is not None:
        result["details"] = details
    return RocDiagnosticsResultEnvelope(
        operation_id=operation_id,
        result=result,
        provenance={} if provenance is None else provenance,
        status=status,
        reason_code=reason_code,
    ).to_dict()


__all__ = [
    "ROC_CALIBRATION_METHODS",
    "ROC_CALIBRATION_RESULT_FIELDS",
    "ROC_CURVE_RESULT_FIELDS",
    "ROC_DIAGNOSTICS_COMPLETED",
    "ROC_DIAGNOSTICS_CONTRACT",
    "ROC_DIAGNOSTICS_CONTRACT_VERSION",
    "ROC_DIAGNOSTICS_FAILED",
    "ROC_DIAGNOSTICS_OPERATION_IDS",
    "ROC_DIAGNOSTICS_REASON_CODES",
    "ROC_DIAGNOSTICS_REJECTED",
    "ROC_DIAGNOSTICS_STATUSES",
    "ROC_ERROR_RESULT_FIELDS",
    "ROC_MISSING_POLICIES",
    "ROC_OPERATION_RESULT_FIELDS",
    "ROC_SCORE_SEMANTICS",
    "ROC_THRESHOLD_POLICIES",
    "RocDiagnosticsInput",
    "RocDiagnosticsResultEnvelope",
    "make_error_envelope",
    "make_result_envelope",
]
