"""LLM provider configuration, resolved per request.

Per-request resolution (no module-level cache) keeps tests monkeypatchable and
lets a running server pick up key changes without restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .provider_store import (
    ProviderRecord,
    environment_provider_from_env,
    load_provider_store,
)

DEFAULT_TIMEOUT_S = 60.0


def validate_provider_url(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlparse(value)
        parsed.port  # Force validation of malformed/out-of-range ports.
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an absolute http or https URL"
        ) from exc
    if (
        any(character.isspace() for character in value)
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
    ):
        raise ValueError(f"{field_name} must be an absolute http or https URL")
    return value.rstrip("/")


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    provider_id: str = ""
    provider_name: str = ""
    source: str = "none"
    context_window_tokens: int | None = None
    supports_1m: bool = False

    def is_configured(self) -> bool:
        return all(value.strip() for value in (self.base_url, self.api_key, self.model))


def load_llm_config() -> LLMConfig:
    store = load_provider_store()
    provider = next(
        (
            candidate
            for candidate in store.providers
            if candidate.id == store.active_provider_id
        ),
        None,
    )
    if provider is not None:
        local_config = _config_from_provider(provider, source="local")
        if local_config.is_configured():
            return local_config

    provider = environment_provider_from_env()
    if provider is not None:
        return _config_from_provider(provider, source="environment")

    return LLMConfig(base_url="", api_key="", model="", source="none")


def _config_from_provider(provider: ProviderRecord, *, source: str) -> LLMConfig:
    try:
        validate_provider_url(provider.base_url, "base_url")
    except ValueError:
        base_url = ""
    else:
        base_url = provider.base_url

    model_record = next(
        (model for model in provider.models if model.request_model == provider.model),
        None,
    )
    return LLMConfig(
        base_url=base_url,
        api_key=provider.api_key,
        model=provider.model,
        timeout_s=provider.timeout_s,
        provider_id=provider.id,
        provider_name=provider.name,
        source=source,
        context_window_tokens=(
            model_record.context_window_tokens if model_record is not None else None
        ),
        supports_1m=model_record.supports_1m if model_record is not None else False,
    )
