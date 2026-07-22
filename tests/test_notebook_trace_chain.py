"""Gate 4 × Gate 3 — one decision chain must emit all twelve trace event types.

Spec §13.3. The chain deliberately contains a *failed* attempt followed by a
successful retry, because `operation.error` and the failure path only exist on
the unhappy branch — a test that only walks the happy path would silently leave
two of the twelve unexercised.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.trace import (
    TRACE_EVENT_SCHEMAS,
    TracePayloadError,
    TraceWriter,
    record_compiled_context,
)
from workbench.contracts.agent.notebook_option import ExpectedArtifact
from workbench.lineage.run_family import bind_run_to_family

from tests.test_notebook_support import make_project, make_run, model_rerun_proposal

_REQUIRED = (
    ExpectedArtifact(
        artifact_id="ts.parameters", artifact_type="time_series_json", required=True, count=1
    ),
)


def _draft(proposal_id: str, covariance: str, option_id: str | None = None) -> OptionDraft:
    return OptionDraft(
        rank=1,
        rationale=covariance,
        proposal=TypedProposal.from_dict(
            model_rerun_proposal(proposal_id, covariance=covariance)
        ),
        expected_artifacts=_REQUIRED,
        option_id=option_id,
    )


def test_one_decision_chain_emits_every_registered_trace_event_type(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(
        title="n", created_by="u", user_focus={"selected_text_hash": "sha256:aaa"}
    )
    trace = TraceWriter(
        project,
        scope={
            "project_id": project.name,
            "notebook_id": notebook.notebook_id,
            "run_family_id": notebook.run_family_id,
        },
        versions={
            "app_commit": "c",
            "model_id": "m",
            "prompt_version": "p",
            "vocabulary_version": "v",
            "context_profile": "notebook-plan/v1",
        },
    )
    context = service.compile_context(notebook.notebook_id)
    record_compiled_context(trace, context)

    (option,) = service.propose_batch(
        notebook.notebook_id, context=context, drafts=[_draft("p1", "robust")], trace=trace
    )
    service.record_decision(
        notebook.notebook_id,
        option.option_id,
        decision="selected",
        actor="user_1",
        trace=trace,
    )
    service.confirm(
        notebook.notebook_id,
        option.option_id,
        option_revision=1,
        proposal_id="p1",
        proposal_revision=1,
        context=service.compile_context(notebook.notebook_id),
        trace=trace,
    )
    failed = make_run(project, "run_failed")
    bind_run_to_family(failed, run_family_id=notebook.run_family_id, bound_by="test")
    first = service.complete_execution(
        notebook.notebook_id,
        option.option_id,
        execution_status="succeeded",
        run_id="run_failed",
        produced_artifacts=[{"artifact_id": "ts.final_model", "artifact_type": "time_series_json"}],
        trace=trace,
    )
    assert first.active_head_advanced is False

    # Retry the same option; this time the run produces what it promised.
    service.confirm(
        notebook.notebook_id,
        option.option_id,
        option_revision=1,
        proposal_id="p1",
        proposal_revision=1,
        context=service.compile_context(notebook.notebook_id),
        trace=trace,
    )
    good = make_run(project, "run_good")
    bind_run_to_family(good, run_family_id=notebook.run_family_id, bound_by="test")
    second = service.complete_execution(
        notebook.notebook_id,
        option.option_id,
        execution_status="succeeded",
        run_id="run_good",
        produced_artifacts=[
            {"artifact_id": "ts.parameters", "artifact_type": "time_series_json"}
        ],
        trace=trace,
    )
    assert second.active_head_advanced is True

    events = TraceWriter.replay(project, trace.trace_id)
    emitted = {event["event_type"] for event in events}
    assert emitted == {f"{name}/v1" for name in TRACE_EVENT_SCHEMAS}
    # The stream is ordered and gapless, so "what happened next" is answerable.
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["scope"]["notebook_id"] == notebook.notebook_id for event in events)
    assert all(event["trace_schema"] == "agent-trace-event/v1" for event in events)

    head_changes = [e for e in events if e["event_type"] == "active_head.changed/v1"]
    assert [e["payload"]["to_run_id"] for e in head_changes] == ["run_good"]
    assert head_changes[0]["payload"]["from_run_id"] is None

    errors = [e for e in events if e["event_type"] == "operation.error/v1"]
    assert [e["payload"]["code"] for e in errors] == ["ARTIFACT_CONTRACT_UNSATISFIED"]
    assert errors[0]["payload"]["fatal"] is False

    decisions = [e for e in events if e["event_type"] == "user.decision.recorded/v1"]
    assert [e["payload"]["decision"] for e in decisions] == ["selected"]
    assert set(decisions[0]["payload"]) == {"option_id", "option_revision", "decision"}


def test_a_decision_carrying_a_reward_is_refused_by_the_trace_schema(tmp_path: Path) -> None:
    """DEC-TRACE-001 — a v1.8.1 trace records observations, not judgements."""
    project = make_project(tmp_path)
    trace = TraceWriter(
        project,
        scope={"project_id": "p", "notebook_id": "nb", "run_family_id": "run-family:x"},
        versions={
            "app_commit": "c",
            "model_id": "m",
            "prompt_version": "p",
            "vocabulary_version": "v",
            "context_profile": "notebook-plan/v1",
        },
    )

    with pytest.raises(TracePayloadError) as excinfo:
        trace.emit(
            "user.decision.recorded",
            payload={
                "option_id": "opt_1",
                "option_revision": 1,
                "decision": "selected",
                "reward": 1.0,
            },
        )

    assert "reward" in str(excinfo.value)
