"""service contracts: extracted behavior owner."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from ...custom_capability.canonical import domain_digest
from ...capability_factory.notebook_binding import CapabilityResolutionBinding

MAX_OPTIONS_PER_BATCH = 3


_REGISTRY_RISK_TO_OPTION_RISK = {
    "none": "low",
    "read": "low",
    "readonly": "low",
    "mutating": "medium",
    "high": "high",
}


def _execution_modes_for(
    risk_level: str, operation_id: str | None = None
) -> tuple[str, ...]:
    """Expose only the execution mode explicitly allowed by the operation."""

    if risk_level == "low":
        return ("materialize_only", "confirm_and_execute")
    if risk_level == "high" and operation_id == "model.custom":
        return ("materialize_only", "experimental_confirm_and_execute")
    return ("materialize_only",)


def _artifact_contract_ref(contract: Any) -> str:
    return domain_digest("workbench.notebook.artifact_contract/v1", contract.to_dict())


def _consumer_projection_ref(binding: CapabilityResolutionBinding) -> str:
    return domain_digest(
        "workbench.capability_factory.consumer_projection/v1",
        {"allowed_consumers": list(binding.allowed_consumers)},
    )


_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"selected", "deferred", "rejected", "archived"}),
    "deferred": frozenset({"selected", "rejected", "archived"}),
    "selected": frozenset({"deferred", "rejected", "materialized", "archived"}),
    "materialized": frozenset({"selected", "executing", "archived"}),
    "executing": frozenset({"executed", "materialized"}),
    "executed": frozenset(),
    "rejected": frozenset(),
    "archived": frozenset(),
}


_LEGACY_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"selected", "deferred", "rejected", "archived"}),
    "deferred": frozenset({"selected", "rejected", "archived"}),
    "selected": frozenset({"deferred", "rejected", "executing", "archived"}),
    "executing": frozenset({"executed", "selected"}),
    "executed": frozenset(),
    "rejected": frozenset(),
    "archived": frozenset(),
}


_DECISION_TO_LIFECYCLE = {
    "selected": "selected",
    "deferred": "deferred",
    "rejected": "rejected",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

