"""Versioned, JSON-safe contracts for missing-data evidence and MI pooling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from workbench.contracts.common.envelope import ContractError


MISSING_DATA_CONTRACT = "missing_data.result"
MISSING_DATA_CONTRACT_VERSION = "1.0"
MISSING_DATA_OPERATION_IDS = frozenset(
    {"missingness.profile", "missing_data.rubin_pool"}
)
MISSING_DATA_STATUSES = frozenset({"completed", "rejected", "failed"})
MISSING_DATA_REASON_CODES = frozenset(
    {
        "MISSING_DATA_DIAGNOSTICS_COMPLETED",
        "MISSING_DATA_RUBIN_COMPLETED",
        "MISSING_DATA_INVALID_INPUT",
        "MISSING_DATA_INVALID_VARIANCE",
        "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
        "MISSING_DATA_COEFFICIENT_MISMATCH",
        "MISSING_DATA_TOO_FEW_IMPUTATIONS",
        "MISSING_DATA_FAILED",
    }
)

_CORE_FIELDS = frozenset(
    {"contract", "contract_version", "operation_id", "status", "reason_code"}
)
_STATUS_REASON = {
    "completed": {
        "MISSING_DATA_DIAGNOSTICS_COMPLETED",
        "MISSING_DATA_RUBIN_COMPLETED",
    },
    "rejected": {
        "MISSING_DATA_INVALID_INPUT",
        "MISSING_DATA_INVALID_VARIANCE",
        "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
        "MISSING_DATA_COEFFICIENT_MISMATCH",
        "MISSING_DATA_TOO_FEW_IMPUTATIONS",
    },
    "failed": {"MISSING_DATA_FAILED"},
}


def make_missing_data_result(
    *, operation_id: str, status: str, reason_code: str, **fields: Any
) -> dict[str, Any]:
    """Build a public result with a closed operation/status/reason vocabulary."""

    payload = {
        "contract": MISSING_DATA_CONTRACT,
        "contract_version": MISSING_DATA_CONTRACT_VERSION,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        **fields,
    }
    validate_missing_data_result(payload)
    return payload


def validate_missing_data_result(value: Mapping[str, Any]) -> None:
    """Validate the shared envelope while leaving operation payloads extensible."""

    if not isinstance(value, Mapping):
        raise ContractError("missing-data result must be a mapping")
    missing = _CORE_FIELDS - set(value)
    if missing:
        raise ContractError("missing missing-data result field(s): " + ", ".join(sorted(missing)))
    if value["contract"] != MISSING_DATA_CONTRACT:
        raise ContractError("missing-data result contract is not declared")
    if value["contract_version"] != MISSING_DATA_CONTRACT_VERSION:
        raise ContractError("missing-data result version is not supported")
    operation_id = value["operation_id"]
    if type(operation_id) is not str or operation_id not in MISSING_DATA_OPERATION_IDS:
        raise ContractError("missing-data operation_id is not declared")
    status = value["status"]
    if type(status) is not str or status not in MISSING_DATA_STATUSES:
        raise ContractError("missing-data status is not declared")
    reason_code = value["reason_code"]
    if type(reason_code) is not str or reason_code not in MISSING_DATA_REASON_CODES:
        raise ContractError("missing-data reason_code is not declared")
    if reason_code not in _STATUS_REASON[status]:
        raise ContractError("missing-data status and reason_code do not agree")


__all__ = [
    "MISSING_DATA_CONTRACT",
    "MISSING_DATA_CONTRACT_VERSION",
    "MISSING_DATA_OPERATION_IDS",
    "MISSING_DATA_REASON_CODES",
    "MISSING_DATA_STATUSES",
    "make_missing_data_result",
    "validate_missing_data_result",
]
