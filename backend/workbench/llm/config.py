"""LLM provider configuration, resolved per request.

Per-request resolution (no module-level cache) keeps tests monkeypatchable and
lets a running server pick up key changes without restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .provider_store import (
    ProviderRecord,
    ProviderStoreError,
    environment_provider_from_env,
    explicit_config_path,
    load_provider_store,
    load_provider_store_strict,
)

DEFAULT_TIMEOUT_S = 60.0

# `source` values for a config that is unusable BECAUSE the operator-pinned
# store is broken. These must never fall through to the environment or default
# config: the one real-provider call this system ever made by accident happened
# exactly that way (explicit path missing → silent environment fallback).
SOURCE_EXPLICIT_CONFIG_MISSING = "explicit_config_missing"
SOURCE_EXPLICIT_CONFIG_INVALID = "explicit_config_invalid"
SOURCE_EXPLICIT_CONFIG_UNCONFIGURED = "explicit_config_unconfigured"


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
    supports_vision: bool = False

    def is_configured(self) -> bool:
        return all(value.strip() for value in (self.base_url, self.api_key, self.model))

    def configuration_error_message(self) -> str:
        """The reason this config cannot be used for a call-out, stated truthfully.

        A broken explicit store must not be reported as plain "not configured" —
        the operator DID configure something; the file they pinned is gone or
        unreadable, and no fallback was consulted on purpose.
        """

        if self.source == SOURCE_EXPLICIT_CONFIG_MISSING:
            return (
                "WORKBENCH_LLM_CONFIG_PATH is set but the file does not exist. "
                "Refusing to fall back to the environment or default provider "
                "configuration; restore the file or unset the variable."
            )
        if self.source == SOURCE_EXPLICIT_CONFIG_INVALID:
            return (
                "WORKBENCH_LLM_CONFIG_PATH is set but the file is not a valid "
                "provider store. Refusing to fall back to the environment or "
                "default provider configuration; fix the file or unset the variable."
            )
        if self.source == SOURCE_EXPLICIT_CONFIG_UNCONFIGURED:
            return (
                "WORKBENCH_LLM_CONFIG_PATH is set but its active provider is not "
                "fully configured. Refusing to fall back to the environment or "
                "default provider configuration; complete the provider or unset "
                "the variable."
            )
        return (
            "LLM is not configured. Set a provider base URL, API key and model."
        )


def load_llm_config() -> LLMConfig:
    explicit = explicit_config_path()
    if explicit is not None:
        # The operator pinned the config source. A missing or unreadable file is
        # a configuration ERROR, not "use something else": falling through to
        # the environment here is how an offline smoke run once made a real
        # provider call. Fail closed — no call-out can use this config, and the
        # message says exactly why.
        if not explicit.is_file():
            return LLMConfig(
                base_url="", api_key="", model="",
                source=SOURCE_EXPLICIT_CONFIG_MISSING,
            )
        try:
            store = load_provider_store_strict(explicit)
        except ProviderStoreError:
            return LLMConfig(
                base_url="", api_key="", model="",
                source=SOURCE_EXPLICIT_CONFIG_INVALID,
            )
    else:
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

    if explicit is not None:
        return LLMConfig(
            base_url="",
            api_key="",
            model="",
            source=SOURCE_EXPLICIT_CONFIG_UNCONFIGURED,
        )

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
        supports_vision=(
            model_record.supports_vision if model_record is not None else False
        ),
    )
