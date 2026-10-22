"""Core phases: entering, checkpointing and driving a phase's provider events and steps."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from ..phases import CorePhase
from ..step_observation import observe_provider
from .budget import AgentCoreBusyError, AgentRunBudget


class PhaseDriverMixin:
    """Part of AgentCore; see agent/core.py."""

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
