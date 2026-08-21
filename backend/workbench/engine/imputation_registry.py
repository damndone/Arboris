from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImputationMethod:
    key: str
    label: str
    description: str = ""


MICE_IMPUTATION_METHOD = ImputationMethod(
    key="mice",
    label="MICE (Multiple Imputation)",
    description=(
        "Multiple Imputation by Chained Equations. Recommended when more than "
        "5-10% of rows would otherwise be dropped due to missing values."
    ),
)


IMPUTATION_REGISTRY: dict[str, ImputationMethod] = {
    MICE_IMPUTATION_METHOD.key: MICE_IMPUTATION_METHOD,
}


def register_imputation_method(method: ImputationMethod) -> None:
    IMPUTATION_REGISTRY[method.key] = method
