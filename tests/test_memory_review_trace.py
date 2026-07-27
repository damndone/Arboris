from __future__ import annotations

import pytest

from workbench.domain_memory.trace_contracts import DomainMemoryTraceError, build_domain_memory_trace


def test_mem3_trace_events_are_exact_and_bounded() -> None:
    review = build_domain_memory_trace(
        event_type="domain_memory.review.completed",
        payload={"review_ref": "review-1", "candidate_or_content_ref": "candidate-1", "outcome": "approved"},
    )
    conflict = build_domain_memory_trace(
        event_type="domain_memory.conflict.recorded",
        payload={"conflict_ref": "conflict-1", "content_revision_refs": ["memory-1@1", "memory-2@1"]},
    )
    assert review.payload["outcome"] == "approved"
    assert conflict.payload["content_revision_refs"] == ("memory-1@1", "memory-2@1")


def test_mem3_trace_rejects_unknown_or_unsafe_effects() -> None:
    with pytest.raises(DomainMemoryTraceError):
        build_domain_memory_trace(
            event_type="domain_memory.usage.recorded",
            payload={"content_revision_ref": "memory-1@1", "context_manifest_ref": "manifest-1", "effect_kind": "execute_code"},
        )
