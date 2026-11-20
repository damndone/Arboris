"""A turn's wall budget leaves out the waits its caller declares, and only those."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.test_agent_harness_foundation import RecordingStreamAdapter
from workbench.agent import turn_clock
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.session import JsonlSessionRepository

HOLD_S = 0.3
BUDGET_S = 0.2


class HeldAdapter(RecordingStreamAdapter):
    """Holds each request back before sending it, as a paced evaluation round does."""

    def __init__(self, responses, held):
        super().__init__(responses)
        self.held = held

    async def stream(self, request):
        self.held[0] += HOLD_S  # the pace declares a wait before sleeping it
        await asyncio.sleep(HOLD_S)
        async for event in super().stream(request):
            yield event


def _reply(tmp_path: Path, *, declared: bool) -> str:
    held = [0.0]

    async def scenario() -> str:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        agent = AgentCore(repository, AgentEventStream(tmp_path / "workbench"),
                          HeldAdapter(["The answer."], held), session_id="session-a")
        return await agent.prompt("answer", budget={"timeout_s": BUDGET_S})

    previous = turn_clock.exclude_waits((lambda: held[0]) if declared else None)
    try:
        return asyncio.run(scenario())
    finally:
        turn_clock.exclude_waits(previous)


def test_a_declared_hold_does_not_spend_the_turn_budget(tmp_path):
    assert _reply(tmp_path, declared=True) == "The answer."


def test_an_undeclared_hold_still_times_the_turn_out(tmp_path):
    assert "agent_timeout" in _reply(tmp_path, declared=False)


@pytest.mark.parametrize("declared", [True, False])
def test_the_budget_still_stops_work_that_is_not_declared(tmp_path, declared):
    class SlowAdapter(RecordingStreamAdapter):
        async def stream(self, request):
            await asyncio.sleep(HOLD_S)
            async for event in super().stream(request):
                yield event

    async def scenario() -> str:
        repository = JsonlSessionRepository(tmp_path / "workbench")
        repository.create_session("session-a", chain_id="chain-a", role="chain")
        agent = AgentCore(repository, AgentEventStream(tmp_path / "workbench"),
                          SlowAdapter(["late"]), session_id="session-a")
        return await agent.prompt("answer", budget={"timeout_s": BUDGET_S})

    previous = turn_clock.exclude_waits((lambda: 0.0) if declared else None)
    try:
        assert "agent_timeout" in asyncio.run(scenario())
    finally:
        turn_clock.exclude_waits(previous)
