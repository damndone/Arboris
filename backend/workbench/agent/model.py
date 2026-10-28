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
    is_nvidia_ultra,
    provider_stream_wait_s,
)
from workbench.llm.config import LLMConfig


_TRANSIENT_UPSTREAM_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _to_openai_wire_messages(
    messages: list[dict[str, Any]],
    *,
    reasoning_source: Mapping[str, Any] | None = None,
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

    An assistant message's private reasoning is sent back only to the provider
    and model that produced it (``reasoning_source``); DeepSeek's thinking mode
    requires it on every later request that carries tools.
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
            reasoning = message.get("reasoning_content")
            if (reasoning_source is not None and isinstance(reasoning, str) and reasoning
                    and message.get("reasoning_source") == dict(reasoning_source)):
                wire["reasoning_content"] = reasoning
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
    #: The person's turn this request belongs to; bounds stall retries per turn.
    turn_key: str | None = None


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
    #: For a ``reasoning`` event: the provider and model that produced it.
    reasoning_source: dict[str, Any] | None = None

    @classmethod
    def text_delta(cls, request_id: str, delta: str) -> "ModelStreamEvent":
        return cls(type="text_delta", request_id=request_id, delta=delta)

    @classmethod
    def tool_call_delta(
        cls, request_id: str, tool_call: dict[str, Any]
    ) -> "ModelStreamEvent":
        return cls(type="tool_call_delta", request_id=request_id, tool_call=tool_call)

    @classmethod
    def reasoning(cls, request_id: str, text: str, source: dict[str, Any]) -> "ModelStreamEvent":
        """The provider's private reasoning for this response; never user-visible."""

        return cls(type="reasoning", request_id=request_id, delta=text, reasoning_source=source)

    @classmethod
    def done(cls, request_id: str, finish_reason: str = "stop") -> "ModelStreamEvent":
        return cls(type="done", request_id=request_id, finish_reason=finish_reason)

    @classmethod
    def from_error(cls, request_id: str, message: str) -> "ModelStreamEvent":
        return cls(type="error", request_id=request_id, error=message)

    @classmethod
    def retrying(cls, request_id: str, message: str) -> "ModelStreamEvent":
        """The provider failed before any output; the adapter tries again."""

        return cls(type="retry", request_id=request_id, error=message)


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


async def _wait_or_abort(seconds: float, abort_event: Any | None) -> bool:
    """Wait, unless the person stops the turn first; True when stopped."""

    if abort_event is None:
        await asyncio.sleep(seconds)
        return False
    try:
        await asyncio.wait_for(abort_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return False
    return True


def _error_label(exc: LLMUpstreamError) -> str:
    label = type(exc).__name__
    if exc.upstream_status is not None:
        label += f":upstream_{exc.upstream_status}"
    if getattr(exc, "context_overflow", False):
        label += ":context_overflow"
    return label


class ModelAdapter(Protocol):
    """Provider adapter boundary consumed by AgentCore."""

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """Yield normalized deltas, tool calls, completion, or an error."""


class OpenAICompatibleModelAdapter:
    """Adapt OpenAI-compatible public SSE to the normalized stream contract."""

    # Seconds to wait before each retry of a request that failed before any
    # output (a dropped connection, a stream cut short, 429/5xx).
    retry_delays_s: tuple[float, ...] = (1.0, 3.0)
    # A request that sent nothing within the idle bound is abandoned, as before
    # (no waiting on the same stalled stream); then a fresh request is sent after
    # each of these waits, at most this many times per turn. Free-route rounds
    # (2026-10-23): 26 of 92 Hy3 turns and 22 of 54 Step-5 turns ended on a stall
    # and needed the person to say "continue".
    stall_retry_delays_s: tuple[float, ...] = (5.0, 15.0)

    def __init__(self, config: LLMConfig, *, idle_timeout_s: float | None = None) -> None:
        self.config = config
        if idle_timeout_s is None:
            idle_timeout_s = provider_stream_wait_s(config, default_s=90.0)
        if idle_timeout_s <= 0:
            raise ValueError("idle_timeout_s must be positive")
        self.idle_timeout_s = float(idle_timeout_s)
        self._stall_retries: dict[str, int] = {}

    def _take_stall_retry(self, request: ModelRequest) -> float | None:
        """The wait before the next fresh request after a stall, while this turn has one left."""

        key = request.turn_key or request.request_id
        used = self._stall_retries.get(key, 0)
        if used >= len(self.stall_retry_delays_s):
            return None
        if len(self._stall_retries) > 64:
            self._stall_retries.pop(next(iter(self._stall_retries)))
        self._stall_retries[key] = used + 1
        return self.stall_retry_delays_s[used]

    def reasoning_source(self) -> dict[str, Any]:
        """Which provider and model private reasoning belongs to; it is sent to no other."""

        return {"provider_id": self.config.provider_id, "base_url": self.config.base_url, "model": self.config.model}

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
        source = self.reasoning_source()
        wire_messages = _to_openai_wire_messages(request.messages, reasoning_source=source)
        wire_tools = _to_openai_tool_descriptors(request.tools)
        # A provider cannot act: a tool runs only after Workbench receives the
        # call. So a request that failed before any public output -- no text,
        # no tool call -- changed nothing and is safe to send again, typed or
        # not. Each retry is yielded as an event so the failure stays on the
        # record. After public output began, nothing is replayed.
        attempt_budget = 1 + len(self.retry_delays_s)
        attempt = -1
        stall_wait: float | None = None
        while attempt + 1 < attempt_budget or stall_wait is not None:
            if stall_wait is not None:
                # A fresh request after a stall does not use the failure retries.
                if await _wait_or_abort(stall_wait, abort_event):
                    yield ModelStreamEvent.from_error(request.request_id, "aborted")
                    return
                stall_wait = None
            else:
                attempt += 1
                if attempt:
                    await asyncio.sleep(self.retry_delays_s[attempt - 1])
                    if abort_event is not None and abort_event.is_set():
                        yield ModelStreamEvent.from_error(request.request_id, "aborted")
                        return
            received_event = False
            public_progress = False
            meaningful_deadline = (asyncio.get_running_loop().time() + self.idle_timeout_s
                                   if is_nvidia_ultra(self.config) else None)
            reasoning_parts: list[str] = []  # this attempt's only; a retry starts over
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
                    remaining = (max(0.0, meaningful_deadline - asyncio.get_running_loop().time())
                                 if meaningful_deadline is not None else self.idle_timeout_s)
                    if meaningful_deadline is not None and remaining <= 0:
                        signal, item = "timeout", None
                    else:
                        signal, item = await _next_stream_item_or_signal(stream, abort_event, remaining)
                    if signal == "timeout":
                        if meaningful_deadline is not None:
                            await stream.aclose()
                        if not public_progress and (wait := self._take_stall_retry(request)) is not None:
                            yield ModelStreamEvent.retrying(request.request_id, "provider_no_progress")
                            stall_wait = wait
                            break
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
                    if meaningful_deadline is not None and (
                        event_type == "text_delta" and isinstance(item.get("delta"), str) and item["delta"].strip()
                        or event_type == "tool_call"
                        or event_type == "provider_activity" and (
                            item.get("meaningful") is True
                            or isinstance(item.get("reasoning"), str) and item["reasoning"].strip()
                        )
                    ):
                        meaningful_deadline = asyncio.get_running_loop().time() + self.idle_timeout_s
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
                        if isinstance(item.get("reasoning"), str):
                            reasoning_parts.append(item["reasoning"])
                    elif event_type == "done":
                        # Close the provider stream here, in this task: left
                        # suspended inside ``client.stream(...)`` it holds the
                        # connection until garbage collection closes it from
                        # another task.
                        await stream.aclose()
                        finish_reason = item.get("finish_reason")
                        if reasoning_parts:
                            yield ModelStreamEvent.reasoning(request.request_id, "".join(reasoning_parts), source)
                        yield ModelStreamEvent(
                            type="done",
                            request_id=request.request_id,
                            finish_reason=finish_reason if isinstance(finish_reason, str) else "stop",
                            provider_request_id=item.get("provider_request_id"),
                            usage=item.get("usage"),
                        )
                        return
                if stall_wait is not None:
                    continue
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
                    yield ModelStreamEvent.retrying(request.request_id, _error_label(exc))
                    continue
                yield ModelStreamEvent.from_error(request.request_id, _error_label(exc))
                return
            except Exception as exc:
                yield ModelStreamEvent.from_error(request.request_id, type(exc).__name__)
                return


class CancellableOpenAICompatibleModelAdapter(OpenAICompatibleModelAdapter):
    """Backward-compatible name for the shared async streaming adapter."""
