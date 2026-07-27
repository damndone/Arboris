from __future__ import annotations

import pytest

from workbench.domain_memory.trace_contracts import (
    ProjectMemoryTraceError,
    build_project_memory_trace,
)


def test_project_memory_trace_contract_is_local_and_strict() -> None:
    event = build_project_memory_trace(
        event_type="memory.project_index.built",
        payload={"index_digest": "a" * 64, "revision": 1},
    )
    assert event.schema_version == "workbench.domain_memory.trace/v1"
    assert event.payload["revision"] == 1

    with pytest.raises(ProjectMemoryTraceError, match="unknown"):
        build_project_memory_trace(
            event_type="memory.project_index.built",
            payload={"index_digest": "a" * 64, "revision": 1, "score": "no"},
        )


def test_project_memory_trace_does_not_accept_decision_or_authority_labels() -> None:
    with pytest.raises(ProjectMemoryTraceError, match="registered"):
        build_project_memory_trace(
            event_type="memory.project_index.approved",
            payload={"index_digest": "a" * 64, "revision": 1},
        )

    with pytest.raises(ProjectMemoryTraceError, match="payload"):
        build_project_memory_trace(
            event_type="memory.project_context.projected",
            payload={"index_digest": "a" * 64, "fact_count": 1, "label": "correct"},
        )
