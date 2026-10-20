"""Generic provider-neutral agent loop for Workbench."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import aclosing, nullcontext
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import math
from numbers import Real
from typing import Any
from uuid import uuid4

from .compaction import CompactionPolicy, compact as compact_session, estimate_messages_tokens, estimate_text_tokens
from .context import ContextBuilder
from .events import AgentEventStream
from . import numeric_grounding
from .model import ModelAdapter, ModelRequest, ModelStreamEvent
from .phases import CorePhase, PhaseStep, RecordedProviderError
from .session import JsonlSessionRepository
from .step_observation import observe_provider
from .business_identity import identity_value
from .tools import ToolResult, ToolRuntime
from .turn_messages import (
    budget_exhausted_message,
    detect_language,
    interrupted_reply_note,
    matches_language,
    proposal_summary,
    provider_failure_message,
)


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
    # The first repeat is answered with "already answered, stop inspecting"; at 2
    # the loop guard fired on that same call, so the model never saw it.
    max_consecutive_identical_tool_calls: int = 3

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
            "max_consecutive_identical_tool_calls", 3
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
        self._core_phase: CorePhase | None = None
        self._phase_messages: list[dict[str, Any]] = []
        self._phase_result: Any = None
        self._phase_completed = False
        self._standalone_phase = False
        self.phase_restorer = None
        self.turn_journal = turn_journal
        self.completion_check = None
        self.research_review_context = None
        self.research_review_mode = lambda: "ask"

    def enter_phase(self, phase: CorePhase) -> None:
        """Schedule a deterministic phase on this running Core's next step.

        This control boundary performs no provider call and grants no operation
        authority. Product tool registration must still admit its source scope.
        """
        if self.phase != "running" or self._core_phase is not None:
            raise AgentCoreBusyError("phase entry requires a running Core without an active phase")
        self._core_phase = phase
        self._phase_messages = []
        self._phase_completed = False

    async def run_phase(self, phase: CorePhase, *, budget=None):
        """Standalone compatibility entry; reuse the existing turn driver."""
        self._begin(AgentRunBudget.from_value(budget))
        self._standalone_phase = True
        try:
            self.enter_phase(phase)
            await self._run_with_budget(None, append_user=False)
            if not self._phase_completed:
                raise phase.failure("timeout" if self._timeout_requested else "budget")
            return self._phase_result
        except BaseException:
            self._final_status = "cancelled" if self._abort_requested else "failed"
            raise
        finally:
            self._core_phase = None
            self._end()

    def _provider_events(self, request, *, timeout_s=None):
        """Core owns the provider call; observations own no command or budget."""
        return observe_provider(
            lambda: self.adapter.stream(request), request=request, events=self.events,
            session_id=self.session_id, command_id=self._active_command_id, provider_step=self._steps_used,
            phase_episode_id=self._core_phase.episode_id if self._core_phase is not None else None,
            model=self.model_name, timeout_s=timeout_s,
        )

    def _phase_checkpoint(self, phase, status):
        writer = self.repository.append_once if self.turn_journal else self.repository.append
        stage = f"phase:{phase.episode_id}:{self._steps_used}:{status}"
        if self.turn_journal:
            original = next((entry for entry in self.repository.get_branch(self.session_id)
                if entry.idempotency and entry.idempotency["key"] == self._active_command_id
                and entry.idempotency["stage"] == stage), None)
            if original is not None:
                return writer(self.session_id, "phase_state", original.payload,
                    key=self._active_command_id, stage=stage)
        writer(self.session_id, "phase_state", {
            "episode_id": phase.episode_id, "status": status,
            "command_id": self._active_command_id, "steps_used": self._steps_used,
            "wall_used_s": asyncio.get_running_loop().time() - self._turn_started_at,
            "phase": phase.checkpoint(),
        }, **({"key":self._active_command_id, "stage":stage}
              if self.turn_journal else {}))

    async def _consume_phase(self, phase, events, error, *, tool_context, replay=False):
        if not replay:
            self.repository.append(self.session_id, "phase_provider_result", {
                "episode_id": phase.episode_id, "events": [asdict(event) for event in events],
                "error": type(error).__name__ if error is not None else None,
            })
            if self.turn_journal:
                self.turn_journal.save(self, "phase_received", phase_events=[asdict(event) for event in events],
                    phase_error=type(error).__name__ if error else None)
        if self._abort_requested:
            self._phase_checkpoint(phase, "interrupted")
            return self._persist_terminal_error("agent_timeout" if self._timeout_requested else "agent_aborted")
        if self.turn_journal:
            self.turn_journal.save(self, "phase_consuming")
        task = asyncio.create_task(phase.consume(events, error=error))
        self._active_tool_task = task
        try:
            step = await task
        except asyncio.CancelledError:
            self._phase_checkpoint(phase, "interrupted")
            if self._abort_requested:
                return self._persist_terminal_error("agent_timeout" if self._timeout_requested else "agent_aborted")
            raise
        except Exception:
            self._final_status = "failed"
            self._phase_checkpoint(phase, "failed")
            raise
        finally:
            if self._active_tool_task is task:
                self._active_tool_task = None
        if step.next not in {"continue", "completed", "refused"}:
            raise ValueError("phase returned an invalid transition")
        if self.turn_journal:
            self.turn_journal.save(self, "phase_applied", phase_step={
                "next":step.next, "append_messages":list(step.append_messages),
                "public_result":dict(step.public_result)})
        return await self._apply_phase_step(phase, step, episode_id=phase.episode_id, tool_context=tool_context)

    async def _apply_phase_step(self, phase, step, *, episode_id, tool_context):
        for index, message in enumerate(step.append_messages):
            self._phase_messages.append(dict(message))
            writer = self.repository.append_once if self.turn_journal else self.repository.append
            writer(self.session_id, "phase_message", {
                "episode_id": episode_id, "message": message,
            }, **({"key":self._active_command_id, "stage":f"phase_message:{episode_id}:{self._steps_used}:{index}"}
                  if self.turn_journal else {}))
        self._active_request_id = None
        self._active_message_started = False
        if phase is not None:
            self._phase_checkpoint(phase, step.next)
        if step.next == "continue":
            return await self._run_turn(None, append_user=False, tool_context=tool_context)
        self._phase_result = step.result
        self._phase_completed = True
        self._core_phase = None
        if self._standalone_phase:
            return ""
        if step.public_result.get("requires_confirmation") is True:
            self._ready_proposal = step.public_result["proposal"]
            return self._finish_proposal_ready("", self._active_command_id)
        terminal = step.public_result.get("terminal_assistant")
        if terminal is not None:
            if len(json.dumps(dict(step.public_result), ensure_ascii=False)) > 64_000:
                raise ValueError("phase_terminal_result_exceeds_64000_characters")
            for audit in step.public_result.get("audit_events", []):
                self.repository.append_once(self.session_id, audit["entry_type"], audit["payload"],
                    key=audit["key"], stage=audit["stage"])
            publication = step.public_result["publication"]
            entry = self.repository.append_once(self.session_id, "message", dict(terminal),
                key=publication["key"], stage=publication["stage"])
            return await self._finish_assistant(dict(terminal), entry,
                request_id=step.public_result["request_id"],
                context_fingerprint=step.public_result["context_fingerprint"], tool_context=tool_context)
        result_text = json.dumps(dict(step.public_result), ensure_ascii=False, sort_keys=True)
        if len(result_text) > 24_000:
            raise ValueError("phase_public_result_exceeds_24000_characters")
        writer = self.repository.append_once if self.turn_journal else self.repository.append
        writer(self.session_id, "custom_message", {
            "audience": "model", "model_role": "user", "name": "workbench_phase_result",
            "content": result_text,
        }, **({"key":self._active_command_id, "stage":f"phase_result:{episode_id}"}
              if self.turn_journal else {}))
        return await self._run_turn(None, append_user=False, tool_context=tool_context)

    def _finish_proposal_ready(self, content: str, command_id: str | None) -> str:
        # A proposal is already persisted, reviewable, and gated by
        # explicit user confirmation. Requiring a further provider
        # completion turn can only waste budget and turn a usable
        # proposal into a misleading max-steps failure.
        # The model's pre-tool narration is often in another
        # language than the question; the reply the user reads is
        # written from the persisted proposal instead.
        language = detect_language(getattr(self, "_user_text", None))
        summary = (
            proposal_summary(self._ready_proposal, language)
            if self._ready_proposal is not None
            else ""
        )
        if summary or not content:
            narration = content if matches_language(content, language) else ""
            if narration and numeric_grounding.check(
                narration, self.context_builder.build(self.session_id).messages
            ):
                # The proposal summary is written from the proposal
                # itself; narration with an unsupported number is dropped.
                narration = ""
            content = "\n\n".join(
                part for part in (narration, summary) if part
            ) or "proposal is ready for confirmation"
            summary_writer = self.repository.append_once if self.turn_journal else self.repository.append
            summary_entry = summary_writer(
                self.session_id,
                "message",
                {
                    "role": "assistant",
                    "content": content,
                    "stop_reason": "proposal_ready",
                    "command_id": command_id,
                },
                **({"key": command_id, "stage": f"proposal_summary:{self._steps_used}"}
                   if self.turn_journal else {}),
            )
            self.events.emit(
                self.session_id,
                "message_end",
                {
                    "entry_id": summary_entry.entry_id,
                    "content": content,
                    "stop_reason": "proposal_ready",
                    "error": None,
                },
                command_id=command_id,
            )
        self.events.emit(
            self.session_id,
            "agent_end",
            {"stop_reason": "proposal_ready"},
            command_id=command_id,
        )
        self._active_turn_started = False
        return content

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
        return await self._command(text, budget=budget, tool_context=tool_context, continuation=False)

    async def continue_(
        self,
        *,
        budget: AgentRunBudget | Mapping[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> str:
        return await self._command(None, budget=budget, tool_context=tool_context, continuation=True)

    async def _command(self, text, *, budget, tool_context, continuation):
        journal = self.turn_journal
        with journal.ownership() if journal else nullcontext():
            self._begin(AgentRunBudget.from_value(budget), command_id=(tool_context or {}).get("command_id"))
            self._user_text = text
            started = False
            try:
                if continuation:
                    self._assert_continuable()
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
        self._turn_started_at = asyncio.get_running_loop().time()
        self._standalone_phase = False
        self._phase_completed = False
        self._phase_result = None
        self._overflow_retried = False
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
        remaining = max(0, self._budget.timeout_s - (asyncio.get_running_loop().time() - self._turn_started_at))
        if remaining <= 0:
            self._mark_timeout()
            return self._persist_terminal_error("agent_timeout")
        timeout_handle = asyncio.get_running_loop().call_later(
            remaining,
            self._mark_timeout,
        )
        try:
            return await asyncio.wait_for(
                self._run_commands(
                    text,
                    append_user=append_user,
                    tool_context=tool_context,
                ),
                timeout=remaining,
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
        repair = getattr(self, "_resume_repair", None)
        if repair is not None:
            self._resume_repair = None
            return await self._finish_numeric_repair(repair["repair"],
                command_id=self._active_command_id, tool_context=tool_context)
        recovery = getattr(self, "_resume_assistant", None)
        if recovery is not None:
            self._resume_assistant = None
            entry = self.turn_journal.assistant_message(recovery["assistant"], self._steps_used)
            return await self._finish_assistant(recovery["assistant"], entry,
                request_id=recovery["request_id"], context_fingerprint=recovery["context_fingerprint"],
                tool_context=tool_context)
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
            if self.turn_journal:
                self.turn_journal.append_user(self, text)
            else:
                self.repository.append(
                    self.session_id, "message",
                    {"role": "user", "content": text, "command_id": command_id},
                )

        active_phase = self._core_phase
        context = self.context_builder.build(self.session_id)
        from .research_review import requested as review_requested
        if append_user and active_phase is None and self.research_review_context is not None and review_requested(text):
            from .research_review import requested_review
            return await requested_review(self, context=context, command_id=command_id, tool_context=tool_context)
        if self.compaction_policy is not None and active_phase is None:
            tokens = self.context_tokens(context.messages)
            if self.compaction_policy.should_compact(tokens):
                if await self.compact("auto", tokens_before=tokens, command_id=command_id) is not None:
                    context = self.context_builder.build(self.session_id)
        self._active_context_fingerprint = context.fingerprint

        try:
            phase_request = active_phase.request(self._phase_messages) if active_phase is not None else None
        except Exception:
            self._final_status = "failed"
            self._phase_checkpoint(active_phase, "failed")
            raise
        if isinstance(phase_request, PhaseStep):
            if self.turn_journal:
                self.turn_journal.save(self, "phase_applied", phase_step={
                    "next":phase_request.next, "append_messages":list(phase_request.append_messages),
                    "public_result":dict(phase_request.public_result)})
            return await self._apply_phase_step(active_phase, phase_request,
                episode_id=active_phase.episode_id, tool_context=tool_context)
        if (
            self._budget.max_steps is not None
            and self._steps_used >= self._budget.max_steps
        ):
            if active_phase is not None:
                self._final_status = "failed"
                self._phase_checkpoint(active_phase, "failed")
                raise active_phase.failure("budget")
            return self._persist_terminal_error("max_steps_exceeded")
        if phase_request is not None and not self._phase_messages:
            self._phase_messages = [dict(message) for message in phase_request.messages]
            for message in self._phase_messages:
                self.repository.append(self.session_id, "phase_message", {
                    "episode_id": active_phase.episode_id, "message": message,
                })
        self._steps_used += 1
        request = ModelRequest(
            request_id=uuid4().hex,
            messages=phase_request.messages if phase_request is not None else context.messages,
            tools=phase_request.tools if phase_request is not None else self.tools,
            response_schema=phase_request.response_schema if phase_request is not None else None,
            model_config=phase_request.model_config if phase_request is not None else {},
            abort_event=self._new_abort_event(),
        )
        self._active_request_id = request.request_id
        if self.turn_journal:
            self.turn_journal.save(self, "provider")
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
        phase_events = []
        phase_error = None
        if active_phase is not None:
            self._phase_checkpoint(active_phase, "running")
        try:
            async with aclosing(self._provider_events(
                request, timeout_s=phase_request.provider_timeout_s if phase_request is not None else None
            )) as stream:
                async for event in stream:
                    if active_phase is not None:
                        phase_events.append(event)
                    if self._abort_requested:
                        finish_reason = "aborted"
                        break
                    if event.type == "text_delta":
                        chunks.append(event.delta)
                        if self.completion_check is None:
                            self.events.emit(
                                self.session_id, "message_update",
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
                        if active_phase is None:
                            break
                    elif event.type == "retry":
                        # Recorded so a flaky provider is visible, not only survived.
                        self.events.emit(
                            self.session_id,
                            "provider_retry",
                            {"request_id": request.request_id, "error": event.error},
                            command_id=command_id,
                        )
                    elif event.type == "error":
                        finish_reason = "error"
                        error = event.error or "provider_error"
                        break
        except Exception as exc:  # Provider errors become durable turn state.
            finish_reason = "error"
            error = type(exc).__name__
            phase_error = exc

        if active_phase is not None:
            return await self._consume_phase(active_phase, phase_events, phase_error, tool_context=tool_context)

        if finish_reason == "tool_calls" and tool_calls and self.tool_runtime is None:
            finish_reason = "error"
            error = "tool_runtime_unavailable"

        if (
            finish_reason == "error"
            and error is not None
            and "context_overflow" in error
            and not chunks
            and not tool_calls
            and self.compaction_policy is not None
            and not self._overflow_retried
        ):
            # The provider refused the request as too long: compact once and
            # resend (pi's overflow recovery). Nothing was said yet.
            self._overflow_retried = True
            self._active_request_id = None
            self._active_message_started = False
            tokens = self.context_tokens(context.messages)
            if await self.compact("overflow", tokens_before=tokens, command_id=command_id) is not None:
                return await self._run_turn(None, append_user=False, tool_context=tool_context)

        content = "".join(chunks)
        if finish_reason == "error" and not content.strip() and not tool_calls and error != "tool_runtime_unavailable":
            # An empty failed turn reads as a hang; say what happened instead.
            content = provider_failure_message(detect_language(getattr(self, "_user_text", None)), str(error))
        elif finish_reason == "error" and content.strip() and error not in {"aborted", "tool_runtime_unavailable"}:
            content = f"{content}\n\n{interrupted_reply_note(detect_language(getattr(self, '_user_text', None)))}"
        completion_result = None
        from .completion import claims_completion, publication
        if (self.completion_check is not None and content.strip()
                and ((finish_reason == "stop" and not tool_calls) or claims_completion(content))):

            completion_result = self.completion_check()
            content = publication(content, completion_result, detect_language(getattr(self, "_user_text", None)),
                                  final=finish_reason == "stop" and not tool_calls,
                                  request_text=getattr(self, "_user_text", ""))
        numeric_findings: tuple[numeric_grounding.Finding, ...] = ()
        numeric_check_failed = False
        if finish_reason == "stop" and not tool_calls and content.strip():
            try:
                numeric_findings = numeric_grounding.check(content, context.messages)
            except Exception:  # A broken check must not pass numbers as checked.
                numeric_check_failed = True
                language = detect_language(getattr(self, "_user_text", None))
                content = f"{content}\n\n{numeric_grounding.unchecked_note(language)}"
            if numeric_findings and self._numeric_repairs_left > 0 and self._has_step_left():
                return await self._withdraw_draft(
                    content, numeric_findings, command_id=command_id, context=context, tool_context=tool_context
                )
            if numeric_findings:
                language = detect_language(getattr(self, "_user_text", None))
                content = f"{content}\n\n{numeric_grounding.unverified_note(numeric_findings, language)}"
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "stop_reason": finish_reason,
            "command_id": command_id,
        }
        if completion_result is not None:
            payload["completion_check"] = completion_result
        if numeric_findings:
            payload["numeric_check"] = {"unverified": [finding.to_dict() for finding in numeric_findings]}
        elif numeric_check_failed:
            payload["numeric_check"] = {"error": "the numeric check could not run"}
        if tool_calls:
            payload["tool_calls"] = list(tool_calls.values())
        if error is not None:
            payload["error"] = error
        from .research_review import needed as review_needed
        if review_needed(self, payload):
            payload["review_pending"] = True
        if self.turn_journal:
            entry = self.turn_journal.assistant(self, payload, request_id=request.request_id,
                                                context_fingerprint=context.fingerprint)
        else:
            entry = self.repository.append(self.session_id, "analysis_candidate" if payload.get("review_pending") else "message", payload)
        return await self._finish_assistant(payload, entry, request_id=request.request_id,
                                            context_fingerprint=context.fingerprint, tool_context=tool_context, completion_checked=True)

    def _recheck_completion(self, payload, entry):
        """An interrupted publication must not reuse an obsolete evidence check."""
        if self.completion_check is None:
            return payload, entry
        from .completion import publication, partial_notice

        result = self.completion_check()
        if result == payload.get("completion_check"):
            return payload, entry
        language = detect_language(getattr(self, "_user_text", None))
        previous = payload.get("completion_check")
        if previous and previous["status"] == "partial":
            if result["status"] == "partial":
                content = partial_notice(result, language)
            elif language == "zh":
                content = "交付证据现已核验齐全。方法适用性、推断有效性和报告结论仍需分别审查。"
            else:
                content = ("Required delivery evidence is now verified. Method suitability, inference validity "
                           "and report conclusions still require separate review.")
        else:
            content = publication(payload["content"], result, language,
                                  request_text=getattr(self, "_user_text", ""))
        reviewed = {**payload, "content": content, "completion_check": result}
        if reviewed != payload:
            digest = hashlib.sha256(json.dumps(reviewed, sort_keys=True).encode()).hexdigest()
            entry = self.repository.append_once(self.session_id, "analysis_candidate" if reviewed.get("review_pending") else "message", reviewed,
                key=self._active_command_id, stage="completion_recheck:" + digest)
        return reviewed, entry

    async def _finish_assistant(self, payload, entry, *, request_id, context_fingerprint, tool_context,
                                completion_checked=False):
        command_id = self._active_command_id
        if not completion_checked and payload["stop_reason"] == "stop" and not payload.get("tool_calls"):
            payload, entry = self._recheck_completion(payload, entry)
        if payload.get("review_pending"):
            from .research_review import start_review
            return await start_review(self, payload, entry, request_id=request_id,
                context_fingerprint=context_fingerprint, tool_context=tool_context)
        if payload.get("review_revision"):
            from .research_review import continue_after_review
            return await continue_after_review(self, payload, entry, command_id=command_id,
                context_fingerprint=context_fingerprint, tool_context=tool_context)
        content, finish_reason = payload["content"], payload["stop_reason"]
        error = payload.get("error")
        tool_calls = {str(call.get("tool_call_id", "")): call for call in payload.get("tool_calls", [])}
        if finish_reason == "aborted":
            self.events.emit(
                self.session_id,
                "aborted",
                {"request_id": request_id},
                command_id=command_id,
            )
        elif finish_reason == "error":
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
                confirmation_ready = False
                recovery_stopped = False
                for tool_call in tool_calls.values():
                    tool_call_id = str(tool_call.get("tool_call_id", ""))
                    tool_id = str(tool_call.get("tool_id", ""))
                    self.events.emit(
                        self.session_id,
                        "tool_execution_start",
                        {"tool_call_id": tool_call_id, "tool_id": tool_id},
                        command_id=command_id,
                    )
                    recovered = self.turn_journal.original_receipt(self, tool_call) if self.turn_journal else None
                    if recovered is not None:
                        payload = recovered
                        result = ToolResult(tool_call_id=tool_call_id, tool_id=tool_id,
                            ok=payload["ok"], output=payload.get("output"), error=payload.get("error"),
                            error_details=payload.get("error_details"))
                        if result.ok:
                            self._answered_tool_calls[self._tool_call_fingerprint(tool_call)] = result.tool_id
                    elif recovery_stopped:
                        result = ToolResult(tool_call_id=tool_call_id, tool_id=tool_id, ok=False,
                            error="analysis_recovery_limit", output={"executed": False})
                        payload = result.to_payload()
                    else:
                        if self.turn_journal:
                            self.turn_journal.before_tool(self, tool_call)
                        tool_task = asyncio.create_task(
                            self.tool_runtime.execute(
                                tool_call,
                                session_id=self.session_id,
                                metadata={
                                    **(tool_context or {}),
                                    "command_id": command_id,
                                    "provider_step": self._steps_used,
                                    "tool_call_id": tool_call_id,
                                    "invocation_id": "invocation_" + hashlib.sha256(
                                        json.dumps([
                                            "workbench.agent.invocation.v1", self.session_id,
                                            command_id, self._steps_used, tool_call_id,
                                        ], separators=(",", ":")).encode("utf-8")
                                    ).hexdigest(),
                                },
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
                    from .recovery import record_failure
                    recovery = (payload.get("bounded_recovery") if recovered is not None else None)
                    if recovery is None:
                        recovery = record_failure(self.repository, self.session_id, command_id,
                            self._steps_used, tool_call, payload)
                    if recovery is not None:
                        if recovered is None:
                            payload = {**payload, "bounded_recovery": recovery}
                        self._last_tool_failure = recovery["reason"]
                        recovery_stopped = recovery_stopped or recovery["exhausted"]
                    if self.turn_journal:
                        result_entry = self.turn_journal.result_message(self, tool_call, payload)
                    else:
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
                    self._tools_used.append(result.tool_id)
                    if not result.ok:
                        details = result.error_details or []
                        first = details[0] if details and isinstance(details[0], Mapping) else {}
                        self._last_tool_failure = str(first.get("message") or result.error or "")[:300]
                    if self._is_confirmation_ready(result):
                        proposal = result.output.get("proposal")
                        if isinstance(proposal, Mapping):
                            self._ready_proposal = proposal
                    confirmation_ready = confirmation_ready or self._is_confirmation_ready(result)
                if recovery_stopped:
                    return self._persist_terminal_error("analysis_recovery_limit")
                self.events.emit(
                    self.session_id,
                    "turn_end",
                    {
                        "stop_reason": (
                            "proposal_ready" if confirmation_ready else "tool_calls"
                        )
                    },
                    command_id=command_id,
                )
                self.events.emit(
                    self.session_id,
                    "save_point",
                    {"entry_id": entry.entry_id, "context_fingerprint": context_fingerprint},
                    command_id=command_id,
                )
                if confirmation_ready:
                    return self._finish_proposal_ready(content, command_id)
                self._active_turn_started = False
                if self._steer_queue:
                    # The person steered while tools ran: their words go in now,
                    # at this tool boundary, before the next model call (v1.9.1).
                    steer_text = self._steer_queue.popleft()
                    self.events.emit(
                        self.session_id,
                        "queue_update",
                        {"queue": "steer", "applied": True, "content": steer_text},
                        command_id=command_id,
                    )
                    return await self._run_turn(steer_text, append_user=True, tool_context=tool_context)
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
            {"entry_id": entry.entry_id, "context_fingerprint": context_fingerprint},
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

    def context_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimated size of a request: its messages and the tool descriptions."""

        tools = estimate_text_tokens(json.dumps(self.tools, ensure_ascii=False)) if self.tools else 0
        return estimate_messages_tokens(messages) + tools

    async def compact(
        self,
        trigger: str,
        *,
        tokens_before: int,
        command_id: str | None = None,
        focus: str | None = None,
    ) -> Any:
        """Summarize the older conversation; on failure the turn goes on uncompacted."""

        if self.compaction_policy is None:
            return None
        self.events.emit(
            self.session_id,
            "compaction_start",
            {"trigger": trigger, "tokens_before": tokens_before, **self.compaction_policy.to_dict()},
            command_id=command_id,
        )
        try:
            entry = await compact_session(
                self.repository,
                self.session_id,
                self.adapter,
                self.compaction_policy,
                trigger=trigger,
                tokens_before=tokens_before,
                focus=focus,
                model=self.model_name,
            )
        except Exception as exc:  # A failed summary must not lose the turn.
            self.events.emit(
                self.session_id,
                "compaction_end",
                {"trigger": trigger, "compacted": False, "error": str(exc) or type(exc).__name__},
                command_id=command_id,
            )
            return None
        tokens_after = self.context_tokens(self.context_builder.build(self.session_id).messages) if entry else tokens_before
        self.events.emit(
            self.session_id,
            "compaction_end",
            {
                "trigger": trigger,
                "compacted": entry is not None,
                "entry_id": entry.entry_id if entry else None,
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "verified": entry.payload.get("verified") if entry else None,
            },
            command_id=command_id,
        )
        return entry

    def _has_step_left(self) -> bool:
        return self._budget.max_steps is None or self._steps_used < self._budget.max_steps

    async def _withdraw_draft(
        self,
        content: str,
        findings: tuple[numeric_grounding.Finding, ...],
        *,
        command_id: str,
        context: Any,
        tool_context: dict[str, Any] | None,
    ) -> str:
        """Keep a reply whose numbers match no result from reaching the user as
        an answer: record it as a withdrawn draft, tell the model which numbers
        failed and their closest real values, and ask for the answer again."""

        self._numeric_repairs_left -= 1
        repair = {"content": content, "unverified": [finding.to_dict() for finding in findings],
                  "correction": numeric_grounding.correction_message(findings),
                  "context_fingerprint": context.fingerprint}
        if self.turn_journal:
            self.turn_journal.save(self, "repair", repair=repair)
        return await self._finish_numeric_repair(repair, command_id=command_id, tool_context=tool_context)

    async def _finish_numeric_repair(self, repair, *, command_id, tool_context):
        content, unverified = repair["content"], repair["unverified"]
        writer = self.repository.append_once if self.turn_journal else self.repository.append
        entry = writer(
            self.session_id,
            "message",
            {
                "role": "assistant",
                "content": content,
                "stop_reason": "revised",
                "command_id": command_id,
                "numeric_check": {"unverified": unverified},
            },
            **({"key": command_id, "stage": f"withdrawn:{self._steps_used}"} if self.turn_journal else {}),
        )
        self.events.emit(
            self.session_id,
            "message_end",
            {"entry_id": entry.entry_id, "content": content, "stop_reason": "revised", "error": None},
            command_id=command_id,
        )
        writer(
            self.session_id,
            "custom_message",
            {
                "message_type": "numeric_check",
                "audience": "model",
                "model_role": "user",
                "name": numeric_grounding.CHECK_MESSAGE_NAME,
                "content": repair["correction"],
                "metadata": {"unverified": unverified},
            },
            **({"key": command_id, "stage": f"numeric_correction:{self._steps_used}"} if self.turn_journal else {}),
        )
        self.events.emit(
            self.session_id,
            "numeric_check",
            {"entry_id": entry.entry_id, "unverified": unverified},
            command_id=command_id,
        )
        self.events.emit(self.session_id, "turn_end", {"stop_reason": "revised"}, command_id=command_id)
        self.events.emit(
            self.session_id,
            "save_point",
            {"entry_id": entry.entry_id, "context_fingerprint": repair["context_fingerprint"]},
            command_id=command_id,
        )
        self._active_request_id = None
        self._active_message_started = False
        self._active_turn_started = False
        if self.turn_journal:
            self.turn_journal.save(self, "ready")
        return await self._run_turn(None, append_user=False, tool_context=tool_context)

    def _persist_terminal_error(self, error: str) -> str:
        """Persist a budget stop as a complete, replayable assistant turn."""

        if error in {"max_steps_exceeded", "repeated_tool_call_limit", "analysis_recovery_limit"}:
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

        # Budget stops and timeouts owe the user a visible explanation.
        content = (
            budget_exhausted_message(
                detect_language(getattr(self, "_user_text", None)),
                error,
                getattr(self, "_tools_used", []),
                getattr(self, "_last_tool_failure", None),
            )
            if error in {"max_steps_exceeded", "repeated_tool_call_limit", "analysis_recovery_limit"}
            else provider_failure_message(detect_language(getattr(self, "_user_text", None)), error)
            if error == "agent_timeout"
            else ""
        )
        writer = self.repository.append_once if self.turn_journal else self.repository.append
        entry = writer(
            self.session_id,
            "message",
            {
                "role": "assistant",
                "content": content,
                "stop_reason": "error",
                "error": error,
                **({"command_id": command_id} if self.turn_journal else {}),
            },
            **({"key": command_id, "stage": "terminal_error"} if self.turn_journal else {}),
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
                "content": content,
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
        return content

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
