"""Process-local Agent turn ownership and execution budgets.

Durable session data lives in JsonlSessionRepository. This registry only owns
in-flight tasks, agents and setup reservations. It provides no restart recovery.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

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
T = TypeVar("T")
logger = logging.getLogger(__name__)


def active_turn_key(project_root: Path, session_id: str) -> TurnKey:
    return (str(project_root.resolve()), session_id)


class TurnRegistry:
    """One owner for setup reservations and the live turn for each session.

    The same lock protects reservation and active-agent transitions across HTTP
    request threads. No lock is held while awaiting a provider or tool call.
    """

    def __init__(self) -> None:
        self.active: dict[TurnKey, AgentCore] = {}
        self.tasks: dict[TurnKey, asyncio.Task[Any]] = {}
        self._waiters: dict[asyncio.Task[Any], asyncio.Task[Any]] = {}
        self.reserved: set[TurnKey] = set()
        self.lock = threading.Lock()

    def reserve(self, root: Path, session_id: str) -> TurnKey:
        key = active_turn_key(root, session_id)
        with self.lock:
            if key in self.active or key in self.reserved or key in self.tasks:
                raise WorkbenchAPIError(
                    status_code=409,
                    code="AGENT_TURN_IN_PROGRESS",
                    message="This Agent session already has a running turn.",
                    details={"session_id": session_id},
                )
            self.reserved.add(key)
        return key

    async def run_owned(self, key: TurnKey, work: Callable[[], Awaitable[T]]) -> T:
        """Wait synchronously while a registry-owned task runs independently.

        Only the task releases its reservation. A cancelled HTTP waiter loses
        its response, but cannot cancel or unregister accepted work.
        """
        async def owned() -> T:
            try:
                # Register even under an eager task factory before work can
                # complete, raise, or acquire the registry lock during cleanup.
                await asyncio.sleep(0)
                return await work()
            finally:
                self.release(key)

        with self.lock:
            if key not in self.reserved or key in self.tasks:
                raise RuntimeError("owned turn requires an unused setup reservation")
            coroutine = owned()
            try:
                task = asyncio.create_task(coroutine)
                self.tasks[key] = task
                waiter = asyncio.current_task()
                self._waiters[waiter] = task
                task.add_done_callback(lambda finished: self._owned_done(key, finished))
            except BaseException:
                coroutine.close()
                self.reserved.discard(key)
                raise
        try:
            return await asyncio.shield(task)
        finally:
            with self.lock:
                self._waiters.pop(waiter, None)

    def owned_task_for(self, waiter: asyncio.Task[Any]) -> asyncio.Task[Any] | None:
        """Capture this waiter's exact task before detaching it for cleanup."""
        with self.lock:
            return self._waiters.get(waiter)

    def _owned_done(self, key: TurnKey, task: asyncio.Task[Any]) -> None:
        with self.lock:
            if self.tasks.get(key) is task:
                self.tasks.pop(key)
                # Also covers cancellation before the coroutine first runs.
                self.reserved.discard(key)
        if not task.cancelled():
            error = task.exception()  # Retrieve even when every waiter left.
            if error is not None:
                logger.error("Agent owned turn failed for session %s", key[1],
                             exc_info=(type(error), error, error.__traceback__))

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
