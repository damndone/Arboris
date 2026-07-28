"""Explicit consumer projections for custom capability outputs.

An adapter's consumer map is only a declaration.  This module turns each
non-null declaration into a server-owned, content-addressed projection.  A
missing slot is deliberately represented as unsupported; no projection is
inferred from a different consumer (for example, report logic is never reused
as diagnostics or figures).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..custom_capability.canonical import domain_digest
from .adapter_contract import AdapterContract, AdapterContractError
from .contracts import CONSUMER_SLOTS, ImplementationRevision
from .trace_contracts import CapabilityTraceEvent, build_trace_event


CONSUMER_ADAPTER_REVISION = "ConsumerAdapterRevision@1.0"
CONSUMER_PROJECTION_CONTRACT_VERSION = "ConsumerProjection@1.0"
_HEX = frozenset("0123456789abcdef")


class ConsumerProjectionError(ValueError):
    """Raised when a consumer slot is absent, rebound, or malformed."""


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ConsumerProjectionError(f"{field} must be bounded non-empty text")
    if any(ord(char) < 0x20 for char in value):
        raise ConsumerProjectionError(f"{field} contains a control character")
    return value


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ConsumerProjectionError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _slot(value: Any) -> str:
    result = _text(value, "slot")
    if result not in CONSUMER_SLOTS:
        raise ConsumerProjectionError("slot is not a registered consumer")
    return result


def _sequence(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or (not value and not allow_empty):
        raise ConsumerProjectionError(f"{field} must be a bounded sequence")
    result = tuple(_text(item, f"{field} item") for item in value)
    if len(set(result)) != len(result):
        raise ConsumerProjectionError(f"{field} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class ConsumerAdapterRevision:
    """One explicit server-owned consumer adapter slot."""

    slot: str
    revision: int
    adapter_ref: str
    implementation_ref: str
    projection_ref: str
    payload_schema_ref: str
    artifact_facets: tuple[str, ...]
    source_eligible: bool = False
    rerun_eligible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _slot(self.slot))
        if type(self.revision) is not int or self.revision < 1:
            raise ConsumerProjectionError("revision must be a positive integer")
        for field in (
            "adapter_ref",
            "implementation_ref",
            "projection_ref",
            "payload_schema_ref",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(self, "artifact_facets", _sequence(self.artifact_facets, "artifact_facets"))
        if type(self.source_eligible) is not bool or type(self.rerun_eligible) is not bool:
            raise ConsumerProjectionError("consumer eligibility flags must be booleans")
        if self.slot not in {"report_projection", "diagnostic_adapter", "figure_provider", "compare_adapter"}:
            if self.source_eligible or self.rerun_eligible:
                raise ConsumerProjectionError(
                    "planner consumer cannot declare source or rerun eligibility"
                )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONSUMER_ADAPTER_REVISION,
            "slot": self.slot,
            "revision": self.revision,
            "adapter_ref": self.adapter_ref,
            "implementation_ref": self.implementation_ref,
            "projection_ref": self.projection_ref,
            "payload_schema_ref": self.payload_schema_ref,
            "artifact_facets": list(self.artifact_facets),
            "source_eligible": self.source_eligible,
            "rerun_eligible": self.rerun_eligible,
        }

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.consumer_adapter_revision/v1", self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConsumerAdapterRevision":
        expected = {
            "contract_version",
            "slot",
            "revision",
            "adapter_ref",
            "implementation_ref",
            "projection_ref",
            "payload_schema_ref",
            "artifact_facets",
            "source_eligible",
            "rerun_eligible",
            "content_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ConsumerProjectionError("consumer adapter revision fields are invalid")
        if value["contract_version"] != CONSUMER_ADAPTER_REVISION:
            raise ConsumerProjectionError("consumer adapter revision contract is unsupported")
        result = cls(
            slot=value["slot"],
            revision=value["revision"],
            adapter_ref=value["adapter_ref"],
            implementation_ref=value["implementation_ref"],
            projection_ref=value["projection_ref"],
            payload_schema_ref=value["payload_schema_ref"],
            artifact_facets=tuple(value["artifact_facets"]),
            source_eligible=value["source_eligible"],
            rerun_eligible=value["rerun_eligible"],
        )
        if value["content_digest"] != result.content_digest:
            raise ConsumerProjectionError("consumer adapter revision digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ConsumerProjection:
    """The exact set of consumer slots admitted for one execution."""

    projection_id: str
    adapter_ref: str
    implementation_ref: str
    slots: tuple[ConsumerAdapterRevision, ...]
    contract_version: str = CONSUMER_PROJECTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CONSUMER_PROJECTION_CONTRACT_VERSION:
            raise ConsumerProjectionError("consumer projection contract is unsupported")
        object.__setattr__(self, "projection_id", _text(self.projection_id, "projection_id"))
        object.__setattr__(self, "adapter_ref", _digest(self.adapter_ref, "adapter_ref"))
        object.__setattr__(self, "implementation_ref", _digest(self.implementation_ref, "implementation_ref"))
        if not isinstance(self.slots, (tuple, list)) or not self.slots:
            raise ConsumerProjectionError("consumer projection must contain at least one slot")
        slots = tuple(self.slots)
        if any(not isinstance(item, ConsumerAdapterRevision) for item in slots):
            raise ConsumerProjectionError("consumer projection slots are invalid")
        if len({item.slot for item in slots}) != len(slots):
            raise ConsumerProjectionError("consumer projection slots must be unique")
        if any(
            item.adapter_ref != self.adapter_ref or item.implementation_ref != self.implementation_ref
            for item in slots
        ):
            raise ConsumerProjectionError("consumer projection slot identity does not match")
        object.__setattr__(self, "slots", slots)

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.consumer_projection/v1",
            {
                "contract_version": self.contract_version,
                "projection_id": self.projection_id,
                "adapter_ref": self.adapter_ref,
                "implementation_ref": self.implementation_ref,
                "slots": [item.to_dict() for item in self.slots],
            },
        )

    @property
    def slot_names(self) -> tuple[str, ...]:
        return tuple(item.slot for item in self.slots)

    def slot(self, name: str) -> ConsumerAdapterRevision:
        _slot(name)
        for item in self.slots:
            if item.slot == name:
                return item
        raise ConsumerProjectionError(f"consumer slot {name} is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "projection_id": self.projection_id,
            "adapter_ref": self.adapter_ref,
            "implementation_ref": self.implementation_ref,
            "slots": [item.to_dict() for item in self.slots],
            "content_digest": self.content_digest,
        }


def build_consumer_projection(
    *,
    adapter: AdapterContract,
    implementation: ImplementationRevision,
    requested_slots: tuple[str, ...] | list[str],
    projection_refs: Mapping[str, str],
    payload_schema_refs: Mapping[str, str],
    artifact_facets: Mapping[str, tuple[str, ...] | list[str]],
    source_eligible_slots: tuple[str, ...] | list[str] = (),
    rerun_eligible_slots: tuple[str, ...] | list[str] = (),
    projection_id: str = "consumer-projection",
    trace_sink: Callable[[CapabilityTraceEvent], None] | None = None,
) -> ConsumerProjection:
    """Build only the explicitly requested, adapter-declared consumer slots."""

    if not isinstance(adapter, AdapterContract) or not isinstance(implementation, ImplementationRevision):
        raise ConsumerProjectionError("adapter and implementation are required")
    try:
        adapter.validate_against(implementation)
    except AdapterContractError as error:
        raise ConsumerProjectionError(f"adapter identity is invalid: {error}") from error
    slots = _sequence(requested_slots, "requested_slots")
    source = set(_sequence(source_eligible_slots, "source_eligible_slots", allow_empty=True))
    rerun = set(_sequence(rerun_eligible_slots, "rerun_eligible_slots", allow_empty=True))
    if not source <= set(slots) or not rerun <= set(slots):
        raise ConsumerProjectionError("consumer eligibility must be a requested slot")
    if set(projection_refs) != set(slots) or set(payload_schema_refs) != set(slots) or set(artifact_facets) != set(slots):
        raise ConsumerProjectionError("consumer projection maps must cover requested slots exactly")
    revisions: list[ConsumerAdapterRevision] = []
    for slot in slots:
        declared = adapter.consumer_support.get(slot)
        if declared is None or implementation.consumer_support.get(slot) is None:
            raise ConsumerProjectionError(f"consumer slot {slot} is unsupported by the adapter")
        # The adapter's declared slot identity is a server-owned revision ref;
        # caller-supplied projection/schema refs describe the trusted consumer
        # implementation and are independently content-addressed.
        revisions.append(
            ConsumerAdapterRevision(
                slot=slot,
                revision=1,
                adapter_ref=adapter.content_digest,
                implementation_ref=implementation.content_digest,
                projection_ref=projection_refs[slot],
                payload_schema_ref=payload_schema_refs[slot],
                artifact_facets=tuple(artifact_facets[slot]),
                source_eligible=slot in source,
                rerun_eligible=slot in rerun,
            )
        )
    projection = ConsumerProjection(
        projection_id=projection_id,
        adapter_ref=adapter.content_digest,
        implementation_ref=implementation.content_digest,
        slots=tuple(revisions),
    )
    if trace_sink is not None:
        trace_sink(
            build_trace_event(
                event_type="capability.consumer_projection.validated",
                payload={
                    "adapter_revision_ref": adapter.content_digest,
                    "projection_ref": projection.content_digest,
                    "outcome": "accepted",
                },
            )
        )
    return projection


__all__ = [
    "CONSUMER_ADAPTER_REVISION",
    "CONSUMER_PROJECTION_CONTRACT_VERSION",
    "ConsumerAdapterRevision",
    "ConsumerProjection",
    "ConsumerProjectionError",
    "build_consumer_projection",
]
