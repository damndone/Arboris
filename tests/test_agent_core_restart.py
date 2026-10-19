"""Restart the actual Core; unknown tool effects must never be resubmitted."""
import asyncio
import multiprocessing
import os
from pathlib import Path

import pytest

from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolResult
from workbench.agent.turn_journal import TurnJournal, TurnRecoveryRequired
from workbench.agent.turn_store import TurnStore


class ProcessLost(BaseException):
    pass


CALL = {"tool_call_id": "call-a", "tool_id": "save", "arguments": {"value": "original"}}


class Adapter:
    def __init__(self, action="answer"):
        self.action, self.requests = action, []

    async def stream(self, request):
        self.requests.append(request)
        if self.action == "lost":
            raise ProcessLost()
        if self.action == "tool":
            self.action = "answer"
            yield ModelStreamEvent.tool_call_delta(request.request_id, CALL)
            yield ModelStreamEvent.done(request.request_id, "tool_calls")
        else:
            yield ModelStreamEvent.text_delta(request.request_id, "Saved.")
            yield ModelStreamEvent.done(request.request_id)


class Runtime:
    def __init__(self, root, *, lose_receipt=False):
        self.root, self.lose_receipt = root, lose_receipt

    async def execute(self, call, *, session_id, metadata):
        path = self.root / "effects.txt"
        with path.open("a") as out:
            out.write(metadata["invocation_id"] + "\n")
        if self.lose_receipt:
            raise ProcessLost()
        return ToolResult(tool_call_id=call["tool_call_id"], tool_id=call["tool_id"], ok=True,
                          output={"saved": "original", "counter_at_execution": 1})


def setup(tmp_path, adapter, *, runtime=None, create=True):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    if create:
        repository.create_session("session-a", chain_id="chain-a", role="chain")
    store = TurnStore(tmp_path)
    journal = TurnJournal(store, repository, session_id="session-a", execution_mode="ask")
    core = AgentCore(repository, AgentEventStream(tmp_path / "workbench"), adapter,
                     session_id="session-a", tool_runtime=runtime, turn_journal=journal)
    return core, store, repository


def test_restart_repairs_original_receipt_without_reexecuting_tool(tmp_path, monkeypatch):
    async def scenario():
        runtime = Runtime(tmp_path)
        core, store, repo = setup(tmp_path, Adapter("tool"), runtime=runtime)
        original = repo.append_once

        def lose_before_message(*args, **kwargs):
            if kwargs.get("stage") == "tool_result":
                raise ProcessLost()
            return original(*args, **kwargs)

        monkeypatch.setattr(repo, "append_once", lose_before_message)
        with pytest.raises(ProcessLost):
            await core.prompt("Save original.", budget={"max_steps": 3, "timeout_s": 30})
        [interrupted] = store.list_active()
        assert interrupted.steps_used == 1 and interrupted.status == "interrupted"
        assert (tmp_path / "effects.txt").read_text().count("\n") == 1
        adapter = Adapter()
        resumed, fresh, repository = setup(tmp_path, adapter, runtime=runtime, create=False)
        assert await resumed.resume(interrupted.turn_id) == "Saved."
        final = fresh.get(interrupted.turn_id)
        assert final.status == "completed" and final.steps_used == 2
        assert (tmp_path / "effects.txt").read_text().count("\n") == 1
        messages = adapter.requests[0].messages
        assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
        assert '"counter_at_execution": 1' in messages[-1]["content"]
        assert len([e for e in repository.get_branch("session-a")
                    if e.payload.get("role") == "tool"]) == 1
        assert {e.payload["command_id"] for e in repository.get_branch("session-a")
                if e.entry_type == "message"} == {interrupted.command_id}
    asyncio.run(scenario())


def test_effect_without_receipt_stays_interrupted_and_is_never_reexecuted(tmp_path):
    async def scenario():
        runtime = Runtime(tmp_path, lose_receipt=True)
        core, store, _ = setup(tmp_path, Adapter("tool"), runtime=runtime)
        with pytest.raises(ProcessLost):
            await core.prompt("Save original.", budget={"max_steps": 3, "timeout_s": 30})
        [record] = store.list_active()
        adapter = Adapter()
        resumed, fresh, _ = setup(tmp_path, adapter, runtime=runtime, create=False)
        with pytest.raises(TurnRecoveryRequired, match="receipt"):
            await resumed.resume(record.turn_id)
        assert not adapter.requests
        assert fresh.get(record.turn_id).status == "interrupted"
        assert (tmp_path / "effects.txt").read_text().count("\n") == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("max_steps,expected", [(3, "completed"), (1, "failed")])
