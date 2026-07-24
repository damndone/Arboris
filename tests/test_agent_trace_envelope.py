"""Gate 3 Task 1 — a stable, versioned event envelope (spec §13.2).

The repo already writes JSONL. What it does not have is a schema, and without
one the stream is a debug log: readable today, unusable as evidence in six
months when the fields have quietly drifted. Every test here defends the
envelope's shape rather than the fact that something was written.
"""
from pathlib import Path

import pytest

from workbench.agent.trace import (
    TRACE_SCHEMA,
    TraceWriter,
    UnknownTraceEventType,
    TracePayloadError,
)

SCOPE = {
    "project_id": "vix-dofile-repro",
    "notebook_id": "nb_0001",
    "run_family_id": "run-family:11111111-1111-4111-8111-111111111111",
}
VERSIONS = {
    "app_commit": "41b0361",
    "model_id": "deepseek-chat",
    "prompt_version": "notebook-plan/2026-07-22",
    "vocabulary_version": "ts.v3",
    "context_profile": "notebook-plan/v1",
}


def _writer(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path, scope=SCOPE, versions=VERSIONS)


def test_envelope_carries_every_declared_field(tmp_path: Path) -> None:
    writer = _writer(tmp_path)

    event = writer.emit(
        "context.compiled",
        payload={
            "context_id": "ctx_1",
            "generation_context_hash": "sha256:" + "a" * 64,
            "freshness_dependency_fingerprint": "fresh1:" + "b" * 64,
            "compiled_context_blob_ref": "blob:abc",
            "omitted_sections": ["artifact_summaries"],
            "content_chars": 3716,
        },
    )

    assert event["trace_schema"] == TRACE_SCHEMA == "agent-trace-event/v1"
    assert event["event_type"] == "context.compiled/v1"
    assert event["payload_schema"] == "context-compiled/v1"
    assert event["sequence"] == 1
    assert event["scope"] == SCOPE
    assert event["versions"] == VERSIONS
    assert event["actor"] == {"type": "agent"}
    assert event["trace_id"] == writer.trace_id
    assert event["occurred_at"].endswith("+00:00")


def test_sequence_increases_strictly(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    payload = {
        "context_id": "ctx_1",
        "generation_context_hash": "sha256:" + "a" * 64,
        "freshness_dependency_fingerprint": "fresh1:" + "b" * 64,
        "compiled_context_blob_ref": "blob:abc",
        "omitted_sections": [],
        "content_chars": 1,
    }

    sequences = [writer.emit("context.compiled", payload=payload)["sequence"] for _ in range(3)]

    assert sequences == [1, 2, 3]


def test_unknown_event_type_is_refused(tmp_path: Path) -> None:
    """An unregistered type must fail loudly, not land in the stream untyped."""
    writer = _writer(tmp_path)

    with pytest.raises(UnknownTraceEventType):
        writer.emit("something.invented", payload={"whatever": 1})


def test_payload_missing_a_required_field_is_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path)

    with pytest.raises(TracePayloadError) as excinfo:
        writer.emit("context.compiled", payload={"context_id": "ctx_1"})

    assert "generation_context_hash" in str(excinfo.value)


def test_unexpected_payload_field_is_refused(tmp_path: Path) -> None:
    """Typed means typed: extra fields would reintroduce payload: any."""
    writer = _writer(tmp_path)

    with pytest.raises(TracePayloadError):
        writer.emit(
            "context.compiled",
            payload={
                "context_id": "ctx_1",
                "generation_context_hash": "sha256:" + "a" * 64,
                "freshness_dependency_fingerprint": "fresh1:" + "b" * 64,
                "compiled_context_blob_ref": "blob:abc",
                "omitted_sections": [],
                "content_chars": 1,
                "smuggled": "extra",
            },
        )


def test_versions_must_be_complete(tmp_path: Path) -> None:
    """A trace that cannot say which prompt produced it is not evidence."""
    with pytest.raises(TracePayloadError):
        TraceWriter(tmp_path, scope=SCOPE, versions={"app_commit": "41b0361"})


def test_events_are_replayable_from_disk(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.emit(
        "context.compiled",
        payload={
            "context_id": "ctx_1",
            "generation_context_hash": "sha256:" + "a" * 64,
            "freshness_dependency_fingerprint": "fresh1:" + "b" * 64,
            "compiled_context_blob_ref": "blob:abc",
            "omitted_sections": [],
            "content_chars": 1,
        },
    )

    replayed = TraceWriter.replay(tmp_path, writer.trace_id)

    assert [e["event_type"] for e in replayed] == ["context.compiled/v1"]
    assert replayed[0]["payload"]["context_id"] == "ctx_1"
