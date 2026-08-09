"""Closed, JSON-safe contract for the standalone P7 rank/statistics pack."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)
from workbench.contracts.model.p7_extension import P7ScopeMetadata


NONPARAMETRIC_CONTRACT = "nonparametric.result"
NONPARAMETRIC_CONTRACT_VERSION = "1.0"
NONPARAMETRIC_OPERATION_IDS = frozenset(
    {
        "nonparametric.mann_whitney",
        "nonparametric.wilcoxon_signed_rank",
        "nonparametric.kruskal_wallis",
        "nonparametric.friedman",
        "nonparametric.spearman",
        "nonparametric.kendall",
        "nonparametric.robust_summary",
    }
)
NONPARAMETRIC_STATUSES = frozenset({"completed", "rejected", "failed"})
NONPARAMETRIC_REASON_CODES = frozenset(
    {
        "NONPARAMETRIC_COMPLETED",
        "NONPARAMETRIC_INVALID_INPUT",
        "NONPARAMETRIC_UNKNOWN_OPERATION",
        "NONPARAMETRIC_UNSUPPORTED_POLICY",
        "NONPARAMETRIC_TOO_FEW_OBSERVATIONS",
        "NONPARAMETRIC_NONFINITE_VALUE",
        "NONPARAMETRIC_NO_COMPLETE_CASES",
        "NONPARAMETRIC_DEGENERATE_INPUT",
        "NONPARAMETRIC_EXACT_UNAVAILABLE",
        "NONPARAMETRIC_OUTPUT_TOO_LARGE",
    }
)
MAX_NONPARAMETRIC_OBSERVATIONS = 100_000
_RESULT_FIELDS = {
    "contract",
    "contract_version",
    "operation_id",
    "status",
    "reason_code",
    "n_observations",
    "result",
}
_REJECTED_RESULT_KEYS = frozenset(
    {
        "data",
        "matrix",
        "raw",
        "raw_rows",
        "raw_values",
        "replicates",
        "rows",
        "values",
    }
)


def _reject_raw_payload(value: Any, path: str = "result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _REJECTED_RESULT_KEYS:
                raise ContractError(f"{path}.{key} must not expose raw observations")
            _reject_raw_payload(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw_payload(item, f"{path}[{index}]")


@dataclass(frozen=True)
class NonparametricResultEnvelope:
    """Immutable result envelope shared by all nonparametric operations."""

    operation_id: str
    status: str
    reason_code: str
    n_observations: int
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or self.operation_id not in NONPARAMETRIC_OPERATION_IDS:
            raise ContractError("operation_id is not a declared nonparametric operation")
        if self.status not in NONPARAMETRIC_STATUSES:
            raise ContractError("status is not a declared nonparametric status")
        if self.reason_code not in NONPARAMETRIC_REASON_CODES:
            raise ContractError("reason_code is not a declared nonparametric reason")
        if type(self.n_observations) is not int or not 0 <= self.n_observations <= MAX_NONPARAMETRIC_OBSERVATIONS:
            raise ContractError("n_observations is outside the declared bound")
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        _reject_raw_payload(self.result)
        frozen_result = freeze_json(self.result, "result")
        if "scope" not in frozen_result:
            raise ContractError("result must include bounded scope metadata")
        P7ScopeMetadata.from_dict(frozen_result["scope"])
        if self.status == "completed" and "method" not in frozen_result:
            raise ContractError("completed result must identify its method")
        object.__setattr__(self, "result", frozen_result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": NONPARAMETRIC_CONTRACT,
            "contract_version": NONPARAMETRIC_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "n_observations": self.n_observations,
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NonparametricResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "nonparametric result envelope")
        if value["contract"] != NONPARAMETRIC_CONTRACT:
            raise ContractError("contract is not the declared nonparametric contract")
        if value["contract_version"] != NONPARAMETRIC_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared nonparametric version")
        return cls(
            operation_id=value["operation_id"],
            status=value["status"],
            reason_code=value["reason_code"],
            n_observations=value["n_observations"],
            result=value["result"],
        )


def make_result_envelope(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    n_observations: int,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return NonparametricResultEnvelope(
        operation_id=operation_id,
        status=status,
        reason_code=reason_code,
        n_observations=n_observations,
        result=result,
    ).to_dict()


__all__ = [
    "MAX_NONPARAMETRIC_OBSERVATIONS",
    "NONPARAMETRIC_CONTRACT",
    "NONPARAMETRIC_CONTRACT_VERSION",
    "NONPARAMETRIC_OPERATION_IDS",
    "NONPARAMETRIC_REASON_CODES",
    "NONPARAMETRIC_STATUSES",
    "NonparametricResultEnvelope",
    "make_result_envelope",
]
