"""Strict contract-only types for Time Series Diagnostics C1.

This module intentionally defines portable input/output contracts only.  It
does not load data, execute statistics, register a model, or expose a runtime
capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from workbench.contracts.common.envelope import ContractError, require_exact_keys


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


def _require_packet_ref_or_none(value: Any, field_name: str) -> None:
    if value is not None and (type(value) is not str or not value):
        raise ContractError(f"{field_name} must be a non-empty string or null")


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
