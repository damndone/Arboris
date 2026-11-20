"""Context size, compaction, terminal errors, timeouts and the abort event."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from ..compaction import (
    compact as compact_session,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from ..turn_messages import budget_exhausted_message, detect_language, provider_failure_message
from ..model import LLMRequestBudgetExceeded


class LifecycleMixin:
    """Part of AgentCore; see agent/core.py."""

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
                check_request_budget=lambda: self._check_provider_request_budget(self._provider_request_wait_s()),
            )
        except LLMRequestBudgetExceeded:
            raise
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

    def _terminal_completion_notice(self):
        """Enrich an already failed turn without losing its original failure."""
        from ..completion import enforce_request_scope, partial_notice
        language = detect_language(getattr(self, '_user_text', None))
        try:
            result = enforce_request_scope(self.completion_check(), getattr(self, '_user_text', ''))
            notice = (partial_notice(result, language) if result['status'] == 'partial'
                      and result['missing'] != ['completion_contract:select_playbooks_and_source'] else '')
            return result, notice, None
        except Exception as exc:
            logging.getLogger(__name__).exception('Completion verification failed while recording an existing turn failure')
            failure = {'type': type(exc).__name__, 'message': str(exc)[:240]}
            notice = (f"完成核验未能运行（{failure['type']}），不能确认分析已完成。原始终止原因和已有操作仍保留；"
                      '请检查核验记录后从已有结果继续。' if language == 'zh' else
                      f"Completion verification could not run ({failure['type']}); analysis completion is unverified. "
                      'The original failure and earlier operations are retained. Inspect the verification records '
                      'before continuing from existing results.')
            return None, notice, failure

    def _persist_terminal_error(self, error: str, *, request_budget=None) -> str:
        """Persist a budget stop as a complete, replayable assistant turn."""

        if error in {"max_steps_exceeded", "repeated_tool_call_limit", "analysis_recovery_limit", "provider_request_budget"}:
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
        if error == "provider_request_budget":
            if detect_language(getattr(self, "_user_text", None)) == "zh":
                content = ("已保存当前结果。本轮剩余时间不足以覆盖下一请求预计需要的时间，下一请求未发送。"
                           "分析尚未完成；可从现有结果继续，原有审批和预算限制仍适用。")
            else:
                content = ("Current results are saved. The next request was not sent because this turn's remaining "
                           "time is shorter than a request is expected to need. The analysis is unfinished; you can "
                           "continue from the saved results with the existing approvals and budget limits.")
            if request_budget["required_s"] >= request_budget["timeout_s"]:
                content += (" 配置的等待额度无法装入当前整轮预算，继续前需调整现有配置。"
                            if detect_language(getattr(self, "_user_text", None)) == "zh" else
                            " The configured wait cannot fit this entire turn budget; adjust the existing configuration before continuing.")
        completion_result = None
        completion_failure = None
        if self.completion_check is not None and content:
            completion_result, notice, completion_failure = self._terminal_completion_notice()
            if notice:
                content += '\n\n' + notice
        writer = self.repository.append_once if self.turn_journal else self.repository.append
        entry = writer(
            self.session_id,
            "message",
            {
                "role": "assistant",
                "content": content,
                "stop_reason": "error",
                "error": error,
                **({"request_budget": request_budget} if request_budget is not None else {}),
                **({"completion_check": completion_result} if completion_result is not None else {}),
                **({"completion_check_error": completion_failure} if completion_failure is not None else {}),
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
            {"request_id": request_id, "error": error,
             **({"request_budget": request_budget} if request_budget is not None else {})},
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
