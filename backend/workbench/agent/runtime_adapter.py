"""Explicit headless model runtime injection, without global provider changes.

Offline scopes admit one exact strict ReplayAdapter and a keyless explicit
configuration. They never consult the default loader or adapter factory. This
boundary covers the Agent route runtime, not providers nested inside tools.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from typing import Callable, Iterator

from ..llm.config import LLMConfig, validate_provider_url
from .model import ModelAdapter
from .model_replay import ReplayAdapter


class RuntimeAdapterError(ValueError):
    """An explicit headless runtime cannot be admitted faithfully."""


@dataclass
class _Runtime:
    factory: Callable[[LLMConfig], ModelAdapter]
    config: LLMConfig | None
    offline: bool
    adapter: ModelAdapter | None = None
    bound_config: LLMConfig | None = None
    closed: bool = False
    lock: RLock = field(default_factory=RLock)

    def check(self, config: LLMConfig | None = None) -> None:
        if self.closed:
            raise RuntimeAdapterError("headless runtime scope is closed")
        if config is not None and ((self.config is not None and config != self.config)
                                   or (self.bound_config is not None and config != self.bound_config)):
            raise RuntimeAdapterError("headless runtime configuration changed within its scope")

    def model_adapter(self, config: LLMConfig) -> ModelAdapter:
        with self.lock:
            self.check(config)
            if self.adapter is None:
                adapter = self.factory(config)
                if self.offline and type(adapter) is not ReplayAdapter:
                    raise RuntimeAdapterError("offline runtime requires one exact strict ReplayAdapter")
                if not callable(getattr(adapter, "stream", None)):
                    raise RuntimeAdapterError("headless runtime factory must return a ModelAdapter")
                self.adapter = adapter
                self.bound_config = config
            return self.adapter


_active: ContextVar[_Runtime | None] = ContextVar("headless_runtime", default=None)


def _offline_config(config: LLMConfig | None) -> LLMConfig:
    if type(config) is not LLMConfig or config.api_key != "":
        raise RuntimeAdapterError("offline runtime requires an explicit keyless LLMConfig")
    if type(config.model) is not str or not config.model.strip():
        raise RuntimeAdapterError("offline runtime requires an explicit model")
    try:
        if type(config.base_url) is not str or not validate_provider_url(config.base_url, "base_url"):
            raise ValueError("missing base URL")
    except ValueError as error:
        raise RuntimeAdapterError("offline runtime requires a valid non-secret provider URL") from error
    return config


@contextmanager
def headless_runtime_scope(*, adapter_factory: Callable[[LLMConfig], ModelAdapter],
                           config: LLMConfig | None = None, offline: bool = False) -> Iterator[None]:
    """Override one local command's route runtime; never enabled by HTTP input."""
    if _active.get() is not None:
        raise RuntimeAdapterError("headless runtime scopes cannot be nested")
    if not callable(adapter_factory) or (config is not None and not isinstance(config, LLMConfig)):
        raise RuntimeAdapterError("invalid explicit headless runtime")
    runtime = _Runtime(adapter_factory, config, offline)
    if offline:
        runtime.model_adapter(_offline_config(config))
    token = _active.set(runtime)
    try:
        yield
    finally:
        with runtime.lock:
            runtime.closed = True
        _active.reset(token)


def resolve_config(default_loader: Callable[[], LLMConfig]) -> LLMConfig:
    runtime = _active.get()
    if runtime is None:
        return default_loader()
    with runtime.lock:
        runtime.check()
        config = runtime.config if runtime.config is not None else default_loader()
        runtime.check(config)
        return config


def make_adapter(config: LLMConfig, *, default_factory: Callable[[LLMConfig], ModelAdapter]) -> ModelAdapter:
    runtime = _active.get()
    return default_factory(config) if runtime is None else runtime.model_adapter(config)


def runtime_configured(config: LLMConfig) -> bool:
    runtime = _active.get()
    if runtime is not None:
        runtime.check(config)
        if runtime.offline:
            return True  # Its keyless config and exact adapter were admitted on scope entry.
    return config.is_configured()


def runtime_config_identity(config: LLMConfig) -> dict:
    """Only runtime semantics used for durable recovery; no key or config source."""
    return {name: getattr(config, name) for name in (
        "base_url", "model", "provider_id", "provider_name", "timeout_s",
        "context_window_tokens", "supports_1m", "supports_vision",
    )}
