from __future__ import annotations

from pathlib import Path

from workbench.agent.trace import TraceWriter, record_domain_memory_retrieval


def test_domain_memory_trace_is_ref_only_and_versioned(tmp_path: Path) -> None:
    writer = TraceWriter(
        tmp_path,
        scope={"project_id": "project-1", "notebook_id": "notebook-1", "run_family_id": "family-1"},
        versions={
            "app_commit": "test",
            "model_id": "test",
            "prompt_version": "test",
            "vocabulary_version": "test",
            "context_profile": "notebook-plan/v1",
        },
    )

    event = record_domain_memory_retrieval(
        writer,
        {
            "retrieval_ref": "retrieval-1",
            "scope_ref": "scope-1",
            "preference_ref": "preference-1",
            "outcome": "used",
            "entries": [{"memory_id": "memory-1", "compact_lesson": "must not enter trace"}],
            "omissions": [],
        },
    )

    assert event["event_type"] == "domain_memory.retrieval.completed/v1"
    assert event["payload"] == {
        "retrieval_ref": "retrieval-1",
        "scope_ref": "scope-1",
        "preference_ref": "preference-1",
        "outcome": "used",
        "entry_count": 1,
        "omission_count": 0,
    }
    assert "compact_lesson" not in event["payload"]
