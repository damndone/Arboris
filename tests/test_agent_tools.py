from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from workbench.analysis_loop.resolver import AnalysisLoopSourceResolutionError
from workbench.agent import model as agent_model
from workbench.agent.core import AgentCore, AgentRunBudget
from workbench.agent.context import CustomAgentMessage
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


def test_tool_registry_surfaces_analysis_loop_source_errors_to_agent() -> None:
    def handler(arguments, context):
        raise AnalysisLoopSourceResolutionError(
            "the selected OLS source covariance is not eligible for this action",
            code="RECOVERY_ACTION_SOURCE_MISMATCH",
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="propose_analysis_loop",
            version="v1",
            input_schema={"type": "object"},
            side_effect="proposal",
            handler=handler,
        )
    )

    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-analysis-loop",
                "tool_id": "propose_analysis_loop",
                "arguments": {},
            },
            session_id="session-a",
        )
    )

    assert result.ok is False
    assert result.error == "AnalysisLoopSourceResolutionError"
    assert result.error_details == [
        {
            "message": "the selected OLS source covariance is not eligible for this action"
        }
    ]


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


class UnknownToolRecoveryAdapter:
    """A provider typo must produce actionable feedback, not kill the turn."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-typo",
                    "tool_id": "inspcet_operation_contract",
                    "arguments": {},
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return

        tool_messages = [message for message in request.messages if message.get("role") == "tool"]
        assert len(tool_messages) == 1
        payload = json.loads(tool_messages[0]["content"])
        assert payload["error"] == "unknown_tool"
        assert "inspect_operation_contract" in payload["error_details"][0]["message"]
        yield ModelStreamEvent.text_delta(request.request_id, "recovered after tool feedback")
        yield ModelStreamEvent.done(request.request_id)


class ProposalReadyAdapter:
    """A proposal tool result is already a complete, user-reviewable outcome."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        yield ModelStreamEvent.text_delta(request.request_id, "proposal prepared")
        yield ModelStreamEvent.tool_call_delta(
            request.request_id,
            {
                "tool_call_id": "call-propose",
                "tool_id": "propose_operation",
                "arguments": {},
            },
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class BoundedWorkflowAnswerAdapter:
    """Follow the published receipt-to-branch route in a fixed two-tool turn."""

    def __init__(self, candidate_run_ids: list[str]) -> None:
        self.candidate_run_ids = candidate_run_ids
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "receipt-1",
                    "tool_id": "inspect_project_notebook_workflow_results",
                    "arguments": {"run_ids": self.candidate_run_ids[:16]},
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        if len(self.requests) == 2:
            tool_messages = [
                message for message in request.messages if message.get("role") == "tool"
            ]
            assert len(tool_messages) == 1
            assert "branch-east" in tool_messages[0]["content"]
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "coefficients-1",
                    "tool_id": "inspect_project_model_coefficients",
                    "arguments": {
                        "run_ids": ["branch-east", "branch-west"],
                        "terms": ["exposure"],
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        yield ModelStreamEvent.text_delta(
            request.request_id,
            "The persisted branch evidence reports the requested coefficient.",
        )
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


def test_tool_registry_returns_bounded_partial_output_instead_of_budget_error() -> None:
    async def handler(arguments, context):
        return {
            "request_id": "request-1",
            "status": "complete",
            "node": {"node_id": "model-1"},
            "large_section": "x" * 2_000,
        }

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="bounded_inspection",
            version="v1",
            input_schema={"type": "object"},
            side_effect="none",
            handler=handler,
            max_output_budget=240,
        )
    )

    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-bounded",
                "tool_id": "bounded_inspection",
                "arguments": {},
            },
            session_id="session-a",
        )
    )

    assert result.ok is True
    assert result.error is None
    assert len(json.dumps(result.output, ensure_ascii=False, sort_keys=True)) <= 240
    assert result.output["status"] == "partial"
    assert "large_section" in result.output["omitted_sections"]


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


def test_unknown_tool_is_visible_to_the_agent_and_does_not_abort_the_turn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        tools = ToolRegistry()
        tools.register(
            ToolDefinition(
                tool_id="inspect_operation_contract",
                version="v1",
                input_schema={"type": "object"},
                side_effect="none",
                handler=lambda _arguments, _context: {"status": "available"},
            )
        )
        adapter = UnknownToolRecoveryAdapter()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=tools.descriptors(),
            tool_runtime=tools,
        )

        assert await agent.prompt("inspect the workflow contract") == "recovered after tool feedback"
        branch = repository.get_branch("session-a")
        tool_payload = json.loads(branch[2].payload["content"])
        assert tool_payload["error"] == "unknown_tool"
        assert len(adapter.requests) == 2
        assert not any(
            event.payload.get("error") == "tool_runtime_error"
            for event in events.replay("session-a")
        )

    asyncio.run(scenario())


