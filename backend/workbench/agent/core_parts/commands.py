"""Commands: prompt, continue, resume, abort, steer and the per-command budget loop."""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from .. import numeric_grounding, turn_clock
from ..model import LLMRequestBudgetExceeded, ModelStreamEvent
from ..phases import PhaseStep, RecordedProviderError
from ..business_identity import identity_value
from ..tools import ToolResult
from .budget import AgentCoreBusyError, AgentCoreContinuationError, AgentRunBudget


class CommandMixin:
    """Part of AgentCore; see agent/core.py."""

    async def prompt(
        self,
        text: str,
        *,
        tool_context: dict[str, Any] | None = None,
        budget: AgentRunBudget | Mapping[str, Any] | None = None,
    ) -> str:
        return await self._command(text, budget=budget, tool_context=tool_context, continuation=False)

    async def continue_(
        self,
        *,
        budget: AgentRunBudget | Mapping[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> str:
        return await self._command(None, budget=budget, tool_context=tool_context, continuation=True)

    def _last_person_text(self):
        for entry in reversed(self.repository.get_branch(self.session_id, payload_entry_types=frozenset({"message"}))):
            if entry.entry_type == "message" and entry.payload.get("role") == "user":
                return entry.payload.get("content")
        return None

    async def _command(self, text, *, budget, tool_context, continuation):
        journal = self.turn_journal
        with journal.ownership() if journal else nullcontext():
            if self.command_check is not None:
                self.command_check()
            self._begin(AgentRunBudget.from_value(budget), command_id=(tool_context or {}).get("command_id"))
            # A continuation has no new text; the person's last request still sets the
            # answer language and what a completion claim answers (off3: English notices
            # in a Chinese task after every confirmation).
            self._user_text = text if not continuation else self._last_person_text()
            started = False
            try:
                if continuation:
                    self._assert_continuable()
                elif self.input_checkpoint is not None:
                    self.input_checkpoint(self._active_command_id)
                if journal:
                    journal.start(self, text, continuation=continuation)
                    started = True
                result = await self._run_with_budget(text, append_user=not continuation, tool_context=tool_context)
                self._durable_response = result
                if journal:
                    journal.finish(self)
                return result
            except BaseException:
                if journal and started:
                    journal.interrupted(self)
                raise
            finally:
                self._end()

    async def resume(self, turn_id, *, tool_context=None):
        """Continue an existing command, preserving its identity and budget."""
        journal = self.turn_journal
        if journal is None:
            raise AgentCoreContinuationError("resume requires a durable turn journal")
        with journal.ownership() as guard:
            if self.command_check is not None:
                self.command_check()
            record = journal.store.get(turn_id)
            self._begin(AgentRunBudget.from_value(record.budget), command_id=record.command_id)
            try:
                state, exhausted, cancelled = journal.recover(self, turn_id, guard)
                if state["stage"] == "terminal":
                    self._final_status = state["final_status"]
                    result = state["response"]
                    if self.completion_check is not None and result.strip():
                        final = next(e for e in reversed(self.repository.get_branch(self.session_id))
                                     if e.entry_type == "message" and e.payload.get("role") == "assistant"
                                     and e.payload.get("command_id") == self._active_command_id)
                        reviewed, _ = self._recheck_completion(final.payload, final)
                        result = reviewed["content"]
                elif exhausted or cancelled:
                    result = self._persist_terminal_error("agent_aborted" if cancelled else "max_steps_exceeded"
                        if self._steps_used >= self._budget.max_steps else "agent_timeout")
                elif state["stage"] == "phase_applied":
                    step = PhaseStep(**state["phase_step"])
                    result = await self._apply_phase_step(self._core_phase, step,
                        episode_id=state["phase_checkpoint"]["episode_id"], tool_context=tool_context)
                elif state["stage"] == "phase_received":
                    error_type = state["phase_error"]
                    error = (TimeoutError() if error_type == "TimeoutError" else RecordedProviderError(error_type)) if error_type else None
                    result = await self._consume_phase(self._core_phase,
                        [ModelStreamEvent(**event) for event in state["phase_events"]], error, tool_context=tool_context, replay=True)
                else:
                    self._resume_assistant = state if state["stage"] == "assistant" else None
                    self._resume_repair = state if state["stage"] == "repair" else None
                    self._resume_input = state if state["stage"] == "input" else None
                    resume_text = state.get("text") if state["stage"] in {"initial", "input"} else None
                    append_user = state["stage"] == "input" or state["stage"] == "initial" and not state["continuation"]
                    if state["stage"] == "input" and state["queue_kind"]:
                        queue = self._steer_queue if state["queue_kind"] == "steer" else self._follow_up_queue
                        if state["text"] in queue:
                            queue.remove(state["text"])
                    if state["stage"] in {"provider", "ready"} and self._steer_queue:
                        resume_text, append_user = self._steer_queue.popleft(), True
                    result = await self._run_with_budget(
                        resume_text, append_user=append_user,
                        tool_context=tool_context)
                self._durable_response = result
                journal.finish(self)
                return result
            except LLMRequestBudgetExceeded as exc:
                # Received/applied phase receipts resume outside _run_with_budget.
                # Their next request uses the same admission and durable stop.
                result = self._persist_request_budget_stop(exc)
                self._durable_response = result
                journal.finish(self)
                return result
            except BaseException:
                if journal.record is not None:
                    journal.interrupted(self)
                raise
            finally:
                self._resume_assistant = None
                self._resume_repair = None
                self._resume_input = None
                self._end()

    async def abort(self) -> None:
        if self.phase == "idle":
            return
        self._abort_requested = True
        if self.turn_journal and self.turn_journal.record:
            self.turn_journal.cancel()
        if self._abort_event is not None:
            self._abort_event.set()
        if self._active_tool_task is not None and not self._active_tool_task.done():
            self._active_tool_task.cancel()

    async def steer(self, text: str) -> None:
        if self.phase == "idle":
            raise AgentCoreBusyError("steer requires an active agent run")
        if self.turn_journal:
            self.turn_journal.enqueue("steer", text)
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
        if self.turn_journal:
            self.turn_journal.enqueue("follow_up", text)
        self._follow_up_queue.append(text)
        self.events.emit(
            self.session_id,
            "queue_update",
            {"queue": "follow_up", "content": text},
            command_id=self._active_command_id,
        )

    def _begin(self, budget: AgentRunBudget, *, command_id: str | None = None) -> None:
        if self.phase != "idle":
            raise AgentCoreBusyError("agent is already running")
        # Dispatch already owns its command. tool_context is server-supplied,
        # unlike model arguments; share that identity with messages and events.
        if command_id is not None and (not isinstance(command_id, str) or not command_id.strip()):
            raise ValueError("command_id must be a non-empty string")
        self.repository.update_status(self.session_id, "running")
        self.phase = "running"
        self._abort_requested = False
        self._timeout_requested = False
        self._active_command_id = identity_value(owner="agent.core.command", slot="command_id",
            inputs={"session_id": self.session_id, "command_id": command_id},
            create=lambda: command_id if command_id is not None else uuid4().hex)
        self._budget = budget
        self._steps_used = 0
        self._slowest_request_s = 0.0
        self._turn_started_at = asyncio.get_running_loop().time()
        self._turn_excluded_at_start = turn_clock.excluded_s()
        self._standalone_phase = False
        self._phase_completed = False
        self._phase_result = None
        self._overflow_retried = False
        self._argument_corrected = False
        self._final_status = None
        self._last_tool_call_fingerprint = None
        self._consecutive_identical_tool_calls = 0
        self._answered_tool_calls = {}
        # Facts for the server-written closing message (see turn_messages).
        self._tools_used: list[str] = []
        self._last_tool_failure: str | None = None
        self._ready_proposal: Mapping[str, Any] | None = None
        self._numeric_repairs_left = numeric_grounding.MAX_REPAIRS

    def _end(self) -> None:
        if self.turn_end_observer is not None and self._active_command_id is not None:
            from ..extensions import ExtensionError
            try:
                self.turn_end_observer(self._active_command_id, self._final_status or "idle")
            except (ExtensionError, OSError):
                self.events.emit(self.session_id, "extension_hook_error", {"event": "turn_end"},
                                 command_id=self._active_command_id)
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
        self._core_phase = None
        self._phase_messages = []

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

    @staticmethod
    def _is_confirmation_ready(result: ToolResult) -> bool:
        """Whether a tool produced a durable, user-owned review boundary."""

        return (
            result.ok
            and isinstance(result.output, Mapping)
            and result.output.get("requires_confirmation") is True
        )

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
        if self._turn_budget_elapsed() >= self._budget.timeout_s:
            self._mark_timeout()
            return self._persist_terminal_error("agent_timeout")
        loop = asyncio.get_running_loop()
        handle = None
        try:
            async with asyncio.timeout(None) as scope:
                def check() -> None:
                    nonlocal handle
                    left = self._budget.timeout_s - self._turn_budget_elapsed()
                    if left <= 0:
                        self._mark_timeout()
                        scope.reschedule(loop.time())
                    else:
                        handle = loop.call_at(loop.time() + left, check)
                check()
                try:
                    return await self._run_commands(
                        text,
                        append_user=append_user,
                        tool_context=tool_context,
                    )
                finally:
                    if handle is not None:
                        handle.cancel()
        except TimeoutError:
            self._mark_timeout()
            return self._persist_terminal_error("agent_timeout")
        except LLMRequestBudgetExceeded as exc:
            return self._persist_request_budget_stop(exc)

    def _persist_request_budget_stop(self, error: LLMRequestBudgetExceeded) -> str:
        if error.details["remaining_s"] <= 0:
            self._mark_timeout()
            return self._persist_terminal_error("agent_timeout")
        return self._persist_terminal_error("provider_request_budget", request_budget=error.details)

    def _provider_request_wait_s(self, provider_timeout_s=None) -> float:
        wait_s = getattr(self.adapter, "request_wait_s", 0.0)
        return min(wait_s, provider_timeout_s) if provider_timeout_s is not None else wait_s

    def _check_provider_request_budget(self, wait_s: float) -> None:
        """Read the existing Core clock; equality is admitted without a hidden margin.

        The configured wait is the longest a provider may queue, not what a request takes: on a
        300 s wait it closed the second half of every 600 s turn. Once a request has completed in
        this turn, the slowest one is the requirement. In the recorded turn of 183, 103 and 105 s
        requests, the fourth (161 s) fits its 209 remaining seconds and the fifth does not. A turn
        with nothing observed, a resumed one included, keeps the configured wait.
        """
        if self._budget.timeout_s is None or not wait_s:
            return
        observed = getattr(self, "_slowest_request_s", 0.0)
        required = min(wait_s, observed) if observed > 0 else wait_s
        remaining = self._budget.timeout_s - self._turn_budget_elapsed()
        if remaining < required:
            raise LLMRequestBudgetExceeded(remaining_s=max(0.0, remaining), required_s=required,
                                           timeout_s=self._budget.timeout_s, configured_wait_s=wait_s)

    def _observe_completed_request(self, started_at: float | None) -> None:
        if started_at is not None:
            self._slowest_request_s = max(getattr(self, "_slowest_request_s", 0.0),
                                          self._turn_budget_elapsed() - started_at)

    def _turn_budget_elapsed(self) -> float:
        held = turn_clock.excluded_s() - getattr(self, "_turn_excluded_at_start", turn_clock.excluded_s())
        return asyncio.get_running_loop().time() - self._turn_started_at - held
