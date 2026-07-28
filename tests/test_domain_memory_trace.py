from __future__ import annotations

import pytest

from workbench.domain_memory.trace_contracts import DomainMemoryTraceError, build_domain_memory_trace


def test_mem2_trace_catalog_is_exact_and_bounded() -> None:
    event = build_domain_memory_trace(
        event_type="domain_memory.retrieval.completed",
        payload={"retrieval_ref": "retrieval-1", "scope_ref": "a" * 64, "outcome": "used"},
    )
    assert event.event_type == "domain_memory.retrieval.completed"
    assert event.payload["outcome"] == "used"


def test_mem2_trace_rejects_unknown_fields_and_raw_payload() -> None:
    with pytest.raises(DomainMemoryTraceError):
        build_domain_memory_trace(
            event_type="domain_memory.preference.changed",
            payload={"preference_ref": "preference-1", "scope_ref": "a" * 64, "to_status": "enabled", "raw": "rows"},
        )
    with pytest.raises(DomainMemoryTraceError):
        build_domain_memory_trace(
            event_type="domain_memory.content.created",
            payload={"content_revision_ref": "content-1", "content_hash": "not-a-digest"},
        )
