"""Stream-first model contracts for the generic agent core."""

from __future__ import annotations

import json
import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from workbench.llm.client import (
    LLMToolCallArgumentsError,
    LLMUpstreamError,
    async_stream_chat_completion,
    deepseek_v4_request_config,
)
from workbench.llm.config import LLMConfig


_TRANSIENT_UPSTREAM_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _to_openai_wire_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert internal session messages to the OpenAI chat wire format.

    The session tree stores tool calls in the provider-neutral shape
    `{tool_call_id, tool_id, arguments(dict)}` and tool results with an extra
    `name` field. OpenAI-compatible providers require
    `{id, type, function: {name, arguments(json-string)}}` on the assistant
    message and a bare `{role, tool_call_id, content}` tool message — sending
    the internal shape kills the post-tool turn with an upstream 4xx (found in
    the v1.7 live DeepSeek smoke; the deterministic suite uses fake adapters
    and never crossed this boundary). Proposal/confirmation audit messages can
    be appended while a tool is executing; they are deferred until the
    assistant's contiguous tool-result block is complete.
    """

    converted: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    pending_tool_call_ids: set[str] = set()

    def convert_message(message: dict[str, Any]) -> dict[str, Any]:
        role = message.get("role")
        if role == "assistant":
            wire: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content") or "",
            }
            internal_calls = message.get("tool_calls") or []
            if internal_calls:
                wire["tool_calls"] = [
                    {
                        "id": str(call.get("tool_call_id", "")),
                        "type": "function",
                        "function": {
                            "name": str(call.get("tool_id", "")),
                            "arguments": json.dumps(
                                call.get("arguments") or {}, ensure_ascii=False
                            ),
                        },
                    }
                    for call in internal_calls
                ]
            return wire
        if role == "tool":
            return {
                "role": "tool",
                "tool_call_id": str(message.get("tool_call_id", "")),
                "content": str(message.get("content", "")),
            }
        return dict(message)

    for message in messages:
        role = message.get("role")
        if pending_tool_call_ids and role != "tool":
            deferred.append(message)
            continue

        converted.append(convert_message(message))
        if role == "assistant":
            pending_tool_call_ids = {
                str(call.get("tool_call_id", ""))
                for call in (message.get("tool_calls") or [])
                if call.get("tool_call_id")
            }
        elif role == "tool" and pending_tool_call_ids:
            pending_tool_call_ids.discard(str(message.get("tool_call_id", "")))
            if not pending_tool_call_ids:
                converted.extend(convert_message(item) for item in deferred)
                deferred.clear()

    if deferred:
        converted.extend(convert_message(item) for item in deferred)
    return converted


def _to_openai_tool_descriptors(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert provider-neutral Workbench tools to OpenAI function tools."""

    converted: list[dict[str, Any]] = []
    for tool in tools:
        if "tool_id" not in tool:
            converted.append(dict(tool))
            continue
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool["tool_id"]),
                    "parameters": dict(tool.get("input_schema") or {}),
                    **(
                        {"description": str(tool["description"])}
                        if tool.get("description")
                        else {}
                    ),
                },
            }
        )
    return converted


@dataclass(frozen=True)
class ModelRequest:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    model_config: Mapping[str, Any] = field(default_factory=dict)
    abort_event: Any | None = None


@dataclass(frozen=True)
class ModelStreamEvent:
    type: str
    request_id: str
    delta: str = ""
    tool_call: dict[str, Any] | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def text_delta(cls, request_id: str, delta: str) -> "ModelStreamEvent":
        return cls(type="text_delta", request_id=request_id, delta=delta)

    @classmethod
    def tool_call_delta(
        cls, request_id: str, tool_call: dict[str, Any]
    ) -> "ModelStreamEvent":
        return cls(type="tool_call_delta", request_id=request_id, tool_call=tool_call)

    @classmethod
    def done(cls, request_id: str, finish_reason: str = "stop") -> "ModelStreamEvent":
        return cls(type="done", request_id=request_id, finish_reason=finish_reason)

    @classmethod
    def from_error(cls, request_id: str, message: str) -> "ModelStreamEvent":
        return cls(type="error", request_id=request_id, error=message)


