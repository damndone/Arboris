from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from workbench.agent.core import (
    AgentCore,
    AgentCoreBusyError,
    AgentCoreBudgetError,
    AgentCoreContinuationError,
    AgentRunBudget,
)
from workbench.agent.context import ContextBuilder, CustomAgentMessage
from workbench.agent.events import AgentEventStream
from workbench.agent.model import (
    ModelRequest,
    ModelStreamEvent,
    OpenAICompatibleModelAdapter,
)
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import EntryRef, JsonlSessionRepository
from workbench.agent.tools import ToolDefinition, ToolRegistry
from workbench.llm.config import LLMConfig


def test_session_repository_keeps_append_only_cross_session_branch(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("session-a", chain_id="chain-a", role="chain")

    user_entry = repository.append(
        "session-a",
        "message",
        {"role": "user", "content": "inspect this model"},
    )
    assistant_entry = repository.append(
        "session-a",
        "message",
        {"role": "assistant", "content": "I found a diagnostic issue."},
    )

    repository.create_session(
        "session-b",
        chain_id="chain-b",
        role="chain",
        inherited_parent_ref=EntryRef("session-a", assistant_entry.entry_id),
    )
    child_entry = repository.append(
        "session-b",
        "message",
        {"role": "user", "content": "try a robust covariance"},
    )

    branch = repository.get_branch("session-b")
    assert [entry.entry_id for entry in branch] == [
        user_entry.entry_id,
        assistant_entry.entry_id,
        child_entry.entry_id,
    ]
    assert [entry.payload["role"] for entry in branch] == ["user", "assistant", "user"]
    assert (tmp_path / "workbench" / "agent-sessions" / "session-b.jsonl").read_text().count("\n") == 1


def test_session_repository_persists_status_metadata_without_touching_entries(
    tmp_path: Path,
) -> None:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("session-a", chain_id="chain-a", role="chain")
    repository.append("session-a", "message", {"role": "user", "content": "inspect"})

    updated = repository.update_status("session-a", "failed")

    assert updated["status"] == "failed"
    assert repository.get_metadata("session-a")["status"] == "failed"
    assert len(repository.get_branch("session-a")) == 1


def test_agent_event_stream_replays_and_deduplicates_events(tmp_path: Path) -> None:
    stream = AgentEventStream(tmp_path / "workbench")

    first = stream.emit("session-a", "agent_start", {"phase": "turn"}, event_id="evt-1")
    duplicate = stream.emit("session-a", "agent_start", {"phase": "turn"}, event_id="evt-1")
    second = stream.emit("session-a", "message_update", {"delta": "hello"}, command_id="cmd-1")

    assert duplicate == first
    assert [event.seq for event in stream.replay("session-a")] == [1, 2]
    assert stream.replay("session-a", after_seq=1)[0] == second


class RecordingStreamAdapter:
    def __init__(self, responses: list[str], *, fail_once: bool = False) -> None:
        self.responses = responses
        self.fail_once = fail_once
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if self.fail_once:
            self.fail_once = False
            yield ModelStreamEvent.from_error(request.request_id, "provider_failed")
            return
        text = self.responses.pop(0)
        midpoint = max(1, len(text) // 2)
        yield ModelStreamEvent.text_delta(request.request_id, text[:midpoint])
        await asyncio.sleep(0)
        yield ModelStreamEvent.text_delta(request.request_id, text[midpoint:])
        yield ModelStreamEvent.done(request.request_id)


class MissingRuntimeToolAdapter:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent.tool_call_delta(
            request.request_id,
            {
                "tool_call_id": "call-without-runtime",
                "tool_id": "inspect_node_context",
                "arguments": {},
            },
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class RepeatingToolCallAdapter:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent.tool_call_delta(
            request.request_id,
            {
                "tool_call_id": f"repeat-{len(self.requests)}",
                "tool_id": "inspect_node_context",
                "arguments": {"node_ref": "model:ols_1"},
            },
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class SequencedToolCallAdapter:
    def __init__(self, node_refs: list[str]) -> None:
        self.node_refs = node_refs
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        node_ref = self.node_refs[len(self.requests) - 1]
        yield ModelStreamEvent.tool_call_delta(
            request.request_id,
            {
                "tool_call_id": f"sequence-{len(self.requests)}",
                "tool_id": "inspect_node_context",
                "arguments": {"node_ref": node_ref},
            },
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class BlockingStreamAdapter:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.started = asyncio.Event()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        self.started.set()
        await asyncio.Event().wait()
        yield ModelStreamEvent.done(request.request_id)


class ExplodingToolRuntime:
    async def execute(self, tool_call, *, session_id: str, metadata=None):
        del tool_call, session_id, metadata
        raise RuntimeError("tool runtime exploded")


class BlockingToolRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(self, tool_call, *, session_id: str, metadata=None):
        del tool_call, session_id, metadata
        self.started.set()
        await asyncio.Event().wait()


class BudgetCapturingAgent:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.budget = None

    def attach_tools(self, tools, tool_runtime) -> None:
        del tools, tool_runtime

    async def prompt(self, text: str, *, tool_context=None, budget=None) -> str:
        del text, tool_context
        self.budget = budget
        return "captured"


def test_agent_core_persists_messages_and_emits_stream_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["robust covariance is safer"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")
        repository.update_status("session-a", "failed")

        response = await agent.prompt("check the model")

        assert response == "robust covariance is safer"
        assert repository.get_metadata("session-a")["status"] == "idle"
        branch = repository.get_branch("session-a")
        assert [entry.payload["role"] for entry in branch] == ["user", "assistant"]
        assert branch[0].payload["command_id"] == branch[1].payload["command_id"]
        assert branch[0].payload["command_id"]
        assert [event.event_type for event in events.replay("session-a")] == [
            "agent_start",
            "turn_start",
            "message_start",
            "message_update",
            "message_update",
            "message_end",
            "turn_end",
            "save_point",
            "agent_end",
        ]
        assert adapter.requests[0].messages[-1]["content"] == "check the model"
        assert "command_id" not in adapter.requests[0].messages[-1]

    asyncio.run(scenario())


def test_agent_core_abort_persists_aborted_message_and_continue_reuses_context(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["first response", "continued response"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")

        running = asyncio.create_task(agent.prompt("start long task"))
        while not adapter.requests:
            await asyncio.sleep(0)
        await agent.abort()
        assert await asyncio.wait_for(running, timeout=0.2) == ""
        assert repository.get_metadata("session-a")["status"] == "cancelled"
        assert "aborted" in [event.event_type for event in events.replay("session-a")]

        response = await agent.continue_()
        assert response == "continued response"
        assert adapter.requests[-1].messages[-1]["role"] == "user"
        assert adapter.requests[-1].messages[-1]["content"] == "start long task"
        assert [entry.payload["role"] for entry in repository.get_branch("session-a")] == [
            "user",
            "assistant",
            "assistant",
        ]

    asyncio.run(scenario())


def test_agent_core_rejects_continue_after_completed_assistant_message(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["completed response"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")

        assert await agent.prompt("finish this turn") == "completed response"

        with pytest.raises(AgentCoreContinuationError, match="last message"):
            await agent.continue_()

        assert len(adapter.requests) == 1
        assert agent.phase == "idle"

    asyncio.run(scenario())


def test_agent_core_persists_tool_runtime_unavailable_as_terminal_error(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = MissingRuntimeToolAdapter()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=[{"tool_id": "inspect_node_context"}],
        )

        assert await agent.prompt("inspect this model") == ""

        branch = repository.get_branch("session-a")
        assert repository.get_metadata("session-a")["status"] == "failed"
        assert [entry.payload["role"] for entry in branch] == ["user", "assistant"]
        assistant = branch[-1].payload
        assert assistant["stop_reason"] == "error"
        assert assistant["error"] == "tool_runtime_unavailable"
        assert len(adapter.requests) == 1
        assert [event.event_type for event in events.replay("session-a")][-3:] == [
            "turn_end",
            "save_point",
            "agent_end",
        ]

    asyncio.run(scenario())


def test_agent_core_persists_tool_runtime_exception_as_terminal_error(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = MissingRuntimeToolAdapter()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=[{"tool_id": "inspect_node_context"}],
            tool_runtime=ExplodingToolRuntime(),
        )

        assert await agent.prompt("inspect this model") == ""

        branch = repository.get_branch("session-a")
        assert [entry.payload["role"] for entry in branch] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert branch[-2].payload["content"]
        assert json.loads(branch[-2].payload["content"])["error"] == "tool_runtime_error"
        assert branch[-1].payload["error"] == "tool_runtime_error"
        assert repository.get_metadata("session-a")["status"] == "failed"
        event_types = [event.event_type for event in events.replay("session-a")]
        assert "tool_execution_end" in event_types
        assert event_types[-3:] == ["turn_end", "save_point", "agent_end"]

    asyncio.run(scenario())


def test_agent_core_abort_closes_active_tool_execution_as_aborted(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = MissingRuntimeToolAdapter()
        runtime = BlockingToolRuntime()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=[{"tool_id": "inspect_node_context"}],
            tool_runtime=runtime,
        )

        running = asyncio.create_task(agent.prompt("inspect this model"))
        await runtime.started.wait()
        await agent.abort()

        assert await running == ""
        branch = repository.get_branch("session-a")
        assert json.loads(branch[-2].payload["content"])["error"] == "agent_aborted"
        assert branch[-1].payload["error"] == "agent_aborted"
        assert repository.get_metadata("session-a")["status"] == "cancelled"
        tool_end = [
            event for event in events.replay("session-a")
            if event.event_type == "tool_execution_end"
        ][-1]
        assert tool_end.payload["error"] == "agent_aborted"
        assert tool_end.payload["ok"] is False

    asyncio.run(scenario())


def test_agent_core_timeout_closes_active_tool_execution_as_timed_out(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = MissingRuntimeToolAdapter()
        runtime = BlockingToolRuntime()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=[{"tool_id": "inspect_node_context"}],
            tool_runtime=runtime,
        )

        assert await agent.prompt("inspect this model", budget={"timeout_s": 0.01}) == ""

        branch = repository.get_branch("session-a")
        assert json.loads(branch[-2].payload["content"])["error"] == "agent_timeout"
        assert branch[-1].payload["error"] == "agent_timeout"
        assert repository.get_metadata("session-a")["status"] == "failed"
        tool_end = [
            event for event in events.replay("session-a")
            if event.event_type == "tool_execution_end"
        ][-1]
        assert tool_end.payload["error"] == "agent_timeout"
        assert tool_end.payload["ok"] is False

    asyncio.run(scenario())


def test_agent_core_orders_steer_before_follow_up_and_publishes_queue_updates(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["first", "steered", "followed"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")

        running = asyncio.create_task(agent.prompt("start"))
        while not adapter.requests:
            await asyncio.sleep(0)
        await agent.steer("change direction")
        await agent.follow_up("now summarize")

        assert await running == "followed"
        assert [request.messages[-1]["content"] for request in adapter.requests] == [
            "start",
            "change direction",
            "now summarize",
        ]
        assert [event.event_type for event in events.replay("session-a")].count("queue_update") == 2

    asyncio.run(scenario())


def test_context_builder_projects_custom_message_and_compaction_without_mutating_history(
    tmp_path: Path,
) -> None:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("session-a", chain_id="chain-a", role="chain")
    repository.append("session-a", "message", {"role": "user", "content": "inspect"})
    custom = CustomAgentMessage(content="diagnostic evidence", name="diagnostics")
    repository.append("session-a", "custom_message", custom.to_entry_payload())
    repository.append(
        "session-a",
        "custom_message",
        {"content": "UI-only note", "audience": "ui", "name": "ui"},
    )
    repository.append(
        "session-a",
        "compaction",
        {"summary": "Earlier evidence was compacted.", "tokens_before": 500},
    )

    snapshot = ContextBuilder(repository).build("session-a")

    assert [message["content"] for message in snapshot.messages] == [
        "inspect",
        "diagnostic evidence",
        "Earlier evidence was compacted.",
    ]
    assert len(snapshot.fingerprint) == 64
    assert len(repository.get_branch("session-a")) == 4


def test_agent_core_rejects_concurrent_prompt(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["response"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")
        running = asyncio.create_task(agent.prompt("first"))
        while not adapter.requests:
            await asyncio.sleep(0)
        with pytest.raises(AgentCoreBusyError):
            await agent.prompt("second")
        await agent.abort()
        await running

    asyncio.run(scenario())


def test_agent_core_enforces_max_steps_before_a_queued_follow_up_call(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["first response", "should not run"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")

        running = asyncio.create_task(
            agent.prompt("start", budget={"max_steps": 1})
        )
        while not adapter.requests:
            await asyncio.sleep(0)
        await agent.steer("queued follow-up")

        assert await running == ""
        assert len(adapter.requests) == 1
        assert repository.get_metadata("session-a")["status"] == "blocked"
        branch = repository.get_branch("session-a")
        assert branch[-1].payload == {
            "role": "assistant",
            "content": "",
            "stop_reason": "error",
            "error": "max_steps_exceeded",
        }
        assert [event.event_type for event in events.replay("session-a")][-3:] == [
            "turn_end",
            "save_point",
            "agent_end",
        ]

    asyncio.run(scenario())


def test_agent_core_blocks_consecutive_identical_tool_calls_before_max_steps(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        tools = ToolRegistry()

        async def handler(arguments, context):
            del context
            return {"node_ref": arguments["node_ref"], "status": "ready"}

        tools.register(
            ToolDefinition(
                tool_id="inspect_node_context",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["node_ref"],
                    "properties": {"node_ref": {"type": "string"}},
                },
                side_effect="none",
                handler=handler,
            )
        )
        adapter = RepeatingToolCallAdapter()
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=tools.descriptors(),
            tool_runtime=tools,
        )

        assert await agent.prompt("inspect the same node", budget={"max_steps": 6}) == ""

        assert len(adapter.requests) == 2
        assert repository.get_metadata("session-a")["status"] == "blocked"
        branch = repository.get_branch("session-a")
        assert branch[-1].payload == {
            "role": "assistant",
            "content": "",
            "stop_reason": "error",
            "error": "repeated_tool_call_limit",
        }
        # Filter by reason: replaying an already-answered inspection also emits
        # a loop_guard, and that is a different, non-terminal signal.
        guard_events = [
            event
            for event in events.replay("session-a")
            if event.event_type == "loop_guard"
            and event.payload.get("reason") == "identical_tool_call"
        ]
        assert len(guard_events) == 1
        assert guard_events[0].payload == {
            "tool_id": "inspect_node_context",
            "repetition_count": 2,
            "reason": "identical_tool_call",
        }

    asyncio.run(scenario())


def test_agent_core_resets_identical_tool_call_counter_when_arguments_change(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        tools = ToolRegistry()

        async def handler(arguments, context):
            del context
            return {"node_ref": arguments["node_ref"], "status": "ready"}

        tools.register(
            ToolDefinition(
                tool_id="inspect_node_context",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["node_ref"],
                    "properties": {"node_ref": {"type": "string"}},
                },
                side_effect="none",
                handler=handler,
            )
        )
        adapter = SequencedToolCallAdapter(
            ["model:ols_1", "model:ols_2", "model:ols_2"]
        )
        agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="session-a",
            tools=tools.descriptors(),
            tool_runtime=tools,
        )

        assert await agent.prompt("inspect the requested nodes", budget={"max_steps": 6}) == ""

        assert len(adapter.requests) == 3
        # Filter by reason: replaying an already-answered inspection also emits
        # a loop_guard, and that is a different, non-terminal signal.
        guard_events = [
            event
            for event in events.replay("session-a")
            if event.event_type == "loop_guard"
            and event.payload.get("reason") == "identical_tool_call"
        ]
        assert guard_events[0].payload["repetition_count"] == 2
        assert guard_events[0].payload["tool_id"] == "inspect_node_context"

    asyncio.run(scenario())


def test_agent_core_timeout_persists_terminal_error_and_returns_idle(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = BlockingStreamAdapter()
        agent = AgentCore(repository, events, adapter, session_id="session-a")

        running = asyncio.create_task(
            agent.prompt("wait", budget={"timeout_s": 0.01})
        )
        await adapter.started.wait()
        assert repository.get_metadata("session-a")["status"] == "running"

        assert await running == ""
        assert agent.phase == "idle"
        assert repository.get_metadata("session-a")["status"] == "failed"
        branch = repository.get_branch("session-a")
        assert branch[-1].payload == {
            "role": "assistant",
            "content": "",
            "stop_reason": "error",
            "error": "agent_timeout",
        }
        event_types = [event.event_type for event in events.replay("session-a")]
        assert "aborted" in event_types
        assert event_types[-3:] == ["turn_end", "save_point", "agent_end"]

    asyncio.run(scenario())


def test_agent_core_rejects_non_positive_budget_values(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["unused"])
        agent = AgentCore(repository, events, adapter, session_id="session-a")

        with pytest.raises(AgentCoreBudgetError, match="max_steps"):
            await agent.prompt("invalid", budget={"max_steps": 0})
        assert agent.phase == "idle"
        assert adapter.requests == []

    asyncio.run(scenario())


def test_workbench_orchestrator_dispatches_idempotent_scoped_chain_commands(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("main-session", chain_id="project", role="main")
        repository.create_session("chain-session", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        adapter = RecordingStreamAdapter(["diagnostics inspected"])
        chain_agent = AgentCore(repository, events, adapter, session_id="chain-session")
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
        )
        orchestrator.register_chain("chain-a", "chain-session", chain_agent)

        command = orchestrator.dispatch_to_chain(
            "chain-a",
            objective="检查当前模型的诊断问题",
            allowed_operations=["inspect"],
            budget={"max_steps": 4, "timeout_s": 30},
        )
        duplicate = orchestrator.dispatch_to_chain(
            "chain-a",
            objective="这条内容不应覆盖原 command",
            allowed_operations=["model.rerun"],
            budget={"max_steps": 99},
            command_id=command.command_id,
        )

        assert duplicate == command
        assert command.dispatch_seq == 1
        assert command.child_agent_id == "chain-session"
        chain_entries = repository.get_branch("chain-session")
        assert chain_entries[-1].entry_type == "custom_message"
        assert chain_entries[-1].payload["message_type"] == "main_to_chain_command"
        assert chain_entries[-1].payload["command"]["allowed_operations"] == ["inspect"]

        assert await orchestrator.execute(command.command_id) == "diagnostics inspected"
        command_events = events.replay("main-session")
        assert [event.event_type for event in command_events] == [
            "command_dispatched",
            "command_completed",
        ]
        assert command_events[0].payload["chain_id"] == "chain-a"

    asyncio.run(scenario())


def test_workbench_orchestrator_passes_command_budget_to_chain_agent(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("main-session", chain_id="project", role="main")
        repository.create_session("chain-session", chain_id="chain-a", role="chain")
        events = AgentEventStream(tmp_path / "workbench")
        agent = BudgetCapturingAgent("chain-session")
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
        )
        orchestrator.register_chain("chain-a", "chain-session", agent)

        command = orchestrator.dispatch_to_chain(
            "chain-a",
            objective="run within command budget",
            allowed_operations=["inspect"],
            budget={"max_steps": 2, "timeout_s": 5},
        )

        assert await orchestrator.execute(command.command_id) == "captured"
        assert agent.budget == {"max_steps": 2, "timeout_s": 5}

    asyncio.run(scenario())


def test_openai_compatible_adapter_normalizes_public_stream_client(monkeypatch) -> None:
    config = LLMConfig(base_url="https://api.example.test", api_key="secret", model="deepseek-chat")
    calls: list[tuple[list[dict[str, str]], LLMConfig]] = []

    async def fake_stream(messages: list[dict[str, str]], actual_config: LLMConfig, **_kwargs):
        calls.append((messages, actual_config))
        yield {"type": "text_delta", "delta": "one streamed answer"}
        yield {"type": "done", "finish_reason": "stop", "model": "deepseek-chat"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario() -> None:
        adapter = OpenAICompatibleModelAdapter(config)
        request = ModelRequest(
            request_id="request-1",
            messages=[{"role": "user", "content": "inspect"}],
        )
        streamed = [event async for event in adapter.stream(request)]
        assert [event.type for event in streamed] == ["text_delta", "done"]
        assert streamed[0].delta == "one streamed answer"
        assert streamed[1].provider_request_id == "request-1"
        assert calls == [(request.messages, config)]

    asyncio.run(scenario())


def test_openai_compatible_adapter_forwards_public_stream_deltas(monkeypatch) -> None:
    config = LLMConfig(base_url="https://api.example.test", api_key="secret", model="deepseek-chat")

    async def fake_stream(*_args, **_kwargs):
        yield {"type": "text_delta", "delta": "first "}
        yield {"type": "text_delta", "delta": "second"}
        yield {"type": "done", "finish_reason": "stop", "model": "deepseek-chat"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario() -> None:
        adapter = OpenAICompatibleModelAdapter(config)
        request = ModelRequest(
            request_id="request-stream-1",
            messages=[{"role": "user", "content": "inspect"}],
        )
        streamed = [event async for event in adapter.stream(request)]
        assert [event.type for event in streamed] == ["text_delta", "text_delta", "done"]
        assert [event.delta for event in streamed[:2]] == ["first ", "second"]
        assert streamed[-1].provider_request_id == "request-stream-1"

    asyncio.run(scenario())


def test_step_budget_becomes_visible_before_it_is_exhausted(tmp_path: Path) -> None:
    """A turn must be able to see the wall it is about to hit.

    ``max_steps_exceeded`` delivered nothing at all: the agent kept inspecting
    a large graph with no signal that the budget was running out. Reporting the
    remaining steps lets a wandering turn still submit what it has.
    """

    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("session-a", chain_id="chain-a", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    agent = AgentCore(
        repository, events, RecordingStreamAdapter(["x"]), session_id="session-a"
    )
    agent._budget = AgentRunBudget(max_steps=10)

    # Early on the payload is left alone — budget noise on every result would
    # crowd out the evidence the agent is actually reading.
    agent._steps_used = 1
    assert agent._annotate_step_budget({"ok": True}) == {"ok": True}

    agent._steps_used = 6
    midway = agent._annotate_step_budget({"ok": True})
    assert midway["steps_remaining"] == 4
    assert "propose" in midway["guidance"]

    agent._steps_used = 9
    final = agent._annotate_step_budget({"ok": True})
    assert final["steps_remaining"] == 1
    assert "nothing delivered" in final["guidance"]

    # Never reports a negative budget, and keeps the repeat guard's guidance
    # instead of overwriting it.
    agent._steps_used = 12
    overrun = agent._annotate_step_budget({"ok": True, "guidance": "already answered"})
    assert overrun["steps_remaining"] == 0
    assert overrun["guidance"].startswith("already answered")


def test_step_budget_annotation_is_silent_without_a_budget(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("session-a", chain_id="chain-a", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    agent = AgentCore(
        repository, events, RecordingStreamAdapter(["x"]), session_id="session-a"
    )
    agent._budget = AgentRunBudget(max_steps=None)
    agent._steps_used = 99

    assert agent._annotate_step_budget({"ok": True}) == {"ok": True}
