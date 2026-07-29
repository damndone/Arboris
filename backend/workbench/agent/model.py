"""Stream-first model contracts for the generic agent core."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from workbench.llm.client import (
    LLMUpstreamError,
    async_chat_completion,
    chat_completion,
)
from workbench.llm.config import LLMConfig


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


class ModelAdapter(Protocol):
    """Provider adapter boundary consumed by AgentCore."""

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """Yield normalized deltas, tool calls, completion, or an error."""


class OpenAICompatibleModelAdapter:
    """Adapt the existing one-shot client to the normalized stream contract.

    The adapter owns provider-specific response handling. This first bridge is
    intentionally one-shot because the existing DeepSeek-compatible client is
    one-shot; the AgentCore still observes a stable delta/done sequence and can
    later accept a native SSE implementation without changing its contract.
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        abort_event = request.abort_event
        if abort_event is not None and abort_event.is_set():
            yield ModelStreamEvent.from_error(request.request_id, "aborted")
            return
        wire_messages = _to_openai_wire_messages(request.messages)
        wire_tools = _to_openai_tool_descriptors(request.tools)
        for attempt in range(2):
            try:
                if request.tools:
                    result = await asyncio.to_thread(
                        chat_completion,
                        wire_messages,
                        self.config,
                        tools=wire_tools,
                    )
                else:
                    result = await asyncio.to_thread(chat_completion, wire_messages, self.config)
                break
            except LLMUpstreamError as exc:
                # A malformed 2xx body or transient network error has no
                # trustworthy response status. Retry it once; never retry a
                # provider-auth/request rejection such as 401/422.
                if attempt == 0 and exc.upstream_status is None:
                    continue
                yield ModelStreamEvent.from_error(request.request_id, type(exc).__name__)
                return
            except Exception as exc:
                yield ModelStreamEvent.from_error(request.request_id, type(exc).__name__)
                return
        if abort_event is not None and abort_event.is_set():
            yield ModelStreamEvent.from_error(request.request_id, "aborted")
            return
        for event in _completion_events(request, result):
            yield event


class CancellableOpenAICompatibleModelAdapter:
    """Async HTTP adapter whose in-flight provider request can be cancelled."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        abort_event = request.abort_event
        if abort_event is not None and abort_event.is_set():
            yield ModelStreamEvent.from_error(request.request_id, "aborted")
            return
        wire_messages = _to_openai_wire_messages(request.messages)
        wire_tools = _to_openai_tool_descriptors(request.tools)
        for attempt in range(2):
            try:
                result = await async_chat_completion(
                    wire_messages,
                    self.config,
                    tools=wire_tools if request.tools else None,
                )
                break
            except LLMUpstreamError as exc:
                if attempt == 0 and exc.upstream_status is None:
                    continue
                yield ModelStreamEvent.from_error(request.request_id, type(exc).__name__)
                return
            except Exception as exc:
                yield ModelStreamEvent.from_error(request.request_id, type(exc).__name__)
                return
        if abort_event is not None and abort_event.is_set():
            yield ModelStreamEvent.from_error(request.request_id, "aborted")
            return
        for event in _completion_events(request, result):
            yield event


def _completion_events(
    request: ModelRequest,
    result: Mapping[str, Any],
) -> tuple[ModelStreamEvent, ...]:
    events: list[ModelStreamEvent] = []
    tool_calls = result.get("tool_calls") or []
    for tool_call in tool_calls:
        events.append(ModelStreamEvent.tool_call_delta(request.request_id, tool_call))
    if result.get("text"):
        events.append(ModelStreamEvent.text_delta(request.request_id, str(result["text"])))
    events.append(
        ModelStreamEvent(
            type="done",
            request_id=request.request_id,
            finish_reason="tool_calls" if tool_calls else "stop",
            provider_request_id=request.request_id,
        )
    )
    return tuple(events)
