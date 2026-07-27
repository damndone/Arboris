"""Package-local exact B1 trace event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..capability_factory.contracts import _digest, _text


TRACE_CONTRACT_VERSION = "workbench.native_containment.trace/v1"
_EVENT_FIELDS = {
    "host_containment.assessed": frozenset({"assessment_ref", "outcome"}),
    "host_containment.validity.changed": frozenset({"assessment_ref", "validity_ref", "to_status"}),
    "containment.dispatch.completed": frozenset({"attempt_ref", "report_ref", "outcome"}),
    "containment.dispatch.unknown": frozenset({"attempt_ref", "reason_code"}),
}


class TraceContractError(ValueError):
    """Raised when a B1 event contains an unknown or unbounded field."""


@dataclass(frozen=True, slots=True)
class ContainmentTraceEvent:
    schema_version: str
    event_type: str
    payload: Mapping[str, Any]


def build_trace_event(*, event_type: str, payload: Mapping[str, Any]) -> ContainmentTraceEvent:
    if event_type not in _EVENT_FIELDS:
        raise TraceContractError("event_type is not registered by native containment")
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
        if key.endswith("_ref"):
            normalized[key] = _digest(value, key)
        else:
            normalized[key] = _text(value, key)
    return ContainmentTraceEvent(
        schema_version=TRACE_CONTRACT_VERSION,
        event_type=event_type,
        payload=MappingProxyType(normalized),
    )


__all__ = ["ContainmentTraceEvent", "TRACE_CONTRACT_VERSION", "TraceContractError", "build_trace_event"]
