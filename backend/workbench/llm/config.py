"""LLM provider configuration, resolved per request.

Per-request resolution (no module-level cache) keeps tests monkeypatchable and
lets a running server pick up key changes without restart.
"""
from __future__ import annotations

from dataclasses import dataclass

from .provider_store import (
    ProviderRecord,
    environment_provider_from_env,
    load_provider_store,
)

DEFAULT_TIMEOUT_S = 60.0


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
        return bool(self.base_url and self.api_key and self.model)


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
        return _config_from_provider(provider, source="local")

    provider = environment_provider_from_env()
    if provider is not None:
        return _config_from_provider(provider, source="environment")

    return LLMConfig(base_url="", api_key="", model="", source="none")


def _config_from_provider(provider: ProviderRecord, *, source: str) -> LLMConfig:
    model_record = next(
        (model for model in provider.models if model.request_model == provider.model),
        None,
    )
    return LLMConfig(
        base_url=provider.base_url,
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
