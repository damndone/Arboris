"""Versioned, JSON-safe contracts for standalone GMM and IV diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json


IV_GMM_CONTRACT = "iv_gmm.result"
IV_GMM_CONTRACT_VERSION = "1.0"
IV_GMM_OPERATION_IDS = frozenset({"iv.gmm", "iv.weak_instruments"})
IV_GMM_STATUSES = frozenset({"completed", "rejected", "failed"})
IV_GMM_REASON_CODES = frozenset(
    {
        "IV_GMM_COMPLETED",
        "IV_GMM_INVALID_INPUT",
        "IV_GMM_NONFINITE_INPUT",
        "IV_GMM_UNDERIDENTIFIED",
        "IV_GMM_SINGULAR_DESIGN",
        "IV_GMM_SINGULAR_WEIGHTING",
        "IV_GMM_NUMERICAL_FAILURE",
        "IV_GMM_UNSUPPORTED_ESTIMATOR",
        "IV_GMM_INVALID_NAMES",
        "IV_GMM_FAILED",
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
        "parameter_names",
        "result",
        "evidence_digest",
    }
)
_RAW_FIELDS = frozenset({"raw_rows", "raw_data", "observations", "residuals_raw"})
_HEX = frozenset("0123456789abcdef")


class IVGMMContractError(ContractError):
    """Raised when a GMM/IV diagnostic result violates its public contract."""


def _validate_json(value: Any, label: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise IVGMMContractError(f"{label} must be finite")
        return
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise IVGMMContractError(f"{label} keys must be strings")
        if _RAW_FIELDS.intersection(value):
            raise IVGMMContractError(f"{label} contains raw observations")
        for key, child in value.items():
            _validate_json(child, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json(child, f"{label}[{index}]")
        return
    raise IVGMMContractError(f"{label} is not JSON-safe")


def _validate_names(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IVGMMContractError("parameter_names must be an array of names")
    names = list(value)
    if not names or any(type(name) is not str or not name for name in names):
        raise IVGMMContractError("parameter_names must contain non-empty names")
    if len(set(names)) != len(names):
        raise IVGMMContractError("parameter_names must be unique")
    return names


def validate_iv_gmm_result(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise IVGMMContractError("IV GMM result must be a mapping")
    unknown = set(value) - _CORE_FIELDS
    missing = _CORE_FIELDS - set(value)
    if unknown:
        raise IVGMMContractError("unknown IV GMM result field(s): " + ", ".join(sorted(unknown)))
    if missing:
        raise IVGMMContractError("missing IV GMM result field(s): " + ", ".join(sorted(missing)))
    if value["contract"] != IV_GMM_CONTRACT:
        raise IVGMMContractError("IV GMM contract is not declared")
    if value["contract_version"] != IV_GMM_CONTRACT_VERSION:
        raise IVGMMContractError("IV GMM contract version is not supported")
    operation_id = value["operation_id"]
    if type(operation_id) is not str or operation_id not in IV_GMM_OPERATION_IDS:
        raise IVGMMContractError("IV GMM operation_id is not declared")
    status = value["status"]
    if type(status) is not str or status not in IV_GMM_STATUSES:
        raise IVGMMContractError("IV GMM status is not declared")
    reason_code = value["reason_code"]
    if type(reason_code) is not str or reason_code not in IV_GMM_REASON_CODES:
        raise IVGMMContractError("IV GMM reason_code is not declared")
    if status == "completed" and reason_code != "IV_GMM_COMPLETED":
        raise IVGMMContractError("completed IV GMM result has the wrong reason")
    if status == "failed" and reason_code not in {"IV_GMM_FAILED", "IV_GMM_NUMERICAL_FAILURE"}:
        raise IVGMMContractError("failed IV GMM result has the wrong reason")
    n_observations = value["n_observations"]
    if type(n_observations) is not int or isinstance(n_observations, bool) or n_observations < 0:
        raise IVGMMContractError("n_observations must be a non-negative integer")
    parameter_names = _validate_names(value["parameter_names"])
    result = value["result"]
    if not isinstance(result, Mapping):
        raise IVGMMContractError("result must be a mapping")
    _validate_json(result, "result")
    digest = value["evidence_digest"]
    if status == "completed":
        if type(digest) is not str or len(digest) != 64 or not set(digest) <= _HEX:
            raise IVGMMContractError("completed IV GMM result requires a SHA-256 digest")
        expected = sha256_canonical(
            {
                "operation_id": operation_id,
                "n_observations": n_observations,
                "parameter_names": parameter_names,
                "result": result,
            }
        )
        if digest != expected:
            raise IVGMMContractError("evidence_digest does not match IV GMM result")
    elif digest is not None:
        raise IVGMMContractError("non-completed IV GMM results cannot publish a digest")
    freeze_json(dict(result), "result")


def make_iv_gmm_result(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    n_observations: int,
    parameter_names: Sequence[str],
    result: Mapping[str, Any],
    evidence_digest: str | None,
) -> dict[str, Any]:
    payload = {
        "contract": IV_GMM_CONTRACT,
        "contract_version": IV_GMM_CONTRACT_VERSION,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        "n_observations": n_observations,
        "parameter_names": list(parameter_names),
        "result": result,
        "evidence_digest": evidence_digest,
    }
    validate_iv_gmm_result(payload)
    return payload


__all__ = [
    "IV_GMM_CONTRACT",
    "IV_GMM_CONTRACT_VERSION",
    "IV_GMM_OPERATION_IDS",
    "IV_GMM_REASON_CODES",
    "IV_GMM_STATUSES",
    "IVGMMContractError",
    "make_iv_gmm_result",
    "validate_iv_gmm_result",
]