async def _next_stream_item_or_signal(
    stream: AsyncIterator[dict[str, Any]],
    abort_event: Any | None,
    timeout_s: float,
) -> tuple[str, dict[str, Any] | None]:
    """Wait for provider progress, cancellation, or the idle boundary."""

    next_item = asyncio.create_task(stream.__anext__())
    abort_waiter = (
        asyncio.create_task(abort_event.wait())
        if abort_event is not None
        else None
    )
    try:
        waiters = {next_item}
        if abort_waiter is not None:
            waiters.add(abort_waiter)
        completed, _ = await asyncio.wait(
            waiters,
            timeout=timeout_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not completed:
            return "timeout", None
        if abort_waiter is not None and abort_waiter in completed:
            return "aborted", None
        try:
            return "item", next_item.result()
        except StopAsyncIteration:
            return "eof", None
    finally:
        if not next_item.done():
            next_item.cancel()
        await asyncio.gather(next_item, return_exceptions=True)
        if abort_waiter is not None:
            if not abort_waiter.done():
                abort_waiter.cancel()
            await asyncio.gather(abort_waiter, return_exceptions=True)


class ModelAdapter(Protocol):
    """Provider adapter boundary consumed by AgentCore."""

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """Yield normalized deltas, tool calls, completion, or an error."""


class OpenAICompatibleModelAdapter:
    """Adapt OpenAI-compatible public SSE to the normalized stream contract."""

    def __init__(self, config: LLMConfig, *, idle_timeout_s: float = 90.0) -> None:
        self.config = config
        if idle_timeout_s <= 0:
            raise ValueError("idle_timeout_s must be positive")
        self.idle_timeout_s = float(idle_timeout_s)

    def supports_named_tool_choice(self) -> bool:
        """Return whether this provider accepts a named ``tool_choice``.

        DeepSeek V4 thinking models accept function tools but reject the
        ``tool_choice`` request field.  The planner still publishes only the
        single typed submission tool for those models; omitting this optional
        field preserves the same tool-surface restriction without turning a
        provider capability mismatch into a planning failure.
        """

        provider = self.config.provider_name.casefold()
        host = (urlparse(self.config.base_url).hostname or "").casefold()
        model = self.config.model.casefold()
        is_deepseek = "deepseek" in provider or host == "api.deepseek.com"
        return not (is_deepseek and model.startswith("deepseek-v4"))

    def planning_request_config(self) -> dict[str, Any]:
        """Return a bounded provider-specific config for typed planning.

        DeepSeek V4 enables high-effort thinking by default. Notebook planning
        already supplies bounded evidence and requires a typed tool call, so a
        non-thinking request avoids spending several minutes on private
        reasoning that cannot be shown or used as evidence. The generic
        adapter leaves other providers unchanged.
        """

        return deepseek_v4_request_config(self.config)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        abort_event = request.abort_event
        if abort_event is not None and abort_event.is_set():
            yield ModelStreamEvent.from_error(request.request_id, "aborted")
            return
        wire_messages = _to_openai_wire_messages(request.messages)
        wire_tools = _to_openai_tool_descriptors(request.tools)
        # A typed request can create a proposal or another durable side effect
        # after the provider accepts it but before this process sees public
        # progress. Replaying it would hide the first-attempt truth and can
        # duplicate work. Untyped prose retains the existing one bounded retry
        # before any public progress; Report owns its separate retry policy.
        attempt_budget = 1 if request.tools or request.response_schema is not None else 2
        for attempt in range(attempt_budget):
            received_event = False
            public_progress = False
            try:
                request_config = (
                    {"model_config": request.model_config}
                    if request.model_config
                    else {}
                )
                stream = async_stream_chat_completion(
                    wire_messages,
                    self.config,
                    tools=wire_tools if request.tools else None,
                    **request_config,
                )
                while True:
                    signal, item = await _next_stream_item_or_signal(
                        stream, abort_event, self.idle_timeout_s
                    )
                    if signal == "timeout":
                        yield ModelStreamEvent.from_error(
                            request.request_id, "provider_no_progress"
                        )
                        return
                    if signal == "aborted":
                        yield ModelStreamEvent.from_error(request.request_id, "aborted")
                        return
                    if signal == "eof":
                        break
                    if abort_event is not None and abort_event.is_set():
                        yield ModelStreamEvent.from_error(request.request_id, "aborted")
                        return
                    event_type = item.get("type")
                    if event_type == "text_delta":
                        delta = item.get("delta")
                        if isinstance(delta, str) and delta:
                            received_event = True
                            public_progress = True
                            yield ModelStreamEvent.text_delta(request.request_id, delta)
                    elif event_type == "tool_call":
                        tool_call = item.get("tool_call")
                        if isinstance(tool_call, dict):
                            received_event = True
                            public_progress = True
                            yield ModelStreamEvent.tool_call_delta(request.request_id, tool_call)
                    elif event_type == "provider_activity":
                        # Providers such as DeepSeek may stream private
                        # reasoning before a public tool call. It is not
                        # user-visible Agent content. If that is the *only*
                        # progress before a disconnect, a single retry is safe:
                        # no public answer or typed tool call has been emitted.
                        received_event = True
                        if item.get("public") is True:
                            public_progress = True
                    elif event_type == "done":
                        finish_reason = item.get("finish_reason")
                        yield ModelStreamEvent(
                            type="done",
                            request_id=request.request_id,
                            finish_reason=finish_reason if isinstance(finish_reason, str) else "stop",
                            provider_request_id=request.request_id,
                        )
                        return
                raise LLMUpstreamError("LLM provider ended the stream without a completion")
            except LLMToolCallArgumentsError:
                # The provider completed a typed call, but the arguments are
                # not executable JSON. Preserve the failed first turn and let
                # a contract-owning caller decide whether to request one
                # bounded correction; the generic adapter never replays it.
                yield ModelStreamEvent.from_error(
                    request.request_id, "provider_tool_arguments_invalid"
                )
                return
            except LLMUpstreamError as exc:
                # A malformed 2xx body, transient network error, or explicitly
                # transient upstream status may recover on one immediate retry.
                # Never retry a provider-auth/request rejection such as 401/422,
                # and never replay a request after public stream content began.
                if (
                    attempt + 1 < attempt_budget
                    and not public_progress
                    and (
                        exc.upstream_status is None
                        or exc.upstream_status in _TRANSIENT_UPSTREAM_STATUSES
                    )
                ):
                    continue
                error_label = type(exc).__name__
                if exc.upstream_status is not None:
                    error_label += f":upstream_{exc.upstream_status}"
                yield ModelStreamEvent.from_error(request.request_id, error_label)
                return
            except Exception as exc:
                yield ModelStreamEvent.from_error(request.request_id, type(exc).__name__)
                return


class CancellableOpenAICompatibleModelAdapter(OpenAICompatibleModelAdapter):
    """Backward-compatible name for the shared async streaming adapter."""
