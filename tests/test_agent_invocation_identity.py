"""A tool invocation's audit identity belongs to the running Core."""

import asyncio

from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolResult


def _run(tmp_path, batches):
    class Provider:
        def __init__(self):
            self.requests = []

        async def stream(self, request):
            index = len(self.requests)
            self.requests.append(request)
            if index < len(batches):
                for call_id, arguments in batches[index]:
                    yield ModelStreamEvent.tool_call_delta(request.request_id, {
                        "tool_call_id": call_id, "tool_id": "inspect", "arguments": arguments,
                    })
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "Finished.")
                yield ModelStreamEvent.done(request.request_id)

    class Runtime:
        def __init__(self):
            self.calls = []

        async def execute(self, tool_call, *, session_id, metadata=None):
            self.calls.append((dict(tool_call), session_id, dict(metadata or {})))
            return ToolResult(tool_call_id=tool_call["tool_call_id"], tool_id="inspect",
                              ok=True, output={"result": "ready"})

    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="c", role="chain")
    provider, runtime = Provider(), Runtime()
    core = AgentCore(repository, AgentEventStream(tmp_path), provider, session_id="s", tool_runtime=runtime)
    supplied = {"allowed_operations": ["model.rerun"], "command_id": "spoof", "provider_step": 999,
                "tool_call_id": "spoof", "invocation_id": "spoof"}
    assert asyncio.run(core.prompt("Inspect.", budget={"max_steps": 4}, tool_context=supplied)) == "Finished."
    command = next(entry.payload["command_id"] for entry in repository.get_branch("s")
                   if entry.payload.get("role") == "user")
    assert supplied["invocation_id"] == "spoof"  # Do not mutate a caller's dictionary.
    # Internal invocation metadata must not be appended as model instructions.
    assert all("invocation_" not in str(request.messages) for request in provider.requests)
    return runtime.calls, command


def test_core_overrides_caller_identity_but_keeps_declared_scope(tmp_path):
    calls, command = _run(tmp_path, [[("first", {}), ("second", {})]])
    metadata = [item[2] for item in calls]
    assert all(item["command_id"] == command != "spoof" for item in metadata)
    assert all(item["provider_step"] == 1 for item in metadata)
    assert [item["tool_call_id"] for item in metadata] == ["first", "second"]
    assert all(item["allowed_operations"] == ["model.rerun"] for item in metadata)
    assert all(item["invocation_id"].startswith("invocation_") for item in metadata)
    assert len({item["invocation_id"] for item in metadata}) == 2


def test_reused_provider_call_id_on_later_step_is_a_distinct_invocation(tmp_path):
    calls, command = _run(tmp_path, [[("same", {"part": "a"})], [("same", {"part": "b"})]])
    metadata = [item[2] for item in calls]
    assert [item["provider_step"] for item in metadata] == [1, 2]
    assert all(item["command_id"] == command for item in metadata)
    assert len({item["invocation_id"] for item in metadata}) == 2
