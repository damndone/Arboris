"""OpenAI-compatible Chat Completions client (httpx, zero vendor SDKs).

Every supported vendor (DeepSeek, Zhipu GLM, Moonshot, Qwen, OpenAI; Anthropic
via its compatibility endpoint) speaks this wire shape, so this is the single
adapter. Error detail is sanitized: upstream response bodies never appear in
anything raised from here.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Callable

import httpx

from .config import LLMConfig

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
    """Provider returned non-2xx, timed out, or sent an unusable body."""

    def __init__(self, message: str, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status


def fetch_models(config: LLMConfig) -> list[dict[str, str]]:
    """GET {base_url}/models and return the provider's model summaries."""
    if not config.is_configured():
        raise LLMNotConfiguredError(config.configuration_error_message())
    try:
        with _client_factory(config) as client:
            response = client.get(
                f"{config.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {config.api_key}"},
                timeout=config.timeout_s,
            )
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
        models: list[dict[str, str]] = []
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
            models.append({"id": model_id, "owned_by": owned_by})
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
                timeout=config.timeout_s,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise LLMUpstreamError(
                        "LLM provider returned an error: "
                        f"{response.status_code}",
                        upstream_status=response.status_code,
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
                        # control in the generic adapter.
                        yield {"type": "provider_activity"}
                    raw_tool_calls = delta.get("tool_calls") or []
                    if not isinstance(raw_tool_calls, list):
                        raise LLMUpstreamError(
                            "LLM provider returned an unexpected streaming response shape"
                        )
                    for raw_tool_call in raw_tool_calls:
                        _merge_stream_tool_call(tool_fragments, raw_tool_call)
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
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if model_config:
        # Only server-owned, provider-neutral request controls cross this
        # boundary. The planner never forwards arbitrary model parameters.
        for key in ("tool_choice", "thinking", "max_tokens"):
            if key in model_config:
                payload[key] = model_config[key]
    return payload


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
            raise LLMUpstreamError(
                "LLM provider returned an unexpected streaming response shape"
            ) from exc
        if not isinstance(arguments, dict):
            raise LLMUpstreamError("LLM provider returned an unexpected streaming response shape")
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
