"""Literal Unicode separators belong to JSON strings, not durable record boundaries."""
import asyncio
from dataclasses import replace
import json

import pytest

from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.model_replay import RecordingError, ReplayAdapter
from workbench.agent.plans import Plan, PlanStore
from workbench.agent.proposals import ProposalInvocation, ProposalStore
from workbench.jsonl_store import append_jsonl_atomic, read_jsonl
from tests.test_agent_model_replay import FakeModel, _collect, _record, _request
from tests.test_agent_proposal_operations import proposal_kwargs


@pytest.fixture(params=["\u2028", "\u2029", "\u0085"])
def text(request):
    return f"first paragraph{request.param}second paragraph"


def test_shared_writer_and_reader_preserve_unicode_inside_records(tmp_path, text):
    path = tmp_path / "rows.jsonl"
    rows = [{"text": text}, {"text": "next record"}]
    for row in rows:
        append_jsonl_atomic(path, row)
    raw = path.read_bytes()
    assert text.encode() in raw
    assert read_jsonl(path) == rows
    assert path.read_bytes() == raw


def test_plan_current_and_history_survive_reopening(tmp_path, text):
    original = Plan(plan_id="unicode-plan", version=1, status="draft", question=text,
                    criteria=(text,), steps=(), allowed_classes=())
    store = PlanStore(tmp_path)
    store.save("session-a", original)
    revised = replace(original, version=2, question=text + " revised")
    store.save("session-a", revised)
    reopened = PlanStore(tmp_path)
    assert reopened.current("session-a") == revised
    assert reopened.history("session-a") == [original, revised]


def test_event_replay_and_idempotent_emit_do_not_drop_the_payload(tmp_path, text):
    original = AgentEventStream(tmp_path).emit("session-a", "notice", {"content": text}, event_id="once")
    reopened = AgentEventStream(tmp_path)
    assert reopened.replay("session-a") == [original]
    assert reopened.emit("session-a", "notice", {"content": text}, event_id="once") == original
    assert reopened.replay("session-a") == [original]


def test_prepared_proposal_reuses_the_same_durable_admission(tmp_path, text):
    arguments = {**proposal_kwargs(), "session_id": "session-a", "expected_effect": [text]}
    invocation = ProposalInvocation("unicode-invocation", 2, "call-a")
    store = ProposalStore(tmp_path)
    original = store.create_prepared(invocation=invocation, **arguments)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.jsonl")}
    reopened = ProposalStore(tmp_path)
    repeated = reopened.create_prepared(invocation=invocation, **arguments)
    assert repeated == original
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.jsonl")} == before


def test_signed_recording_replays_the_original_unicode_request_and_events(tmp_path, text):
    request = replace(_request(), messages=[{"role": "user", "content": text}])
    model = FakeModel([ModelStreamEvent.text_delta(request.request_id, text),
                       ModelStreamEvent.done(request.request_id)])
    _, _, recorded = _record(tmp_path, request, model)
    path = tmp_path / "provider.jsonl"
    before = path.read_bytes()
    replay = ReplayAdapter(root=tmp_path, name="provider.jsonl")
    assert asyncio.run(_collect(replay, request)) == recorded
    assert replay.remaining == 0 and model.calls == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("separator", [b"\r\n", b"\r"])
def test_signed_recording_keeps_legacy_ascii_record_separators(tmp_path, separator):
    _, _, recorded = _record(tmp_path)
    path = tmp_path / "provider.jsonl"
    # The existing terminal-LF admission remains in force even for CR records.
    path.write_bytes(separator.join(path.read_bytes().split(b"\n")[:-1]) + b"\n")
    replay = ReplayAdapter(root=tmp_path, name="provider.jsonl")
    assert asyncio.run(_collect(replay, _request())) == recorded


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_signed_recording_keeps_the_strict_utf8_encoding_boundary(tmp_path, encoding):
    _record(tmp_path)
    path = tmp_path / "provider.jsonl"
    path.write_bytes(b"\n".join(line.encode(encoding) for line in path.read_text().split("\n")[:-1]) + b"\n")
    with pytest.raises(RecordingError, match="corrupt or unsupported"):
        ReplayAdapter(root=tmp_path, name="provider.jsonl")


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_shared_reader_keeps_legacy_record_endings_and_valid_unterminated_last_record(tmp_path, ending):
    path = tmp_path / "rows.jsonl"
    path.write_bytes((json.dumps({"value": 1}) + ending + json.dumps({"value": 2})).encode())
    assert read_jsonl(path) == [{"value": 1}, {"value": 2}]


def test_shared_reader_only_ignores_the_unterminated_invalid_last_record(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"value": 1}\n{"unfinished":', encoding="utf-8")
    assert read_jsonl(path) == [{"value": 1}]
    for raw in ('{"value": 1}\n{"unfinished":\n', '{"unfinished":\n{"value": 2}\n'):
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSONL record"):
            read_jsonl(path)
