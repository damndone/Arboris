"""Thinking and context are per model: detected from the provider, chosen in the Agent's model menu (v1.9.1).

Thinking was only the WORKBENCH_REASONING_EFFORT variable, which still wins so
evaluation rounds compare configurations whatever a person stored. A model's
window and efforts are read from the provider's model list when it reports
them (Magpie/WorkBuddy does); the person's context limit is kept apart from
the model's window, which it only caps.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.http import llm_routes
from workbench.llm.client import _chat_request_payload, reported_capabilities
from workbench.llm.config import LLMConfig, load_llm_config
from workbench.llm.provider_store import load_provider_store, model_from_dict

#: The Magpie/WorkBuddy model list for the three free models, as served 2026-10-22 (abridged).
LISTED = [
    {"id": "workbuddy-ai/deepseek-v4.1-flash", "owned_by": "workbuddy", "context_length": 1000000, "reasoning": True,
     "reasoning_levels": ["low", "high", "max"], "modalities": {"input": ["text", "image"], "output": ["text"]}},
    {"id": "workbuddy-ai/hy3", "owned_by": "workbuddy", "context_length": 192000, "reasoning": True,
     "reasoning_levels": ["low", "high"], "modalities": {"input": ["text", "image"], "output": ["text"]}},
    {"id": "workbuddy-ai/step-5-preview", "owned_by": "workbuddy", "context_length": 1000000, "reasoning": True,
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}, {"effort": "high"}]},
]


def _model(request_model, **fields):
    return model_from_dict({"display_name": request_model, "request_model": request_model, **fields})


def test_an_undeclared_model_takes_the_efforts_its_id_implies():
    assert _model("workbuddy-ai/deepseek-v4.1-flash").reasoning_efforts == ("none", "low", "high", "max")
    assert _model("glm-5.3-flash-free").reasoning_efforts == ()
    assert _model("deepseek-flash", supports_reasoning_effort=False).reasoning_efforts == ()  # the earlier boolean
    record = _model("deepseek-flash", reasoning_effort="max", context_limit_tokens=128_000)
    assert model_from_dict(record.to_dict()) == record
    assert _model("glm-5.3-flash-free", reasoning_effort="max").reasoning_effort is None  # not offered
    with pytest.raises(ValueError, match="reasoning_efforts"):
        _model("x", reasoning_efforts=["extreme"])


def test_the_context_limit_caps_the_models_window_without_replacing_it():
    capped = _model("m", context_window_tokens=1_000_000, supports_1m=True, context_limit_tokens=256_000)
    assert capped.context_window_tokens == 1_000_000 and capped.effective_window_tokens == 256_000
    assert _model("m", supports_1m=True).effective_window_tokens == 1_000_000
    assert _model("m", context_window_tokens=192_000, context_limit_tokens=256_000).effective_window_tokens == 192_000


def _payload(monkeypatch, effort, *, env=None, efforts=None, model="workbuddy-ai/deepseek-v4.1-flash"):
    if env is None:
        monkeypatch.delenv("WORKBENCH_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("WORKBENCH_REASONING_EFFORT", env)
    config = LLMConfig(base_url="http://127.0.0.1:3425/v1", api_key="k", model=model,
                       reasoning_efforts=efforts, reasoning_effort=effort)
    return _chat_request_payload([{"role": "user", "content": "hi"}], config, None)


def test_the_stored_effort_is_sent_and_the_variable_still_wins(monkeypatch):
    assert _payload(monkeypatch, "max")["reasoning_effort"] == "max"
    off = _payload(monkeypatch, "none")
    assert off["thinking"] == {"type": "disabled"} and "reasoning_effort" not in off
    assert _payload(monkeypatch, None)["reasoning_effort"] == "high"
    forced = _payload(monkeypatch, "max", env="none")
    assert forced["thinking"] == {"type": "disabled"} and "reasoning_effort" not in forced


def test_a_model_without_efforts_gets_none_and_one_without_high_gets_its_strongest(monkeypatch):
    payload = _payload(monkeypatch, None, efforts=())
    assert "reasoning_effort" not in payload and "thinking" not in payload
    assert _payload(monkeypatch, None, efforts=("low", "medium"), model="other")["reasoning_effort"] == "medium"


def test_the_listing_reports_window_efforts_and_images_and_nothing_it_does_not_say():
    assert reported_capabilities(LISTED[1]) == {"context_window_tokens": 192000, "reasoning_efforts": ["low", "high"],
                                                "supports_vision": True}
    assert reported_capabilities(LISTED[2])["reasoning_efforts"] == ["low", "medium", "high"]
    assert reported_capabilities({"id": "deepseek-chat", "owned_by": "deepseek"}) == {}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "llm-providers.json"))
    return TestClient(app)


def _create(api, models):
    response = api.post("/llm/providers", json={"id": "magpie", "name": "Magpie", "base_url": "http://127.0.0.1:3425/v1",
                                                "model": models[0]["request_model"], "api_key": "sk-test", "models": models})
    assert response.status_code == 200, response.text
    assert api.post("/llm/providers/magpie/activate").status_code == 200


def test_the_model_menu_saves_effort_and_limit_on_the_provider(api):
    model = {"display_name": "Flash", "request_model": "deepseek-flash", "supports_1m": True}
    _create(api, [model])
    updated = api.put("/llm/providers/magpie", json={"models": [{**model, "reasoning_effort": "max",
                                                                 "context_limit_tokens": 128_000}]})
    assert updated.status_code == 200, updated.text
    stored = load_provider_store().providers[0].models[0]
    assert stored.reasoning_effort == "max" and stored.context_limit_tokens == 128_000
    assert stored.supports_1m and load_llm_config().context_window_tokens == 128_000  # the Agent's working window
    assert api.put("/llm/providers/magpie", json={"models": [{**model, "reasoning_effort": "extreme"}]}).status_code == 422


def test_detection_updates_the_configured_models_only_and_keeps_the_choices(api, monkeypatch):
    _create(api, [
        {"display_name": "Flash", "request_model": "workbuddy-ai/deepseek-v4.1-flash", "reasoning_effort": "max",
         "context_limit_tokens": 256_000},
        {"display_name": "Hy3", "request_model": "workbuddy-ai/hy3"},
        {"display_name": "Step", "request_model": "workbuddy-ai/step-5-preview", "context_window_tokens": 128_000},
    ])
    monkeypatch.setattr(llm_routes, "fetch_models", lambda config: [{**item, **reported_capabilities(item)} for item in LISTED]
                        + [{"id": "workbuddy-ai/other", "owned_by": "x"}])
    response = api.post("/llm/providers/magpie/models/detect")
    assert response.status_code == 200, response.text
    flash, hy3, step = load_provider_store().providers[0].models
    assert len(load_provider_store().providers[0].models) == 3  # nothing added
    assert flash.reasoning_efforts == ("none", "low", "high", "max") and flash.reasoning_effort == "max"
    assert flash.context_window_tokens == 1_000_000 and flash.context_limit_tokens == 256_000
    assert hy3.reasoning_efforts == ("low", "high") and hy3.context_window_tokens == 192_000 and not hy3.supports_1m
    assert step.reasoning_efforts == ("low", "medium", "high") and step.supports_1m


def test_an_evaluation_run_can_pick_another_model_of_the_provider(api, monkeypatch):
    _create(api, [{"display_name": "Flash", "request_model": "workbuddy-ai/deepseek-v4.1-flash"},
                  {"display_name": "Hy3", "request_model": "workbuddy-ai/hy3", "context_window_tokens": 192_000,
                   "reasoning_efforts": ["low", "high"]}])
    monkeypatch.setenv("WORKBENCH_AGENT_MODEL", "workbuddy-ai/hy3")
    config = load_llm_config()
    assert config.model == "workbuddy-ai/hy3" and config.context_window_tokens == 192_000
    assert config.reasoning_efforts == ("low", "high")
    assert load_provider_store().providers[0].model == "workbuddy-ai/deepseek-v4.1-flash"  # the selection is unchanged
    monkeypatch.setenv("WORKBENCH_AGENT_MODEL", "not-listed")
    assert not load_llm_config().is_configured()
