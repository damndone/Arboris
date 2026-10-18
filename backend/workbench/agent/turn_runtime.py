"""Process-local Agent turn ownership and execution budgets.

Durable session data lives in JsonlSessionRepository. This registry only owns
in-flight agents and setup reservations, and retains no prompt or replay data.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from ..api_errors import WorkbenchAPIError

if TYPE_CHECKING:
    from .core import AgentCore

# One step = one provider call. A read-only inspection sweep is typically
# question → 5 inspect tools → summary, so 4 blocked legitimate turns in the
# live DeepSeek smoke; 8 leaves headroom without unbounding the loop.
# Raised to 10 after a live turn on an ARMA-GARCH node inspected, proposed on
# step 9, and then reported max_steps_exceeded even though the proposal had
# been created — the user saw a failed turn with a valid proposal sitting
# behind it. The protocol now also makes a successful proposal terminal, so
# this is headroom rather than permission to sprawl.
DEFAULT_MAX_STEPS = 10
# The wall-clock ceiling for a whole turn. 120 s cut off a live DeepSeek turn
# (2026-10-13, global Agent, "report on both runs"): five tool steps, a long
# report drafted by 58 s, withdrawn by the numeric check, and the rewrite then
# stopped at exactly 120 s. Loops are bounded by DEFAULT_MAX_STEPS, a stalled
# provider by the adapter's 90 s idle timeout, and the person can stop a turn
# at any time; this ceiling only has to leave room for a long answer and one
# rewrite.
DEFAULT_TIMEOUT_S = 300.0
# v1.9.1 execution modes do more inside one turn, so they get more room.
# Ask every step: read-only analysis runs inline and a turn ends at the
# first card, so it needs room for a few analyses and their reading, not for
# a whole analysis. Auto within plan: planned steps execute inside the turn
# (run, read the result, write it up), so a turn may cover several of them.
# In the v1.9.1 smoke, turns used 1-7 steps in Ask, and an Auto turn that
# executed two planned steps and read their results stopped at 11 of 10.
# The person can stop a turn at any time; these bound a runaway loop.
MODE_BUDGETS = {
    None: {"max_steps": DEFAULT_MAX_STEPS, "timeout_s": DEFAULT_TIMEOUT_S},
    "ask": {"max_steps": 25, "timeout_s": 600.0},
    "auto": {"max_steps": 40, "timeout_s": 1200.0},
}


def turn_budget(execution_mode: str | None) -> dict[str, float | int]:
    return dict(MODE_BUDGETS.get(execution_mode, MODE_BUDGETS[None]))


TurnKey = tuple[str, str]


def active_turn_key(project_root: Path, session_id: str) -> TurnKey:
    return (str(project_root.resolve()), session_id)


class TurnRegistry:
    """One owner for setup reservations and the live turn for each session.

    The same lock protects reservation and active-agent transitions across HTTP
    request threads. No lock is held while awaiting a provider or tool call.
    """

    def __init__(self) -> None:
        self.active: dict[TurnKey, AgentCore] = {}
        self.reserved: set[TurnKey] = set()
        self.lock = threading.Lock()

    def reserve(self, root: Path, session_id: str) -> TurnKey:
        key = active_turn_key(root, session_id)
        with self.lock:
            if key in self.active or key in self.reserved:
                raise WorkbenchAPIError(
                    status_code=409,
                    code="AGENT_TURN_IN_PROGRESS",
                    message="This Agent session already has a running turn.",
                    details={"session_id": session_id},
                )
            self.reserved.add(key)
        return key

    def release(self, key: TurnKey) -> None:
        with self.lock:
            self.reserved.discard(key)

    def activate(self, key: TurnKey, agent: AgentCore) -> None:
        with self.lock:
            self.active[key] = agent

    def deactivate(self, key: TurnKey, agent: AgentCore) -> None:
        with self.lock:
            if self.active.get(key) is agent:
                self.active.pop(key, None)

    def get(self, root: Path, session_id: str) -> AgentCore | None:
        key = active_turn_key(root, session_id)
        with self.lock:
            return self.active.get(key)


turn_registry = TurnRegistry()
