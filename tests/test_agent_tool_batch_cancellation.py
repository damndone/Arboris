"""Owner cancellation before a tool task's first step still closes its durable receipt."""
import asyncio
import json

import pytest

from tests.test_agent_core_restart import Adapter, CALL, setup
from workbench.agent import tool_batches, tool_receipts
from workbench.agent.turn_journal import TurnRecoveryRequired


@pytest.mark.parametrize("cause", ["timeout", "abort", "external"])
def test_cancel_before_first_tool_step_preserves_owner_and_original_receipt_semantics(tmp_path, monkeypatch, cause):
    class Runtime:
        calls = 0

        async def execute(self, call, *, session_id, metadata):
            self.calls += 1
            pytest.fail("the cancelled task must never enter the tool runtime")

    async def scenario():
        runtime, adapter = Runtime(), Adapter("tool")
        core, store, repository = setup(tmp_path, adapter, runtime=runtime)
        original_create_task = asyncio.create_task
        cancelled, owner_tasks, flags = [], [], []

        def request_timeout():
            core._mark_timeout()
            flags.append((core._timeout_requested, core._abort_requested))

        async def request_abort():
            await core.abort()
            flags.append((core._timeout_requested, core._abort_requested))

        def cancel_before_entry(coroutine, *args, **kwargs):
            if getattr(coroutine, "cr_code", None) is not tool_batches._invoke.__code__:
                return original_create_task(coroutine, *args, **kwargs)
            # Queue the real owner request before the child's first scheduled
            # step, then cancel the child while its coroutine has not entered.
            if cause == "timeout":
                asyncio.get_running_loop().call_soon(request_timeout)
            elif cause == "abort":
                owner_tasks.append(original_create_task(request_abort()))
            task = original_create_task(coroutine, *args, **kwargs)
            assert task.cancel()
            cancelled.append(task)
            return task

        monkeypatch.setattr(asyncio, "create_task", cancel_before_entry)
        if cause == "external":
            with pytest.raises(asyncio.CancelledError):
                await core.prompt("Save original.", budget={"max_steps": 3, "timeout_s": 30})
        else:
            reply = await core.prompt("Save original.", budget={"max_steps": 3, "timeout_s": 30})
            assert ("agent_timeout" in reply) if cause == "timeout" else reply == ""
        if owner_tasks:
            await asyncio.gather(*owner_tasks)
        assert runtime.calls == 0 and len(cancelled) == 1 and cancelled[0].cancelled()
        assert core._active_tool_task is None
        branch = repository.get_branch("session-a")
        [intent] = [entry for entry in branch if entry.entry_type == "tool_intent"]
        assert intent.payload["tool_call"] == CALL
        receipt = tool_receipts.read(repository, **intent.payload)
        ends = [event for event in core.events.replay("session-a") if event.event_type == "tool_execution_end"]
        if cause == "external":
            assert not flags and receipt is None and not ends
            [turn] = store.list_active()
            fresh_adapter = Adapter()
            resumed, _, _ = setup(tmp_path, fresh_adapter, runtime=runtime, create=False)
            with pytest.raises(TurnRecoveryRequired, match="receipt"):
                await resumed.resume(turn.turn_id)
            assert not fresh_adapter.requests and runtime.calls == 0
            return
        expected = "agent_timeout" if cause == "timeout" else "agent_aborted"
        assert flags == [(True, True) if cause == "timeout" else (False, True)]
        assert receipt is not None and receipt.payload["tool_call_sha256"] == tool_receipts.tool_call_sha256(CALL)
        assert receipt.payload["tool_result"]["error"] == expected
        [message] = [entry for entry in branch if entry.payload.get("role") == "tool"]
        assert message.payload["tool_call_id"] == CALL["tool_call_id"]
        assert json.loads(message.payload["content"])["error"] == expected
        assert len(ends) == 1 and ends[0].payload == {"tool_call_id": CALL["tool_call_id"],
            "tool_id": CALL["tool_id"], "ok": False, "entry_id": message.entry_id, "error": expected}
        assert repository.get_metadata("session-a")["status"] == ("failed" if cause == "timeout" else "cancelled")
        assert not store.list_active() and len(adapter.requests) == 1

    asyncio.run(scenario())
