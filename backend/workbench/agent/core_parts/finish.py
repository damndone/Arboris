"""Finishing a turn: proposals, completion re-checks, numeric repair and draft withdrawal."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .. import numeric_grounding
from ..turn_messages import detect_language, matches_language, proposal_summary


class FinishMixin:
    """Part of AgentCore; see agent/core.py."""

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

    def _recheck_completion(self, payload, entry):
        """An interrupted publication must not reuse an obsolete evidence check."""
        if self.completion_check is None:
            return payload, entry
        from ..completion import publication, partial_notice

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
        from ..recovery import prepare_completion_recovery, continue_completion_recovery
        if prepare_completion_recovery(self, payload, entry):
            return await continue_completion_recovery(self, payload, entry, request_id=request_id,
                context_fingerprint=context_fingerprint, tool_context=tool_context)
        if payload.get("review_pending"):
            from ..research_review import start_review
            return await start_review(self, payload, entry, request_id=request_id,
                context_fingerprint=context_fingerprint, tool_context=tool_context)
        if payload.get("review_revision"):
            from ..research_review import continue_after_review
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
                from ..tool_batches import can_parallelize, run_reads, run_single
                confirmation_ready = False
                recovery_stopped = False
                prepared = None
                calls = list(tool_calls.values())
                if can_parallelize(self, calls):
                    task = asyncio.create_task(run_reads(self, calls, tool_context=tool_context))
                    self._active_tool_task = task
                    try:
                        prepared = await task
                    finally:
                        if self._active_tool_task is task:
                            self._active_tool_task = None
                for tool_call in calls:
                    tool_id = str(tool_call.get("tool_id", ""))
                    result, recovery = (prepared[tool_call["tool_call_id"]] if prepared is not None else
                        await run_single(self, tool_call, tool_context=tool_context, skip=recovery_stopped))
                    recovery_stopped = recovery_stopped or bool(recovery and recovery["exhausted"])
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
