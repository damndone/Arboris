"""Package-local MEM1 trace payload contracts; Core Trace registration is deferred."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .project_index_contract import ProjectIndexError


TRACE_CONTRACT_VERSION = "workbench.domain_memory.trace/v1"
_EVENT_FIELDS = {
    "memory.project_index.built": frozenset({"index_digest", "revision"}),
    "memory.project_context.projected": frozenset({"index_digest", "fact_count", "omitted_count"}),
}


class ProjectMemoryTraceError(ProjectIndexError):
    """A local memory trace payload is not registered or bounded."""


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ProjectMemoryTraceError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ProjectMemoryTraceEvent:
    schema_version: str
    event_type: str
    payload: Mapping[str, Any]


def build_project_memory_trace(
    *, event_type: str, payload: Mapping[str, Any]
) -> ProjectMemoryTraceEvent:
    if event_type not in _EVENT_FIELDS:
        raise ProjectMemoryTraceError("event_type is not registered by domain memory")
    if not isinstance(payload, Mapping):
        raise ProjectMemoryTraceError("trace payload must be an object")
    expected = _EVENT_FIELDS[event_type]
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ProjectMemoryTraceError(f"trace payload contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ProjectMemoryTraceError(f"trace payload is missing fields: {sorted(missing)}")
    normalized: dict[str, Any] = {"index_digest": _digest(payload["index_digest"], "index_digest")}
    count_field = "revision" if event_type.endswith("built") else "fact_count"
    count = payload[count_field]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ProjectMemoryTraceError(f"{count_field} must be a non-negative integer")
    normalized[count_field] = count
    if event_type.endswith("projected"):
        omitted = payload["omitted_count"]
        if not isinstance(omitted, int) or isinstance(omitted, bool) or omitted < 0:
            raise ProjectMemoryTraceError("omitted_count must be a non-negative integer")
        normalized["omitted_count"] = omitted
    return ProjectMemoryTraceEvent(
        schema_version=TRACE_CONTRACT_VERSION,
        event_type=event_type,
        payload=MappingProxyType(normalized),
    )


__all__ = [
    "ProjectMemoryTraceError",
    "ProjectMemoryTraceEvent",
    "TRACE_CONTRACT_VERSION",
    "build_project_memory_trace",
]
