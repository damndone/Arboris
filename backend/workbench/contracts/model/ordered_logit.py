"""Independent typed request contract for ordered logit/probit models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..common.envelope import ContractError


@dataclass(frozen=True)
class OrderedLogitRequest:
    link: Literal["logit", "probit"] = "logit"
    optimizer: Literal["bfgs", "lbfgs"] = "bfgs"
    maxiter: int = 1000
    outcome_order: tuple[str, ...] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OrderedLogitRequest":
        _check_keys(value, {"optimizer", "maxiter", "link", "outcome_order"}, "ordered_logit")
        outcome_order = value.get("outcome_order")
        if outcome_order is not None:
            if (
                not isinstance(outcome_order, (list, tuple))
                or len(outcome_order) < 3
                or any(type(level) is not str or not level for level in outcome_order)
                or len(set(outcome_order)) != len(outcome_order)
            ):
                raise ContractError("ordered_logit.outcome_order must contain at least three unique labels")
            outcome_order = tuple(outcome_order)
        link = value.get("link", "logit")
        optimizer = value.get("optimizer", "bfgs")
        maxiter = value.get("maxiter", 1000)
        if link not in {"logit", "probit"}:
            raise ContractError("ordered_logit.link must be logit or probit")
        if optimizer not in {"bfgs", "lbfgs"}:
            raise ContractError("ordered_logit.optimizer must be bfgs or lbfgs")
        if type(maxiter) is not int or not 50 <= maxiter <= 5000:
            raise ContractError("ordered_logit.maxiter must be between 50 and 5000")
        return cls(link=link, optimizer=optimizer, maxiter=maxiter, outcome_order=outcome_order)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link": self.link,
            "optimizer": self.optimizer,
            "maxiter": self.maxiter,
            "outcome_order": list(self.outcome_order) if self.outcome_order is not None else None,
        }


def _check_keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} request must be a mapping")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ContractError(f"{name} request has unknown field(s): {', '.join(unknown)}")
