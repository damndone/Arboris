from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImputationMethod:
    key: str
    label: str
    description: str = ""


IMPUTATION_REGISTRY: dict[str, ImputationMethod] = {}


def register_imputation_method(method: ImputationMethod) -> None:
    IMPUTATION_REGISTRY[method.key] = method
