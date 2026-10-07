"""Draft discovery must not need a model name or persist credentials."""

import httpx
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.llm import client as llm_client
from workbench.llm.config import LLMConfig


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    store = tmp_path / "providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(store))
    requests = []

    def install(response):
        def handle(request):
            requests.append(request)
            return response
        monkeypatch.setattr(llm_client, "_client_factory", lambda _config: httpx.Client(
            transport=httpx.MockTransport(handle)))

    install(httpx.Response(200, json={"data": [{"id": "vendor-next-flash"}, {"id": "vendor-research"}]}))
    return TestClient(app), store, requests, install


def test_draft_discovery_without_model_returns_upstream_ids_without_saving(discovery):
    api, store, requests, _ = discovery
    response = api.post("/llm/providers/models/discover", json={
        "base_url": "https://provider.example/v1", "api_key": "draft-secret", "timeout_s": 30,
    })
    assert response.status_code == 200, response.text
    assert [m["request_model"] for m in response.json()["models"]] == ["vendor-next-flash", "vendor-research"]
    assert str(requests[0].url) == "https://provider.example/v1/models"
    assert requests[0].headers["authorization"] == "Bearer draft-secret"
    assert "draft-secret" not in response.text
    assert not store.exists()
    assert not store.with_suffix(".json.lock").exists()


def test_models_metadata_fetch_does_not_require_a_selected_chat_model(discovery):
    _, _, requests, _ = discovery
    result = llm_client.fetch_models(LLMConfig("https://provider.example", "draft-secret", ""))
    assert result[0]["id"] == "vendor-next-flash"
    assert requests


@pytest.mark.parametrize("patch", [
    {"base_url": "file:///tmp/private"},
    {"base_url": "https://user:secret@provider.example"},
    {"timeout_s": 601}, {"api_key": ""}, {"model": "invented-model"},
])
def test_invalid_draft_is_rejected_without_upstream_or_secret_echo(discovery, patch):
    api, store, requests, _ = discovery
    response = api.post("/llm/providers/models/discover", json={
        "base_url": "https://provider.example", "api_key": "draft-secret", **patch,
    })
    assert response.status_code == 422
    assert not requests
    assert "draft-secret" not in response.text
    assert not store.exists()


def test_upstream_failure_is_sanitized_and_does_not_save(discovery):
    api, store, _, install = discovery
    install(httpx.Response(401, text="credential draft-secret refused"))
    response = api.post("/llm/providers/models/discover", json={
        "base_url": "https://provider.example", "api_key": "draft-secret",
    })
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_UPSTREAM_ERROR"
    assert "draft-secret" not in response.text
    assert not store.exists()


def test_empty_discovery_is_explicit_without_inventing_models(discovery):
    api, store, _, install = discovery
    install(httpx.Response(200, json={"data": []}))
    response = api.post("/llm/providers/models/discover", json={
        "base_url": "https://provider.example", "api_key": "draft-secret",
    })
    assert response.status_code == 200, response.text
    assert response.json()["models"] == []
    assert "manually" in response.json()["message"]
    assert not store.exists()
