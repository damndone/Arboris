"""Thinking effort is a choice per model, made in the Agent's model menu (v1.9.1).

It was only the WORKBENCH_REASONING_EFFORT variable; the variable still wins, so
evaluation rounds compare configurations whatever a person stored.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.llm.client import _chat_request_payload
from workbench.llm.config import LLMConfig
from workbench.llm.provider_store import load_provider_store, model_from_dict


def _model(request_model, **fields):
    return model_from_dict({"display_name": request_model, "request_model": request_model, **fields})


def test_an_undeclared_model_takes_thinking_by_its_id():
    assert _model("workbuddy-ai/deepseek-v4.1-flash").supports_reasoning_effort
    assert _model("deepseek-flash").supports_reasoning_effort
    assert not _model("glm-5.3-flash-free").supports_reasoning_effort
    assert not _model("deepseek-flash", supports_reasoning_effort=False).supports_reasoning_effort
    record = _model("deepseek-flash", reasoning_effort="max")
    assert record.reasoning_effort == "max" and model_from_dict(record.to_dict()) == record
    with pytest.raises(ValueError, match="reasoning_effort"):
        _model("deepseek-flash", reasoning_effort="extreme")


def _payload(monkeypatch, effort, *, env=None, supports=None, model="workbuddy-ai/deepseek-v4.1-flash"):
    if env is None:
        monkeypatch.delenv("WORKBENCH_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("WORKBENCH_REASONING_EFFORT", env)
    config = LLMConfig(base_url="http://127.0.0.1:3425/v1", api_key="k", model=model,
                       supports_reasoning_effort=supports, reasoning_effort=effort)
    return _chat_request_payload([{"role": "user", "content": "hi"}], config, None)


def test_the_stored_effort_is_sent_and_the_variable_still_wins(monkeypatch):
    assert _payload(monkeypatch, "max")["reasoning_effort"] == "max"
    off = _payload(monkeypatch, "none")
    assert off["thinking"] == {"type": "disabled"} and "reasoning_effort" not in off
    assert _payload(monkeypatch, None)["reasoning_effort"] == "high"
    forced = _payload(monkeypatch, "max", env="none")
    assert forced["thinking"] == {"type": "disabled"} and "reasoning_effort" not in forced


def test_a_model_declared_without_thinking_gets_no_effort(monkeypatch):
    payload = _payload(monkeypatch, "max", supports=False)
    assert "reasoning_effort" not in payload and "thinking" not in payload
    assert "reasoning_effort" in _payload(monkeypatch, "low", supports=True, model="some-other-model")


def test_the_model_menu_saves_effort_and_context_on_the_provider(tmp_path, monkeypatch):
    path = tmp_path / "llm-providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(path))
    api = TestClient(app)
    model = {"display_name": "Flash", "request_model": "deepseek-flash", "supports_1m": True}
    created = api.post("/llm/providers", json={"id": "ds", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                                               "model": "deepseek-flash", "api_key": "sk-test", "models": [model]})
    assert created.status_code == 200, created.text
    listed = created.json()["models"][0]
    assert listed["supports_reasoning_effort"] is True and listed["reasoning_effort"] is None
    updated = api.put("/llm/providers/ds", json={"models": [{**model, "reasoning_effort": "max",
                                                             "context_window_tokens": 1_000_000}]})
    assert updated.status_code == 200, updated.text
    stored = load_provider_store().providers[0].models[0]
    assert stored.reasoning_effort == "max" and stored.context_window_tokens == 1_000_000
    refused = api.put("/llm/providers/ds", json={"models": [{**model, "reasoning_effort": "extreme"}]})
    assert refused.status_code == 422
