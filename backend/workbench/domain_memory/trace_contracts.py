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


class DomainMemoryTraceError(ProjectMemoryTraceError):
    """A MEM2 local trace payload is not registered or bounded."""


_DOMAIN_EVENT_FIELDS = {
    "domain_memory.preference.changed": frozenset({"preference_ref", "scope_ref", "to_status"}),
    "domain_memory.candidate.created": frozenset({"candidate_ref", "summary_manifest_ref"}),
    "domain_memory.content.created": frozenset({"content_revision_ref", "content_hash"}),
    "domain_memory.source_access.validity_changed": frozenset({"source_access_binding_ref", "validity_ref", "to_status"}),
    "domain_memory.approval.recorded": frozenset({"approval_ref", "content_revision_ref", "outcome"}),
    "domain_memory.validity.changed": frozenset({"approval_ref", "validity_ref", "to_status"}),
    "domain_memory.retrieval.completed": frozenset({"retrieval_ref", "scope_ref", "outcome"}),
}


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


def build_domain_memory_trace(*, event_type: str, payload: Mapping[str, Any]) -> ProjectMemoryTraceEvent:
    if event_type not in _DOMAIN_EVENT_FIELDS:
        raise DomainMemoryTraceError("domain memory event_type is not registered")
    if not isinstance(payload, Mapping):
        raise DomainMemoryTraceError("trace payload must be an object")
    expected = _DOMAIN_EVENT_FIELDS[event_type]
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown or missing:
        raise DomainMemoryTraceError("domain memory trace payload fields are invalid")
    normalized: dict[str, Any] = {}
    for field in expected:
        value = payload[field]
        if field.endswith("_hash") or field == "scope_ref":
            try:
                normalized[field] = _digest(value, field)
            except ProjectMemoryTraceError as error:
                raise DomainMemoryTraceError(str(error)) from error
        elif field in {"preference_ref", "candidate_ref", "summary_manifest_ref", "content_revision_ref", "source_access_binding_ref", "validity_ref", "approval_ref", "retrieval_ref"}:
            if not isinstance(value, str) or not value or "/" in value or "\\" in value or len(value) > 256:
                raise DomainMemoryTraceError(f"{field} must be an opaque bounded ref")
            normalized[field] = value
        elif field == "to_status":
            if value not in {"enabled", "disabled", "valid", "revoked", "deleted", "tainted", "superseded", "active", "stale", "archived"}:
                raise DomainMemoryTraceError("to_status is not registered")
            normalized[field] = value
        elif field == "outcome":
            if value not in {"used", "not_used", "empty", "blocked", "approved", "rejected"}:
                raise DomainMemoryTraceError("outcome is not registered")
            normalized[field] = value
    return ProjectMemoryTraceEvent(
        schema_version=TRACE_CONTRACT_VERSION,
        event_type=event_type,
        payload=MappingProxyType(normalized),
    )


__all__ = [
    "DomainMemoryTraceError",
    "ProjectMemoryTraceError",
    "ProjectMemoryTraceEvent",
    "TRACE_CONTRACT_VERSION",
    "build_domain_memory_trace",
    "build_project_memory_trace",
]
