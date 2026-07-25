"""Generic provider-neutral agent loop for Workbench."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any
from uuid import uuid4

from .context import ContextBuilder
from .events import AgentEventStream
from .model import ModelAdapter, ModelRequest
from .session import JsonlSessionRepository
from .tools import ToolResult, ToolRuntime


class AgentCoreBusyError(RuntimeError):
    """Raised when a second control command races an active agent turn."""


class AgentCoreContinuationError(ValueError):
    """Raised when continuation would send an invalid message tail to the model."""


class AgentCoreBudgetError(ValueError):
    """Raised when a run budget cannot be enforced safely."""


@dataclass(frozen=True)
class AgentRunBudget:
    """Cooperative limits for one prompt/continue command."""

    max_steps: int | None = None
    timeout_s: float | None = None
    max_consecutive_identical_tool_calls: int = 2

    @classmethod
    def from_value(
        cls,
        value: "AgentRunBudget | Mapping[str, Any] | None",
    ) -> "AgentRunBudget":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise AgentCoreBudgetError("budget must be a mapping")

        max_steps = value.get("max_steps")
        if max_steps is not None:
            if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
                raise AgentCoreBudgetError("max_steps must be a positive integer")

        timeout_s = value.get("timeout_s")
        if timeout_s is not None:
            if (
                isinstance(timeout_s, bool)
                or not isinstance(timeout_s, Real)
                or not math.isfinite(float(timeout_s))
                or float(timeout_s) <= 0
            ):
                raise AgentCoreBudgetError("timeout_s must be a positive finite number")

        max_consecutive_identical_tool_calls = value.get(
            "max_consecutive_identical_tool_calls", 2
        )
        if (
            isinstance(max_consecutive_identical_tool_calls, bool)
            or not isinstance(max_consecutive_identical_tool_calls, int)
            or max_consecutive_identical_tool_calls <= 0
        ):
            raise AgentCoreBudgetError(
                "max_consecutive_identical_tool_calls must be a positive integer"
            )

        return cls(
            max_steps=max_steps,
            timeout_s=float(timeout_s) if timeout_s is not None else None,
            max_consecutive_identical_tool_calls=max_consecutive_identical_tool_calls,
        )


class AgentCore:
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
        self._active_tool_task: asyncio.Task[ToolResult] | None = None
        self._steer_queue: deque[str] = deque()
        self._follow_up_queue: deque[str] = deque()
        self._active_command_id: str | None = None
        self._budget = AgentRunBudget()
        self._steps_used = 0
        self._active_turn_started = False
        self._active_request_id: str | None = None
        self._active_message_started = False
        self._active_context_fingerprint: str | None = None
        self._final_status: str | None = None
        self._last_tool_call_fingerprint: str | None = None
        self._consecutive_identical_tool_calls = 0
        self._answered_tool_calls: dict[str, str] = {}

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

    async def prompt(
        self,
        text: str,
        *,
        tool_context: dict[str, Any] | None = None,
        budget: AgentRunBudget | Mapping[str, Any] | None = None,
    ) -> str:
        normalized_budget = AgentRunBudget.from_value(budget)
        self._begin(normalized_budget)
        try:
            return await self._run_with_budget(
                text,
                append_user=True,
                tool_context=tool_context,
            )
        finally:
            self._end()

    async def continue_(
        self,
        *,
        budget: AgentRunBudget | Mapping[str, Any] | None = None,
    ) -> str:
        normalized_budget = AgentRunBudget.from_value(budget)
        self._begin(normalized_budget)
        try:
            self._assert_continuable()
            return await self._run_with_budget(None, append_user=False)
        finally:
            self._end()

    async def abort(self) -> None:
        if self.phase == "idle":
            return
        self._abort_requested = True
        if self._abort_event is not None:
            self._abort_event.set()
        if self._active_tool_task is not None and not self._active_tool_task.done():
            self._active_tool_task.cancel()

    async def steer(self, text: str) -> None:
        if self.phase == "idle":
            raise AgentCoreBusyError("steer requires an active agent run")
        self._steer_queue.append(text)
        self.events.emit(
            self.session_id,
            "queue_update",
            {"queue": "steer", "content": text},
            command_id=self._active_command_id,
        )

    async def follow_up(self, text: str) -> None:
        if self.phase == "idle":
            raise AgentCoreBusyError("follow_up requires an active agent run")
        self._follow_up_queue.append(text)
        self.events.emit(
            self.session_id,
            "queue_update",
            {"queue": "follow_up", "content": text},
            command_id=self._active_command_id,
        )

    def _begin(self, budget: AgentRunBudget) -> None:
        if self.phase != "idle":
            raise AgentCoreBusyError("agent is already running")
        self.repository.update_status(self.session_id, "running")
        self.phase = "running"
        self._abort_requested = False
        self._timeout_requested = False
        self._active_command_id = uuid4().hex
        self._budget = budget
        self._steps_used = 0
        self._final_status = None
        self._last_tool_call_fingerprint = None
        self._consecutive_identical_tool_calls = 0
        self._answered_tool_calls = {}

    def _end(self) -> None:
        self.repository.update_status(self.session_id, self._final_status or "idle")
        if self._active_tool_task is not None and not self._active_tool_task.done():
            self._active_tool_task.cancel()
        self.phase = "idle"
        self._active_command_id = None
        self._abort_event = None
        self._active_tool_task = None
        self._timeout_requested = False
        self._budget = AgentRunBudget()
        self._steps_used = 0
        self._last_tool_call_fingerprint = None
        self._consecutive_identical_tool_calls = 0
        self._answered_tool_calls = {}
        self._active_turn_started = False
        self._active_request_id = None
        self._active_message_started = False
        self._active_context_fingerprint = None
        self._final_status = None

    def _assert_continuable(self) -> None:
        """Match the provider contract: continue only from user/tool results."""

        snapshot = self.context_builder.build(self.session_id)
        if not snapshot.messages:
            raise AgentCoreContinuationError("cannot continue without a message")
        last_role = snapshot.messages[-1].get("role")
        if last_role not in {"user", "tool"}:
            raise AgentCoreContinuationError(
                "cannot continue when the last message is not user or tool result"
            )

    def _annotate_step_budget(self, payload: Any) -> Any:
        """Tell the agent how much budget is left once most of it is spent.

        Without this the step budget is invisible: the turn simply stops at
        ``max_steps_exceeded`` with nothing produced, which is the worst
        outcome for the user and the one the agent had no way to avoid. A
        wandering turn that knows it has two steps left can still deliver.

        Deliberately content-free about *what* to propose — it reports budget,
        not an opinion on the task.
        """

        max_steps = self._budget.max_steps
        if max_steps is None or not isinstance(payload, dict):
            return payload
        remaining = max_steps - self._steps_used
        if remaining > max(2, max_steps // 2):
            return payload
        if remaining <= 2:
            guidance = (
                "Step budget is nearly spent. Stop inspecting: submit your "
                "proposal now with the evidence you already have, or answer "
                "the user directly. Another inspection will end the turn with "
                "nothing delivered."
            )
        else:
            guidance = (
                "More than half the step budget is spent. Inspect only what a "
                "required field still depends on, then propose."
            )
        # The repeat guard may already have written guidance; both matter, so
        # keep them rather than letting whichever runs last win.
        existing = payload.get("guidance")
        if isinstance(existing, str) and existing:
            guidance = f"{existing} {guidance}"
        return {**payload, "steps_remaining": max(remaining, 0), "guidance": guidance}

    @staticmethod
    def _tool_call_fingerprint(tool_call: Mapping[str, Any]) -> str:
        """Return a stable identity for loop detection, excluding provider call ids."""

        tool_id = str(tool_call.get("tool_id", ""))
        arguments = tool_call.get("arguments", {})
        try:
            encoded_arguments = json.dumps(
                arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            encoded_arguments = repr(arguments)
        return f"{tool_id}\x00{encoded_arguments}"

    async def _run_commands(
        self,
        text: str | None,
        *,
        append_user: bool,
        tool_context: dict[str, Any] | None = None,
    ) -> str:
        last_response = ""
        next_text = text
        next_append_user = append_user
        while next_text is not None or not next_append_user:
            last_response = await self._run_turn(
                next_text,
                append_user=next_append_user,
                tool_context=tool_context,
            )
            if self._abort_requested:
                break
            if self._steer_queue:
                next_text = self._steer_queue.popleft()
                next_append_user = True
                continue
            if self._follow_up_queue:
                next_text = self._follow_up_queue.popleft()
                next_append_user = True
                continue
            break
        return last_response

    async def _run_with_budget(
        self,
        text: str | None,
        *,
        append_user: bool,
        tool_context: dict[str, Any] | None = None,
    ) -> str:
        if self._budget.timeout_s is None:
            return await self._run_commands(
                text,
                append_user=append_user,
                tool_context=tool_context,
            )
        timeout_handle = asyncio.get_running_loop().call_later(
            self._budget.timeout_s,
            self._mark_timeout,
        )
        try:
            return await asyncio.wait_for(
                self._run_commands(
                    text,
                    append_user=append_user,
                    tool_context=tool_context,
                ),
                timeout=self._budget.timeout_s,
            )
        except asyncio.TimeoutError:
            self._mark_timeout()
            return self._persist_terminal_error("agent_timeout")
        finally:
            timeout_handle.cancel()

    async def _run_turn(
        self,
        text: str | None,
        *,
        append_user: bool,
        tool_context: dict[str, Any] | None = None,
    ) -> str:
        command_id = self._active_command_id or uuid4().hex
        self.events.emit(
            self.session_id,
            "agent_start",
            {"phase": "turn", "command_id": command_id},
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "turn_start",
            {"append_user": append_user},
            command_id=command_id,
        )
        self._active_turn_started = True
        if append_user:
            if text is None:
                raise ValueError("prompt text is required")
            self.repository.append(
                self.session_id,
                "message",
                {"role": "user", "content": text, "command_id": command_id},
            )

        context = self.context_builder.build(self.session_id)
        self._active_context_fingerprint = context.fingerprint

        if (
            self._budget.max_steps is not None
            and self._steps_used >= self._budget.max_steps
        ):
            return self._persist_terminal_error("max_steps_exceeded")
        self._steps_used += 1
        request = ModelRequest(
            request_id=uuid4().hex,
            messages=context.messages,
            tools=self.tools,
            abort_event=self._new_abort_event(),
        )
        self._active_request_id = request.request_id
        self.events.emit(
            self.session_id,
            "message_start",
            {"role": "assistant", "request_id": request.request_id},
            command_id=command_id,
        )
        self._active_message_started = True
        chunks: list[str] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        finish_reason = "stop"
        error: str | None = None
        try:
            async for event in self.adapter.stream(request):
                if self._abort_requested:
                    finish_reason = "aborted"
                    break
                if event.type == "text_delta":
                    chunks.append(event.delta)
                    self.events.emit(
                        self.session_id,
                        "message_update",
                        {"delta": event.delta, "request_id": request.request_id},
                        command_id=command_id,
                    )
                elif event.type in {"tool_call_start", "tool_call_delta"}:
                    if event.tool_call is not None:
                        call = dict(event.tool_call)
                        call_id = str(call.get("tool_call_id", uuid4().hex))
                        current = tool_calls.setdefault(call_id, {})
                        current.update(call)
                elif event.type == "done":
                    finish_reason = event.finish_reason or "stop"
                    break
                elif event.type == "error":
                    finish_reason = "error"
                    error = event.error or "provider_error"
                    break
        except Exception as exc:  # Provider errors become durable turn state.
            finish_reason = "error"
            error = type(exc).__name__

        if finish_reason == "tool_calls" and tool_calls and self.tool_runtime is None:
            finish_reason = "error"
            error = "tool_runtime_unavailable"

        content = "".join(chunks)
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "stop_reason": finish_reason,
            "command_id": command_id,
        }
        if tool_calls:
            payload["tool_calls"] = list(tool_calls.values())
        if error is not None:
            payload["error"] = error
        entry = self.repository.append(self.session_id, "message", payload)
        if finish_reason == "aborted":
            self.events.emit(
                self.session_id,
                "aborted",
                {"request_id": request.request_id},
                command_id=command_id,
            )
        elif finish_reason == "error":
            self.events.emit(
                self.session_id,
                "error",
                {"request_id": request.request_id, "error": error},
                command_id=command_id,
            )
        self.events.emit(
            self.session_id,
            "message_end",
            {
                "entry_id": entry.entry_id,
                "content": content,
                "stop_reason": finish_reason,
                "error": error,
            },
            command_id=command_id,
        )
        if finish_reason == "aborted":
            self._final_status = "cancelled"
        elif finish_reason == "error":
            self._final_status = "failed"
        self._active_request_id = None
        self._active_message_started = False
        if finish_reason == "tool_calls" and tool_calls:
            if self.tool_runtime is None:
                error = "tool_runtime_unavailable"
            else:
                for tool_call in tool_calls.values():
                    tool_call_id = str(tool_call.get("tool_call_id", ""))
                    tool_id = str(tool_call.get("tool_id", ""))
                    self.events.emit(
                        self.session_id,
                        "tool_execution_start",
                        {"tool_call_id": tool_call_id, "tool_id": tool_id},
                        command_id=command_id,
                    )
                    tool_task = asyncio.create_task(
                        self.tool_runtime.execute(
                            tool_call,
                            session_id=self.session_id,
                            metadata=tool_context,
                        )
                    )
                    self._active_tool_task = tool_task
                    try:
                        result = await tool_task
                    except asyncio.CancelledError:
                        if self._timeout_requested:
                            result = ToolResult(
                                tool_call_id=tool_call_id,
                                tool_id=tool_id,
                                ok=False,
                                error="agent_timeout",
                            )
                        elif self._abort_requested:
                            result = ToolResult(
                                tool_call_id=tool_call_id,
                                tool_id=tool_id,
                                ok=False,
                                error="agent_aborted",
                            )
                        else:
                            raise
                    except Exception:
                        result = ToolResult(
                            tool_call_id=tool_call_id,
                            tool_id=tool_id,
                            ok=False,
                            error="tool_runtime_error",
                        )
                    finally:
                        if self._active_tool_task is tool_task:
                            self._active_tool_task = None
                    # A turn that re-asks a question it already answered learns
                    # nothing and spends a provider step doing it. The guard above
                    # only catches *consecutive* repeats, so an agent alternating
                    # between two inspections loops until the budget is gone. Hand
                    # the same evidence back with an explicit "you already have
                    # this" so the loop converges instead of erroring out.
                    payload = result.to_payload()
                    repeat_fingerprint = self._tool_call_fingerprint(tool_call)
                    if result.ok and repeat_fingerprint in self._answered_tool_calls:
                        if isinstance(payload, dict):
                            payload = {
                                **payload,
                                "already_answered_this_turn": True,
                                "guidance": (
                                    "This exact inspection was already answered in "
                                    "this turn; its evidence is unchanged. Stop "
                                    "inspecting and either submit a proposal or "
                                    "answer the user."
                                ),
                            }
                        self.events.emit(
                            self.session_id,
                            "loop_guard",
                            {
                                "tool_id": result.tool_id,
                                "reason": "repeated_inspection_replayed",
                            },
                            command_id=command_id,
                        )
                    elif result.ok:
                        self._answered_tool_calls[repeat_fingerprint] = result.tool_id
                    payload = self._annotate_step_budget(payload)
                    result_entry = self.repository.append(
                        self.session_id,
                        "message",
                        {
                            "role": "tool",
                            "tool_call_id": result.tool_call_id,
                            "name": result.tool_id,
                            "command_id": command_id,
                            "content": json.dumps(
                                payload,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        },
                    )
                    self.events.emit(
                        self.session_id,
                        "tool_execution_end",
                        {
                            "tool_call_id": result.tool_call_id,
                            "tool_id": result.tool_id,
                            "ok": result.ok,
                            "entry_id": result_entry.entry_id,
                            "error": result.error,
                        },
                        command_id=command_id,
                    )
                    if not result.ok and result.error in {
                        "agent_aborted",
                        "agent_timeout",
                        "tool_runtime_error",
                    }:
                        return self._persist_terminal_error(result.error)
                    if self._abort_requested:
                        return self._persist_terminal_error(
                            "agent_timeout" if self._timeout_requested else "agent_aborted"
                        )
                    fingerprint = self._tool_call_fingerprint(tool_call)
                    if fingerprint == self._last_tool_call_fingerprint:
                        self._consecutive_identical_tool_calls += 1
                    else:
                        self._last_tool_call_fingerprint = fingerprint
                        self._consecutive_identical_tool_calls = 1
                    if (
                        self._consecutive_identical_tool_calls
                        >= self._budget.max_consecutive_identical_tool_calls
                    ):
                        self.events.emit(
                            self.session_id,
                            "loop_guard",
                            {
                                "tool_id": tool_id,
                                "repetition_count": self._consecutive_identical_tool_calls,
                                "reason": "identical_tool_call",
                            },
                            command_id=command_id,
                        )
                        return self._persist_terminal_error(
                            "repeated_tool_call_limit"
                        )
                self.events.emit(
                    self.session_id,
                    "turn_end",
                    {"stop_reason": "tool_calls"},
                    command_id=command_id,
                )
                self.events.emit(
                    self.session_id,
                    "save_point",
                    {"entry_id": entry.entry_id, "context_fingerprint": context.fingerprint},
                    command_id=command_id,
                )
                self._active_turn_started = False
                return await self._run_turn(
                    None,
                    append_user=False,
                    tool_context=tool_context,
                )
        self.events.emit(
            self.session_id,
            "turn_end",
            {"stop_reason": finish_reason},
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "save_point",
            {"entry_id": entry.entry_id, "context_fingerprint": context.fingerprint},
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "agent_end",
            {"stop_reason": finish_reason},
            command_id=command_id,
        )
        self._active_turn_started = False
        return content if finish_reason == "stop" else ""

    def _persist_terminal_error(self, error: str) -> str:
        """Persist a budget stop as a complete, replayable assistant turn."""

        if error in {"max_steps_exceeded", "repeated_tool_call_limit"}:
            self._final_status = "blocked"
        elif error == "agent_aborted":
            self._final_status = "cancelled"
        else:
            self._final_status = "failed"
        command_id = self._active_command_id or uuid4().hex
        if not self._active_turn_started:
            self.events.emit(
                self.session_id,
                "agent_start",
                {"phase": "turn", "command_id": command_id},
                command_id=command_id,
            )
            self.events.emit(
                self.session_id,
                "turn_start",
                {"append_user": False},
                command_id=command_id,
            )
            self._active_turn_started = True

        request_id = self._active_request_id or uuid4().hex
        if not self._active_message_started:
            self.events.emit(
                self.session_id,
                "message_start",
                {"role": "assistant", "request_id": request_id},
                command_id=command_id,
            )
            self._active_message_started = True

        entry = self.repository.append(
            self.session_id,
            "message",
            {
                "role": "assistant",
                "content": "",
                "stop_reason": "error",
                "error": error,
            },
        )
        if error in {"agent_timeout", "agent_aborted"}:
            self.events.emit(
                self.session_id,
                "aborted",
                {"request_id": request_id, "error": error},
                command_id=command_id,
            )
        self.events.emit(
            self.session_id,
            "error",
            {"request_id": request_id, "error": error},
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "message_end",
            {
                "entry_id": entry.entry_id,
                "content": "",
                "stop_reason": "error",
                "error": error,
            },
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "turn_end",
            {"stop_reason": "error", "error": error},
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "save_point",
            {
                "entry_id": entry.entry_id,
                "context_fingerprint": self._active_context_fingerprint,
            },
            command_id=command_id,
        )
        self.events.emit(
            self.session_id,
            "agent_end",
            {"stop_reason": "error", "error": error},
            command_id=command_id,
        )
        self._active_request_id = None
        self._active_message_started = False
        self._active_turn_started = False
        return ""

    def _mark_timeout(self) -> None:
        self._timeout_requested = True
        self._abort_requested = True
        if self._abort_event is not None:
            self._abort_event.set()
        if self._active_tool_task is not None and not self._active_tool_task.done():
            self._active_tool_task.cancel()

    def _new_abort_event(self) -> asyncio.Event:
        self._abort_event = asyncio.Event()
        return self._abort_event
