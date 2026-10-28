"""OpenAI-compatible Chat Completions client (httpx, zero vendor SDKs).

Every supported vendor (DeepSeek, Zhipu GLM, Moonshot, Qwen, OpenAI; Anthropic
via its compatibility endpoint) speaks this wire shape, so this is the single
adapter. Error detail is sanitized: upstream response bodies never appear in
anything raised from here.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ..egress import EgressPolicyError, guard_outgoing_messages
from .config import LLMConfig
from .provider_store import REASONING_EFFORTS, default_efforts, takes_reasoning_effort

# Test seam: monkeypatch to inject httpx.MockTransport-backed clients.
_client_factory: Callable[[LLMConfig], httpx.Client] = lambda config: httpx.Client(
    timeout=config.timeout_s
)
_async_client_factory: Callable[[LLMConfig], httpx.AsyncClient] = (
    lambda config: httpx.AsyncClient(timeout=config.timeout_s)
)


class LLMNotConfiguredError(Exception):
    """Raised when base_url/api_key/model are not all set."""


class LLMUpstreamError(Exception):
    """Provider returned non-2xx, failed in transport, or sent a bad body."""

    def __init__(
        self,
        message: str,
        upstream_status: int | None = None,
        *,
        retryable: bool = False,
        context_overflow: bool = False,
    ) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status
        self.retryable = retryable
        # The provider said the request is longer than the model accepts; the
        # Agent compacts its conversation and tries once more.
        self.context_overflow = context_overflow


# How OpenAI-compatible providers word a request that exceeds the model's
# context ("maximum context length is 65536 tokens", "context_length_exceeded",
# "prompt is too long", "超过最大长度"). Only the classification is kept.
_CONTEXT_OVERFLOW = re.compile(
    r"context[ _-]?(?:length|window)|maximum (?:context|prompt)|too many tokens|prompt is too long"
    r"|exceeds? (?:the )?(?:model'?s? )?(?:maximum|max|context|token)|上下文|超过最大长度",
    re.IGNORECASE,
)


def is_context_overflow(status: int, body: bytes) -> bool:
    return status in {400, 413, 422} and bool(_CONTEXT_OVERFLOW.search(body[:4000].decode("utf-8", "replace")))


class LLMToolCallArgumentsError(LLMUpstreamError):
    """Provider completed a tool call whose arguments are not a JSON object."""


def is_deepseek_v4(config: LLMConfig) -> bool:
    """Whether the configured model is DeepSeek V4, by its id, also behind a gateway.

    Gateways prefix a vendor (Magpie/WorkBuddy: ``workbuddy-ai/deepseek-v4.1-flash``)
    and run on other hosts, so neither the provider name nor the host identifies it.
    """

    return takes_reasoning_effort(config.model)


def deepseek_v4_request_config(config: LLMConfig) -> dict[str, Any]:
    """Return bounded, provider-owned controls for DeepSeek V4 requests.

    DeepSeek V4 enables high-effort private reasoning by default. Workbench's
    typed Notebook planner and evidence-bound Report writer both need bounded
    public responses, so they share this adapter policy instead of each caller
    guessing provider controls independently. No thinking is stated only as
    ``thinking: disabled``: the Magpie/WorkBuddy gateway thinks whenever
    ``reasoning_effort`` is present, whatever its value, even beside
    ``thinking: disabled`` (probe 2026-10-22).
    """

    # "deepseek-flash" is the V4.1 Flash alias this Workbench is configured with;
    # matching only "deepseek-v4*" left planner, report writer and conversation
    # summaries in default high-effort thinking with a bounded output.
    if is_deepseek_v4(config):
        return {"thinking": {"type": "disabled"}, "max_tokens": 8192}
    return {}


# A streaming provider sends bytes continuously (tokens, reasoning or
# keep-alives). Seen live: DeepSeek connections that went silent for the whole
# 60 s timeout before failing, so each retry cost a minute. Silence this long
# means the connection is dead; give up and let the adapter retry.
STREAM_SILENCE_S = 30.0


def _stream_timeout(config: LLMConfig) -> httpx.Timeout:
    # Only silence after the connection is up is shortened: connecting can
    # legitimately be slow (a TLS handshake took 10-14 s in the same session).
    return httpx.Timeout(config.timeout_s, read=min(config.timeout_s, STREAM_SILENCE_S))


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def reported_capabilities(raw_model: Mapping[str, Any]) -> dict[str, Any]:
    """What a model list says about a model, when it says it (Magpie/WorkBuddy, OpenRouter-style
    fields): its context window, the thinking efforts it accepts, and image input. A field the
    provider does not report is left out, so nothing is guessed."""

    found: dict[str, Any] = {}
    window = next((_positive_int(raw_model.get(key)) for key in ("context_length", "context_window", "max_input_tokens")
                   if _positive_int(raw_model.get(key))), None)
    if window:
        found["context_window_tokens"] = window
    levels = raw_model.get("reasoning_levels")
    if not isinstance(levels, list):
        supported = raw_model.get("supported_reasoning_levels")
        levels = [item.get("effort") for item in supported if isinstance(item, Mapping)] if isinstance(supported, list) else None
    if isinstance(levels, list):
        found["reasoning_efforts"] = [level for level in REASONING_EFFORTS if level in levels]
    elif raw_model.get("reasoning") is False:
        found["reasoning_efforts"] = []
    modalities = raw_model.get("modalities")
    if isinstance(modalities, Mapping) and isinstance(modalities.get("input"), list):
        found["supports_vision"] = "image" in modalities["input"]
    return found


def fetch_models(config: LLMConfig) -> list[dict[str, Any]]:
    """GET {base_url}/models and return the provider's model summaries."""
    if not config.base_url.strip() or not config.api_key.strip():
        raise LLMNotConfiguredError("Provider base URL and API key are required to fetch models.")
    try:
        with _client_factory(config) as client:
            response = client.get(
                f"{config.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {config.api_key}"},
                timeout=config.timeout_s,
            )
    except httpx.TransportError as exc:
        raise LLMUpstreamError(
            f"LLM provider request failed: {type(exc).__name__}",
            retryable=True,
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMUpstreamError(
            f"LLM provider request failed: {type(exc).__name__}"
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise LLMUpstreamError(
            "LLM provider returned an error: "
            f"{response.status_code}",
            upstream_status=response.status_code,
        )

    try:
        payload = response.json()
        raw_models = payload["data"]
        if not isinstance(raw_models, list):
            raise TypeError
        models: list[dict[str, Any]] = []
        model_ids: set[str] = set()
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                raise TypeError
            model_id = raw_model["id"]
            owned_by = raw_model.get("owned_by", "")
            if not isinstance(model_id, str) or not model_id.strip():
                raise TypeError
            if model_id in model_ids:
                raise TypeError
            if not isinstance(owned_by, str):
                raise TypeError
            model_ids.add(model_id)
            models.append({"id": model_id, "owned_by": owned_by, **reported_capabilities(raw_model)})
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMUpstreamError(
            "LLM provider returned an unexpected models response shape"
        ) from exc
    return models


def chat_completion(
    messages: list[dict[str, Any]],
    config: LLMConfig,
    *,
    tools: list[dict[str, Any]] | None = None,
    model_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """POST Chat Completions and normalize text plus optional tool calls."""
    if not config.is_configured():
        raise LLMNotConfiguredError(config.configuration_error_message())
    request_payload = _chat_request_payload(messages, config, tools, model_config=model_config)
    try:
        with _client_factory(config) as client:
            response = client.post(
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=config.timeout_s,
            )
    except httpx.TransportError as exc:
        raise LLMUpstreamError(
            f"LLM provider request failed: {type(exc).__name__}",
            retryable=True,
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMUpstreamError(f"LLM provider request failed: {type(exc).__name__}") from exc

    return _normalize_chat_completion_response(response, config)


async def async_chat_completion(
    messages: list[dict[str, Any]],
    config: LLMConfig,
    *,
    tools: list[dict[str, Any]] | None = None,
    model_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Cancellable async variant used by long-running Agent workflows."""

    if not config.is_configured():
        raise LLMNotConfiguredError(config.configuration_error_message())
    request_payload = _chat_request_payload(messages, config, tools, model_config=model_config)
    try:
        async with _async_client_factory(config) as client:
            response = await client.post(
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=config.timeout_s,
            )
    except httpx.TransportError as exc:
        raise LLMUpstreamError(
            f"LLM provider request failed: {type(exc).__name__}",
            retryable=True,
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMUpstreamError(f"LLM provider request failed: {type(exc).__name__}") from exc

    return _normalize_chat_completion_response(response, config)


async def async_stream_chat_completion(
    messages: list[dict[str, Any]],
    config: LLMConfig,
    *,
    tools: list[dict[str, Any]] | None = None,
    model_config: Mapping[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield normalized public Chat Completions SSE events.

    The public ``content`` stream is deliberately distinct from any
    provider-specific hidden reasoning fields. Workbench records only text
    placed in the normal assistant response channel and complete typed tool
    calls required by the Agent contract.
    """

    if not config.is_configured():
        raise LLMNotConfiguredError(config.configuration_error_message())
    request_payload = _chat_request_payload(
        messages,
        config,
        tools,
        model_config=model_config,
        stream=True,
    )
    tool_fragments: dict[int, dict[str, Any]] = {}
    model = config.model
    finish_reason: str | None = None
    try:
        async with _async_client_factory(config) as client:
            async with client.stream(
                "POST",
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=_stream_timeout(config),
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    body = await response.aread() if response.status_code in {400, 413, 422} else b""
                    raise LLMUpstreamError(
                        "LLM provider returned an error: "
                        f"{response.status_code}",
                        upstream_status=response.status_code,
                        context_overflow=is_context_overflow(response.status_code, body),
                    )
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[5:].strip()
                    if raw_data == "[DONE]":
                        if finish_reason is not None:
                            return
                        break
                    try:
                        payload = json.loads(raw_data)
                        choice = payload["choices"][0]
                        if not isinstance(choice, dict):
                            raise TypeError
                        delta = choice.get("delta") or {}
                        if not isinstance(delta, dict):
                            raise TypeError
                    except (ValueError, LookupError, TypeError) as exc:
                        raise LLMUpstreamError(
                            "LLM provider returned an unexpected streaming response shape"
                        ) from exc
                    candidate_model = payload.get("model")
                    if isinstance(candidate_model, str) and candidate_model:
                        model = candidate_model
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield {"type": "text_delta", "delta": content}
                    if delta.get("reasoning_content") is not None:
                        # Keep private reasoning out of the public stream while
                        # preserving a provider-activity signal for retry
                        # control in the generic adapter. The text travels with
                        # it: DeepSeek requires it back on later requests that
                        # carry tools (the adapter keeps it private).
                        reasoning = delta.get("reasoning_content")
                        yield {"type": "provider_activity",
                               **({"reasoning": reasoning} if isinstance(reasoning, str) and reasoning else {})}
                    raw_tool_calls = delta.get("tool_calls") or []
                    if not isinstance(raw_tool_calls, list):
                        raise LLMUpstreamError(
                            "LLM provider returned an unexpected streaming response shape"
                        )
                    for raw_tool_call in raw_tool_calls:
                        _merge_stream_tool_call(tool_fragments, raw_tool_call)
                    if raw_tool_calls and any(
                        _is_json_argument_prefix(str(fragment.get("arguments", "")))
                        for fragment in tool_fragments.values()
                    ):
                        # A tool call is assembled only after the provider sends
                        # a finish reason, but receiving any valid fragment is
                        # already actionable provider progress. Keep that
                        # signal internal so the adapter does not retry a
                        # request after a disconnect halfway through a typed
                        # submission.
                        yield {"type": "provider_activity", "public": True}
                    candidate_finish_reason = choice.get("finish_reason")
                    if candidate_finish_reason is not None:
                        if not isinstance(candidate_finish_reason, str) or not candidate_finish_reason:
                            raise LLMUpstreamError(
                                "LLM provider returned an unexpected streaming response shape"
                            )
                        finish_reason = candidate_finish_reason
                        for tool_call in _complete_stream_tool_calls(tool_fragments):
                            yield {"type": "tool_call", "tool_call": tool_call}
                        yield {
                            "type": "done",
                            "finish_reason": finish_reason,
                            "model": model,
                            **({"usage": payload["usage"]} if isinstance(payload.get("usage"), dict) else {}),
                            **({"provider_request_id": payload["id"]}
                               if isinstance(payload.get("id"), str) and payload["id"] else {}),
                        }
                        return
    except LLMUpstreamError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMUpstreamError(
            f"LLM provider request failed: {type(exc).__name__}"
        ) from exc
    raise LLMUpstreamError("LLM provider ended the stream without a completion")


def _chat_request_payload(
    messages: list[dict[str, Any]],
    config: LLMConfig,
    tools: list[dict[str, Any]] | None,
    *,
    model_config: Mapping[str, Any] | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    # The single egress checkpoint: every provider call is built here.
    try:
        guarded = guard_outgoing_messages(
            messages,
            base_url=config.base_url,
            provider_id=config.provider_id,
            model=config.model,
            data_location=config.data_location,
        )
    except EgressPolicyError as exc:
        # A broken policy blocks the call; it never falls back to sending more.
        raise LLMUpstreamError(f"Data-sharing policy is invalid: {exc}") from exc
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": guarded,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if model_config:
        # Only server-owned, provider-neutral request controls cross this
        # boundary. The planner never forwards arbitrary model parameters.
        for key in ("tool_choice", "thinking", "reasoning_effort", "max_tokens"):
            if key in model_config:
                payload[key] = model_config[key]
    efforts = config.reasoning_efforts if config.reasoning_efforts is not None else default_efforts(config.model)
    if efforts and "thinking" not in payload and "reasoning_effort" not in payload:
        # The effort is always stated: a gateway serving the same model
        # (Magpie/WorkBuddy) otherwise answers without thinking.
        effort = agent_reasoning_effort(config)
        # WorkBuddy's DeepSeek route treats any reasoning_effort as enabling
        # thinking. Other compatible providers (including NVIDIA) accept the
        # standard "none" value and must not receive DeepSeek-only controls.
        if effort == "none" and is_deepseek_v4(config):
            payload["thinking"] = {"type": "disabled"}
        else:
            payload["reasoning_effort"] = effort
    return payload


def agent_reasoning_effort(config: LLMConfig | None = None) -> str:
    """Effort for requests that do not bound it: WORKBENCH_REASONING_EFFORT, else the
    model's choice in the Agent's model menu, else the documented V4 default ``high``.

    Evaluation runs set the variable to compare a strong configuration (``max``)
    and a weak one (``none``, no thinking) on the same tasks, whatever is stored.
    """

    stored = config.reasoning_effort if config is not None else None
    efforts = (config.reasoning_efforts if config is not None and config.reasoning_efforts is not None
               else default_efforts(config.model) if config is not None else ())
    # The documented V4 default, else the strongest effort the model lists.
    default = "high" if not efforts or "high" in efforts else efforts[-1]
    value = os.environ.get("WORKBENCH_REASONING_EFFORT", "").strip().lower() or stored or default
    if value not in REASONING_EFFORTS:
        raise LLMUpstreamError(f"WORKBENCH_REASONING_EFFORT must be one of {', '.join(REASONING_EFFORTS)}")
    return value


def _merge_stream_tool_call(
    fragments: dict[int, dict[str, Any]],
    raw_tool_call: Any,
) -> None:
    if not isinstance(raw_tool_call, dict):
        raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
    index = raw_tool_call.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
    fragment = fragments.setdefault(index, {"arguments": ""})
    tool_call_id = raw_tool_call.get("id")
    if tool_call_id is not None:
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
        fragment["tool_call_id"] = tool_call_id
    function = raw_tool_call.get("function") or {}
    if not isinstance(function, dict):
        raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
    tool_id = function.get("name")
    if tool_id is not None:
        if not isinstance(tool_id, str) or not tool_id:
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
        fragment["tool_id"] = tool_id
    arguments = function.get("arguments")
    if arguments is not None:
        if not isinstance(arguments, str):
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
        fragment["arguments"] = f"{fragment.get('arguments', '')}{arguments}"


def _is_json_argument_prefix(raw_arguments: str) -> bool:
    """Tell a recoverable partial JSON prefix from an invalid payload."""

    trimmed = raw_arguments.rstrip()
    if not trimmed:
        return True
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError as exc:
        if "Unterminated string" in exc.msg:
            return True
        return exc.pos >= len(trimmed)
    return isinstance(parsed, dict)


def _complete_stream_tool_calls(
    fragments: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    for _, fragment in sorted(fragments.items()):
        tool_call_id = fragment.get("tool_call_id")
        tool_id = fragment.get("tool_id")
        raw_arguments = fragment.get("arguments", "{}")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
        if not isinstance(tool_id, str) or not tool_id:
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
        if not isinstance(raw_arguments, str):
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
        try:
            arguments = json.loads(raw_arguments or "{}")
        except ValueError as exc:
            raise LLMToolCallArgumentsError(
                "LLM provider returned invalid tool-call arguments"
            ) from exc
        if not isinstance(arguments, dict):
            raise LLMToolCallArgumentsError(
                "LLM provider returned non-object tool-call arguments"
            )
        completed.append(
            {
                "tool_call_id": tool_call_id,
                "tool_id": tool_id,
                "arguments": arguments,
            }
        )
    return completed


def _normalize_chat_completion_response(
    response: httpx.Response,
    config: LLMConfig,
) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise LLMUpstreamError(
            "LLM provider returned an error: "
            f"{response.status_code}",
            upstream_status=response.status_code,
        )
    try:
        payload = response.json()
        message = payload["choices"][0]["message"]
        if not isinstance(message, dict):
            raise TypeError
        text = message.get("content") or ""
        if not isinstance(text, str):
            raise TypeError
        raw_tool_calls = message.get("tool_calls") or []
        if not isinstance(raw_tool_calls, list):
            raise TypeError
        tool_calls: list[dict[str, Any]] = []
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise TypeError
            function = raw_tool_call.get("function")
            if not isinstance(function, dict):
                raise TypeError
            tool_call_id = raw_tool_call.get("id")
            tool_id = function.get("name")
            raw_arguments = function.get("arguments", "{}")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                raise TypeError
            if not isinstance(tool_id, str) or not tool_id:
                raise TypeError
            if isinstance(raw_arguments, str):
                arguments = json.loads(raw_arguments)
            else:
                arguments = raw_arguments
            if not isinstance(arguments, dict):
                raise TypeError
            tool_calls.append(
                {
                    "tool_call_id": tool_call_id,
                    "tool_id": tool_id,
                    "arguments": arguments,
                }
            )
    except (ValueError, LookupError, TypeError) as exc:
        raise LLMUpstreamError(
            "LLM provider returned an unexpected response shape"
        ) from exc
    model = payload.get("model")
    if not isinstance(model, str) or not model:
        model = config.model
    result = {"text": text, "model": model}
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result
