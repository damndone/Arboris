"""Gate 3 Tasks 2/3/5 — the decision chain, the reward refusal, the boundary.

`test_user_decision_refuses_a_reward_field` is the 命门 of Task 3. A user
clicking an option is evidence that they clicked it, nothing more. The moment a
trace can carry `reward`, someone downstream will train on it, and the label
will have been invented by the logging layer rather than by anyone who looked at
the analysis.
"""
from pathlib import Path

import pytest

from workbench.agent.trace import (
    TRACE_EVENT_SCHEMAS,
    USER_DECISIONS,
    TracePayloadError,
    TraceWriter,
    telemetry_projection,
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
HASH = "sha256:" + "a" * 64
FRESH = "fresh1:" + "b" * 64


def _writer(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path, scope=SCOPE, versions=VERSIONS)


def _full_chain(writer: TraceWriter) -> list[dict]:
    """One option, start to finish, in the order it really happens."""
    events = [
        writer.emit(
            "context.compiled",
            payload={
                "context_id": "ctx_1",
                "generation_context_hash": HASH,
                "freshness_dependency_fingerprint": FRESH,
                "compiled_context_blob_ref": "blob:abc",
                "omitted_sections": ["artifact_summaries"],
                "content_chars": 3716,
            },
        ),
        writer.emit(
            "agent.plan.requested",
            payload={"context_id": "ctx_1", "requested_option_count": 3},
        ),
        writer.emit(
            "agent.plan.completed",
            payload={"context_id": "ctx_1", "generated_option_count": 3, "duration_ms": 4210},
        ),
        writer.emit(
            "option.revision.created",
            payload={
                "option_id": "opt_1",
                "option_revision": 1,
                "generation_context_hash": HASH,
                "freshness_dependency_fingerprint": FRESH,
            },
        ),
        writer.emit(
            "option.lifecycle.changed",
            payload={
                "option_id": "opt_1",
                "option_revision": 1,
                "axis": "lifecycle_status",
                "from_status": "proposed",
                "to_status": "selected",
            },
        ),
        writer.emit(
            "user.decision.recorded",
            payload={"option_id": "opt_1", "option_revision": 1, "decision": "selected"},
        ),
        writer.emit(
            "proposal.validation.completed",
            payload={
                "option_id": "opt_1",
                "option_revision": 1,
                "proposal_id": "prop_1",
                "validation_status": "valid",
            },
        ),
        writer.emit(
            "option.execution.started",
            payload={
                "option_id": "opt_1",
                "option_revision": 1,
                "proposal_id": "prop_1",
                "proposal_revision": 1,
            },
        ),
        writer.emit(
            "option.execution.completed",
            payload={
                "option_id": "opt_1",
                "option_revision": 1,
                "execution_status": "succeeded",
                "run_id": "run_002",
            },
        ),
        writer.emit(
            "artifact_contract.validation.completed",
            payload={"option_id": "opt_1", "option_revision": 1, "validation_status": "passed"},
        ),
        writer.emit(
            "active_head.changed",
            payload={
                "from_run_id": "run_001",
                "to_run_id": "run_002",
                "reason": "option_execution_passed_contract",
            },
        ),
        writer.emit("operation.error", payload={"code": "NONE", "fatal": False}),
    ]
    return events


def test_all_registered_trace_event_types_are_registered() -> None:
    assert set(TRACE_EVENT_SCHEMAS) == {
        "context.compiled",
        "agent.plan.requested",
        "agent.plan.completed",
        "option.revision.created",
        "option.lifecycle.changed",
        "user.decision.recorded",
        "proposal.validation.completed",
        "option.execution.started",
        "option.execution.completed",
        "artifact_contract.validation.completed",
        "active_head.changed",
        "operation.error",
        "evidence.inspection.requested",
        "evidence.inspection.completed",
        "evidence.inspection.failed",
    }


def test_the_chain_is_contiguous_and_correlated(tmp_path: Path) -> None:
    writer = _writer(tmp_path)

    events = _full_chain(writer)

    assert [e["sequence"] for e in events] == list(range(1, 13))
    assert {e["trace_id"] for e in events} == {writer.trace_id}
    replayed = TraceWriter.replay(tmp_path, writer.trace_id)
    assert len(replayed) == 12


def test_user_decision_refuses_a_reward_field(tmp_path: Path) -> None:
    """The 命门: the trace records the click, never grades it."""
    writer = _writer(tmp_path)

    for forbidden in ("reward", "label", "correct", "score", "rating"):
        with pytest.raises(TracePayloadError) as excinfo:
            writer.emit(
                "user.decision.recorded",
                payload={
                    "option_id": "opt_1",
                    "option_revision": 1,
                    "decision": "selected",
                    forbidden: 1,
                },
            )
        assert "evaluation harness" in str(excinfo.value)


def test_every_user_decision_value_is_expressible(tmp_path: Path) -> None:
    """Deferring or asking for an explanation is data too, not an absence of data."""
    writer = _writer(tmp_path)

    for decision in USER_DECISIONS:
        event = writer.emit(
            "user.decision.recorded",
            payload={"option_id": "opt_1", "option_revision": 1, "decision": decision},
        )
        assert event["payload"]["decision"] == decision


def test_telemetry_projection_carries_no_content(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    event = writer.emit(
        "user.decision.recorded",
        payload={"option_id": "opt_secret", "option_revision": 1, "decision": "rejected"},
    )

    projected = telemetry_projection(event)

    assert set(projected) == {
        "trace_schema",
        "event_type",
        "sequence",
        "occurred_at",
        "payload_schema",
        "versions",
    }
    serialized = str(projected)
    assert "opt_secret" not in serialized
    assert SCOPE["project_id"] not in serialized


def test_trace_stays_inside_the_project(tmp_path: Path) -> None:
    """Project-scoped storage is what keeps trace under the project's own ACL."""
    writer = _writer(tmp_path)
    writer.emit("operation.error", payload={"code": "X", "fatal": False})

    written = list(tmp_path.rglob("*.jsonl"))

    assert written
    for path in written:
        assert tmp_path in path.parents
