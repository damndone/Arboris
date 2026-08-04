"""Independent typed request contract for multi-quantile regression."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.envelope import ContractError


@dataclass(frozen=True)
class QuantileRegressionRequest:
    quantiles: tuple[float, ...] = (0.25, 0.5, 0.75)
    bootstrap_reps: int = 0
    random_state: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QuantileRegressionRequest":
        if not isinstance(value, Mapping):
            raise ContractError("quantile_regression request must be a mapping")
        unknown = sorted(set(value) - {"quantiles", "bootstrap_reps", "random_state"})
        if unknown:
            raise ContractError(f"quantile_regression request has unknown field(s): {', '.join(unknown)}")
        raw_quantiles = value.get("quantiles", [0.25, 0.5, 0.75])
        if (
            not isinstance(raw_quantiles, (list, tuple))
            or not raw_quantiles
            or any(type(q) not in {int, float} or not 0 < float(q) < 1 for q in raw_quantiles)
            or len(set(float(q) for q in raw_quantiles)) != len(raw_quantiles)
            or len(raw_quantiles) > 7
        ):
            raise ContractError("quantile_regression.quantiles must be unique values strictly between zero and one")
        bootstrap_reps = value.get("bootstrap_reps", 0)
        random_state = value.get("random_state")
        if type(bootstrap_reps) is not int or not 0 <= bootstrap_reps <= 1000:
            raise ContractError("quantile_regression.bootstrap_reps must be between 0 and 1000")
        if random_state is not None and (type(random_state) is not int or random_state < 0):
            raise ContractError("quantile_regression.random_state must be non-negative")
        return cls(
            quantiles=tuple(float(q) for q in raw_quantiles),
            bootstrap_reps=bootstrap_reps,
            random_state=random_state,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantiles": list(self.quantiles),
            "bootstrap_reps": self.bootstrap_reps,
            "random_state": self.random_state,
        }
