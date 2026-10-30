"""One model turn: request, stream, tool calls and the loop guard."""

from __future__ import annotations

from contextlib import aclosing
from typing import Any
from uuid import uuid4

from .. import numeric_grounding
from ..model import ModelRequest, ModelStreamEvent
from ..phases import PhaseStep
from ..turn_messages import detect_language, interrupted_reply_note, provider_failure_message


class TurnLoopMixin:
    """Part of AgentCore; see agent/core.py."""

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
        from ..research_review import requested as review_requested
        if append_user and active_phase is None and self.research_review_context is not None and review_requested(text):
            from ..research_review import requested_review
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
        if phase_request is None:
            from ..context import project_published_contracts

            context = project_published_contracts(context, self.tools)
            self._active_context_fingerprint = context.fingerprint
        self._steps_used += 1
        request = ModelRequest(
            request_id=uuid4().hex,
            messages=phase_request.messages if phase_request is not None else context.messages,
            tools=phase_request.tools if phase_request is not None else self.tools,
            response_schema=phase_request.response_schema if phase_request is not None else None,
            model_config=phase_request.model_config if phase_request is not None else {},
            abort_event=self._new_abort_event(),
            turn_key=command_id,
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
        output_started = False
        reasoning: ModelStreamEvent | None = None
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
                    if (not output_started and event.type in {"text_delta", "activity"}
                            and (event.type == "activity" or event.delta.strip())):
                        output_started = True
                        if self.completion_check is not None or event.type == "activity":
                            self.events.emit(self.session_id, "message_progress", {
                                "request_id": request.request_id, "stage": "receiving",
                                "validation_pending": self.completion_check is not None,
                            }, command_id=command_id)
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
                    elif event.type == "reasoning":
                        reasoning = event  # private: kept for the provider, never emitted
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

        if finish_reason == "length":
            # Usage was still received by the provider-event boundary, but a
            # truncated reply or tool request is not a successful turn.
            finish_reason, error = "error", "provider_output_limit"

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

        if (finish_reason == "error" and error == "provider_tool_arguments_invalid"
                and not self._argument_corrected and self._has_step_left()):
            # The provider ended a tool call with arguments that are not JSON, so
            # nothing ran. One bounded correction per command instead of failing the
            # turn (paid fix4 round, survival, Ask: a whole nudge turn was lost).
            self._argument_corrected = True
            self._active_request_id = None
            self._active_message_started = False
            self.repository.append(self.session_id, "custom_message", {
                "message_type": "tool_arguments_correction", "audience": "model", "model_role": "user",
                "name": "workbench_tool_arguments",
                "content": ("[Workbench -- an automatic message, not from the user] Your last tool call's "
                            "arguments were not valid JSON, so nothing ran. Send that call again with valid "
                            "JSON arguments, or continue without it."),
            })
            return await self._run_turn(None, append_user=False, tool_context=tool_context)

        content = "".join(chunks)
        if error == "provider_output_limit":
            note = provider_failure_message(detect_language(getattr(self, '_user_text', None)), error)
            content = f"{content}\n\n{note}" if content.strip() else note
        elif finish_reason == "error" and not content.strip() and not tool_calls and error != "tool_runtime_unavailable":
            # An empty failed turn reads as a hang; say what happened instead.
            content = provider_failure_message(detect_language(getattr(self, "_user_text", None)), str(error))
        elif finish_reason == "error" and content.strip() and error not in {"aborted", "tool_runtime_unavailable"}:
            content = f"{content}\n\n{interrupted_reply_note(detect_language(getattr(self, '_user_text', None)))}"
        completion_result = None
        completion_failure = None
        from ..completion import claims_completion, publication, enforce_request_scope
        if self.completion_check is not None and content.strip() and finish_reason == 'error':
            completion_result, notice, completion_failure = self._terminal_completion_notice()
            if completion_failure is not None:
                content += '\n\n' + notice
            else:
                content = publication(content, completion_result, detect_language(getattr(self, '_user_text', None)),
                                      final=True, request_text=getattr(self, '_user_text', ''))
        elif (self.completion_check is not None and content.strip()
                and ((finish_reason == "stop" and not tool_calls)
                     or claims_completion(content))):

            completion_result = enforce_request_scope(self.completion_check(), getattr(self, '_user_text', ''))
            content = publication(content, completion_result, detect_language(getattr(self, "_user_text", None)),
                                  final=(finish_reason == "stop" and not tool_calls) or finish_reason == "error",
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
        if completion_failure is not None:
            payload['completion_check_error'] = completion_failure
        if numeric_findings:
            payload["numeric_check"] = {"unverified": [finding.to_dict() for finding in numeric_findings]}
        elif numeric_check_failed:
            payload["numeric_check"] = {"error": "the numeric check could not run"}
        if tool_calls:
            payload["tool_calls"] = list(tool_calls.values())
        if reasoning is not None and reasoning.delta and finish_reason != "aborted":
            payload["reasoning_content"] = reasoning.delta
            payload["reasoning_source"] = dict(reasoning.reasoning_source or {})
        if error is not None:
            payload["error"] = error
        from ..research_review import needed as review_needed
        if review_needed(self, payload):
            payload["review_pending"] = True
        if self.turn_journal:
            entry = self.turn_journal.assistant(self, payload, request_id=request.request_id,
                                                context_fingerprint=context.fingerprint)
        else:
            entry = self.repository.append(self.session_id, "analysis_candidate" if payload.get("review_pending") else "message", payload)
        return await self._finish_assistant(payload, entry, request_id=request.request_id,
                                            context_fingerprint=context.fingerprint, tool_context=tool_context, completion_checked=True)
