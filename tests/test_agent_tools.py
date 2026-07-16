from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import (
    ModelRequest,
    ModelStreamEvent,
    OpenAICompatibleModelAdapter,
)
from workbench.agent.tools import ToolDefinition, ToolRegistry
from workbench.llm.config import LLMConfig
from workbench.llm import client as llm_client
from workbench.agent.session import JsonlSessionRepository


class ToolRoundTripAdapter:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-1",
                    "tool_id": "inspect_node_context",
                    "arguments": {"node_ref": "model-ols"},
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        yield ModelStreamEvent.text_delta(request.request_id, "evidence found")
        yield ModelStreamEvent.done(request.request_id)


def test_tool_registry_validates_and_executes_allowlisted_tool() -> None:
    async def handler(arguments, context):
        return {"node_ref": arguments["node_ref"], "status": "review"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="inspect_node_context",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["node_ref"],
                "properties": {"node_ref": {"type": "string"}},
                "additionalProperties": False,
            },
            side_effect="none",
            handler=handler,
        )
    )

    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-1",
                "tool_id": "inspect_node_context",
                "arguments": {"node_ref": "model-ols"},
            },
            session_id="session-a",
        )
    )

    assert result.ok is True
    assert result.output == {"node_ref": "model-ols", "status": "review"}
    assert registry.descriptors()[0]["tool_id"] == "inspect_node_context"


def test_agent_core_round_trips_tool_call_and_persists_tool_result(tmp_path: Path) -> None:
    async def handler(arguments, context):
        return {"node_ref": arguments["node_ref"], "diagnostic": "heteroskedasticity"}

    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        tools = ToolRegistry()
        tools.register(
            ToolDefinition(
                tool_id="inspect_node_context",
                version="v1",
                input_schema={"type": "object", "required": ["node_ref"]},
                side_effect="none",
                handler=handler,
            )
        )
        adapter = ToolRoundTripAdapter()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=tools.descriptors(),
            tool_runtime=tools,
        )

        assert await agent.prompt("inspect the model") == "evidence found"
        branch = repository.get_branch("session-a")
        assert [entry.payload["role"] for entry in branch] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert branch[2].payload["tool_call_id"] == "call-1"
        assert adapter.requests[0].tools[0]["tool_id"] == "inspect_node_context"
        assert [event.event_type for event in events.replay("session-a")].count(
            "tool_execution_start"
        ) == 1
        assert [event.event_type for event in events.replay("session-a")].count(
            "tool_execution_end"
        ) == 1

    asyncio.run(scenario())


def test_openai_compatible_adapter_normalizes_provider_tool_calls(monkeypatch) -> None:
    config = LLMConfig(base_url="https://api.example.test", api_key="secret", model="deepseek-chat")

    def fake_chat_completion(messages, actual_config, *, tools):
        assert actual_config == config
        assert tools[0] == {
            "type": "function",
            "function": {
                "name": "inspect_node_context",
                "parameters": {"type": "object"},
            },
        }
        return {
            "text": "",
            "model": "deepseek-chat",
            "tool_calls": [
                {
                    "tool_call_id": "call-1",
                    "tool_id": "inspect_node_context",
                    "arguments": {"node_ref": "model-ols"},
                }
            ],
        }

    monkeypatch.setattr("workbench.agent.model.chat_completion", fake_chat_completion)

    async def scenario() -> None:
        adapter = OpenAICompatibleModelAdapter(config)
        request = ModelRequest(
            request_id="request-tools",
            messages=[{"role": "user", "content": "inspect"}],
            tools=[
                {
                    "tool_id": "inspect_node_context",
                    "input_schema": {"type": "object"},
                }
            ],
        )
        events = [event async for event in adapter.stream(request)]
        assert [event.type for event in events] == ["tool_call_delta", "done"]
        assert events[0].tool_call["tool_call_id"] == "call-1"
        assert events[1].finish_reason == "tool_calls"

    asyncio.run(scenario())


