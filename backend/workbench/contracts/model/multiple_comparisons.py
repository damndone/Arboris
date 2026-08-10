"""Versioned, JSON-safe contract for standalone post-hoc comparisons."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json


MULTIPLE_COMPARISONS_CONTRACT = "multiple_comparisons.result"
MULTIPLE_COMPARISONS_CONTRACT_VERSION = "1.0"
MULTIPLE_COMPARISONS_OPERATION_IDS = frozenset(
    {"multiple_comparisons.scheffe", "multiple_comparisons.games_howell"}
)
MULTIPLE_COMPARISONS_STATUSES = frozenset({"completed", "rejected", "failed"})
MULTIPLE_COMPARISONS_REASON_CODES = frozenset(
    {
        "MULTIPLE_COMPARISONS_COMPLETED",
        "MULTIPLE_COMPARISONS_INVALID_INPUT",
        "MULTIPLE_COMPARISONS_TOO_FEW_GROUPS",
        "MULTIPLE_COMPARISONS_TOO_FEW_OBSERVATIONS",
        "MULTIPLE_COMPARISONS_DEGENERATE_VARIANCE",
        "MULTIPLE_COMPARISONS_NUMERICAL_FAILURE",
        "MULTIPLE_COMPARISONS_FAILED",
    }
)
_CORE_FIELDS = frozenset(
    {
        "contract",
        "contract_version",
        "operation_id",
        "status",
        "reason_code",
        "n_observations",
        "group_names",
        "result",
        "evidence_digest",
    }
)
_RAW_FIELDS = frozenset({"observations", "raw_rows", "raw_data", "group_values"})
_HEX = frozenset("0123456789abcdef")


class MultipleComparisonsContractError(ContractError):
    """Raised when a post-hoc result violates its public contract."""


def _validate_json(value: Any, label: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise MultipleComparisonsContractError(f"{label} must be finite")
        return
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise MultipleComparisonsContractError(f"{label} keys must be strings")
        if _RAW_FIELDS.intersection(value):
            raise MultipleComparisonsContractError(f"{label} contains raw observations")
        for key, child in value.items():
            _validate_json(child, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json(child, f"{label}[{index}]")
        return
    raise MultipleComparisonsContractError(f"{label} is not JSON-safe")


def _names(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MultipleComparisonsContractError("group_names must be an array of names")
    names = list(value)
    if not names or any(type(name) is not str or not name for name in names):
        raise MultipleComparisonsContractError("group_names must contain non-empty names")
    if len(set(names)) != len(names):
        raise MultipleComparisonsContractError("group_names must be unique")
    return names


def validate_multiple_comparisons_result(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise MultipleComparisonsContractError("multiple-comparisons result must be a mapping")
    unknown = set(value) - _CORE_FIELDS
    missing = _CORE_FIELDS - set(value)
    if unknown:
        raise MultipleComparisonsContractError("unknown result field(s): " + ", ".join(sorted(unknown)))
    if missing:
        raise MultipleComparisonsContractError("missing result field(s): " + ", ".join(sorted(missing)))
    if value["contract"] != MULTIPLE_COMPARISONS_CONTRACT:
        raise MultipleComparisonsContractError("contract is not declared")
    if value["contract_version"] != MULTIPLE_COMPARISONS_CONTRACT_VERSION:
        raise MultipleComparisonsContractError("contract version is not supported")
    operation_id = value["operation_id"]
    if type(operation_id) is not str or operation_id not in MULTIPLE_COMPARISONS_OPERATION_IDS:
        raise MultipleComparisonsContractError("operation_id is not declared")
    status = value["status"]
    if type(status) is not str or status not in MULTIPLE_COMPARISONS_STATUSES:
        raise MultipleComparisonsContractError("status is not declared")
    reason_code = value["reason_code"]
    if type(reason_code) is not str or reason_code not in MULTIPLE_COMPARISONS_REASON_CODES:
        raise MultipleComparisonsContractError("reason_code is not declared")
    if status == "completed" and reason_code != "MULTIPLE_COMPARISONS_COMPLETED":
        raise MultipleComparisonsContractError("completed result has the wrong reason")
    if status == "failed" and reason_code not in {
        "MULTIPLE_COMPARISONS_FAILED",
        "MULTIPLE_COMPARISONS_NUMERICAL_FAILURE",
    }:
        raise MultipleComparisonsContractError("failed result has the wrong reason")
    n_observations = value["n_observations"]
    if type(n_observations) is not int or isinstance(n_observations, bool) or n_observations < 0:
        raise MultipleComparisonsContractError("n_observations must be a non-negative integer")
    group_names = _names(value["group_names"])
    result = value["result"]
    if not isinstance(result, Mapping):
        raise MultipleComparisonsContractError("result must be a mapping")
    _validate_json(result, "result")
    digest = value["evidence_digest"]
    if status == "completed":
        if type(digest) is not str or len(digest) != 64 or not set(digest) <= _HEX:
            raise MultipleComparisonsContractError("completed result requires a SHA-256 digest")
        expected = sha256_canonical(
            {
                "operation_id": operation_id,
                "n_observations": n_observations,
                "group_names": group_names,
                "result": result,
            }
        )
        if digest != expected:
            raise MultipleComparisonsContractError("evidence_digest does not match result")
    elif digest is not None:
        raise MultipleComparisonsContractError("non-completed result cannot publish a digest")
    freeze_json(dict(result), "result")


def make_multiple_comparisons_result(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    n_observations: int,
    group_names: Sequence[str],
    result: Mapping[str, Any],
    evidence_digest: str | None,
) -> dict[str, Any]:
    payload = {
        "contract": MULTIPLE_COMPARISONS_CONTRACT,
        "contract_version": MULTIPLE_COMPARISONS_CONTRACT_VERSION,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        "n_observations": n_observations,
        "group_names": list(group_names),
        "result": result,
        "evidence_digest": evidence_digest,
    }
    validate_multiple_comparisons_result(payload)
    return payload


__all__ = [
    "MULTIPLE_COMPARISONS_CONTRACT",
    "MULTIPLE_COMPARISONS_CONTRACT_VERSION",
    "MULTIPLE_COMPARISONS_OPERATION_IDS",
    "MULTIPLE_COMPARISONS_REASON_CODES",
    "MULTIPLE_COMPARISONS_STATUSES",
    "MultipleComparisonsContractError",
    "make_multiple_comparisons_result",
    "validate_multiple_comparisons_result",
]