def test_provider_interruption_preserves_charged_step_and_original_input(tmp_path, max_steps, expected):
    async def scenario():
        core, store, _ = setup(tmp_path, Adapter("lost"))
        with pytest.raises(ProcessLost):
            await core.prompt("Original question.", budget={"max_steps": max_steps, "timeout_s": 30})
        [record] = store.list_active()
        assert record.steps_used == 1
        adapter = Adapter()
        resumed, fresh, repo = setup(tmp_path, adapter, create=False)
        await resumed.resume(record.turn_id)
        final = fresh.get(record.turn_id)
        assert final.status == expected
        assert final.steps_used == (2 if max_steps == 3 else 1)
        assert len(adapter.requests) == (1 if max_steps == 3 else 0)
        assert len([e for e in repo.get_branch("session-a") if e.payload.get("role") == "user"]) == 1
    asyncio.run(scenario())


def test_durable_steering_is_applied_before_the_next_provider_request(tmp_path):
    async def scenario():
        class QueueThenLose(Adapter):
            async def stream(self, request):
                await core.steer("Use the corrected outcome.")
                raise ProcessLost()
                yield
        core, store, _ = setup(tmp_path, QueueThenLose())
        with pytest.raises(ProcessLost):
            await core.prompt("Original question.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        assert len(record.queue) == 1 and not record.queue[0]["consumed"]
        adapter = Adapter()
        resumed, fresh, repo = setup(tmp_path, adapter, create=False)
        await resumed.resume(record.turn_id)
        assert adapter.requests[0].messages[-1] == {"role": "user", "content": "Use the corrected outcome."}
        assert fresh.get(record.turn_id).queue[0]["consumed"]
        assert len([e for e in repo.get_branch("session-a")
                    if e.payload.get("content") == "Use the corrected outcome."]) == 1
    asyncio.run(scenario())


def test_cancel_intent_survives_restart_without_another_provider_request(tmp_path):
    async def scenario():
        core, store, _ = setup(tmp_path, Adapter("lost"))
        with pytest.raises(ProcessLost):
            await core.prompt("Original question.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        store.request_cancel(record.turn_id, expected_version=record.version)
        adapter = Adapter()
        resumed, fresh, _ = setup(tmp_path, adapter, create=False)
        await resumed.resume(record.turn_id)
        assert fresh.get(record.turn_id).status == "cancelled"
        assert not adapter.requests
    asyncio.run(scenario())


def _exit_after_receipt(root):
    root = Path(root)
    async def scenario():
        core, _, repo = setup(root, Adapter("tool"), runtime=Runtime(root))
        original = repo.append_once
        def exit_at_message(*args, **kwargs):
            if kwargs.get("stage") == "tool_result":
                os._exit(73)
            return original(*args, **kwargs)
        repo.append_once = exit_at_message
        await core.prompt("Save original.", budget={"max_steps": 4, "timeout_s": 30})
    asyncio.run(scenario())


def test_os_process_death_releases_guard_and_repairs_the_original_receipt(tmp_path):
    process = multiprocessing.get_context("spawn").Process(target=_exit_after_receipt, args=(str(tmp_path),))
    process.start()
    process.join(15)
    try:
        assert process.exitcode == 73
        [record] = TurnStore(tmp_path).list_active()
        assert record.status == "running"  # No Python finally ran in the child.
        async def recover():
            adapter = Adapter()
            core, fresh, _ = setup(tmp_path, adapter, runtime=Runtime(tmp_path), create=False)
            await core.resume(record.turn_id)
            assert fresh.get(record.turn_id).status == "completed"
            assert len(adapter.requests) == 1
        asyncio.run(recover())
        assert (tmp_path / "effects.txt").read_text().count("\n") == 1
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_recovery_refuses_changed_runtime_contract_before_a_provider_call(tmp_path):
    async def scenario():
        core, store, _ = setup(tmp_path, Adapter("lost"))
        core.model_config_identity = {"model": "frozen", "temperature": 0}
        with pytest.raises(ProcessLost):
            await core.prompt("Original question.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        adapter = Adapter()
        resumed, _, _ = setup(tmp_path, adapter, create=False)
        resumed.model_config_identity = {"model": "changed", "temperature": 0}
        with pytest.raises(TurnRecoveryRequired, match="runtime contract"):
            await resumed.resume(record.turn_id)
        assert not adapter.requests
    asyncio.run(scenario())


def test_downtime_does_not_refund_the_wall_budget(tmp_path, monkeypatch):
    async def scenario():
        from workbench.agent import turn_journal
        core, store, _ = setup(tmp_path, Adapter("lost"))
        with pytest.raises(ProcessLost):
            await core.prompt("Original question.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        original_clock = turn_journal.time.time
        monkeypatch.setattr(turn_journal.time, "time", lambda: original_clock() + 40)
        adapter = Adapter()
        resumed, fresh, _ = setup(tmp_path, adapter, create=False)
        await resumed.resume(record.turn_id)
        final = fresh.get(record.turn_id)
        assert not adapter.requests
        assert final.status == "failed" and final.wall_s_used >= 40
        assert final.steps_used == 1
    asyncio.run(scenario())


def test_missing_receipt_does_not_leave_a_live_recovery_claim(tmp_path):
    async def scenario():
        core, store, _ = setup(tmp_path, Adapter("tool"), runtime=Runtime(tmp_path, lose_receipt=True))
        with pytest.raises(ProcessLost):
            await core.prompt("Save original.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        for _ in range(2):
            resumed, fresh, _ = setup(tmp_path, Adapter(), runtime=Runtime(tmp_path), create=False)
            with pytest.raises(TurnRecoveryRequired, match="receipt"):
                await resumed.resume(record.turn_id)
            assert fresh.get(record.turn_id).lease_owner is None
    asyncio.run(scenario())


def test_accepted_turn_resumes_from_frozen_input_before_its_first_claim(tmp_path, monkeypatch):
    async def scenario():
        adapter = Adapter()
        core, store, _ = setup(tmp_path, adapter)
        monkeypatch.setattr(store, "claim", lambda *args, **kwargs: (_ for _ in ()).throw(ProcessLost()))
        with pytest.raises(ProcessLost):
            await core.prompt("Accepted original.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        assert record.status == "accepted" and not adapter.requests
        resumed, fresh, repo = setup(tmp_path, Adapter(), create=False)
        assert await resumed.resume(record.turn_id) == "Saved."
        assert fresh.get(record.turn_id).steps_used == 1
        assert len([e for e in repo.get_branch("session-a") if e.payload.get("role") == "user"]) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["follow_up", "steer"])
def test_consumed_queue_input_is_not_lost_before_the_provider_checkpoint(tmp_path, monkeypatch, kind):
    async def scenario():
        class QueueAndAnswer(Adapter):
            async def stream(self, request):
                await getattr(core, kind)("Accepted next question.")
                yield ModelStreamEvent.text_delta(request.request_id, "First answer.")
                yield ModelStreamEvent.done(request.request_id)
        core, store, _ = setup(tmp_path, QueueAndAnswer())
        original = store.consume_queue
        def consume_then_lose(*args, **kwargs):
            original(*args, **kwargs)
            raise ProcessLost()
        monkeypatch.setattr(store, "consume_queue", consume_then_lose)
        with pytest.raises(ProcessLost):
            await core.prompt("Original question.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        assert record.queue[0]["consumed"]
        adapter = Adapter()
        resumed, fresh, repo = setup(tmp_path, adapter, create=False)
        await resumed.resume(record.turn_id)
        assert len(adapter.requests) == 1
        assert adapter.requests[0].messages[-1]["content"] == "Accepted next question."
        assert len([e for e in repo.get_branch("session-a")
                    if e.payload.get("content") == "Accepted next question."]) == 1
        assert fresh.get(record.turn_id).steps_used == 2
    asyncio.run(scenario())


def test_numeric_repair_allowance_is_not_refunded_before_ready_checkpoint(tmp_path, monkeypatch):
    async def scenario():
        class UnsupportedNumber(Adapter):
            async def stream(self, request):
                yield ModelStreamEvent.text_delta(request.request_id, "The sample contains 2024 observations.")
                yield ModelStreamEvent.done(request.request_id)
        core, store, _ = setup(tmp_path, UnsupportedNumber())
        original = core.turn_journal.save
        def lose_before_ready(core, stage, **details):
            if stage == "ready":
                raise ProcessLost()
            return original(core, stage, **details)
        monkeypatch.setattr(core.turn_journal, "save", lose_before_ready)
        with pytest.raises(ProcessLost):
            await core.prompt("Summarize the sample.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        observed = []
        class InspectAllowance(Adapter):
            async def stream(self, request):
                observed.append(resumed._numeric_repairs_left)
                async for event in super().stream(request):
                    yield event
        resumed, fresh, repo = setup(tmp_path, InspectAllowance(), create=False)
        await resumed.resume(record.turn_id)
        assert observed == [0]
        assert fresh.get(record.turn_id).steps_used == 2
        assert len([e for e in repo.get_branch("session-a")
                    if e.payload.get("message_type") == "numeric_check"]) == 1
    asyncio.run(scenario())


def test_input_append_intent_without_a_log_entry_uses_the_prepared_checkpoint(tmp_path, monkeypatch):
    async def scenario():
        core, store, repo = setup(tmp_path, Adapter())
        original = repo._finish_append_intent
        def lose_before_user_log(session_id, intent, **kwargs):
            if intent["idempotency"]["stage"] == "initial_user":
                raise ProcessLost()
            return original(session_id, intent, **kwargs)
        monkeypatch.setattr(repo, "_finish_append_intent", lose_before_user_log)
        with pytest.raises(ProcessLost):
            await core.prompt("Frozen original.", budget={"max_steps": 4, "timeout_s": 30})
        [record] = store.list_active()
        adapter = Adapter()
        resumed, fresh, repository = setup(tmp_path, adapter, create=False)
        await resumed.resume(record.turn_id)
        assert fresh.get(record.turn_id).steps_used == 1
        assert adapter.requests[0].messages == [{"role": "user", "content": "Frozen original."}]
        assert len([e for e in repository.get_branch("session-a") if e.payload.get("role") == "user"]) == 1
    asyncio.run(scenario())


def test_completed_terminal_checkpoint_does_not_spend_another_step(tmp_path, monkeypatch):
    async def scenario():
        core, store, _ = setup(tmp_path, Adapter())
        original = store.transition
        def lose_before_terminal(turn_id, status, **kwargs):
            if status == "completed":
                raise ProcessLost()
            return original(turn_id, status, **kwargs)
        monkeypatch.setattr(store, "transition", lose_before_terminal)
        with pytest.raises(ProcessLost):
            await core.prompt("Finish.", budget={"max_steps": 1, "timeout_s": 30})
        [record] = store.list_active()
        adapter = Adapter()
        resumed, fresh, _ = setup(tmp_path, adapter, create=False)
        assert await resumed.resume(record.turn_id) == "Saved."
        assert not adapter.requests
        assert fresh.get(record.turn_id).status == "completed"
        assert fresh.get(record.turn_id).steps_used == 1
    asyncio.run(scenario())


def test_final_charged_step_repairs_receipt_but_never_grants_a_provider_retry(tmp_path, monkeypatch):
    async def scenario():
        core, store, repo = setup(tmp_path, Adapter("tool"), runtime=Runtime(tmp_path))
        original = repo.append_once
        def lose_before_message(*args, **kwargs):
            if kwargs.get("stage") == "tool_result":
                raise ProcessLost()
            return original(*args, **kwargs)
        monkeypatch.setattr(repo, "append_once", lose_before_message)
        with pytest.raises(ProcessLost):
            await core.prompt("Save original.", budget={"max_steps": 1, "timeout_s": 30})
        [record] = store.list_active()
        adapter = Adapter()
        resumed, fresh, repository = setup(tmp_path, adapter, runtime=Runtime(tmp_path), create=False)
        await resumed.resume(record.turn_id)
        assert not adapter.requests
        assert fresh.get(record.turn_id).steps_used == 1
        assert fresh.get(record.turn_id).status == "failed"
        assert len([e for e in repository.get_branch("session-a") if e.payload.get("role") == "tool"]) == 1
        assert (tmp_path / "effects.txt").read_text().count("\n") == 1
    asyncio.run(scenario())
