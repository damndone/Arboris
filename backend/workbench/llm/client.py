"""OpenAI-compatible Chat Completions client (httpx, zero vendor SDKs).

Every supported vendor (DeepSeek, Zhipu GLM, Moonshot, Qwen, OpenAI; Anthropic
via its compatibility endpoint) speaks this wire shape, so this is the single
adapter. Error detail is sanitized: upstream response bodies never appear in
anything raised from here.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx

from .config import LLMConfig

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


def fetch_models(config: LLMConfig) -> list[dict[str, str]]:
    """GET {base_url}/models and return the provider's model summaries."""
    if not config.is_configured():
        raise LLMNotConfiguredError(
            "LLM is not configured. Set a provider base URL, API key and model."
        )
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
                f"{config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": config.model, "messages": messages, "stream": False},
                timeout=config.timeout_s,
            )
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMUpstreamError(f"LLM provider request failed: {type(exc).__name__}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise LLMUpstreamError(
            "LLM provider returned an error: "
            f"{response.status_code}",
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
    model = payload.get("model")
    if not isinstance(model, str) or not model:
        model = config.model
    return {"text": text, "model": model}
