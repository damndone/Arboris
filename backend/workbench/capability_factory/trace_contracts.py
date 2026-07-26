"""Package-local CF1 trace payload contracts; Core Trace owns registration later."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import _digest, _text


TRACE_CONTRACT_VERSION = "workbench.capability_factory.trace/v1"
_EVENT_FIELDS = {
    "capability.requirement.created": frozenset({"requirement_digest", "revision"}),
    "capability.registry.registered": frozenset({"implementation_ref", "profile_digest"}),
    "capability.resolution.decided": frozenset({"decision_digest", "outcome"}),
    "capability.dependency.proposed": frozenset({"proposal_digest", "lock_ref", "risk_level"}),
    "capability.dependency.quarantined": frozenset({"bundle_ref", "lock_ref", "status"}),
    "capability.dependency.admission.changed": frozenset({"bundle_ref", "status", "validity_ref"}),
}


class TraceContractError(ValueError):
    """Raised when a CF1 event is not in the package-local vocabulary."""


@dataclass(frozen=True, slots=True)
class CapabilityTraceEvent:
    schema_version: str
    event_type: str
    payload: Mapping[str, Any]


def build_trace_event(*, event_type: str, payload: Mapping[str, Any]) -> CapabilityTraceEvent:
    if event_type not in _EVENT_FIELDS:
        raise TraceContractError("event_type is not registered by the capability factory")
    if not isinstance(payload, Mapping):
        raise TraceContractError("trace payload must be an object")
    expected = _EVENT_FIELDS[event_type]
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise TraceContractError(f"trace payload contains unknown fields: {sorted(unknown)}")
    if missing:
        raise TraceContractError(f"trace payload is missing fields: {sorted(missing)}")
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key.endswith("digest") or key.endswith("_ref"):
            try:
                normalized[key] = _digest(value, key)
            except ValueError as error:
                raise TraceContractError(str(error)) from error
        elif key == "revision":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise TraceContractError("revision must be a positive integer")
            normalized[key] = value
        else:
            normalized[key] = _text(value, key)
    return CapabilityTraceEvent(
        schema_version=TRACE_CONTRACT_VERSION,
        event_type=event_type,
        payload=MappingProxyType(normalized),
    )


__all__ = ["CapabilityTraceEvent", "TRACE_CONTRACT_VERSION", "TraceContractError", "build_trace_event"]
