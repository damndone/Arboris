"""Versioned contracts for the standalone repeated-measures ANOVA pack."""

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


REPEATED_MEASURES_ANOVA_CONTRACT = "repeated_measures_anova.result"
REPEATED_MEASURES_ANOVA_CONTRACT_VERSION = "1.0"
REPEATED_ONLY_OPERATION_ID = "repeated_measures_anova.repeated_only"
MIXED_DESIGN_OPERATION_ID = "repeated_measures_anova.mixed_design"
REPEATED_MEASURES_ANOVA_OPERATION_IDS = frozenset(
    {REPEATED_ONLY_OPERATION_ID, MIXED_DESIGN_OPERATION_ID}
)
REPEATED_MEASURES_ANOVA_CORRECTIONS = frozenset(
    {"none", "greenhouse_geisser", "huynh_feldt"}
)
REPEATED_MEASURES_ANOVA_STATUSES = frozenset(
    {"completed", "rejected", "failed"}
)

REPEATED_MEASURES_ANOVA_COMPLETED = "REPEATED_MEASURES_ANOVA_COMPLETED"
REPEATED_MEASURES_ANOVA_REASON_CODES = frozenset(
    {
        REPEATED_MEASURES_ANOVA_COMPLETED,
        "REPEATED_MEASURES_ANOVA_BAD_INPUT",
        "REPEATED_MEASURES_ANOVA_UNKNOWN_OPERATION",
        "REPEATED_MEASURES_ANOVA_INVALID_DESIGN",
        "REPEATED_MEASURES_ANOVA_MULTIPLE_BETWEEN_FACTORS",
        "REPEATED_MEASURES_ANOVA_UNSUPPORTED_WITHIN_FACTORS",
        "REPEATED_MEASURES_ANOVA_UNSUPPORTED_FORMULA",
        "REPEATED_MEASURES_ANOVA_INVALID_CORRECTION",
        "REPEATED_MEASURES_ANOVA_MISSING_COLUMN",
        "REPEATED_MEASURES_ANOVA_NON_NUMERIC_RESPONSE",
        "REPEATED_MEASURES_ANOVA_NON_FINITE_RESPONSE",
        "REPEATED_MEASURES_ANOVA_EMPTY_LEVEL",
        "REPEATED_MEASURES_ANOVA_DUPLICATE_COLUMN",
        "REPEATED_MEASURES_ANOVA_DUPLICATE_CELL",
        "REPEATED_MEASURES_ANOVA_INCOMPLETE_BALANCE",
        "REPEATED_MEASURES_ANOVA_INCONSISTENT_BETWEEN_LABEL",
        "REPEATED_MEASURES_ANOVA_INVALID_LEVEL",
        "REPEATED_MEASURES_ANOVA_TOO_FEW_SUBJECTS",
        "REPEATED_MEASURES_ANOVA_TOO_FEW_LEVELS",
        "REPEATED_MEASURES_ANOVA_BOUND_EXCEEDED",
        "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
        "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
        "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
    }
)

_INPUT_FIELDS = {
    "operation_id",
    "response_column",
    "subject_column",
    "within_factor_columns",
    "between_factor_column",
    "correction",
}
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
    if type(value) is not str or value not in REPEATED_MEASURES_ANOVA_OPERATION_IDS:
        raise ContractError("operation_id is not a declared repeated-measures operation")


