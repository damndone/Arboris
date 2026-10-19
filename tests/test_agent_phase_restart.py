"""Durable phases resume original transitions without repeating side effects."""
import asyncio

import pytest

from tests.test_agent_core_restart import ProcessLost, setup
from workbench.agent.model import ModelStreamEvent
from workbench.agent.phases import PhaseRequest, PhaseStep
from workbench.agent.tools import ToolDefinition, ToolRegistry
from workbench.agent.turn_journal import TurnRecoveryRequired


class Phase:
    episode_id = "original-phase"

    def __init__(self, effects, *, lose=False):
        self.effects, self.lose = effects, lose

    def request(self, transcript):
        return PhaseRequest(list(transcript) or [{"role":"user", "content":"Original phase input."}], [])

    async def consume(self, events, *, error=None):
        assert error is None
        self.effects.append("consumed")
        if self.lose:
            raise ProcessLost()
        return PhaseStep("completed", public_result={"verified":"original"})

    def checkpoint(self):
        return {"kind":"fixture", "episode_id":self.episode_id}

    def failure(self, reason, error=None):
        return RuntimeError(reason)


class ContinuingPhase(Phase):
    def __init__(self, effects, *, consumed=0):
        super().__init__(effects)
        self.consumed = consumed

    async def consume(self, events, *, error=None):
        self.effects.append("consumed")
        self.consumed += 1
        return PhaseStep("continue", ({"role":"user", "content":"Original correction."},)) if self.consumed == 1 else PhaseStep(
            "completed", public_result={"verified":"original"})

    def checkpoint(self):
        return {**super().checkpoint(), "consumed":self.consumed}


def configured(tmp_path, model, effects, *, create, lose=False):
    core, store, repo = setup(tmp_path, model, create=create)
    tools = ToolRegistry()
    def enter(arguments, context):
        core.enter_phase(Phase(effects, lose=lose))
        return {"phase_started":True}
    tools.register(ToolDefinition("enter", "v1", {"type":"object"}, "none", enter))
    core.attach_tools(tools.descriptors(), tools)
    core.phase_restorer = lambda snapshot: Phase(effects)
    return core, store, repo


class Model:
    def __init__(self, *, lost=False, enter=True):
        self.lost, self.enter, self.requests = lost, enter, []

    async def stream(self, request):
        self.requests.append(request)
        if self.enter and len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id":"start", "tool_id":"enter", "arguments":{}})
            yield ModelStreamEvent.done(request.request_id, "tool_calls")
        elif self.lost:
            raise ProcessLost()
        else:
            yield ModelStreamEvent.text_delta(request.request_id, "Verified.")
            yield ModelStreamEvent.done(request.request_id)


def test_phase_provider_restart_keeps_transcript_command_and_charged_steps(tmp_path):
    async def scenario():
        effects = []
        model = Model(lost=True)
        core, store, _ = configured(tmp_path, model, effects, create=True)
        with pytest.raises(ProcessLost):
            await core.prompt("Plan.", budget={"max_steps":4, "timeout_s":30})
        [turn] = store.list_active()
        assert turn.steps_used == 2
        fresh_model = Model(enter=False)
        fresh, state, _ = configured(tmp_path, fresh_model, effects, create=False)
        assert await fresh.resume(turn.turn_id) == "Verified."
        assert fresh_model.requests[0].messages == model.requests[1].messages
        assert fresh_model.requests[0].tools == model.requests[1].tools
        assert effects == ["consumed"]
        assert state.get(turn.turn_id).steps_used == 4
        assert state.get(turn.turn_id).command_id == turn.command_id
    asyncio.run(scenario())


