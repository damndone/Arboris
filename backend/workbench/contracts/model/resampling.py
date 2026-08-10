"""Versioned, JSON-safe contracts for bootstrap and permutation inference."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json


RESAMPLING_CONTRACT = "resampling.result"
RESAMPLING_CONTRACT_VERSION = "1.0"
RESAMPLING_OPERATION_IDS = frozenset(
    {"resampling.bootstrap", "resampling.permutation"}
)
RESAMPLING_STATUSES = frozenset({"completed", "rejected", "failed"})
RESAMPLING_REASON_CODES = frozenset(
    {
        "RESAMPLING_COMPLETED",
        "RESAMPLING_INVALID_INPUT",
        "RESAMPLING_UNSUPPORTED_STATISTIC",
        "RESAMPLING_UNSUPPORTED_METHOD",
        "RESAMPLING_TOO_FEW_OBSERVATIONS",
        "RESAMPLING_TOO_FEW_REPLICATES",
        "RESAMPLING_EXACT_STATE_SPACE_EXCEEDED",
        "RESAMPLING_DEGENERATE_STATISTIC",
        "RESAMPLING_DEGENERATE_INTERVAL",
        "RESAMPLING_BATCH_FAILED",
        "RESAMPLING_COMBINE_FAILED",
        "RESAMPLING_FAILED",
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
        "result",
        "batch",
        "evidence_digest",
    }
)
_RAW_FIELDS = frozenset(
    {
        "replicate_rows",
        "replicate_values",
        "raw_data",
        "raw_rows",
        "raw_values",
        "distribution_values",
    }
)
_HEX = frozenset("0123456789abcdef")


class ResamplingContractError(ContractError):
    """Raised when a resampling result violates its public contract."""


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str]) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ResamplingContractError(
            "unknown resampling result field(s): " + ", ".join(sorted(unknown))
        )
    if missing:
        raise ResamplingContractError(
            "missing resampling result field(s): " + ", ".join(sorted(missing))
        )


def _validate_json(value: Any, label: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ResamplingContractError(f"{label} must be finite")
        return
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ResamplingContractError(f"{label} keys must be strings")
        if _RAW_FIELDS.intersection(value):
            raise ResamplingContractError(f"{label} contains raw replicate values")
        for key, child in value.items():
            _validate_json(child, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json(child, f"{label}[{index}]")
        return
    raise ResamplingContractError(f"{label} is not JSON-safe")


def _validate_digest(value: Any, label: str) -> None:
    if type(value) is not str or len(value) != 64 or not set(value) <= _HEX:
        raise ResamplingContractError(f"{label} must be a lowercase SHA-256 digest")


def validate_resampling_result(value: Mapping[str, Any]) -> None:
    """Validate the closed public envelope without interpreting pack statistics."""

    if not isinstance(value, Mapping):
        raise ResamplingContractError("resampling result must be a mapping")
    _require_exact_keys(value, _CORE_FIELDS)
    if value["contract"] != RESAMPLING_CONTRACT:
        raise ResamplingContractError("resampling contract is not declared")
    if value["contract_version"] != RESAMPLING_CONTRACT_VERSION:
        raise ResamplingContractError("resampling contract version is not supported")
    operation_id = value["operation_id"]
    if type(operation_id) is not str or operation_id not in RESAMPLING_OPERATION_IDS:
        raise ResamplingContractError("resampling operation_id is not declared")
    status = value["status"]
    if type(status) is not str or status not in RESAMPLING_STATUSES:
        raise ResamplingContractError("resampling status is not declared")
    reason_code = value["reason_code"]
    if type(reason_code) is not str or reason_code not in RESAMPLING_REASON_CODES:
        raise ResamplingContractError("resampling reason_code is not declared")
    if status == "completed" and reason_code != "RESAMPLING_COMPLETED":
        raise ResamplingContractError("completed resampling result has the wrong reason")
    if status == "rejected" and reason_code in {
        "RESAMPLING_COMPLETED",
        "RESAMPLING_BATCH_FAILED",
        "RESAMPLING_COMBINE_FAILED",
        "RESAMPLING_FAILED",
    }:
        raise ResamplingContractError("rejected resampling result has the wrong reason")
    if status == "failed" and reason_code not in {
        "RESAMPLING_BATCH_FAILED",
        "RESAMPLING_COMBINE_FAILED",
        "RESAMPLING_FAILED",
    }:
        raise ResamplingContractError("failed resampling result has the wrong reason")
    n_observations = value["n_observations"]
    if type(n_observations) is not int or isinstance(n_observations, bool) or n_observations < 0:
        raise ResamplingContractError("n_observations must be a non-negative integer")
    result = value["result"]
    if not isinstance(result, Mapping):
        raise ResamplingContractError("resampling result.result must be a mapping")
    _validate_json(result, "result")
    batch = value["batch"]
    if status == "completed":
        if not isinstance(batch, Mapping):
            raise ResamplingContractError("completed resampling result requires a batch")
    elif batch is not None and not isinstance(batch, Mapping):
        raise ResamplingContractError("resampling batch must be a mapping or null")
    evidence_digest = value["evidence_digest"]
    if status == "completed":
        _validate_digest(evidence_digest, "evidence_digest")
        expected_digest = sha256_canonical({"batch": batch, "result": result})
        if evidence_digest != expected_digest:
            raise ResamplingContractError("evidence_digest does not match batch and result")
    elif evidence_digest is not None:
        raise ResamplingContractError("non-completed resampling results cannot publish a digest")
    if batch is not None:
        _validate_json(batch, "batch")
    # Exercise the same immutable JSON boundary used by other P7 contracts.
    freeze_json(dict(result), "result")


def make_resampling_result(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    n_observations: int,
    result: Mapping[str, Any],
    batch: Mapping[str, Any] | None,
    evidence_digest: str | None,
) -> dict[str, Any]:
    """Build and validate one bootstrap/permutation result envelope."""

    payload = {
        "contract": RESAMPLING_CONTRACT,
        "contract_version": RESAMPLING_CONTRACT_VERSION,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        "n_observations": n_observations,
        "result": result,
        "batch": batch,
        "evidence_digest": evidence_digest,
    }
    validate_resampling_result(payload)
    return payload


__all__ = [
    "RESAMPLING_CONTRACT",
    "RESAMPLING_CONTRACT_VERSION",
    "RESAMPLING_OPERATION_IDS",
    "RESAMPLING_REASON_CODES",
    "RESAMPLING_STATUSES",
    "ResamplingContractError",
    "make_resampling_result",
    "validate_resampling_result",
]
