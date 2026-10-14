"""Conversation compaction (specs/2026-10-14-v1.9.0-agent-context-design.md)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from workbench.agent import numeric_grounding
from workbench.agent.compaction import (
    CompactionPolicy,
    compact,
    estimate_text_tokens,
    plan_cut,
)
from workbench.agent.context import ContextBuilder
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.session import JsonlSessionRepository


class Scripted:
    """Replies in order; ``"!overflow"`` fails as a too-long request."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if reply == "!overflow":
            yield ModelStreamEvent.from_error(request.request_id, "LLMUpstreamError:upstream_400:context_overflow")
            return
        yield ModelStreamEvent.text_delta(request.request_id, reply)
        yield ModelStreamEvent.done(request.request_id)


def session(tmp_path: Path) -> JsonlSessionRepository:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    standing = [("workbench_agent_protocol", "protocol v1"), ("workbench_agent_identity", "identity"),
                ("workbench_context", "context with R2 0.984")]
    for name, content in standing:
        repository.append("s", "custom_message", {"audience": "model", "name": name, "content": content})
    return repository


def exchange(repository: JsonlSessionRepository, question: str, answer: str, *, tool: str | None = None) -> None:
    repository.append("s", "message", {"role": "user", "content": question})
    if tool is not None:
        repository.append("s", "message", {"role": "assistant", "content": "", "tool_calls": [{"tool_call_id": "t1", "tool_id": "inspect", "arguments": {}}]})
        repository.append("s", "message", {"role": "tool", "tool_call_id": "t1", "name": "inspect", "content": tool})
    repository.append("s", "message", {"role": "assistant", "content": answer})


def run(coroutine):
    return asyncio.run(coroutine)


def test_the_cut_is_a_user_message_so_a_tool_result_stays_with_its_call(tmp_path):
    repository = session(tmp_path)
    exchange(repository, "q1 " + "x" * 400, "a1", tool='{"coef": 2564.12}')
    exchange(repository, "q2", "a2", tool='{"se": 74.03}')
    exchange(repository, "q3", "a3")
    plan = plan_cut(repository.get_branch("s"), keep_recent_tokens=10)
    assert plan.first_kept.payload == {"role": "user", "content": "q3"}
    roles = [entry.payload.get("role") for entry in plan.summarize]
    assert roles == ["user", "assistant", "tool", "assistant"] * 2
    # Standing messages are never summarized.
    assert all(entry.entry_type == "message" for entry in plan.summarize)


def test_one_exchange_is_never_compacted(tmp_path):
    repository = session(tmp_path)
    exchange(repository, "only question", "answer")
    assert plan_cut(repository.get_branch("s"), keep_recent_tokens=1) is None


def test_after_compaction_the_model_sees_standing_messages_summary_then_kept_messages(tmp_path):
    repository = session(tmp_path)
    exchange(repository, "q1", "a1", tool='{"coef": 2564.12}')
    exchange(repository, "q2", "a2")
    adapter = Scripted(["## Analyses and results\neducation coefficient 2564.12 (run r1)"])
    entry = run(compact(repository, "s", adapter, CompactionPolicy(None), trigger="manual", tokens_before=999))
    assert entry.payload["verified"] is True and entry.payload["first_kept_entry_id"]
    messages = ContextBuilder(repository).build("s").messages
    names = [message.get("name") for message in messages]
    assert names[:3] == ["workbench_agent_protocol", "workbench_agent_identity", "workbench_context"]
    assert names[3] == "context_compaction" and "2564.12" in messages[3]["content"]
    assert [message["content"] for message in messages[4:]] == ["q2", "a2"]
    # The summarizer was asked for a transcript, not a conversation to continue.
    request = adapter.requests[0].messages[1]["content"]
    assert "[User]: q1" in request and '[Tool result inspect]: {"coef": 2564.12}' in request
    # A verified summary's numbers support later answers.
    assert numeric_grounding.check("The coefficient is 2564.12.", messages) == ()


def test_a_summary_with_an_unsupported_number_is_rewritten_once_then_kept_out_of_evidence(tmp_path):
    repository = session(tmp_path)
    exchange(repository, "q1", "a1", tool='{"coef": 2564.12}')
    exchange(repository, "q2", "a2")
    adapter = Scripted(["coefficient 2600.5", "coefficient 2600.5 still"])
    entry = run(compact(repository, "s", adapter, CompactionPolicy(None), trigger="auto", tokens_before=1))
    assert entry.payload["verified"] is False and entry.payload["unverified_numbers"] == ["2600.5"]
    assert "2600.5" in adapter.requests[1].messages[-1]["content"]
    messages = ContextBuilder(repository).build("s").messages
    summary = next(message for message in messages if message.get("name") == "context_compaction_unverified")
    assert "do not cite numbers from it" in summary["content"]
    assert numeric_grounding.check("It was 2600.5.", messages)


