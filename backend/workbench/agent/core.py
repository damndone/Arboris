"""Generic provider-neutral agent loop for Workbench."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

from .compaction import CompactionPolicy
from .context import ContextBuilder
from .events import AgentEventStream
from . import numeric_grounding
from .model import ModelAdapter
from .phases import CorePhase
from .session import JsonlSessionRepository
from .tools import ToolRuntime
from .core_parts.budget import (  # noqa: F401  (re-exported)
    AgentCoreBusyError,
    AgentCoreContinuationError,
    AgentCoreBudgetError,
    AgentRunBudget,
)
from .core_parts.phase_driver import PhaseDriverMixin
from .core_parts.commands import CommandMixin
from .core_parts.turn_loop import TurnLoopMixin
from .core_parts.finish import FinishMixin
from .core_parts.lifecycle import LifecycleMixin


class AgentCore(PhaseDriverMixin, CommandMixin, TurnLoopMixin, FinishMixin, LifecycleMixin):
    """Run turns while keeping messages and normalized events durable."""

    def __init__(
        self,
        repository: JsonlSessionRepository,
        events: AgentEventStream,
        adapter: ModelAdapter,
        *,
        session_id: str,
        context_builder: ContextBuilder | None = None,
        tools: Iterable[dict[str, Any]] = (),
        tool_runtime: ToolRuntime | None = None,
        compaction_policy: CompactionPolicy | None = None,
        model_name: str | None = None,
        model_config_identity: Mapping[str, Any] | None = None,
        turn_journal=None,
    ) -> None:
        self.repository = repository
        self.events = events
        self.adapter = adapter
        self.session_id = session_id
        self.context_builder = context_builder or ContextBuilder(repository)
        self.tools = list(tools)
        self.tool_runtime = tool_runtime
        self.phase = "idle"
        self._abort_requested = False
        self._timeout_requested = False
        self._abort_event: asyncio.Event | None = None
        self._active_tool_task: asyncio.Task[Any] | None = None
        self._steer_queue: deque[str] = deque()
        self._follow_up_queue: deque[str] = deque()
        self._active_command_id: str | None = None
        self._budget = AgentRunBudget()
        self._numeric_repairs_left = numeric_grounding.MAX_REPAIRS
        self._steps_used = 0
        self._active_turn_started = False
        self._active_request_id: str | None = None
        self._active_message_started = False
        self._active_context_fingerprint: str | None = None
        self._final_status: str | None = None
        self._last_tool_call_fingerprint: str | None = None
        self._consecutive_identical_tool_calls = 0
        self._answered_tool_calls: dict[str, str] = {}
        # Compaction (agent/compaction.py): None keeps the whole conversation.
        self.compaction_policy = compaction_policy
        self.model_name = model_name
        self.model_config_identity = dict(model_config_identity or {})
        self._overflow_retried = False
        self._argument_corrected = False
        self._core_phase: CorePhase | None = None
        self._phase_messages: list[dict[str, Any]] = []
        self._phase_result: Any = None
        self._phase_completed = False
        self._standalone_phase = False
        self.phase_restorer = None
        self.turn_journal = turn_journal
        self.command_check = None
        self.input_checkpoint = None
        self.completion_check = None
        self.turn_end_observer = None
        self.research_review_context = None
        self.research_review_mode = lambda: "ask"


    def attach_tools(
        self,
        tools: Iterable[dict[str, Any]],
        tool_runtime: ToolRuntime,
    ) -> None:
        """Attach a scoped runtime before the agent starts running."""

        if self.phase != "idle":
            raise AgentCoreBusyError("tools can only be attached while agent is idle")
        self.tools = list(tools)
        self.tool_runtime = tool_runtime