def test_phase_applied_receipt_repairs_message_without_consuming_twice(tmp_path, monkeypatch):
    async def scenario():
        effects = []
        core, store, repo = configured(tmp_path, Model(), effects, create=True)
        original = repo.append_once
        def lost_before_public_message(session_id, entry_type, payload, **kwargs):
            if entry_type == "custom_message" and payload.get("name") == "workbench_phase_result":
                raise ProcessLost()
            return original(session_id, entry_type, payload, **kwargs)
        monkeypatch.setattr(repo, "append_once", lost_before_public_message)
        with pytest.raises(ProcessLost):
            await core.prompt("Plan.", budget={"max_steps":3, "timeout_s":30})
        [turn] = store.list_active()
        assert effects == ["consumed"]
        model = Model(enter=False)
        resumed, final, repository = configured(tmp_path, model, effects, create=False)
        assert await resumed.resume(turn.turn_id) == "Verified."
        assert effects == ["consumed"] and len(model.requests) == 1
        messages = [e for e in repository.get_branch("session-a") if e.payload.get("name") == "workbench_phase_result"]
        assert len(messages) == 1 and '"original"' in messages[0].payload["content"]
        assert final.get(turn.turn_id).steps_used == 3
    asyncio.run(scenario())


def test_phase_with_unknown_consumption_effect_refuses_blind_replay(tmp_path):
    async def scenario():
        effects = []
        core, store, _ = configured(tmp_path, Model(), effects, create=True, lose=True)
        with pytest.raises(ProcessLost):
            await core.prompt("Plan.", budget={"max_steps":4, "timeout_s":30})
        [turn] = store.list_active()
        model = Model(enter=False)
        resumed, state, _ = configured(tmp_path, model, effects, create=False)
        with pytest.raises(TurnRecoveryRequired, match="original.*receipt"):
            await resumed.resume(turn.turn_id)
        assert effects == ["consumed"] and not model.requests
        assert state.get(turn.turn_id).status == "interrupted"
    asyncio.run(scenario())


def test_applied_continuation_replays_messages_after_checkpoint_boundary(tmp_path, monkeypatch):
    async def scenario():
        effects = []
        model = Model()
        core, store, repo = configured(tmp_path, model, effects, create=True)
        tools = ToolRegistry()
        def enter(arguments, context):
            core.enter_phase(ContinuingPhase(effects))
            return {"phase_started":True}
        tools.register(ToolDefinition("enter", "v1", {"type":"object"}, "none", enter))
        core.attach_tools(tools.descriptors(), tools)
        original = core._phase_checkpoint
        def lost_after_checkpoint(phase, status):
            original(phase, status)
            if status == "continue":
                raise ProcessLost()
        monkeypatch.setattr(core, "_phase_checkpoint", lost_after_checkpoint)
        with pytest.raises(ProcessLost):
            await core.prompt("Plan.", budget={"max_steps":4, "timeout_s":30})
        [turn] = store.list_active()
        fresh_model = Model(enter=False)
        resumed, _, repository = configured(tmp_path, fresh_model, effects, create=False)
        resumed.phase_restorer = lambda snapshot: ContinuingPhase(effects, consumed=snapshot["consumed"])
        assert await resumed.resume(turn.turn_id) == "Verified."
        assert effects == ["consumed", "consumed"]
        assert fresh_model.requests[0].messages[-1]["content"] == "Original correction."
        assert len([e for e in repository.get_branch("session-a") if e.entry_type == "phase_message"
                    and e.payload["message"]["content"] == "Original correction."]) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["phase_ready", "phase_received"])
def test_phase_restart_before_consumption_uses_original_input_or_reply(tmp_path, monkeypatch, boundary):
    async def scenario():
        effects = []
        core, store, _ = configured(tmp_path, Model(), effects, create=True)
        original = core.turn_journal.save
        def lost_after_saved_state(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == boundary:
                raise ProcessLost()
            return result
        monkeypatch.setattr(core.turn_journal, "save", lost_after_saved_state)
        with pytest.raises(ProcessLost):
            await core.prompt("Plan.", budget={"max_steps":3, "timeout_s":30})
        [turn] = store.list_active()
        assert not effects
        model = Model(enter=False)
        resumed, final, _ = configured(tmp_path, model, effects, create=False)
        assert await resumed.resume(turn.turn_id) == "Verified."
        assert effects == ["consumed"]
        assert len(model.requests) == (2 if boundary == "phase_ready" else 1)
        assert final.get(turn.turn_id).steps_used == 3
    asyncio.run(scenario())