def test_a_second_compaction_builds_on_the_first(tmp_path):
    repository = session(tmp_path)
    for index in range(3):
        exchange(repository, f"q{index}", f"a{index}")
    adapter = Scripted(["first summary", "second summary"])
    run(compact(repository, "s", adapter, CompactionPolicy(None), trigger="manual", tokens_before=1))
    exchange(repository, "q3", "a3")
    run(compact(repository, "s", adapter, CompactionPolicy(None), trigger="manual", tokens_before=1))
    second = adapter.requests[1].messages[1]["content"]
    assert "<previous-summary>\nfirst summary" in second and "[User]: q2" in second and "[User]: q0" not in second
    messages = ContextBuilder(repository).build("s").messages
    assert [message["content"] for message in messages if message.get("name", "").startswith("context_compaction")][0].endswith("second summary")
    assert [message["content"] for message in messages if message["role"] in {"user", "assistant"}] == ["q3", "a3"]


def test_a_refreshed_standing_message_replaces_the_older_copy(tmp_path):
    repository = session(tmp_path)
    exchange(repository, "q1", "a1")
    repository.append("s", "custom_message", {"audience": "model", "name": "workbench_context", "content": "context v2"})
    exchange(repository, "q2", "a2")
    exchange(repository, "q3", "a3")
    run(compact(repository, "s", Scripted(["summary"]), CompactionPolicy(None), trigger="manual", tokens_before=1))
    contents = [message["content"] for message in ContextBuilder(repository).build("s").messages]
    assert "context v2" in contents and "context with R2 0.984" not in contents


def agent(tmp_path: Path, replies: list[str], window: int) -> tuple[AgentCore, Scripted, JsonlSessionRepository]:
    repository = session(tmp_path)
    adapter = Scripted(replies)
    core = AgentCore(repository, AgentEventStream(tmp_path / "workbench"), adapter, session_id="s",
                     compaction_policy=CompactionPolicy(window, reserve_tokens=10, keep_recent_tokens=10))
    return core, adapter, repository


def test_the_agent_compacts_before_a_step_that_would_overflow(tmp_path):
    core, adapter, repository = agent(tmp_path, ["summary of q1", "answer two"], window=4_000)
    exchange(repository, "q1 " + "long " * 4_000, "a1")
    run(core.prompt("q2"))
    assert [request.messages[0]["content"] for request in adapter.requests][0].startswith("You write a checkpoint")
    final = adapter.requests[1].messages
    assert any(message.get("name") == "context_compaction" for message in final)
    assert not any("long long" in str(message.get("content")) for message in final)
    kinds = [event.event_type for event in core.events.replay("s")]
    assert kinds.index("compaction_start") < kinds.index("compaction_end") < kinds.index("message_end")


def test_a_provider_overflow_is_compacted_and_retried_once(tmp_path):
    core, adapter, repository = agent(tmp_path, ["!overflow", "summary", "answer"], window=1_000_000)
    exchange(repository, "q1", "a1")
    run(core.prompt("q2"))
    branch = repository.get_branch("s")
    assert branch[-1].payload["content"] == "answer"
    assert any(entry.entry_type == "compaction" and entry.payload["trigger"] == "overflow" for entry in branch)


def test_chinese_text_is_not_underestimated():
    assert estimate_text_tokens("系数为正且显著") == 7
    assert estimate_text_tokens("x" * 35) == 10


def test_an_interrupted_event_line_does_not_break_the_log(tmp_path):
    events = AgentEventStream(tmp_path)
    first = events.emit("s", "a", {})
    with (tmp_path / "agent-events" / "s.jsonl").open("ab") as handle:
        handle.write(b'{"partial":')
    fresh = AgentEventStream(tmp_path)
    second = fresh.emit("s", "b", {})
    assert second.seq == first.seq + 1
    assert [event.event_type for event in fresh.replay("s")] == ["a", "b"]
    assert json.loads((tmp_path / "agent-events" / "s.jsonl").read_text().splitlines()[-1])["event_type"] == "b"


def test_a_large_window_is_worked_within_a_budget(monkeypatch):
    policy = CompactionPolicy.from_config(1_048_576)
    assert policy.window == 1_048_576 and policy.threshold == 200_000
    assert CompactionPolicy.from_config(64_000).threshold == 64_000 - 16_000
    monkeypatch.setenv("WORKBENCH_AGENT_COMPACT_AT", "400_000")
    assert CompactionPolicy.from_config(1_048_576).threshold == 400_000
    monkeypatch.setenv("WORKBENCH_AGENT_COMPACT_AT", "12")
    assert CompactionPolicy.from_config(1_048_576).threshold == 200_000


def test_deepseeks_real_length_refusal_is_recognised():
    from workbench.llm.client import is_context_overflow

    body = (b'{"error": {"message": "This model\'s maximum context length is 1048576 tokens. However, you requested '
            b'1155193 tokens (1155177 in the messages, 16 in the completion). Please reduce the length of the messages '
            b'or completion.", "type": "invalid_request_error"}}')
    assert is_context_overflow(400, body)
    assert not is_context_overflow(400, b'{"error": {"message": "Invalid API key"}}')


def test_the_1m_flag_from_settings_counts_as_a_declared_window():
    policy = CompactionPolicy.from_config(None, supports_1m=True)
    assert policy.window == 1_000_000 and policy.window_declared and policy.threshold == 200_000
    assert CompactionPolicy.from_config(None).window_declared is False
