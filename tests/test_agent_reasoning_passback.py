"""Private reasoning goes back to the provider that wrote it, filtered like its reply, and nowhere else.

DeepSeek's thinking mode requires an assistant message's reasoning_content on
every later request that carries tools; Workbench used to drop it.
"""

import asyncio

from workbench.agent import model as model_module
from workbench.agent.compaction import estimate_message_tokens
from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter, _to_openai_wire_messages
from workbench.egress import egress_project, guard_outgoing_messages
from workbench.llm.config import LLMConfig

CONFIG = LLMConfig(base_url="https://api.example.test", api_key="secret", model="deepseek-flash", provider_id="deepseek")
SOURCE = {"provider_id": "deepseek", "base_url": "https://api.example.test", "model": "deepseek-flash"}


def _stream(monkeypatch, *attempts):
    calls = []

    async def fake_stream(messages, _config, **_kwargs):
        calls.append(messages)
        for item in attempts[len(calls) - 1]:
            if isinstance(item, Exception):
                raise item
            yield item

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)
    return calls


def _events(adapter, request):
    async def run():
        return [event async for event in adapter.stream(request)]
    return asyncio.run(run())


def test_the_adapter_reports_the_reasoning_privately_with_its_source(monkeypatch):
    _stream(monkeypatch, [
        {"type": "provider_activity", "reasoning": "Check the "},
        {"type": "provider_activity", "reasoning": "residuals first."},
        {"type": "text_delta", "delta": "Done."},
        {"type": "done", "finish_reason": "stop"},
    ])
    events = _events(OpenAICompatibleModelAdapter(CONFIG), ModelRequest(messages=[{"role": "user", "content": "go"}]))
    assert [e.type for e in events] == ["text_delta", "reasoning", "done"]
    assert events[1].delta == "Check the residuals first."
    assert events[1].reasoning_source == SOURCE


def test_a_retried_attempt_keeps_only_the_successful_attempts_reasoning(monkeypatch):
    from workbench.llm import client as llm_client

    _stream(monkeypatch,
            [{"type": "provider_activity", "reasoning": "lost half"}, llm_client.LLMUpstreamError("dropped")],
            [{"type": "provider_activity", "reasoning": "whole"}, {"type": "done", "finish_reason": "stop"}])
    adapter = OpenAICompatibleModelAdapter(CONFIG)
    adapter.retry_delays_s = (0.0,)
    events = _events(adapter, ModelRequest(messages=[{"role": "user", "content": "go"}]))
    assert [e.delta for e in events if e.type == "reasoning"] == ["whole"]


def test_reasoning_is_sent_back_only_to_the_provider_and_model_that_wrote_it():
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "reasoning_content": "mine", "reasoning_source": SOURCE,
         "tool_calls": [{"tool_call_id": "c1", "tool_id": "inspect", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
        {"role": "assistant", "content": "other", "reasoning_content": "theirs",
         "reasoning_source": {**SOURCE, "model": "another-model"}},
    ]
    same = _to_openai_wire_messages(messages, reasoning_source=SOURCE)
    assert same[1]["reasoning_content"] == "mine"
    assert "reasoning_content" not in same[3]
    assert all("reasoning_source" not in message for message in same)
    assert all("reasoning_content" not in message for message in _to_openai_wire_messages(messages))


def test_the_adapter_sends_its_own_earlier_reasoning(monkeypatch):
    calls = _stream(monkeypatch, [{"type": "done", "finish_reason": "stop"}])
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": "", "reasoning_content": "kept", "reasoning_source": SOURCE,
                "tool_calls": [{"tool_call_id": "c1", "tool_id": "inspect", "arguments": {}}]},
               {"role": "tool", "tool_call_id": "c1", "content": "{}"}]
    _events(OpenAICompatibleModelAdapter(CONFIG), ModelRequest(messages=history))
    assert calls[0][1]["reasoning_content"] == "kept"


def test_egress_filters_reasoning_like_the_reply(tmp_path):
    from workbench.egress import save_policy, EgressPolicy

    save_policy(tmp_path, EgressPolicy(columns={"name": "restricted"}))
    with egress_project(tmp_path):
        guarded = guard_outgoing_messages([
            {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true, "output": {"columns": ["name"]}, "error": null}'},
            {"role": "assistant", "content": "C(Q('name'))[T.Alice] matters",
             "reasoning_content": "Look at C(Q('name'))[T.Alice] again."},
        ], base_url="https://api.example.test", provider_id="deepseek", model="deepseek-flash")
    assert "Alice" not in guarded[1]["content"]
    assert "Alice" not in guarded[1]["reasoning_content"]


def test_reasoning_counts_toward_the_context_estimate():
    plain = {"role": "assistant", "content": "x"}
    assert estimate_message_tokens({**plain, "reasoning_content": "y" * 4000}) > estimate_message_tokens(plain) + 500


def test_the_turn_stores_reasoning_on_the_assistant_message_and_never_streams_it(tmp_path):
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.session import JsonlSessionRepository

    class Adapter:
        async def stream(self, request):
            yield model_module.ModelStreamEvent.text_delta(request.request_id, "Answer.")
            yield model_module.ModelStreamEvent.reasoning(request.request_id, "private chain", SOURCE)
            yield model_module.ModelStreamEvent.done(request.request_id)

    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="s", role="chain")
    events = AgentEventStream(tmp_path)
    core = AgentCore(repository, events, Adapter(), session_id="s")
    asyncio.run(core.prompt("go"))
    assistant = [e.payload for e in repository.get_branch("s") if e.entry_type == "message"
                 and e.payload.get("role") == "assistant"][-1]
    assert assistant["reasoning_content"] == "private chain"
    assert assistant["reasoning_source"] == SOURCE
    streamed = events.replay("s")
    assert all("private chain" not in str(e) for e in streamed)

