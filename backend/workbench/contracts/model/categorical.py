"""Versioned, JSON-safe contracts for categorical-count test results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


CATEGORICAL_CONTRACT = "categorical_count.result"
CATEGORICAL_CONTRACT_VERSION = "1.0"
CATEGORICAL_OPERATION_IDS = frozenset(
    {"categorical.cramers_v", "categorical.mcnemar"}
)

# Required fields emitted by each operation. Additive result fields remain valid.
CATEGORICAL_CRAMERS_V_RESULT_FIELDS = frozenset(
    {
        "chi_square",
        "degrees_of_freedom",
        "p_value",
        "sample_size",
        "cramers_v",
        "expected_counts",
        "expected_count_diagnostics",
        "method",
        "correction",
        "correction_policy",
    }
)
CATEGORICAL_CRAMERS_V_EXPECTED_COUNT_DIAGNOSTIC_FIELDS = frozenset(
    {
        "cells_below_5",
        "cells_total",
        "fraction_below_5",
        "maximum",
        "minimum",
    }
)
CATEGORICAL_MCNEMAR_RESULT_FIELDS = frozenset(
    {
        "discordant_counts",
        "statistic",
        "p_value",
        "method",
        "exact",
        "correction",
        "correction_policy",
        "paired_effect",
    }
)
CATEGORICAL_MCNEMAR_DISCORDANT_COUNT_FIELDS = frozenset({"b", "c"})
CATEGORICAL_MCNEMAR_PAIRED_EFFECT_FIELDS = frozenset(
    {"discordant_total", "discordance_rate", "directional_discordance"}
)
CATEGORICAL_OPERATION_RESULT_FIELDS = MappingProxyType(
    {
        "categorical.cramers_v": CATEGORICAL_CRAMERS_V_RESULT_FIELDS,
        "categorical.mcnemar": CATEGORICAL_MCNEMAR_RESULT_FIELDS,
    }
)

_RESULT_FIELDS = {"contract", "contract_version", "operation_id", "result"}


def _require_fields(
    value: Mapping[str, Any], required: frozenset[str], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be a mapping")
    missing = required - set(value)
    if missing:
        raise ContractError(
            f"missing {label} field(s): {', '.join(sorted(missing))}"
        )


@dataclass(frozen=True)
class CategoricalResultEnvelope:
    """Immutable result envelope shared by the categorical-count kernels."""

    operation_id: str
    result: Mapping[str, Any]

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or self.operation_id not in CATEGORICAL_OPERATION_IDS:
            raise ContractError("operation_id is not a declared categorical operation")
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        frozen_result = freeze_json(self.result, "result")
        required_fields = CATEGORICAL_OPERATION_RESULT_FIELDS[self.operation_id]
        _require_fields(frozen_result, required_fields, f"{self.operation_id} result")
        if self.operation_id == "categorical.cramers_v":
            _require_fields(
                frozen_result["expected_count_diagnostics"],
                CATEGORICAL_CRAMERS_V_EXPECTED_COUNT_DIAGNOSTIC_FIELDS,
                f"{self.operation_id} expected_count_diagnostics",
            )
        else:
            _require_fields(
                frozen_result["discordant_counts"],
                CATEGORICAL_MCNEMAR_DISCORDANT_COUNT_FIELDS,
                f"{self.operation_id} discordant_counts",
            )
            _require_fields(
                frozen_result["paired_effect"],
                CATEGORICAL_MCNEMAR_PAIRED_EFFECT_FIELDS,
                f"{self.operation_id} paired_effect",
            )
        object.__setattr__(self, "result", frozen_result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": CATEGORICAL_CONTRACT,
            "contract_version": CATEGORICAL_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CategoricalResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "categorical result")
        if value["contract"] != CATEGORICAL_CONTRACT:
            raise ContractError("contract is not the declared categorical result contract")
        if value["contract_version"] != CATEGORICAL_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared categorical version")
        return cls(operation_id=value["operation_id"], result=value["result"])


def make_result_envelope(
    *, operation_id: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate and return a mutable JSON-shaped categorical result envelope."""

    return CategoricalResultEnvelope(operation_id=operation_id, result=result).to_dict()


__all__ = [
    "CATEGORICAL_CONTRACT",
    "CATEGORICAL_CONTRACT_VERSION",
    "CATEGORICAL_CRAMERS_V_EXPECTED_COUNT_DIAGNOSTIC_FIELDS",
    "CATEGORICAL_CRAMERS_V_RESULT_FIELDS",
    "CATEGORICAL_MCNEMAR_DISCORDANT_COUNT_FIELDS",
    "CATEGORICAL_MCNEMAR_PAIRED_EFFECT_FIELDS",
    "CATEGORICAL_MCNEMAR_RESULT_FIELDS",
    "CATEGORICAL_OPERATION_IDS",
    "CATEGORICAL_OPERATION_RESULT_FIELDS",
    "CategoricalResultEnvelope",
    "make_result_envelope",
]
