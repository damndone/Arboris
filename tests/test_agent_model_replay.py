"""Strict provider recording and offline replay using only fake models."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import importlib
import importlib.util
import hashlib
import json
import os
from pathlib import Path

import pytest

from workbench.agent.model import ModelRequest, ModelStreamEvent


def _api():
    assert importlib.util.find_spec("workbench.agent.model_replay") is not None, (
        "Provider record/replay needs a reusable adapter boundary"
    )
    return importlib.import_module("workbench.agent.model_replay")


async def _collect(adapter, request):
    return [event async for event in adapter.stream(request)]


class FakeModel:
    def __init__(self, events=None, *, exception=None):
        self.events = events
        self.exception = exception
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        events = self.events if self.events is not None else [ModelStreamEvent.done(request.request_id)]
        for event in events:
            yield replace(event, request_id=request.request_id)
        if self.exception is not None:
            raise self.exception


def _request():
    return ModelRequest(
        request_id="original-request",
        messages=[{"role": "user", "content": "Inspect the schema", "name": "researcher"}],
        tools=[{"tool_id": "inspect_schema", "version": "v1", "input_schema": {"type": "object"}}],
        response_schema={"type": "object", "required": ["result"]},
        model_config={"temperature": 0, "extra_body": {"thinking": {"type": "disabled"}}},
    )


def _record(root, request=None, model=None):
    api = _api()
    request = request or _request()
    model = model or FakeModel()
    recorder = api.RecordingAdapter(model, root=root, name="provider.jsonl")
    events = asyncio.run(_collect(recorder, request))
    return recorder, model, events


def _payloads(root):
    return [json.loads(line)["payload"] for line in (root / "provider.jsonl").read_text().splitlines()]


def test_events_retry_usage_provider_ids_and_tool_call_ids_roundtrip(tmp_path):
    request = _request()
    events = [
        ModelStreamEvent.retrying(request.request_id, "temporary_429"),
        ModelStreamEvent.text_delta(request.request_id, "Inspecting"),
        ModelStreamEvent.tool_call_delta(request.request_id, {
            "tool_call_id": "original-tool-call", "tool_id": "inspect_schema", "arguments": {},
        }),
        ModelStreamEvent(
            type="done", request_id=request.request_id, finish_reason="tool_calls",
            provider_request_id="provider-original",
            usage={"prompt_tokens": 80, "completion_tokens": 9, "prompt_cache_hit_tokens": 60},
        ),
    ]
    _, model, recorded = _record(tmp_path, request, FakeModel(events))
    replay = _api().ReplayAdapter(root=tmp_path, name="provider.jsonl")
    replayed = asyncio.run(_collect(replay, replace(request, request_id="new-request", abort_event=asyncio.Event())))
    assert replayed == [replace(event, request_id="new-request") for event in recorded]
    assert replayed[2].tool_call["tool_call_id"] == "original-tool-call"
    assert replayed[-1].provider_request_id == "provider-original"
    assert model.calls == 1 and replay.remaining == 0


@pytest.mark.parametrize("field,value", [
    ("messages", [{"role": "user", "content": "Different question", "name": "researcher"}]),
    ("tools", [{"tool_id": "inspect_schema", "version": "v2", "input_schema": {"type": "object"}}]),
    ("response_schema", {"type": "object"}),
    ("model_config", {"temperature": 0.1, "extra_body": {"thinking": {"type": "disabled"}}}),
    ("messages", [{"role": "user", "content": "Inspect the schema"}]),
    ("messages", [{"role": "user", "content": "Inspect the schema", "name": "researcher", "request_id": "visible"}]),
])
def test_request_drift_is_rejected_without_consumption_or_upstream(tmp_path, field, value):
    request = _request()
    _, model, _ = _record(tmp_path, request)
    api = _api()
    replay = api.ReplayAdapter(root=tmp_path, name="provider.jsonl")
    with pytest.raises(api.ReplayMismatch, match="request mismatch"):
        asyncio.run(_collect(replay, replace(request, **{field: value})))
    assert replay.remaining == 1 and model.calls == 1
    assert not hasattr(replay, "adapter")
    assert asyncio.run(_collect(replay, request))[-1].type == "done"
    with pytest.raises(api.ReplayExhausted, match="exhausted"):
        asyncio.run(_collect(replay, request))


def test_terminal_provider_error_is_recorded_without_conversion_to_success(tmp_path):
    request = _request()
    _, _, original = _record(tmp_path, request, FakeModel([
        ModelStreamEvent.retrying(request.request_id, "retry"),
        ModelStreamEvent.from_error(request.request_id, "provider_failed"),
    ]))
    replay = _api().ReplayAdapter(root=tmp_path, name="provider.jsonl")
    assert asyncio.run(_collect(replay, request)) == original
    assert _payloads(tmp_path)[-1]["complete"] is True
    assert _payloads(tmp_path)[-1]["termination"] == "error"


@pytest.mark.parametrize("failure", ["eof", "exception", "exception_after_done", "length", "after_terminal"])
def test_incomplete_or_malformed_stream_never_becomes_a_successful_replay(tmp_path, failure):
    api = _api()
    request = _request()
    events = [ModelStreamEvent.text_delta(request.request_id, "partial")]
    if failure == "length":
        events.append(ModelStreamEvent.done(request.request_id, "length"))
    elif failure == "after_terminal":
        events.extend([ModelStreamEvent.done(request.request_id), ModelStreamEvent.text_delta(request.request_id, "late")])
    elif failure == "exception_after_done":
        events.append(ModelStreamEvent.done(request.request_id))
    model = FakeModel(events, exception=RuntimeError("upstream crash") if failure.startswith("exception") else None)
    recorder = api.RecordingAdapter(model, root=tmp_path, name="provider.jsonl")
    with pytest.raises(RuntimeError if failure.startswith("exception") else api.RecordingError):
        asyncio.run(_collect(recorder, request))
    assert _payloads(tmp_path)[-1]["complete"] is False
    replay = api.ReplayAdapter(root=tmp_path, name="provider.jsonl")
    with pytest.raises(api.ReplayIncomplete, match="incomplete"):
        asyncio.run(_collect(replay, request))


def test_consumer_close_leaves_an_incomplete_record(tmp_path):
    api = _api()

    async def scenario():
        request = _request()
        recorder = api.RecordingAdapter(FakeModel([
            ModelStreamEvent.text_delta(request.request_id, "partial"),
            ModelStreamEvent.done(request.request_id),
        ]), root=tmp_path, name="provider.jsonl")
        stream = recorder.stream(request)
        assert (await anext(stream)).delta == "partial"
        await stream.aclose()

    asyncio.run(scenario())
    assert _payloads(tmp_path)[-1]["complete"] is False
    assert _payloads(tmp_path)[-1]["termination"] == "consumer_closed"


@pytest.mark.parametrize("cancel_task", [False, True])
def test_recording_abort_or_task_cancellation_is_durable(tmp_path, cancel_task):
    api = _api()

    async def scenario():
        started = asyncio.Event()

        class Blocking:
            async def stream(self, request):
                started.set()
                await asyncio.Event().wait()
                yield ModelStreamEvent.done(request.request_id)

        abort = asyncio.Event()
        recorder = api.RecordingAdapter(Blocking(), root=tmp_path, name="provider.jsonl")
        task = asyncio.create_task(_collect(recorder, replace(_request(), abort_event=abort)))
        await started.wait()
        if cancel_task:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            abort.set()
            result = await asyncio.wait_for(task, timeout=1)
            assert len(result) == 1 and result[0].error == "aborted"

    asyncio.run(scenario())
    assert _payloads(tmp_path)[-1]["complete"] is False
    assert _payloads(tmp_path)[-1]["termination"] == ("cancelled" if cancel_task else "aborted")


def test_replay_honors_current_abort_before_and_between_events(tmp_path):
    request = _request()
    _record(tmp_path, request, FakeModel([
        ModelStreamEvent.text_delta(request.request_id, "first"),
        ModelStreamEvent.done(request.request_id),
    ]))

    async def scenario():
        replay = _api().ReplayAdapter(root=tmp_path, name="provider.jsonl")
        abort = asyncio.Event()
        abort.set()
        cancelled = await _collect(replay, replace(request, abort_event=abort))
        assert cancelled[0].error == "aborted" and replay.remaining == 1
        abort.clear()
        stream = replay.stream(replace(request, abort_event=abort))
        assert (await anext(stream)).delta == "first"
        abort.set()
        assert (await anext(stream)).error == "aborted"
        await stream.aclose()
        assert replay.remaining == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("corruption", ["half_write", "checksum", "removed_end", "empty", "version"])
def test_corrupt_or_truncated_files_fail_closed(tmp_path, corruption):
    _record(tmp_path)
    path = tmp_path / "provider.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    if corruption == "half_write":
        path.write_text("".join(lines)[:-5])
    elif corruption == "checksum":
        path.write_text(path.read_text().replace('"stop"', '"other"'))
    elif corruption == "removed_end":
        path.write_text("".join(lines[:-1]))
    elif corruption == "version":
        path.write_text(path.read_text().replace('"version":1', '"version":2'))
    else:
        path.write_text("")
    with pytest.raises(_api().RecordingError):
        _api().ReplayAdapter(root=tmp_path, name="provider.jsonl")


def test_existing_record_is_never_overwritten(tmp_path):
    _record(tmp_path)
    path = tmp_path / "provider.jsonl"
    original = path.read_bytes()
    with pytest.raises(_api().RecordingError):
        _api().RecordingAdapter(FakeModel(), root=tmp_path, name="provider.jsonl")
    assert path.read_bytes() == original


@pytest.mark.parametrize("name", ["../outside.jsonl", "/outside.jsonl", "nested/file.jsonl", "..", ""])
def test_record_paths_cannot_escape_the_explicit_directory(tmp_path, name):
    api = _api()
    for constructor in (
        lambda: api.RecordingAdapter(FakeModel(), root=tmp_path, name=name),
        lambda: api.ReplayAdapter(root=tmp_path, name=name),
    ):
        with pytest.raises(api.RecordingError):
            constructor()


def test_symlink_roots_ancestors_and_files_are_rejected(tmp_path):
    api = _api()
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    (real / "nested").mkdir()
    for root in (tmp_path / "linked", tmp_path / "linked" / "nested"):
        with pytest.raises(api.RecordingError):
            api.RecordingAdapter(FakeModel(), root=root, name="provider.jsonl")
    _record(real)
    (tmp_path / "provider.jsonl").symlink_to(real / "provider.jsonl")
    with pytest.raises(api.RecordingError):
        api.ReplayAdapter(root=tmp_path, name="provider.jsonl")
    with pytest.raises(api.RecordingError):
        api.RecordingAdapter(FakeModel(), root=tmp_path, name="provider.jsonl")


def test_real_agent_core_multiround_tool_loop_records_and_replays_offline(tmp_path):
    api = _api()
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.tools import ToolDefinition, ToolRegistry

    class ToolThenAnswer:
        def __init__(self):
            self.calls = 0

        async def stream(self, request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "fixed-call-id", "tool_id": "inspect_schema", "arguments": {},
                })
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "The schema contains wage.")
                yield ModelStreamEvent.done(request.request_id)

    async def run(adapter, root):
        repository = JsonlSessionRepository(root)
        repository.create_session("session", chain_id="chain", role="chain")
        tools = ToolRegistry()
        tools.register(ToolDefinition(
            "inspect_schema", "v1", {"type": "object"}, "none",
            lambda arguments, context: {"columns": ["wage"]},
        ))
        core = AgentCore(repository, AgentEventStream(root), adapter, session_id="session",
                         tools=tools.descriptors(), tool_runtime=tools)
        return await core.prompt("Inspect the schema and summarize it.")

    upstream = ToolThenAnswer()
    recorder = api.RecordingAdapter(upstream, root=tmp_path, name="provider.jsonl")
    first = asyncio.run(run(recorder, tmp_path / "original"))
    replay = api.ReplayAdapter(root=tmp_path, name="provider.jsonl")
    second = asyncio.run(run(replay, tmp_path / "replayed"))
    assert first == second == "The schema contains wage."
    assert upstream.calls == 2 and replay.remaining == 0


def test_preaborted_recording_does_not_open_the_upstream_stream(tmp_path):
    api = _api()

    class MustNotStart:
        def stream(self, request):
            pytest.fail("An already aborted recording must not open an upstream stream")

    async def scenario():
        abort = asyncio.Event()
        abort.set()
        recorder = api.RecordingAdapter(MustNotStart(), root=tmp_path, name="provider.jsonl")
        events = await _collect(recorder, replace(_request(), abort_event=abort))
        assert events[0].error == "aborted"

    asyncio.run(scenario())
    assert _payloads(tmp_path)[-1]["complete"] is False


def test_model_mutation_cannot_change_the_recorded_request_or_prior_events(tmp_path):
    request = _request()

    class Mutating:
        async def stream(self, request):
            call = {"tool_call_id": "call", "tool_id": "inspect_schema", "arguments": {"items": []}}
            yield ModelStreamEvent.tool_call_delta(request.request_id, call)
            call["arguments"]["items"].append("later mutation")
            request.messages[0]["content"] = "mutated by provider"
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    _, _, events = _record(tmp_path, request, Mutating())
    replayed = asyncio.run(_collect(_api().ReplayAdapter(root=tmp_path, name="provider.jsonl"), _request()))
    assert replayed == events
    assert replayed[0].tool_call["arguments"] == {"items": []}


def test_rehashed_false_completion_and_unsupported_version_are_still_rejected(tmp_path):
    _record(tmp_path)
    payloads = _payloads(tmp_path)

    def write(payloads):
        previous = None
        records = []
        for index, payload in enumerate(payloads):
            body = {"index": index, "previous_sha256": previous, "payload": payload}
            previous = hashlib.sha256(json.dumps(
                body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
            ).encode()).hexdigest()
            records.append(json.dumps({**body, "sha256": previous}))
        (tmp_path / "provider.jsonl").write_text("\n".join(records) + "\n")

    payloads[0]["version"] = 2
    write(payloads)
    with pytest.raises(_api().RecordingError):
        _api().ReplayAdapter(root=tmp_path, name="provider.jsonl")
    payloads[0]["version"] = 1
    payloads[2]["event"]["type"] = "text_delta"
    write(payloads)
    with pytest.raises(_api().RecordingError):
        _api().ReplayAdapter(root=tmp_path, name="provider.jsonl")


def test_file_replacement_or_hardlink_is_rejected_without_modifying_the_replacement(tmp_path):
    api = _api()
    recorder = api.RecordingAdapter(FakeModel(), root=tmp_path, name="provider.jsonl")
    path = tmp_path / "provider.jsonl"
    path.rename(tmp_path / "original.jsonl")
    path.write_bytes(b"unrelated contents\n")
    with pytest.raises(api.RecordingError):
        asyncio.run(_collect(recorder, _request()))
    assert path.read_bytes() == b"unrelated contents\n"
    os.link(tmp_path / "original.jsonl", tmp_path / "hardlinked.jsonl")
    with pytest.raises(api.RecordingError):
        api.ReplayAdapter(root=tmp_path, name="hardlinked.jsonl")