def test_openai_wire_format_converts_workbench_tool_descriptor(monkeypatch) -> None:
    config = LLMConfig(
        base_url="https://api.example.test",
        api_key="secret",
        model="deepseek-chat",
    )
    seen: list[dict] = []
    input_schema = {
        "type": "object",
        "required": ["node_ref"],
        "properties": {"node_ref": {"type": "string"}},
        "additionalProperties": False,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-wire-1",
                                    "type": "function",
                                    "function": {
                                        "name": "inspect_node_context",
                                        "arguments": '{"node_ref":"model-ols"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda actual_config: httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=actual_config.timeout_s,
        ),
    )

    async def scenario() -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                tool_id="inspect_node_context",
                version="v1",
                input_schema=input_schema,
                side_effect="none",
                handler=lambda arguments, context: arguments,
            )
        )
        adapter = OpenAICompatibleModelAdapter(config)
        request = ModelRequest(
            request_id="request-wire",
            messages=[{"role": "user", "content": "inspect"}],
            tools=registry.descriptors(),
        )

        events = [event async for event in adapter.stream(request)]

        assert seen[0]["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "inspect_node_context",
                    "parameters": input_schema,
                },
            }
        ]
        assert events[0].tool_call == {
            "tool_call_id": "call-wire-1",
            "tool_id": "inspect_node_context",
            "arguments": {"node_ref": "model-ols"},
        }

    asyncio.run(scenario())


def test_existing_openai_compatible_client_wires_and_normalizes_tool_calls(
    monkeypatch,
) -> None:
    config = LLMConfig(
        base_url="https://api.example.test",
        api_key="secret",
        model="deepseek-chat",
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "inspect_node_context",
                                        "arguments": '{"node_ref":"model-ols"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda actual_config: httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=actual_config.timeout_s,
        ),
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "inspect_node_context",
                "parameters": {"type": "object"},
            },
        }
    ]

    result = llm_client.chat_completion(
        [{"role": "user", "content": "inspect"}],
        config,
        tools=tools,
    )

    payload = json.loads(seen[0].content)
    assert payload["tools"] == tools
    assert result["text"] == ""
    assert result["tool_calls"] == [
        {
            "tool_call_id": "call-1",
            "tool_id": "inspect_node_context",
            "arguments": {"node_ref": "model-ols"},
        }
    ]


def test_openai_wire_format_converts_internal_tool_messages(monkeypatch) -> None:
    """Live DeepSeek regression (v1.7 browser smoke): the second provider call
    after a tool execution must serialize the internal assistant tool_calls and
    the tool-result message in OpenAI wire format, or the upstream rejects the
    request and the turn dies with LLMUpstreamError."""
    config = LLMConfig(
        base_url="https://api.example.test",
        api_key="secret",
        model="deepseek-chat",
    )
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [
                    {"message": {"role": "assistant", "content": "summary done"}}
                ],
            },
        )

    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda actual_config: httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=actual_config.timeout_s,
        ),
    )

    async def scenario() -> None:
        adapter = OpenAICompatibleModelAdapter(config)
        request = ModelRequest(
            request_id="request-wire-2",
            messages=[
                {"role": "system", "content": "ctx", "name": "workbench_context"},
                {"role": "user", "content": "inspect the node"},
                {
                    "role": "assistant",
                    "content": "checking",
                    "request_id": "req-1",
                    "tool_calls": [
                        {
                            "tool_call_id": "call-1",
                            "tool_id": "inspect_node_context",
                            "arguments": {"owner_run_id": "run-a"},
                        }
                    ],
                },
                {
                    "role": "system",
                    "content": "proposal audit",
                    "name": "operation_proposal",
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "name": "inspect_node_context",
                    "content": '{"ok": true}',
                },
            ],
        )
        events = [event async for event in adapter.stream(request)]
        assert events[-1].type == "done"

        posted = seen[0]["messages"]
        assistant = posted[2]
        assert "request_id" not in assistant
        assert assistant["tool_calls"] == [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "inspect_node_context",
                    "arguments": '{"owner_run_id": "run-a"}',
                },
            }
        ]
        tool = posted[3]
        assert tool == {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"ok": true}',
        }
        assert posted[4] == {
            "role": "system",
            "content": "proposal audit",
            "name": "operation_proposal",
        }

    asyncio.run(scenario())
