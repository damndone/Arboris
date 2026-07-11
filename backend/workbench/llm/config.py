"""LLM provider configuration, resolved from the environment per request.

Per-request resolution (no module-level cache) keeps tests monkeypatchable and
lets a running server pick up key changes without restart.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = DEFAULT_TIMEOUT_S

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_llm_config() -> LLMConfig:
    raw_timeout = os.environ.get("WORKBENCH_LLM_TIMEOUT_S", "")
    try:
        timeout_s = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_S
    except ValueError:
        timeout_s = DEFAULT_TIMEOUT_S
    return LLMConfig(
        base_url=os.environ.get("WORKBENCH_LLM_BASE_URL", "").rstrip("/"),
        api_key=os.environ.get("WORKBENCH_LLM_API_KEY", ""),
        model=os.environ.get("WORKBENCH_LLM_MODEL", ""),
        timeout_s=timeout_s,
    )
