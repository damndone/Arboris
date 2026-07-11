"""OpenAI-compatible Chat Completions client (httpx, zero vendor SDKs).

Every supported vendor (DeepSeek, Zhipu GLM, Moonshot, Qwen, OpenAI; Anthropic
via its compatibility endpoint) speaks this wire shape, so this is the single
adapter. Error detail is sanitized: upstream bodies are truncated and the API
key never appears in anything raised from here.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx

from .config import LLMConfig

_UPSTREAM_DETAIL_MAX_CHARS = 300

# Test seam: monkeypatch to inject httpx.MockTransport-backed clients.
_client_factory: Callable[[LLMConfig], httpx.Client] = lambda config: httpx.Client(
    timeout=config.timeout_s
)


class LLMNotConfiguredError(Exception):
    """Raised when base_url/api_key/model are not all set."""


class LLMUpstreamError(Exception):
    """Provider returned non-2xx, timed out, or sent an unusable body."""

    def __init__(self, message: str, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status


def chat_completion(messages: list[dict[str, str]], config: LLMConfig) -> dict[str, Any]:
    """POST {base_url}/chat/completions; return {"text", "model"}."""
    if not config.is_configured():
        raise LLMNotConfiguredError(
            "LLM is not configured. Set WORKBENCH_LLM_BASE_URL, "
            "WORKBENCH_LLM_API_KEY and WORKBENCH_LLM_MODEL."
        )
    try:
        with _client_factory(config) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": config.model, "messages": messages, "stream": False},
            )
    except httpx.HTTPError as exc:
        raise LLMUpstreamError(f"LLM provider request failed: {type(exc).__name__}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise LLMUpstreamError(
            "LLM provider returned an error: "
            f"{response.status_code} {_sanitized_body(response)}",
            upstream_status=response.status_code,
        )
    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (ValueError, LookupError, TypeError) as exc:
        raise LLMUpstreamError(
            "LLM provider returned an unexpected response shape"
        ) from exc
    if not isinstance(text, str):
        raise LLMUpstreamError("LLM provider returned non-text content")
    return {"text": text, "model": payload.get("model", config.model)}


def _sanitized_body(response: httpx.Response) -> str:
    try:
        body = response.text
    except Exception:  # pragma: no cover - defensive
        return ""
    return body[:_UPSTREAM_DETAIL_MAX_CHARS]
