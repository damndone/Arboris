"""Result envelope for regression-adjustment, weighting and doubly robust treatment effects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from workbench.contracts.model.p7_extension import P7ScopeMetadata

TREATMENT_EFFECTS_CONTRACT = "workbench.treatment_effects.result"
TREATMENT_EFFECTS_CONTRACT_VERSION = "v1"
TREATMENT_EFFECTS_OPERATION_IDS = frozenset({"treatment_effects.estimate"})
TREATMENT_EFFECTS_ESTIMANDS = ("ATE", "ATT", "ATC")
TREATMENT_EFFECTS_METHODS = ("aipw", "ipw", "ra")
_FIELDS = {"contract", "contract_version", "operation_id", "status", "reason_code", "n_observations", "result"}


def validate_treatment_effects_result(value: Mapping[str, Any]) -> None:
    if set(value) != _FIELDS:
        raise ValueError("treatment effects result has undeclared or missing fields")
    if value["contract"] != TREATMENT_EFFECTS_CONTRACT or value["contract_version"] != TREATMENT_EFFECTS_CONTRACT_VERSION:
        raise ValueError("treatment effects contract or version is not declared")
    if value["operation_id"] not in TREATMENT_EFFECTS_OPERATION_IDS or value["status"] != "completed":
        raise ValueError("treatment effects operation or status is not declared")
    result = value["result"]
    if not isinstance(result, Mapping) or result.get("estimand") not in TREATMENT_EFFECTS_ESTIMANDS:
        raise ValueError("treatment effects result must state its estimand")
    if result.get("method") not in TREATMENT_EFFECTS_METHODS or type(result.get("estimate")) is not float:
        raise ValueError("treatment effects result must state its method and estimate")
    P7ScopeMetadata.from_dict(result["scope"])


__all__ = [
    "TREATMENT_EFFECTS_CONTRACT", "TREATMENT_EFFECTS_CONTRACT_VERSION", "TREATMENT_EFFECTS_ESTIMANDS",
    "TREATMENT_EFFECTS_METHODS", "TREATMENT_EFFECTS_OPERATION_IDS", "validate_treatment_effects_result",
]
