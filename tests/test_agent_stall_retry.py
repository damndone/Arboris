"""A provider that sends nothing for the idle bound gets a fresh request, at most twice per turn.

Free-route rounds (2026-10-23): 26 of 92 Hy3 turns and 22 of 54 Step-5 turns
ended on a stall and waited for the person to say "continue"; DeepSeek had none.
The stalled stream itself is still abandoned, never waited on (v1.8.5 lesson).
"""
import asyncio

from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
from workbench.llm.config import LLMConfig


def _adapter(monkeypatch, script):
    """script: one entry per request -- 'stall', 'text' or 'text_then_stall'."""
    calls = []

    async def fake_stream(*_args, **_kwargs):
        kind = script[len(calls)] if len(calls) < len(script) else "stall"
        calls.append(kind)
        if kind == "text_then_stall":
            yield {"type": "text_delta", "delta": "partial"}
            await asyncio.sleep(1)
        if kind == "stall":
            await asyncio.sleep(1)
        yield {"type": "text_delta", "delta": "answer"}
        yield {"type": "done", "finish_reason": "stop"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)
    adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url="http://127.0.0.1:3425/v1", api_key="k", model="m"),
                                           idle_timeout_s=0.02)
    adapter.stall_retry_delays_s = (0.0, 0.0)
    return adapter, calls


def _run(adapter, request):
    async def scenario():
        return [event async for event in adapter.stream(request)]
    return asyncio.run(scenario())


def test_a_stall_then_an_answer_completes_the_request(monkeypatch):
    adapter, calls = _adapter(monkeypatch, ["stall", "text"])
    events = _run(adapter, ModelRequest(messages=[], turn_key="turn-1"))
    assert calls == ["stall", "text"]
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[0].error == "provider_no_progress"


def test_the_two_fresh_requests_are_shared_by_the_whole_turn(monkeypatch):
    adapter, calls = _adapter(monkeypatch, ["stall", "text", "stall", "stall"])
    first = _run(adapter, ModelRequest(messages=[], turn_key="turn-1"))
    assert first[-1].type == "done"
    second = _run(adapter, ModelRequest(messages=[], turn_key="turn-1"))
    assert [event.type for event in second] == ["retry", "error"] and second[-1].error == "provider_no_progress"
    third = _run(adapter, ModelRequest(messages=[], turn_key="turn-2"))  # a new turn starts afresh
    assert third[0].type == "retry"


def test_a_stall_after_the_answer_began_is_not_retried(monkeypatch):
    adapter, calls = _adapter(monkeypatch, ["text_then_stall"])
    events = _run(adapter, ModelRequest(messages=[], turn_key="turn-1"))
    assert calls == ["text_then_stall"]
    assert [event.type for event in events] == ["text_delta", "error"]


def test_stopping_during_the_wait_ends_the_request(monkeypatch):
    adapter, calls = _adapter(monkeypatch, ["stall", "text"])
    adapter.stall_retry_delays_s = (5.0, 5.0)

    async def scenario():
        abort = asyncio.Event()
        request = ModelRequest(messages=[], turn_key="turn-1", abort_event=abort)
        events = []
        async for event in adapter.stream(request):
            events.append(event)
            if event.type == "retry":
                abort.set()
        return events
    events = asyncio.run(scenario())
    assert [event.type for event in events] == ["retry", "error"] and events[-1].error == "aborted"
    assert calls == ["stall"]
