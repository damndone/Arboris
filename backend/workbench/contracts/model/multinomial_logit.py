"""Independent typed request contract for multinomial logit models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.envelope import ContractError


@dataclass(frozen=True)
class MultinomialLogitRequest:
    maxiter: int = 1000
    base_category: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MultinomialLogitRequest":
        if not isinstance(value, Mapping):
            raise ContractError("multinomial_logit request must be a mapping")
        unknown = sorted(set(value) - {"maxiter", "base_category"})
        if unknown:
            raise ContractError(f"multinomial_logit request has unknown field(s): {', '.join(unknown)}")
        maxiter = value.get("maxiter", 1000)
        base_category = value.get("base_category")
        if type(maxiter) is not int or not 50 <= maxiter <= 5000:
            raise ContractError("multinomial_logit.maxiter must be between 50 and 5000")
        if base_category is not None and (type(base_category) is not str or not base_category):
            raise ContractError("multinomial_logit.base_category must be a non-empty label")
        return cls(maxiter=maxiter, base_category=base_category)

    def to_dict(self) -> dict[str, Any]:
        return {"maxiter": self.maxiter, "base_category": self.base_category}
