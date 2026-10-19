"""agent route runtime: extracted HTTP responsibility."""
from __future__ import annotations
from ..agent.model import OpenAICompatibleModelAdapter
from ..agent.runtime_adapter import make_adapter as _runtime_model_adapter, resolve_config as _runtime_llm_config, runtime_configured as _runtime_configured
from ..agent.turn_runtime import turn_registry
from ..llm.config import load_llm_config

MAX_CONTEXT_CHARS = 24_000


MAX_QUESTION_CHARS = 4_000


_ACTIVE_TURNS = turn_registry.active


_RESERVED_TURNS = turn_registry.reserved


_TURN_RESERVATION_LOCK = turn_registry.lock


_reserve_turn = turn_registry.reserve


_release_turn = turn_registry.release


def _agent_llm_config():
    # Resolve aliases at call time to preserve existing route injection callers.
    return _runtime_llm_config(load_llm_config)


def _agent_model_adapter(config):
    return _runtime_model_adapter(config, default_factory=OpenAICompatibleModelAdapter)


def _agent_llm_configured(config):
    return _runtime_configured(config)

