"""Provider-agnostic LLM access (v1.6.11 slice A).

Single wire protocol: OpenAI-compatible Chat Completions. The provider is
runtime configuration (``WORKBENCH_LLM_BASE_URL`` / ``_API_KEY`` / ``_MODEL``),
never code — swapping DeepSeek for any other vendor is an env change.
"""
from .client import LLMNotConfiguredError, LLMUpstreamError, chat_completion
from .config import LLMConfig, load_llm_config

__all__ = [
    "LLMConfig",
    "LLMNotConfiguredError",
    "LLMUpstreamError",
    "chat_completion",
    "load_llm_config",
]