def _normalize_within_factor_columns(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError("within_factor_columns must be an array of column names")
    columns = tuple(value)
    if len(columns) != 1:
        raise ContractError(
            "within_factor_columns must contain exactly one column in this version"
        )
    if any(type(column) is not str or not column for column in columns):
        raise ContractError(
            "within_factor_columns must contain non-empty strings"
        )
    if len(set(columns)) != len(columns):
        raise ContractError("within_factor_columns must not contain duplicates")
    return columns


def _normalize_result_columns(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError("columns must be an array of strings")
    columns = tuple(value)
    if any(type(column) is not str or not column for column in columns):
        raise ContractError("columns must contain only non-empty strings")
    if len(set(columns)) != len(columns):
        raise ContractError("columns must not contain duplicates")
    return columns


@dataclass(frozen=True)
class RepeatedMeasuresAnovaInput:
    """Explicit structured declaration for one bounded ANOVA design."""

    operation_id: str
    response_column: str
    subject_column: str
    within_factor_columns: tuple[str, ...]
    between_factor_column: str | None
    correction: str

    def __post_init__(self) -> None:
        _require_operation_id(self.operation_id)
        _require_non_empty_string(self.response_column, "response_column")
        _require_non_empty_string(self.subject_column, "subject_column")
        normalized_within = _normalize_within_factor_columns(self.within_factor_columns)
        if self.response_column == self.subject_column:
            raise ContractError("response_column and subject_column must differ")
        if self.response_column in normalized_within:
            raise ContractError("response_column must differ from within_factor_columns")
        if self.subject_column in normalized_within:
            raise ContractError("subject_column must differ from within_factor_columns")
        if (
            type(self.correction) is not str
            or self.correction not in REPEATED_MEASURES_ANOVA_CORRECTIONS
        ):
            raise ContractError("correction is not a declared repeated-measures policy")

        if self.operation_id == MIXED_DESIGN_OPERATION_ID:
            _require_non_empty_string(self.between_factor_column, "between_factor_column")
            if self.between_factor_column in {
                self.response_column,
                self.subject_column,
                *normalized_within,
            }:
                raise ContractError("between_factor_column must be a distinct column")
        elif self.between_factor_column is not None:
            raise ContractError(
                "between_factor_column must be null for repeated-only operation"
            )

        object.__setattr__(self, "within_factor_columns", normalized_within)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "response_column": self.response_column,
            "subject_column": self.subject_column,
            "within_factor_columns": list(self.within_factor_columns),
            "between_factor_column": self.between_factor_column,
            "correction": self.correction,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepeatedMeasuresAnovaInput":
        require_exact_keys(value, _INPUT_FIELDS, "repeated-measures input")
        return cls(
            operation_id=value["operation_id"],
            response_column=value["response_column"],
            subject_column=value["subject_column"],
            within_factor_columns=_normalize_within_factor_columns(
                value["within_factor_columns"]
            ),
            between_factor_column=value["between_factor_column"],
            correction=value["correction"],
        )


@dataclass(frozen=True)
class RepeatedMeasuresAnovaResultEnvelope:
    """Immutable JSON-safe result envelope for both declared operations."""

    operation_id: str
    status: str
    reason_code: str
    n_observations: int
    columns: tuple[str, ...]
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_operation_id(self.operation_id)
        if (
            type(self.status) is not str
            or self.status not in REPEATED_MEASURES_ANOVA_STATUSES
        ):
            raise ContractError("status is not a declared repeated-measures status")
        if (
            type(self.reason_code) is not str
            or self.reason_code not in REPEATED_MEASURES_ANOVA_REASON_CODES
        ):
            raise ContractError("reason_code is not a declared repeated-measures reason")
        if self.status == "completed" and self.reason_code != REPEATED_MEASURES_ANOVA_COMPLETED:
            raise ContractError("completed results require the completed reason code")
        if self.status != "completed" and self.reason_code == REPEATED_MEASURES_ANOVA_COMPLETED:
            raise ContractError("rejected or failed results require an error reason code")
        if type(self.n_observations) is not int or self.n_observations < 0:
            raise ContractError("n_observations must be a non-negative integer")
        normalized_columns = _normalize_result_columns(self.columns)
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        object.__setattr__(self, "columns", normalized_columns)
        object.__setattr__(self, "result", freeze_json(self.result, "result"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": REPEATED_MEASURES_ANOVA_CONTRACT,
            "contract_version": REPEATED_MEASURES_ANOVA_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "n_observations": self.n_observations,
            "columns": list(self.columns),
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepeatedMeasuresAnovaResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "repeated-measures result envelope")
        if value["contract"] != REPEATED_MEASURES_ANOVA_CONTRACT:
            raise ContractError(
                "contract is not the declared repeated-measures result contract"
            )
        if value["contract_version"] != REPEATED_MEASURES_ANOVA_CONTRACT_VERSION:
            raise ContractError(
                "contract_version is not the declared repeated-measures version"
            )
        return cls(
            operation_id=value["operation_id"],
            status=value["status"],
            reason_code=value["reason_code"],
            n_observations=value["n_observations"],
            columns=_normalize_result_columns(value["columns"]),
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
    """Validate and return a mutable JSON-shaped public envelope."""

    normalized_columns = _normalize_result_columns(columns)
    return RepeatedMeasuresAnovaResultEnvelope(
        operation_id=operation_id,
        status=status,
        reason_code=reason_code,
        n_observations=n_observations,
        columns=normalized_columns,
        result=result,
    ).to_dict()


__all__ = [
    "MIXED_DESIGN_OPERATION_ID",
    "REPEATED_MEASURES_ANOVA_COMPLETED",
    "REPEATED_MEASURES_ANOVA_CONTRACT",
    "REPEATED_MEASURES_ANOVA_CONTRACT_VERSION",
    "REPEATED_MEASURES_ANOVA_CORRECTIONS",
    "REPEATED_MEASURES_ANOVA_OPERATION_IDS",
    "REPEATED_MEASURES_ANOVA_REASON_CODES",
    "REPEATED_MEASURES_ANOVA_STATUSES",
    "REPEATED_ONLY_OPERATION_ID",
    "RepeatedMeasuresAnovaInput",
    "RepeatedMeasuresAnovaResultEnvelope",
    "make_result_envelope",
]
