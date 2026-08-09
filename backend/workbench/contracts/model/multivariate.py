"""Versioned, JSON-safe contracts for the standalone multivariate pack.

This module deliberately contains no data loading, Agent registration, or
statistical execution.  It is the future CapabilityContract seam: callers can
declare an operation and its explicit missing-data policy before a kernel runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


MULTIVARIATE_CONTRACT = "multivariate.result"
MULTIVARIATE_CONTRACT_VERSION = "1.0"
MULTIVARIATE_OPERATION_IDS = frozenset(
    {
        "multivariate.pca",
        "multivariate.efa",
        "multivariate.cronbach_alpha",
    }
)
MULTIVARIATE_EXTENSION_OPERATION_IDS = frozenset(
    {
        "multivariate.clustering",
        "multivariate.discriminant",
        "multivariate.correspondence",
        "multivariate.mca",
        "multivariate.manova",
    }
)
MULTIVARIATE_ALL_OPERATION_IDS = (
    MULTIVARIATE_OPERATION_IDS | MULTIVARIATE_EXTENSION_OPERATION_IDS
)
MULTIVARIATE_MISSING_POLICIES = frozenset({"complete_case_v1"})
MULTIVARIATE_STATUSES = frozenset({"completed", "rejected", "failed"})
MULTIVARIATE_REASON_CODES = frozenset(
    {
        "ANALYSIS_COMPLETED",
        "MULTIVARIATE_BAD_INPUT",
        "MULTIVARIATE_UNKNOWN_OPERATION",
        "MULTIVARIATE_UNSUPPORTED_MISSING_POLICY",
        "MULTIVARIATE_TOO_FEW_COLUMNS",
        "MULTIVARIATE_TOO_FEW_OBSERVATIONS",
        "MULTIVARIATE_NON_NUMERIC_COLUMN",
        "MULTIVARIATE_NON_FINITE_VALUE",
        "MULTIVARIATE_NO_COMPLETE_CASES",
        "MULTIVARIATE_MISSING_COLUMN",
        "MULTIVARIATE_DUPLICATE_COLUMN",
        "MULTIVARIATE_UNSUPPORTED_OPTION",
        "MULTIVARIATE_INVALID_OPTION",
        "MULTIVARIATE_NUMERIC_DEGENERACY",
        "MULTIVARIATE_FACTORABILITY_FAILED",
        "MULTIVARIATE_INSUFFICIENT_VARIANCE",
        "MULTIVARIATE_TOO_FEW_CATEGORIES",
        "MULTIVARIATE_INVALID_CATEGORY_TABLE",
        "MULTIVARIATE_ZERO_MARGIN",
        "MULTIVARIATE_CATEGORY_OVERFLOW",
        "MULTIVARIATE_INVALID_DIMENSIONS",
        "MULTIVARIATE_INVALID_CATEGORY_LABEL",
        "MULTIVARIATE_DUPLICATE_CATEGORY_LABEL",
        "MULTIVARIATE_INVALID_CATEGORY",
        "MULTIVARIATE_OUTPUT_TOO_LARGE",
        "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
        "MULTIVARIATE_SINGULAR_DESIGN",
        "MULTIVARIATE_INSUFFICIENT_RESIDUAL_DF",
    }
)

_INPUT_FIELDS = {"operation_id", "columns", "missing_policy"}
_RESULT_FIELDS = {
    "contract",
    "contract_version",
    "operation_id",
    "status",
    "reason_code",
    "n_observations",
    "columns",
    "result",
}


def _require_non_empty_string(value: Any, field_name: str) -> None:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")


def _require_operation_id(value: Any) -> None:
    if type(value) is not str or value not in MULTIVARIATE_ALL_OPERATION_IDS:
        raise ContractError("operation_id is not a declared multivariate operation")


def _normalize_columns(value: Sequence[str], field_name: str = "columns") -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{field_name} must be an array of strings")
    columns = tuple(value)
    if len(columns) < 2 or any(type(column) is not str or not column for column in columns):
        raise ContractError(f"{field_name} must contain at least two non-empty strings")
    if len(set(columns)) != len(columns):
        raise ContractError(f"{field_name} must not contain duplicates")
    return columns


@dataclass(frozen=True)
class MultivariateInput:
    """Explicit operation declaration for a multivariate kernel call."""

    operation_id: str
    columns: tuple[str, ...]
    missing_policy: str

    def __post_init__(self) -> None:
        _require_operation_id(self.operation_id)
        normalized_columns = _normalize_columns(self.columns)
        if self.missing_policy not in MULTIVARIATE_MISSING_POLICIES:
            raise ContractError("missing_policy is not a declared multivariate policy")
        object.__setattr__(self, "columns", normalized_columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "columns": list(self.columns),
            "missing_policy": self.missing_policy,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultivariateInput":
        require_exact_keys(value, _INPUT_FIELDS, "multivariate input")
        return cls(
            operation_id=value["operation_id"],
            columns=_normalize_columns(value["columns"]),
            missing_policy=value["missing_policy"],
        )


@dataclass(frozen=True)
class MultivariateResultEnvelope:
    """Immutable result envelope shared by all standalone multivariate kernels."""

    operation_id: str
    status: str
    reason_code: str
    n_observations: int
    columns: tuple[str, ...]
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_operation_id(self.operation_id)
        if self.status not in MULTIVARIATE_STATUSES:
            raise ContractError("status is not a declared multivariate status")
        if self.reason_code not in MULTIVARIATE_REASON_CODES:
            raise ContractError("reason_code is not a declared multivariate reason")
        if type(self.n_observations) is not int or self.n_observations < 0:
            raise ContractError("n_observations must be a non-negative integer")
        normalized_columns = _normalize_columns(self.columns)
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        object.__setattr__(self, "columns", normalized_columns)
        object.__setattr__(self, "result", freeze_json(self.result, "result"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": MULTIVARIATE_CONTRACT,
            "contract_version": MULTIVARIATE_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "n_observations": self.n_observations,
            "columns": list(self.columns),
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultivariateResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "multivariate result envelope")
        if value["contract"] != MULTIVARIATE_CONTRACT:
            raise ContractError("contract is not the declared multivariate result contract")
        if value["contract_version"] != MULTIVARIATE_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared multivariate version")
        return cls(
            operation_id=value["operation_id"],
            status=value["status"],
            reason_code=value["reason_code"],
            n_observations=value["n_observations"],
            columns=_normalize_columns(value["columns"]),
            result=value["result"],
        )


def make_result_envelope(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    n_observations: int,
    columns: Sequence[str],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and thaw a validated envelope at the kernel/public boundary."""

    return MultivariateResultEnvelope(
        operation_id=operation_id,
        status=status,
        reason_code=reason_code,
        n_observations=n_observations,
        columns=tuple(columns),
        result=result,
    ).to_dict()


__all__ = [
    "MULTIVARIATE_CONTRACT",
    "MULTIVARIATE_CONTRACT_VERSION",
    "MULTIVARIATE_ALL_OPERATION_IDS",
    "MULTIVARIATE_EXTENSION_OPERATION_IDS",
    "MULTIVARIATE_MISSING_POLICIES",
    "MULTIVARIATE_OPERATION_IDS",
    "MULTIVARIATE_REASON_CODES",
    "MultivariateInput",
    "MultivariateResultEnvelope",
    "make_result_envelope",
]
