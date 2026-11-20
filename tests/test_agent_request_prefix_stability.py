"""Every model request of a session extends the previous one byte for byte.

A provider's prompt cache serves the longest common prefix it has seen. The standing layers
(protocol, identity, instructions) lead, the tool definitions do not change, and each later
request only appends, so the earlier request is a byte-identical prefix of the next. Across
sessions only the volatile layers after the standing ones (context, focus) differ.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

from tests.test_agent_core_restart import setup
from tests.test_agent_read_batches import registry
from workbench.agent.model import ModelStreamEvent
from workbench.agent.protocol import CHAIN_AGENT_PROTOCOL, step_vocabulary_lines

STANDING = ("workbench_agent_protocol", "workbench_agent_identity", "workbench_instructions")


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class Recording:
    """Answers with one tool call, then text, per user turn; keeps every request."""

    def __init__(self):
        self.requests = []

    async def stream(self, request):
        self.requests.append({"messages": [dict(message) for message in request.messages],
                              "tools": [definition.to_provider_schema() if hasattr(definition, "to_provider_schema")
                                        else repr(definition) for definition in request.tools or ()]})
        last = request.messages[-1]
        if last.get("role") == "user" and not last.get("name"):
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id": f"call-{len(self.requests)}", "tool_id": "read_a", "arguments": {}})
            yield ModelStreamEvent.done(request.request_id, "tool_calls")
        else:
            yield ModelStreamEvent.text_delta(request.request_id, "Done.")
            yield ModelStreamEvent.done(request.request_id)


def _session(tmp_path, focus_run: str):
    adapter = Recording()
    runtime = registry([("read_a", lambda args, context: {"rows": 3}, "none")])
    core, _store, repository = setup(tmp_path, adapter, runtime=runtime)
    protocol = CHAIN_AGENT_PROTOCOL.replace("{step_vocabulary}", step_vocabulary_lines())
    for name, content in (("workbench_agent_protocol", protocol), ("workbench_agent_identity", "identity"),
                          ("workbench_instructions", "instructions"),
                          ("workbench_context", f"context for {focus_run}"),
                          ("workbench_agent_focus", f"Focus: run {focus_run}")):
        repository.append("session-a", "custom_message", {"name": name, "audience": "model", "content": content})
    return core, adapter


def test_each_request_is_a_byte_identical_prefix_extension_of_the_last(tmp_path):
    async def scenario():
        core, adapter = _session(tmp_path, "run-1")
        await core.prompt("First question.", budget={"max_steps": 4, "timeout_s": 5})
        await core.prompt("Second question.", budget={"max_steps": 4, "timeout_s": 5})
        return adapter.requests
    requests = asyncio.run(scenario())
    assert len(requests) == 4
    assert len({_digest(request["tools"]) for request in requests}) == 1
    for earlier, later in zip(requests, requests[1:]):
        prefix = later["messages"][: len(earlier["messages"])]
        assert _canonical(prefix) == _canonical(earlier["messages"])
    names = [message.get("name") for message in requests[0]["messages"]]
    assert names[: len(STANDING)] == list(STANDING)


def test_sessions_on_different_runs_share_the_standing_prefix(tmp_path):
    async def first_request(folder, run):
        core, adapter = _session(folder, run)
        await core.prompt("Question.", budget={"max_steps": 4, "timeout_s": 5})
        return adapter.requests[0]["messages"]
    one = asyncio.run(first_request(tmp_path / "a", "run-1"))
    two = asyncio.run(first_request(tmp_path / "b", "run-2"))
    assert _canonical(one[: len(STANDING)]) == _canonical(two[: len(STANDING)])
    assert one[len(STANDING)] != two[len(STANDING)]
