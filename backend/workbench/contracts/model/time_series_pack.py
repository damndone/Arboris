"""Standalone time-series kernel result contract, separate from Agent C1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json


TIME_SERIES_PACK_CONTRACT = "time_series.pack.result"
TIME_SERIES_PACK_CONTRACT_VERSION = "1.0"
TIME_SERIES_PACK_OPERATION_IDS = frozenset(
    {
        "time_series.acf",
        "time_series.pacf",
        "time_series.adf",
        "time_series.kpss",
        "time_series.arima",
        "time_series.var",
        "time_series.granger",
        "time_series.irf",
        "time_series.cointegration",
        "time_series.vecm",
    }
)
_FIELDS = {
    "contract",
    "contract_version",
    "operation_id",
    "status",
    "reason_code",
    "n_observations",
    "variables",
    "result",
}


@dataclass(frozen=True)
class TimeSeriesResultEnvelope:
    operation_id: str
    status: str
    reason_code: str
    n_observations: int
    variables: tuple[str, ...]
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.operation_id not in TIME_SERIES_PACK_OPERATION_IDS:
            raise ContractError("operation_id is not a declared time-series operation")
        if self.status not in {"completed", "rejected", "failed"}:
            raise ContractError("status is not a declared time-series status")
        if type(self.reason_code) is not str or not self.reason_code:
            raise ContractError("reason_code must be a non-empty string")
        if type(self.n_observations) is not int or self.n_observations < 0:
            raise ContractError("n_observations must be a non-negative integer")
        if (
            len(self.variables) < 1
            or any(type(variable) is not str or not variable for variable in self.variables)
            or len(set(self.variables)) != len(self.variables)
        ):
            raise ContractError("variables must contain unique non-empty names")
        object.__setattr__(self, "result", freeze_json(self.result, "result"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": TIME_SERIES_PACK_CONTRACT,
            "contract_version": TIME_SERIES_PACK_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "n_observations": self.n_observations,
            "variables": list(self.variables),
            "result": thaw_json(self.result),
        }


def make_time_series_result(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    n_observations: int,
    variables: Sequence[str],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return TimeSeriesResultEnvelope(
        operation_id=operation_id,
        status=status,
        reason_code=reason_code,
        n_observations=n_observations,
        variables=tuple(variables),
        result=result,
    ).to_dict()


__all__ = [
    "TIME_SERIES_PACK_CONTRACT",
    "TIME_SERIES_PACK_CONTRACT_VERSION",
    "TIME_SERIES_PACK_OPERATION_IDS",
    "TimeSeriesResultEnvelope",
    "make_time_series_result",
]