def test_proposal_ready_is_a_successful_terminal_state_even_at_step_budget(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        tools = ToolRegistry()
        tools.register(
            ToolDefinition(
                tool_id="propose_operation",
                version="v1",
                input_schema={"type": "object"},
                side_effect="proposal",
                handler=lambda _arguments, _context: {
                    "requires_confirmation": True,
                    "proposal": {"proposal_id": "proposal-a"},
                },
            )
        )
        adapter = ProposalReadyAdapter()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=tools.descriptors(),
            tool_runtime=tools,
        )

        assert await agent.prompt(
            "prepare a proposal",
            budget=AgentRunBudget(max_steps=1),
        ) == "proposal prepared"
        assert len(adapter.requests) == 1
        assert repository.get_metadata("session-a")["status"] == "idle"
        branch = repository.get_branch("session-a")
        assert [entry.payload["role"] for entry in branch] == ["user", "assistant", "tool"]
        assert not any(
            entry.payload.get("error") == "max_steps_exceeded"
            for entry in branch
        )
        assert events.replay("session-a")[-1].event_type == "agent_end"
        assert events.replay("session-a")[-1].payload["stop_reason"] == "proposal_ready"

    asyncio.run(scenario())


def test_completed_workflow_answer_uses_the_same_two_evidence_calls_for_eight_or_twenty_candidates(
    tmp_path: Path,
) -> None:
    """Candidate count changes bounded input, never the receipt-to-answer path."""

    async def answer_for(candidate_count: int) -> tuple[int, int]:
        candidate_run_ids = [f"candidate-{index}" for index in range(candidate_count)]
        repository = JsonlSessionRepository(tmp_path / f"workbench-{candidate_count}")
        repository.create_session("main-session", chain_id="project-a", role="main")
        repository.append(
            "main-session",
            "custom_message",
            CustomAgentMessage(
                content=(
                    "A completed workflow must first use one receipt lookup with up to "
                    "sixteen visible candidate run ids, then use returned branch runs for "
                    "one bounded coefficient lookup."
                ),
                name="workbench_global_agent_protocol",
            ).to_entry_payload(),
        )
        repository.append(
            "main-session",
            "custom_message",
            CustomAgentMessage(
                content=json.dumps({"visible_run_ids": candidate_run_ids}),
                name="workbench_context",
            ).to_entry_payload(),
        )
        events = AgentEventStream(tmp_path / f"workbench-{candidate_count}")
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                tool_id="inspect_project_notebook_workflow_results",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_ids"],
                    "properties": {
                        "run_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 16,
                            "items": {"type": "string"},
                        }
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                handler=lambda _arguments, _context: {
                    "workflows": [
                        {
                            "status": "completed",
                            "branch_runs": [
                                {"branch_id": "east", "run_id": "branch-east"},
                                {"branch_id": "west", "run_id": "branch-west"},
                            ],
                            "post_estimation_evidence": [],
                        }
                    ]
                },
            )
        )
        registry.register(
            ToolDefinition(
                tool_id="inspect_project_model_coefficients",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_ids", "terms"],
                    "properties": {
                        "run_ids": {"type": "array", "minItems": 1, "maxItems": 4},
                        "terms": {"type": "array", "minItems": 1, "maxItems": 4},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                handler=lambda _arguments, _context: {
                    "models": [
                        {
                            "run_id": "branch-east",
                            "term": "exposure",
                            "estimate": 1.25,
                            "evidence_ref": "model_results:ols_1",
                        }
                    ]
                },
            )
        )
        adapter = BoundedWorkflowAnswerAdapter(candidate_run_ids)
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="main-session",
            tools=registry.descriptors(),
            tool_runtime=registry,
        )

        response = await agent.prompt("What is the exposure coefficient?")

        assert response == "The persisted branch evidence reports the requested coefficient."
        calls = [
            event for event in events.replay("main-session")
            if event.event_type == "tool_execution_start"
        ]
        assert [call.payload["tool_id"] for call in calls] == [
            "inspect_project_notebook_workflow_results",
            "inspect_project_model_coefficients",
        ]
        assert len(adapter.requests) == 3
        return len(calls), len(adapter.requests)

    eight = asyncio.run(answer_for(8))
    twenty = asyncio.run(answer_for(20))

    assert eight == twenty == (2, 3)


def test_openai_compatible_adapter_normalizes_provider_tool_calls(monkeypatch) -> None:
    config = LLMConfig(base_url="https://api.example.test", api_key="secret", model="deepseek-chat")

    async def fake_stream(messages, actual_config, *, tools):
        assert actual_config == config
        assert tools[0] == {
            "type": "function",
            "function": {
                "name": "inspect_node_context",
                "parameters": {"type": "object"},
            },
        }
        yield {
            "type": "tool_call",
            "tool_call": {
                "tool_call_id": "call-1",
                "tool_id": "inspect_node_context",
                "arguments": {"node_ref": "model-ols"},
            },
        }
        yield {
            "type": "done",
            "finish_reason": "tool_calls",
            "model": "deepseek-chat",
        }

    monkeypatch.setattr(
        "workbench.agent.model.async_stream_chat_completion", fake_stream
    )

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


