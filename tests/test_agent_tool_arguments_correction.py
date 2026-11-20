"""A tool call with non-JSON arguments gets one bounded correction instead of failing the turn."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.test_numeric_grounding import INSPECT, ScriptedAdapter, _agent
from workbench.agent.model import ModelStreamEvent


class BrokenArguments:
    """Stands for the provider ending a tool call whose arguments are not JSON."""


class Adapter(ScriptedAdapter):
    async def stream(self, request):
        if self.replies and isinstance(self.replies[0], BrokenArguments):
            self.replies.pop(0)
            self.requests.append(request)
            yield ModelStreamEvent.from_error(request.request_id, "provider_tool_arguments_invalid")
            return
        async for event in super().stream(request):
            yield event


def _run(tmp_path: Path, replies: list[object]):
    agent, _, repository, _ = _agent(tmp_path, [])
    agent.model = adapter = Adapter(replies)
    if hasattr(agent, "adapter"):
        agent.adapter = adapter
    reply = asyncio.run(agent.prompt("男女工资有差别吗"))
    return reply, adapter, repository


def test_one_broken_call_is_corrected_and_the_turn_finishes(tmp_path: Path) -> None:
    reply, adapter, repository = _run(tmp_path, [BrokenArguments(), INSPECT, "p 值为 0.098。"])
    assert reply == "p 值为 0.098。"
    notes = [e.payload for e in repository.get_branch("s") if e.payload.get("name") == "workbench_tool_arguments"]
    assert len(notes) == 1 and notes[0]["model_role"] == "user"
    assert adapter.requests[1].messages[-1]["content"].startswith("[Workbench")


def test_a_second_broken_call_in_one_command_still_fails_visibly(tmp_path: Path) -> None:
    reply, adapter, repository = _run(tmp_path, [BrokenArguments(), BrokenArguments(), "unused"])
    last = [e.payload for e in repository.get_branch("s") if e.payload.get("role") == "assistant"][-1]
    assert last["stop_reason"] == "error" and "provider_tool_arguments_invalid" in last["content"]
    assert len(adapter.requests) == 2
