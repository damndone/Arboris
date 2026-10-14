"""What the Agent is told about itself comes from the live configuration."""
from __future__ import annotations

import pytest

from workbench.agent.identity import identity_text, provider_label
from workbench.llm.config import LLMConfig
from workbench.llm.provider_store import environment_provider_from_env


def config(**overrides):
    values = dict(base_url="https://api.deepseek.com/v1", api_key="k", model="deepseek-flash",
                  provider_id="environment", provider_name="Environment")
    values.update(overrides)
    return LLMConfig(**values)


def test_an_environment_provider_is_named_by_its_host_not_the_config_id():
    assert provider_label(config()) == "DeepSeek (api.deepseek.com)"
    assert provider_label(config(base_url="https://llm.example.org/v1")) == "llm.example.org"
    assert provider_label(config(provider_id="p1", provider_name="Lab gateway")) == "Lab gateway (api.deepseek.com)"
    text = identity_text("chain", config())
    assert "'environment'" not in text and "DeepSeek (api.deepseek.com)" in text and "'deepseek-flash'" in text


def test_the_context_window_is_stated_only_when_declared():
    assert "does not declare your context window" in identity_text("main", config())
    assert "128,000 tokens" in identity_text("main", config(context_window_tokens=128_000))


def test_memory_and_instructions_are_described_as_they_are():
    text = identity_text("chain", config())
    assert "Workbench Chain Agent" in text and "no automatic long-term memory" in text and "AGENTS.md" in text
    assert "append-only log" in text and "analysis ledger" in text
    assert "not secret" in text and "agent_routes.py" in text
    assert "Workbench Global Agent" in identity_text("main", config())


@pytest.mark.parametrize("raw, expected", [("128000", 128_000), ("1_000_000", 1_000_000), ("", None), ("lots", None), ("12", None)])
def test_the_environment_provider_reads_a_declared_context_window(monkeypatch, raw, expected):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "test-key")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("WORKBENCH_LLM_CONTEXT_WINDOW", raw)
    provider = environment_provider_from_env()
    assert provider.models[0].context_window_tokens == expected