def test_cancellable_openai_adapter_propagates_task_cancellation(monkeypatch) -> None:
    config = LLMConfig(
        base_url="https://api.example.test",
        api_key="secret",
        model="deepseek-chat",
        timeout_s=120,
    )
    started = asyncio.Event()
    cancelled = False

    async def slow_stream(messages, actual_config, *, tools):
        nonlocal cancelled
        assert actual_config == config
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        yield {"type": "done", "finish_reason": "stop", "model": "deepseek-chat"}

    monkeypatch.setattr(
        "workbench.agent.model.async_stream_chat_completion",
        slow_stream,
    )

    async def scenario() -> None:
        adapter = agent_model.CancellableOpenAICompatibleModelAdapter(config)
        request = ModelRequest(
            request_id="request-cancellable",
            messages=[{"role": "user", "content": "plan"}],
            tools=[{"tool_id": "submit", "input_schema": {"type": "object"}}],
        )

        async def collect():
            return [event async for event in adapter.stream(request)]

        task = asyncio.create_task(collect())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert cancelled is True


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
            content=(
                b'data: {"model":"deepseek-chat","choices":[{"delta":{"tool_calls":'
                b'[{"index":0,"id":"call-wire-1","type":"function","function":'
                b'{"name":"inspect_node_context","arguments":"{\\"node_ref\\":\\"model-ols\\"}"}}]},'
                b'"finish_reason":null}]}\n\n'
                b'data: {"model":"deepseek-chat","choices":[{"delta":{},'
                b'"finish_reason":"tool_calls"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    monkeypatch.setattr(
        llm_client,
        "_async_client_factory",
        lambda actual_config: httpx.AsyncClient(
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


def test_openai_compatible_adapter_retries_one_malformed_tool_json_response(
    monkeypatch,
) -> None:
    """A transient provider JSON defect gets one bounded retry, never repair."""

    config = LLMConfig(
        base_url="https://api.example.test",
        api_key="secret",
        model="deepseek-chat",
    )
    seen: list[httpx.Request] = []
    # A tool-call fragment whose assembled arguments are not valid JSON. The
    # defect only becomes visible at the end of the stream, so the retry has to
    # survive a well-formed SSE envelope carrying a malformed payload.
    responses = iter(
        [
            httpx.Response(
                200,
                content=(
                    b'data: {"model":"deepseek-chat","choices":[{"delta":{"tool_calls":'
                    b'[{"index":0,"id":"call-bad","type":"function","function":'
                    b'{"name":"inspect_node_context","arguments":"{not-json"}}]},'
                    b'"finish_reason":null}]}\n\n'
                    b'data: {"model":"deepseek-chat","choices":[{"delta":{},'
                    b'"finish_reason":"tool_calls"}]}\n\n'
                    b"data: [DONE]\n\n"
                ),
            ),
            httpx.Response(
                200,
                content=(
                    b'data: {"model":"deepseek-chat","choices":[{"delta":{"tool_calls":'
                    b'[{"index":0,"id":"call-good","type":"function","function":'
                    b'{"name":"inspect_node_context","arguments":"{\\"node_ref\\":\\"model-ols\\"}"}}]},'
                    b'"finish_reason":null}]}\n\n'
                    b'data: {"model":"deepseek-chat","choices":[{"delta":{},'
                    b'"finish_reason":"tool_calls"}]}\n\n'
                    b"data: [DONE]\n\n"
                ),
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(responses)

    monkeypatch.setattr(
        llm_client,
        "_async_client_factory",
        lambda actual_config: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            timeout=actual_config.timeout_s,
        ),
    )

    async def scenario() -> None:
        adapter = OpenAICompatibleModelAdapter(config)
        events = [
            event
            async for event in adapter.stream(
                ModelRequest(
                    request_id="request-retry",
                    messages=[{"role": "user", "content": "inspect"}],
                    tools=[
                        {
                            "tool_id": "inspect_node_context",
                            "input_schema": {"type": "object"},
                        }
                    ],
                )
            )
        ]
        assert [event.type for event in events] == ["tool_call_delta", "done"]
        assert events[0].tool_call["tool_call_id"] == "call-good"

    asyncio.run(scenario())
    assert len(seen) == 2


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
            content=(
                b'data: {"model":"deepseek-chat","choices":[{"delta":'
                b'{"content":"summary done"},"finish_reason":null}]}\n\n'
                b'data: {"model":"deepseek-chat","choices":[{"delta":{},'
                b'"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    monkeypatch.setattr(
        llm_client,
        "_async_client_factory",
        lambda actual_config: httpx.AsyncClient(
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
