"""LLM provider management APIs (all upstream calls stay offline)."""
from __future__ import annotations

import json
import asyncio
import hashlib
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread

import httpx
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.http import llm_routes
from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
from workbench.llm import client as llm_client
from workbench.llm.client import LLMConfig, LLMUpstreamError
from workbench.llm.config import load_llm_config
from workbench.llm.provider_store import (
    ModelRecord,
    ProviderRecord,
    ProviderStore,
    load_provider_store,
    save_provider_store,
)
from tests.test_v189_provider_egress import host as egress_host


def _admit_synthetic_payload(host, config, payload, **grant_limits):
    """Test host resolves only synthetic fixture content, never project files."""
    from workbench.services.provider_egress import provider_payload_bytes
    authority, handle, now = host
    digest = hashlib.sha256(provider_payload_bytes(payload)).hexdigest()
    source = ("source:synthetic-protocol-fixture", digest, "user_text")
    authority.classify(authority_handle=handle, source_ref=source[0],
        source_digest=digest, category=source[2], sensitivity="public")
    provider_ref = llm_client.provider_egress_ref(config)
    grant = authority.grant(authority_handle=handle, provider_ref=provider_ref,
        purpose_ref="purpose:protocol-test", categories=("user_text",),
        allowed_sensitivity=("public",), expires_at=now[0] + timedelta(minutes=5), **grant_limits)
    assembly = authority.mint_trusted_assembly(authority_handle=handle,
        project_ref="project:egress", payload=payload, sources=(source,), admitted_rows=0)
    admission = authority.prepare(project_ref="project:egress", provider_ref=provider_ref,
        purpose_ref="purpose:protocol-test", assembly=assembly)
    return admission, grant


def _admit_synthetic_request(host, config, request):
    from workbench.agent.model import _to_openai_wire_messages, _to_openai_tool_descriptors
    payload = llm_client._chat_request_payload(_to_openai_wire_messages(request.messages), config,
        _to_openai_tool_descriptors(request.tools), model_config=request.model_config, stream=True)
    admission, grant = _admit_synthetic_payload(host, config, payload)
    return replace(request, provider_admission=admission), grant, payload


@pytest.fixture
def admitted_adapter(egress_host):
    """Real adapter/security boundary with explicitly admitted synthetic inputs."""
    def make(config, *, adapter_type=OpenAICompatibleModelAdapter, **kwargs):
        class SyntheticFixtureAdapter(adapter_type):
            async def stream(self, request):
                admitted, _grant, _payload = _admit_synthetic_request(egress_host, self.config, request)
                async for event in super().stream(admitted):
                    yield event
        return SyntheticFixtureAdapter(config, project_ref="project:egress",
            purpose_ref="purpose:protocol-test", **kwargs)
    return make


@pytest.fixture
def admitted_stream(egress_host):
    async def stream(messages, config, *, tools=None, model_config=None):
        payload = llm_client._chat_request_payload(messages, config, tools,
            model_config=model_config, stream=True)
        admission, _grant = _admit_synthetic_payload(egress_host, config, payload)
        async for event in llm_client.async_stream_chat_completion(messages, config,
                tools=tools, model_config=model_config, provider_admission=admission,
                project_ref="project:egress", purpose_ref="purpose:protocol-test"):
            yield event
    return stream


def test_admitted_agent_sends_exact_bytes_and_revocation_blocks_replay(monkeypatch, egress_host):
    from workbench.services.provider_egress import provider_payload_bytes
    seen = _install_async_upstream(monkeypatch, lambda request: httpx.Response(200,
        content=b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'))
    config = LLMConfig(base_url="https://provider.example/v1", api_key="test-only", model="test")
    request, grant, payload = _admit_synthetic_request(egress_host, config,
        ModelRequest(messages=[{"role": "user", "content": "synthetic e\u0301"}]))
    adapter = OpenAICompatibleModelAdapter(config, project_ref="project:egress",
        purpose_ref="purpose:protocol-test")

    async def run():
        return [event async for event in adapter.stream(request)]

    events = asyncio.run(run())
    assert events[-1].type == "done", events
    assert len(seen) == 1 and seen[0].content == provider_payload_bytes(payload)
    authority, handle, _ = egress_host
    authority.revoke(authority_handle=handle, grant_id=grant)
    denied = asyncio.run(run())
    assert len(seen) == 1
    assert denied[-1].error == "EGRESS_GRANT_REQUIRED"


@pytest.mark.parametrize("attack,code", [
    ("payload", "EGRESS_PAYLOAD_MISMATCH"), ("project", "EGRESS_SCOPE_MISMATCH"),
    ("purpose", "EGRESS_SCOPE_MISMATCH"), ("provider", "EGRESS_SCOPE_MISMATCH"),
    ("credential", "EGRESS_SCOPE_MISMATCH"), ("forged", "EGRESS_ADMISSION_REQUIRED"),
    ("expired", "EGRESS_GRANT_REQUIRED"), ("reclassified", "EGRESS_SOURCE_CLASSIFICATION_REQUIRED"),
])
def test_send_mutations_reject_before_transport(monkeypatch, egress_host, attack, code):
    from workbench.services.provider_egress import provider_payload_bytes
    seen = _install_async_upstream(monkeypatch, lambda request: pytest.fail("unauthorized HTTP send"))
    config = LLMConfig(base_url="https://provider.example/v1", api_key="test-only", model="test")
    request, _grant, payload = _admit_synthetic_request(egress_host, config,
        ModelRequest(messages=[{"role": "user", "content": "synthetic"}]))
    project, purpose = "project:egress", "purpose:protocol-test"
    if attack == "payload":
        request.messages[0]["content"] = "changed historical content"
    elif attack == "project": project = "project:foreign"
    elif attack == "purpose": purpose = "purpose:foreign"
    elif attack == "provider": config = replace(config, base_url="https://foreign.example/v1")
    elif attack == "credential": config = replace(config, api_key="changed-test-key")
    elif attack == "forged": request = replace(request, provider_admission={"approved": True})
    elif attack == "expired": egress_host[2][0] += timedelta(minutes=5)
    elif attack == "reclassified":
        egress_host[0].classify(authority_handle=egress_host[1],
            source_ref="source:synthetic-protocol-fixture",
            source_digest=hashlib.sha256(provider_payload_bytes(payload)).hexdigest(),
            category="conversation", sensitivity="restricted")

    async def run():
        return [event async for event in OpenAICompatibleModelAdapter(config,
            project_ref=project, purpose_ref=purpose).stream(request)]

    events = asyncio.run(run())
    assert seen == [] and len(events) == 1 and events[0].error == code


def test_retry_rechecks_revocation_instead_of_replaying_admitted_body(monkeypatch, egress_host):
    config = LLMConfig(base_url="https://provider.example/v1", api_key="test-only", model="test")
    request, grant, _payload = _admit_synthetic_request(egress_host, config,
        ModelRequest(messages=[{"role": "user", "content": "synthetic"}]))

    def revoke_and_retry(_request):
        egress_host[0].revoke(authority_handle=egress_host[1], grant_id=grant)
        return httpx.Response(503)

    seen = _install_async_upstream(monkeypatch, revoke_and_retry)

    async def run():
        return [event async for event in OpenAICompatibleModelAdapter(config,
            project_ref="project:egress", purpose_ref="purpose:protocol-test").stream(request)]

    events = asyncio.run(run())
    assert len(seen) == 1 and events[-1].error == "EGRESS_GRANT_REQUIRED"


def test_provider_stream_stops_at_granted_total_time_budget(monkeypatch, egress_host):
    from workbench.services.provider_egress import ProviderEgressError
    config = LLMConfig(base_url="https://provider.example/v1", api_key="test-only", model="test", timeout_s=60)
    messages = [{"role": "user", "content": "synthetic"}]
    payload = llm_client._chat_request_payload(messages, config, None, stream=True)
    admission, _grant = _admit_synthetic_payload(egress_host, config, payload, timeout_ms=20)
    cancelled = []

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                await asyncio.sleep(0.2)
                yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

    _install_async_upstream(monkeypatch,
        lambda request: httpx.Response(200, stream=SlowStream()))

    async def run():
        with pytest.raises(ProviderEgressError, match="EGRESS_TIME_BUDGET_EXCEEDED"):
            async for _ in llm_client.async_stream_chat_completion(messages, config,
                    provider_admission=admission, project_ref="project:egress",
                    purpose_ref="purpose:protocol-test"):
                pass
    asyncio.run(run())
    assert cancelled == [True]

API_KEY = "sk-provider-secret"


def test_provider_egress_identity_binds_effective_destination_and_credential():
    from dataclasses import replace
    identity = getattr(llm_client, "provider_egress_ref", None)
    assert callable(identity), "provider grant has no effective destination binding"
    config = LLMConfig(base_url="https://provider.example/v1", api_key="test-only", model="test")
    ref = identity(config)
    assert ref == identity(replace(config, timeout_s=config.timeout_s + 1))
    assert "test-only" not in ref and "provider.example" not in ref
    for changes in ({"base_url": "https://other.example/v1"}, {"model": "other"},
                    {"api_key": "other-test-key"}, {"provider_id": "other-account"}):
        assert identity(replace(config, **changes)) != ref


def test_agent_send_without_host_admission_never_opens_transport(monkeypatch):
    opened = []

    def forbidden_transport(config):
        opened.append(config.model)
        raise AssertionError("unadmitted provider request reached transport")

    monkeypatch.setattr(llm_client, "_async_client_factory", forbidden_transport)
    config = LLMConfig(base_url="https://provider.example/v1", api_key="test-only", model="test")

    async def run():
        return [event async for event in OpenAICompatibleModelAdapter(config).stream(
            ModelRequest(messages=[{"role": "user", "content": "local project result"}]))]

    events = asyncio.run(run())
    assert opened == [], "an API key is not authority to send project content"
    assert len(events) == 1 and events[0].type == "error"
    assert events[0].error == "EGRESS_ADMISSION_REQUIRED"


@pytest.fixture
def api() -> TestClient:
    return TestClient(app)


@pytest.fixture
def store_path(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "llm-providers.json"
    monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(path))
    return path


def _provider_payload(**overrides) -> dict:
    payload = {
        "id": "deepseek",
        "name": "DeepSeek",
        "icon": "deepseek-mark",
        "notes": "Primary research provider",
        "website_url": "https://platform.deepseek.com",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": API_KEY,
        "timeout_s": 30,
        "models": [
            {
                "display_name": "DeepSeek Chat",
                "request_model": "deepseek-chat",
                "context_window_tokens": 128000,
                "supports_1m": False,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _create(api: TestClient, **overrides) -> dict:
    response = api.post("/llm/providers", json=_provider_payload(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def test_create_and_list_return_only_public_provider_data(api, store_path):
    created = _create(api)

    assert created["id"] == "deepseek"
    assert created["icon"] == "deepseek-mark"
    assert created["notes"] == "Primary research provider"
    assert created["key_present"] is True
    assert "api_key" not in created
    assert API_KEY not in json.dumps(created)

    listed = api.get("/llm/providers")
    assert listed.status_code == 200
    assert listed.json() == {
        "active_provider_id": None,
        "providers": [created],
    }
    assert API_KEY not in listed.text

    stored = load_provider_store(store_path)
    assert stored.providers[0].api_key == API_KEY
    assert stored.providers[0].icon == "deepseek-mark"
    assert stored.providers[0].notes == "Primary research provider"


def test_environment_provider_is_visible_and_publishes_only_its_configured_model(
    api, store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", API_KEY)
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-v4-flash")

    listed = api.get("/llm/providers")
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["active_provider_id"] == "environment"
    # The environment variables *declare* one model; listing is not a
    # capability-discovery protocol. Inferring extra vendor models from the
    # base URL would offer a model this credential was never configured for.
    # A genuine second choice can only arrive from the provider itself, via
    # POST /llm/providers/{id}/models/refresh.
    assert [
        model["request_model"] for model in payload["providers"][0]["models"]
    ] == ["deepseek-v4-flash"]
    assert API_KEY not in listed.text


def test_environment_provider_model_switch_materializes_local_settings(
    api, store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", API_KEY)
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-v4-flash")

    # An explicit operator write is the authoritative channel for `model`, so it
    # is taken as given rather than checked against the published catalog.
    updated = api.put(
        "/llm/providers/environment",
        json={"model": "deepseek-v4-pro"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["model"] == "deepseek-v4-pro"
    # The partial update omits `models`, so the bootstrapped catalog survives
    # verbatim: switching the request model must not silently invent entries.
    assert [model["request_model"] for model in updated.json()["models"]] == [
        "deepseek-v4-flash"
    ]
    assert load_provider_store(store_path).active_provider_id == "environment"
    assert load_llm_config().source == "local"
    assert load_llm_config().model == "deepseek-v4-pro"


def test_update_preserves_and_can_replace_management_metadata(api, store_path):
    _create(api)

    preserved = api.put(
        "/llm/providers/deepseek",
        json={"name": "DeepSeek Updated"},
    )
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["icon"] == "deepseek-mark"
    assert preserved.json()["notes"] == "Primary research provider"

    replaced = api.put(
        "/llm/providers/deepseek",
        json={"icon": "new-mark", "notes": "Updated context"},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["icon"] == "new-mark"
    assert replaced.json()["notes"] == "Updated context"
    stored = load_provider_store(store_path).providers[0]
    assert stored.icon == "new-mark"
    assert stored.notes == "Updated context"


def test_public_urls_redact_legacy_userinfo_and_query(api, store_path, monkeypatch):
    for name in (
        "WORKBENCH_LLM_BASE_URL",
        "WORKBENCH_LLM_API_KEY",
        "WORKBENCH_LLM_MODEL",
        "WORKBENCH_LLM_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    save_provider_store(
        ProviderStore(
            active_provider_id="legacy",
            providers=[
                ProviderRecord(
                    id="legacy",
                    name="Legacy",
                    website_url=(
                        "https://website-user:website-secret@example.com/"
                        "?token=website-query"
                    ),
                    base_url="https://user:secret@example.com/v1?token=x",
                    model="legacy-model",
                    api_key="legacy-key",
                    models=[ModelRecord("Legacy", "legacy-model")],
                )
            ],
        )
    )

    providers = api.get("/llm/providers")
    config = api.get("/llm/config")

    assert providers.status_code == 200, providers.text
    assert config.status_code == 200, config.text
    assert providers.json()["providers"][0]["website_url"] == "https://example.com/"
    assert providers.json()["providers"][0]["base_url"] == "https://example.com/v1"
    assert config.json()["base_url"] is None
    for response in (providers, config):
        assert "secret" not in response.text
        assert "token=x" not in response.text
        assert "website-secret" not in response.text
        assert "website-query" not in response.text


@pytest.mark.parametrize(
    "website_url",
    [
        "/relative",
        "ftp://example.com",
        "https://example.com/path with space",
        "https://user:password@example.com",
        "https://example.com/path?token=secret",
        "https://example.com/path#fragment",
        "https://example.com:bad",
        "https://example.com:65536",
    ],
)
def test_provider_validation_rejects_unsafe_website_urls(api, website_url):
    response = api.post(
        "/llm/providers",
        json=_provider_payload(website_url=website_url),
    )

    assert response.status_code == 422, response.text


def test_bad_website_url_validation_error_hides_secret_and_query(api):
    website_url = "https://website-user:website-secret@example.com/?token=website-query"

    response = api.post(
        "/llm/providers",
        json=_provider_payload(website_url=website_url),
    )

    assert response.status_code == 422, response.text
    assert "website-secret" not in response.text
    assert "website-query" not in response.text


def test_provider_validation_normalizes_website_url_trailing_slash(api, store_path):
    response = api.post(
        "/llm/providers",
        json=_provider_payload(website_url="https://platform.deepseek.com///"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["website_url"] == "https://platform.deepseek.com"
    assert load_provider_store(store_path).providers[0].website_url == (
        "https://platform.deepseek.com"
    )


def test_malformed_legacy_website_url_becomes_null_without_leaking_query(
    api, store_path
):
    save_provider_store(
        ProviderStore(
            providers=[
                ProviderRecord(
                    id="legacy",
                    name="Legacy",
                    website_url="https://example.com:bad/?token=legacy-query",
                    base_url="https://example.com/v1",
                    model="legacy-model",
                    api_key="legacy-key",
                )
            ]
        )
    )

    response = api.get("/llm/providers")

    assert response.status_code == 200, response.text
    assert response.json()["providers"][0]["website_url"] is None
    assert "legacy-query" not in response.text


def test_provider_validation_rejects_bad_identity_url_and_timeout(api):
    cases = [
        {"id": "", "name": "Name", "model": "model"},
        {"id": "id", "name": "", "model": "model"},
        {"id": "id", "name": "Name", "model": ""},
        {"id": "id", "name": "Name", "model": "model", "base_url": "/relative"},
        {"id": "id", "name": "Name", "model": "model", "base_url": "ftp://host"},
        {"id": "id", "name": "Name", "model": "model", "timeout_s": 0},
    ]
    for overrides in cases:
        response = api.post("/llm/providers", json=_provider_payload(**overrides))
        assert response.status_code == 422, response.text


def test_provider_validation_rejects_timeout_above_maximum(api, store_path):
    response = api.post(
        "/llm/providers",
        json=_provider_payload(timeout_s=600.1),
    )

    assert response.status_code == 422, response.text


def test_provider_validation_rejects_duplicate_request_models_before_saving(
    api, store_path
):
    payload = _provider_payload(
        models=[
            {"display_name": "First", "request_model": "same-model"},
            {"display_name": "Second", "request_model": "same-model"},
        ]
    )

    response = api.post("/llm/providers", json=payload)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]
    assert not store_path.exists()


def test_create_rejects_clear_api_key_without_persisting_api_key(api, store_path):
    response = api.post(
        "/llm/providers",
        json=_provider_payload(clear_api_key=True),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"] == {
        "code": "LLM_PROVIDER_INVALID",
        "message": "clear_api_key is only valid when updating an existing provider.",
        "details": {"field": "clear_api_key"},
    }
    assert not store_path.exists()
    assert API_KEY not in response.text


def test_list_provider_store_invalid_file_returns_structured_error(api, store_path):
    store_path.write_text("{not json", encoding="utf-8")

    response = api.get("/llm/providers")

    assert response.status_code == 500, response.text
    assert response.json()["error"] == {
        "code": "LLM_PROVIDER_STORE_INVALID",
        "message": "LLM provider store is invalid.",
        "details": {},
    }


@pytest.mark.parametrize("provider_id", ["deep/seek", "deep seek", "deep?seek", "deep#seek"])
def test_provider_validation_rejects_unrouteable_ids_in_create_and_update(
    api, store_path, provider_id
):
    create = api.post("/llm/providers", json=_provider_payload(id=provider_id))
    assert create.status_code == 422, create.text

    update = api.put(
        "/llm/providers/deepseek",
        json={"id": provider_id},
    )
    assert update.status_code == 422, update.text


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("put", ""),
        ("delete", ""),
        ("post", "/activate"),
        ("post", "/models/refresh"),
        ("post", "/probe"),
    ],
)
def test_provider_path_operations_reject_unrouteable_ids(api, method, suffix):
    request = getattr(api, method)
    kwargs = {"json": {}} if method == "put" else {}

    response = request(f"/llm/providers/bad%3Fid{suffix}", **kwargs)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "base_url",
    [
        "http://:8080",
        "https://:8080/v1",
        "https://api.example.com/v1/path with space",
        "https://user:password@api.example.com/v1",
        "https://api.example.com/v1?api_key=secret",
        "https://api.example.com/v1#fragment",
        "https://api.example.com/v1?",
        "https://api.example.com/v1#",
        "https://api.example.com:bad/v1",
        "https://api.example.com:65536/v1",
    ],
)
def test_provider_validation_rejects_unsafe_base_urls(api, base_url):
    response = api.post("/llm/providers", json=_provider_payload(base_url=base_url))

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field_name", ["base_url", "website_url"])
@pytest.mark.parametrize("url", ["http://:8080", "https://:8080/v1"])
def test_provider_validation_rejects_urls_without_hostname(
    api, store_path, field_name, url
):
    response = api.post(
        "/llm/providers",
        json=_provider_payload(**{field_name: url}),
    )

    assert response.status_code == 422, response.text
    assert url not in response.text


def test_provider_validation_accepts_absolute_http_base_url(api, store_path):
    response = api.post(
        "/llm/providers",
        json=_provider_payload(id="local", base_url="http://localhost:8000/v1"),
    )

    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@example.com/v1",
        "https://api.example.com/v1?token=secret",
        "https://api.example.com/v1#fragment",
        "https://:8080/v1",
        "https://api.example.com:65536/v1",
        "https://api.example.com/v1 path",
        "https://[::1",
    ],
)
def test_probe_rejects_unsafe_legacy_provider_base_url_at_runtime(
    api, store_path, monkeypatch, base_url
):
    save_provider_store(
        ProviderStore(
            active_provider_id=None,
            providers=[
                ProviderRecord(
                    id="legacy",
                    name="Legacy",
                    base_url=base_url,
                    api_key=API_KEY,
                    model="legacy-model",
                )
            ],
        )
    )
    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda config: (_ for _ in ()).throw(
            AssertionError("unsafe provider URL must not reach upstream")
        ),
    )

    response = api.post("/llm/providers/legacy/probe")

    assert response.status_code == 422, response.text
    assert response.json()["error"] == {
        "code": "LLM_PROVIDER_INVALID",
        "message": "Provider base_url must be an absolute http or https URL.",
        "details": {"field": "base_url"},
    }


def test_load_llm_config_fails_closed_for_unsafe_active_legacy_base_url(
    store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")
    save_provider_store(
        ProviderStore(
            active_provider_id="legacy",
            providers=[
                ProviderRecord(
                    id="legacy",
                    name="Legacy",
                    base_url="https://legacy.example.com/v1?token=secret",
                    api_key=API_KEY,
                    model="legacy-model",
                )
            ],
        )
    )

    config = load_llm_config()

    assert config.base_url == ""
    assert config.api_key == ""
    assert config.model == ""
    assert config.is_configured() is False
    assert config.source == "explicit_config_unconfigured"


def test_load_llm_config_fails_closed_when_active_local_provider_is_unconfigured(
    store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")
    save_provider_store(
        ProviderStore(
            active_provider_id="local",
            providers=[
                ProviderRecord(
                    id="local",
                    name="Local",
                    base_url="https://local.example.com/v1",
                    api_key="",
                    model="local-model",
                )
            ],
        )
    )

    config = load_llm_config()

    assert config.source == "explicit_config_unconfigured"
    assert config.is_configured() is False
    assert config.base_url == ""


def test_unsafe_legacy_provider_cannot_be_activated(api, store_path):
    save_provider_store(
        ProviderStore(
            providers=[
                ProviderRecord(
                    id="legacy",
                    name="Legacy",
                    base_url="https://legacy.example.com/v1?token=secret",
                    api_key=API_KEY,
                    model="legacy-model",
                )
            ]
        )
    )

    response = api.post("/llm/providers/legacy/activate")

    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"] == {"fields": ["base_url"]}
    assert load_provider_store(store_path).active_provider_id is None


def test_unsafe_legacy_provider_does_not_open_environment_fallback(
    api, store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "environment-secret")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "environment-model")
    save_provider_store(
        ProviderStore(
            active_provider_id="active",
            providers=[
                ProviderRecord(
                    id="active",
                    name="Active",
                    base_url="https://active.example.com/v1",
                    api_key="active-secret",
                    model="active-model",
                ),
                ProviderRecord(
                    id="legacy",
                    name="Legacy",
                    base_url="https://legacy.example.com/v1?token=secret",
                    api_key=API_KEY,
                    model="legacy-model",
                ),
            ],
        )
    )

    deleted = api.delete("/llm/providers/active")

    assert deleted.status_code == 200, deleted.text
    assert api.get("/llm/providers").json()["active_provider_id"] is None
    config = api.get("/llm/config")
    assert config.status_code == 200, config.text
    assert config.json()["source"] == "explicit_config_unconfigured"
    assert config.json()["configured"] is False
    assert config.json()["base_url"] is None
    assert "environment-secret" not in config.text
    assert load_provider_store(store_path).active_provider_id is None


@pytest.mark.parametrize("source", ["legacy", "environment"])
def test_public_config_reports_whitespace_key_as_absent(
    api, store_path, monkeypatch, source
):
    if source == "legacy":
        for name in (
            "WORKBENCH_LLM_BASE_URL",
            "WORKBENCH_LLM_API_KEY",
            "WORKBENCH_LLM_MODEL",
            "WORKBENCH_LLM_TIMEOUT_S",
        ):
            monkeypatch.delenv(name, raising=False)
        save_provider_store(
            ProviderStore(
                active_provider_id="legacy",
                providers=[
                    ProviderRecord(
                        id="legacy",
                        name="Legacy",
                        base_url="https://legacy.example.com/v1",
                        api_key=" \t\n",
                        model="legacy-model",
                    )
                ],
            )
        )
    else:
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/v1")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", " \t\n")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "environment-model")

    listed = api.get("/llm/providers")
    config = api.get("/llm/config")

    assert listed.status_code == 200, listed.text
    assert config.status_code == 200, config.text
    if source == "legacy":
        assert listed.json()["providers"][0]["key_present"] is False
    assert config.json()["key_present"] is False


def test_update_blank_key_preserves_secret_and_clear_key_removes_it(api, store_path):
    _create(api)

    response = api.put(
        "/llm/providers/deepseek",
        json={"name": "DeepSeek Updated", "api_key": ""},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "DeepSeek Updated"
    assert response.json()["key_present"] is True
    assert API_KEY not in response.text
    assert load_provider_store(store_path).providers[0].api_key == API_KEY

    response = api.put(
        "/llm/providers/deepseek",
        json={"clear_api_key": True},
    )
    assert response.status_code == 200
    assert response.json()["key_present"] is False
    assert load_provider_store(store_path).providers[0].api_key == ""


def test_update_whitespace_key_preserves_secret(api, store_path):
    _create(api)

    response = api.put(
        "/llm/providers/deepseek",
        json={"api_key": " \t\n"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["key_present"] is True
    assert API_KEY not in response.text
    assert load_provider_store(store_path).providers[0].api_key == API_KEY


def test_create_whitespace_key_is_empty_and_cannot_activate(api, store_path):
    created = _create(api, api_key=" \t\n")

    assert created["key_present"] is False
    assert load_provider_store(store_path).providers[0].api_key == ""

    response = api.post("/llm/providers/deepseek/activate")

    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"] == {"fields": ["api_key"]}
    assert api.get("/llm/providers").json()["active_provider_id"] is None


@pytest.mark.parametrize("field_name", ["base_url", "api_key", "model"])
def test_activation_rejects_whitespace_only_configuration_fields(
    api, store_path, field_name
):
    values = {
        "base_url": "https://candidate.example.com/v1",
        "api_key": "candidate-secret",
        "model": "candidate-model",
    }
    values[field_name] = " \t\n"
    save_provider_store(
        ProviderStore(
            providers=[
                ProviderRecord(
                    id="candidate",
                    name="Candidate",
                    **values,
                )
            ]
        )
    )

    response = api.post("/llm/providers/candidate/activate")

    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"] == {"fields": [field_name]}
    assert load_provider_store(store_path).active_provider_id is None


def test_clear_key_takes_precedence_over_replacement_key(api, store_path):
    _create(api)

    response = api.put(
        "/llm/providers/deepseek",
        json={"api_key": "sk-replacement-secret", "clear_api_key": True},
    )

    assert response.status_code == 200
    assert response.json()["key_present"] is False
    assert load_provider_store(store_path).providers[0].api_key == ""


def test_activation_and_delete_keep_active_provider_id_valid(api, store_path):
    _create(api)
    _create(
        api,
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-openai-secret",
    )

    activated = api.post("/llm/providers/openai/activate")
    assert activated.status_code == 200
    assert activated.json()["id"] == "openai"
    assert api.get("/llm/providers").json()["active_provider_id"] == "openai"

    deleted = api.delete("/llm/providers/openai")
    assert deleted.status_code == 200
    assert deleted.json()["id"] == "openai"
    assert "api_key" not in deleted.json()
    assert api.get("/llm/providers").json()["active_provider_id"] == "deepseek"

    missing = api.delete("/llm/providers/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LLM_PROVIDER_NOT_FOUND"


@pytest.mark.parametrize("missing_field", ["base_url", "api_key", "model"])
def test_activation_rejects_unconfigured_provider_and_preserves_active(
    api, store_path, missing_field
):
    candidate_values = {
        "base_url": "https://candidate.example.com/v1",
        "api_key": "candidate-secret",
        "model": "candidate-model",
    }
    candidate_values[missing_field] = ""
    save_provider_store(
        ProviderStore(
            active_provider_id="active",
            providers=[
                ProviderRecord(
                    id="active",
                    name="Active",
                    base_url="https://active.example.com/v1",
                    api_key="active-secret",
                    model="active-model",
                ),
                ProviderRecord(
                    id="candidate",
                    name="Candidate",
                    **candidate_values,
                ),
            ],
        )
    )

    response = api.post("/llm/providers/candidate/activate")

    assert response.status_code == 422, response.text
    assert response.json()["error"] == {
        "code": "LLM_PROVIDER_NOT_CONFIGURED",
        "message": "LLM provider is not fully configured.",
        "details": {"fields": [missing_field]},
    }
    assert api.get("/llm/providers").json()["active_provider_id"] == "active"
    assert load_provider_store(store_path).active_provider_id == "active"


def test_clearing_active_provider_key_fails_closed(
    api, store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "environment-secret")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "environment-model")
    _create(api)
    activated = api.post("/llm/providers/deepseek/activate")
    assert activated.status_code == 200, activated.text

    response = api.put(
        "/llm/providers/deepseek",
        json={"clear_api_key": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["key_present"] is False
    assert api.get("/llm/providers").json()["active_provider_id"] is None
    config = api.get("/llm/config")
    assert config.status_code == 200, config.text
    assert config.json()["source"] == "explicit_config_unconfigured"
    assert config.json()["configured"] is False
    assert config.json()["base_url"] is None
    assert "environment-secret" not in config.text
    assert load_provider_store(store_path).providers[0].api_key == ""


def test_delete_active_provider_skips_unconfigured_remaining_provider(
    api, store_path
):
    save_provider_store(
        ProviderStore(
            active_provider_id="active",
            providers=[
                ProviderRecord(
                    id="active",
                    name="Active",
                    base_url="https://active.example.com/v1",
                    api_key="active-secret",
                    model="active-model",
                ),
                ProviderRecord(
                    id="local",
                    name="Local",
                    base_url="",
                    api_key="",
                    model="",
                ),
                ProviderRecord(
                    id="configured",
                    name="Configured",
                    base_url="https://configured.example.com/v1",
                    api_key="configured-secret",
                    model="configured-model",
                ),
            ],
        )
    )

    deleted = api.delete("/llm/providers/active")

    assert deleted.status_code == 200, deleted.text
    assert api.get("/llm/providers").json()["active_provider_id"] == "configured"


def test_delete_active_provider_clears_id_fail_closed(
    api, store_path, monkeypatch
):
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "environment-secret")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "environment-model")
    save_provider_store(
        ProviderStore(
            active_provider_id="active",
            providers=[
                ProviderRecord(
                    id="active",
                    name="Active",
                    base_url="https://active.example.com/v1",
                    api_key="active-secret",
                    model="active-model",
                ),
                ProviderRecord(
                    id="local",
                    name="Local",
                    base_url="",
                    api_key="",
                    model="",
                ),
            ],
        )
    )

    deleted = api.delete("/llm/providers/active")

    assert deleted.status_code == 200, deleted.text
    listed = api.get("/llm/providers")
    assert listed.json()["active_provider_id"] is None
    config = api.get("/llm/config")
    assert config.json()["source"] == "explicit_config_unconfigured"
    assert config.json()["configured"] is False
    assert config.json()["base_url"] is None
    assert "environment-secret" not in config.text


def test_duplicate_create_and_missing_update_use_workbench_errors(api, store_path):
    _create(api)

    duplicate = api.post("/llm/providers", json=_provider_payload())
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "LLM_PROVIDER_ALREADY_EXISTS"

    missing = api.put("/llm/providers/missing", json={"name": "x"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LLM_PROVIDER_NOT_FOUND"


def test_chat_upstream_echoed_api_key_is_redacted(
    api, store_path, tmp_path, monkeypatch
):
    # This test exercises redaction via the ENVIRONMENT provider on the default
    # path. An explicit incomplete store is intentionally fail-closed.
    monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
    monkeypatch.setattr(
        "workbench.llm.provider_store.Path.home", lambda: tmp_path
    )
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://llm.example.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", API_KEY)
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "test-model")
    _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            401, text=f"upstream echoed Authorization Bearer {API_KEY}"
        ),
    )

    response = api.post(
        "/llm/chat",
        json={
            "mode": "workbench_node_context_v1",
            "question": "Explain this node.",
            "packet": {"context_fingerprint": "fp"},
        },
    )

    assert response.status_code == 502
    assert API_KEY not in response.text


def test_chat_upstream_error_does_not_include_encoded_or_escaped_api_key(
    monkeypatch,
):
    api_key = "sk-secret/key?value"
    body = (
        '{"error":"Bearer sk-secret%2Fkey%3Fvalue; '
        'escaped Bearer sk-secret\\/key?value"}'
    )
    _install_upstream(monkeypatch, lambda request: httpx.Response(401, text=body))
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key=api_key,
        model="test-model",
    )

    with pytest.raises(LLMUpstreamError) as exc_info:
        llm_client.chat_completion([], config)

    assert str(exc_info.value) == "LLM provider returned an error: 401"
    assert "sk-secret%2Fkey%3Fvalue" not in str(exc_info.value)
    assert "sk-secret\\/key?value" not in str(exc_info.value)


def test_provider_store_write_failure_returns_workbench_error(
    api, store_path, monkeypatch
):
    def fail_save(_store):
        raise OSError("permission denied")

    monkeypatch.setattr(llm_routes, "save_provider_store", fail_save)

    response = api.post("/llm/providers", json=_provider_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_PROVIDER_STORE_UNAVAILABLE"


def test_provider_store_lock_failure_returns_workbench_error(
    api, store_path, monkeypatch
):
    class BrokenLock:
        def __enter__(self):
            raise OSError("permission denied")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(llm_routes, "provider_store_lock", lambda: BrokenLock())

    response = api.post("/llm/providers", json=_provider_payload())

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "LLM_PROVIDER_STORE_UNAVAILABLE"


def test_provider_store_invalid_file_returns_structured_error_without_overwrite(
    api, store_path
):
    store_path.write_text("{not json", encoding="utf-8")

    response = api.post("/llm/providers", json=_provider_payload())

    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "LLM_PROVIDER_STORE_INVALID"
    assert store_path.read_text(encoding="utf-8") == "{not json"


def test_provider_store_unavailable_returns_structured_error_without_overwrite(
    api, store_path
):
    store_path.mkdir()

    response = api.post("/llm/providers", json=_provider_payload())

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "LLM_PROVIDER_STORE_UNAVAILABLE"
    assert store_path.is_dir()


def _install_upstream(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording_handler)
    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda config: httpx.Client(transport=transport, timeout=config.timeout_s),
    )
    return seen


def _install_async_upstream(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording_handler)
    monkeypatch.setattr(
        llm_client,
        "_async_client_factory",
        lambda config: httpx.AsyncClient(transport=transport, timeout=config.timeout_s),
    )
    return seen


def test_refresh_models_uses_get_models_and_returns_public_provider(
    api, store_path, monkeypatch
):
    _create(api)
    seen = _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-chat", "owned_by": "deepseek"},
                    {"id": "deepseek-reasoner", "owned_by": "deepseek"},
                ]
            },
        ),
    )

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 200, response.text
    assert str(seen[0].url) == "https://api.deepseek.com/v1/models"
    assert seen[0].method == "GET"
    assert seen[0].headers["Authorization"] == f"Bearer {API_KEY}"
    assert [model["request_model"] for model in response.json()["models"]] == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]
    assert "api_key" not in response.json()
    assert API_KEY not in response.text
    assert response.json()["icon"] == "deepseek-mark"
    assert response.json()["notes"] == "Primary research provider"
    assert [model.request_model for model in load_provider_store(store_path).providers[0].models] == [
        "deepseek-chat",
        "deepseek-reasoner",
    ]


def test_refresh_models_rejects_duplicate_upstream_ids_without_store_mutation(
    api, store_path, monkeypatch
):
    _create(api)
    before = store_path.read_text(encoding="utf-8")
    _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-chat", "owned_by": "deepseek"},
                    {"id": "deepseek-chat"},
                ]
            },
        ),
    )

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "LLM_UPSTREAM_ERROR"
    assert "deepseek-chat" not in response.text
    assert API_KEY not in response.text
    assert store_path.read_text(encoding="utf-8") == before


def test_refresh_models_preserves_provider_updates_during_fetch(
    api, store_path, monkeypatch
):
    _create(api)

    def fetch_and_update(_config):
        save_provider_store(
            ProviderStore(
                active_provider_id="deepseek",
                providers=[
                    ProviderRecord(
                        id="deepseek",
                        name="Updated DeepSeek",
                        website_url="https://updated.example.com",
                        base_url="https://api.deepseek.com/v1",
                        model="deepseek-chat",
                        api_key=API_KEY,
                        timeout_s=30,
                        models=[
                            ModelRecord(
                                "DeepSeek Chat",
                                "deepseek-chat",
                                256000,
                                True,
                            )
                        ],
                    )
                ],
            )
        )
        return [{"id": "deepseek-chat", "owned_by": "deepseek"}]

    monkeypatch.setattr(llm_routes, "fetch_models", fetch_and_update)

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Updated DeepSeek"
    assert body["website_url"] == "https://updated.example.com"
    assert body["base_url"] == "https://api.deepseek.com/v1"
    assert body["model"] == "deepseek-chat"
    assert body["timeout_s"] == 30
    assert body["models"] == [
        {
            "display_name": "DeepSeek Chat",
            "request_model": "deepseek-chat",
            "context_window_tokens": 256000,
            "supports_1m": True,
            # v1.7 G2: vision capability is preserved across a model refresh
            # exactly like supports_1m (it is operator metadata, not upstream's).
            "supports_vision": False,
        }
    ]
    assert "updated-secret" not in response.text

    stored = load_provider_store(store_path).providers[0]
    assert stored.name == "Updated DeepSeek"
    assert stored.api_key == API_KEY
    assert stored.models[0].context_window_tokens == 256000


def test_refresh_models_rejects_provider_configuration_change_during_fetch(
    api, store_path, monkeypatch
):
    _create(api)

    changed = ProviderRecord(
        id="deepseek",
        name="Changed DeepSeek",
        website_url="https://platform.deepseek.com",
        base_url="https://changed.example.com/v1",
        model="changed-model",
        api_key="changed-secret",
        timeout_s=45,
        models=[ModelRecord("Existing", "existing-model")],
    )

    def fetch_and_change_configuration(_config):
        save_provider_store(ProviderStore(providers=[changed]))
        return [{"id": "fetched-model", "owned_by": "provider"}]

    monkeypatch.setattr(llm_routes, "fetch_models", fetch_and_change_configuration)

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == (
        "LLM_PROVIDER_CHANGED_DURING_REFRESH"
    )
    stored = load_provider_store(store_path).providers[0]
    assert stored == changed


def test_refresh_does_not_hold_provider_lock_until_fetch_finishes(
    api, store_path, monkeypatch
):
    _create(api)
    mutation_started = Event()
    mutation_finished = Event()
    mutation_result = {}

    def update_during_fetch():
        mutation_started.set()
        mutation_result["response"] = api.put(
            "/llm/providers/deepseek",
            json={"name": "Concurrent edit"},
        )
        mutation_finished.set()

    def fetch_and_start_update(_config):
        mutation = Thread(target=update_during_fetch)
        mutation.start()
        assert mutation_started.wait(1)
        assert mutation_finished.wait(1)
        mutation.join(1)
        return [{"id": "deepseek-chat", "owned_by": "deepseek"}]

    monkeypatch.setattr(llm_routes, "fetch_models", fetch_and_start_update)

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 200, response.text
    assert mutation_finished.wait(1)
    assert mutation_result["response"].status_code == 200
    stored = load_provider_store(store_path).providers[0]
    assert stored.name == "Concurrent edit"


def test_refresh_models_returns_not_found_if_provider_deleted_during_fetch(
    api, store_path, monkeypatch
):
    _create(api)

    def fetch_and_delete(_config):
        save_provider_store(ProviderStore())
        return [{"id": "deepseek-chat", "owned_by": "deepseek"}]

    monkeypatch.setattr(llm_routes, "fetch_models", fetch_and_delete)

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "LLM_PROVIDER_NOT_FOUND"
    assert load_provider_store(store_path).providers == []


def test_chat_completion_preserves_existing_base_url_joining(monkeypatch):
    seen = _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}}],
            },
        ),
    )
    llm_client.chat_completion(
        [],
        LLMConfig(
            base_url="https://api.example.com/v1/",
            api_key=API_KEY,
            model="test-model",
        ),
    )

    assert str(seen[0].url) == "https://api.example.com/v1/chat/completions"


def test_async_stream_chat_completion_yields_public_text_deltas(monkeypatch, admitted_stream) -> None:
    seen = _install_async_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            content=(
                b'data: {"model":"test-model","choices":[{"delta":{"content":"first "},"finish_reason":null}]}\n\n'
                b'data: {"model":"test-model","choices":[{"delta":{"content":"second"},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        ),
    )

    async def scenario() -> list[dict[str, object]]:
        return [
            event
            async for event in admitted_stream(
                [{"role": "user", "content": "stream a public answer"}],
                LLMConfig(
                    base_url="https://api.example.com/v1",
                    api_key=API_KEY,
                    model="test-model",
                ),
            )
        ]

    events = asyncio.run(scenario())

    assert events == [
        {"type": "text_delta", "delta": "first "},
        {"type": "text_delta", "delta": "second"},
        {"type": "done", "finish_reason": "stop", "model": "test-model"},
    ]
    assert json.loads(seen[0].content)["stream"] is True


@pytest.mark.parametrize("second_id", ["upstream-42", "different-upstream"])
def test_async_stream_preserves_only_consistent_upstream_identity(monkeypatch, second_id, admitted_stream) -> None:
    chunks = [
        {"id": "upstream-42", "choices": [{"delta": {"content": "answer"}, "finish_reason": None}]},
        {"id": second_id, "choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    _install_async_upstream(monkeypatch, lambda request: httpx.Response(
        200, content="".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks).encode(),
    ))

    async def scenario():
        return [event async for event in admitted_stream(
            [{"role": "user", "content": "inspect"}],
            LLMConfig(base_url="https://api.example.com/v1", api_key=API_KEY, model="test-model"),
        )]

    if second_id != "upstream-42":
        with pytest.raises(llm_client.LLMUpstreamError, match="identity changed"):
            asyncio.run(scenario())
    else:
        assert asyncio.run(scenario())[-1]["provider_request_id"] == "upstream-42"


def test_async_stream_chat_completion_assembles_split_typed_tool_call(monkeypatch, admitted_stream) -> None:
    _install_async_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","type":"function","function":{"name":"inspect_node","arguments":"{\\"node_ref\\":\\""}}]},"finish_reason":null}]}\n\n'
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"model:ols_1\\"}"}}]},"finish_reason":"tool_calls"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        ),
    )

    async def scenario() -> list[dict[str, object]]:
        return [
            event
            async for event in admitted_stream(
                [{"role": "user", "content": "inspect the selected node"}],
                LLMConfig(
                    base_url="https://api.example.com/v1",
                    api_key=API_KEY,
                    model="test-model",
                ),
                tools=[{"type": "function", "function": {"name": "inspect_node"}}],
            )
        ]

    assert asyncio.run(scenario()) == [
            {"type": "provider_activity", "public": True},
            {"type": "provider_activity", "public": True},
        {
            "type": "tool_call",
            "tool_call": {
                "tool_call_id": "call-1",
                "tool_id": "inspect_node",
                "arguments": {"node_ref": "model:ols_1"},
            },
        },
        {"type": "done", "finish_reason": "tool_calls", "model": "test-model"},
    ]


def test_async_stream_classifies_complete_invalid_tool_arguments(monkeypatch, admitted_stream) -> None:
    """Malformed completed arguments are a correctable tool contract, not transport loss."""

    _install_async_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-bad","function":{"name":"submit_notebook_option_batch","arguments":"{\\"options\\":[}"}}]},"finish_reason":"tool_calls"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        ),
    )

    async def scenario() -> None:
        with pytest.raises(llm_client.LLMToolCallArgumentsError):
            async for _event in admitted_stream(
                [{"role": "user", "content": "submit"}],
                LLMConfig(
                    base_url="https://api.example.com/v1",
                    api_key=API_KEY,
                    model="test-model",
                ),
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "submit_notebook_option_batch"},
                    }
                ],
            ):
                pass

    asyncio.run(scenario())


def test_openai_adapter_exposes_invalid_tool_arguments_without_replay(monkeypatch, admitted_adapter) -> None:
    """The planner can correct invalid JSON while the adapter preserves attempt one."""

    attempts = 0

    async def fake_stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise llm_client.LLMToolCallArgumentsError(
            "LLM provider returned invalid tool-call arguments"
        )
        yield

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.test",
                api_key=API_KEY,
                model="test-model",
            )
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(
                    messages=[{"role": "user", "content": "plan"}],
                    tools=[
                        {
                            "tool_id": "submit_notebook_option_batch",
                            "input_schema": {"type": "object"},
                        }
                    ],
                )
            )
        ]

    events = asyncio.run(scenario())
    assert attempts == 1
    assert events[-1].error == "provider_tool_arguments_invalid"


def test_async_stream_chat_completion_forwards_safe_model_request_config(monkeypatch, admitted_stream) -> None:
    seen = _install_async_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"submit_notebook_option_batch","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        ),
    )

    async def scenario() -> list[dict[str, object]]:
        return [
            event
            async for event in admitted_stream(
                [{"role": "user", "content": "submit"}],
                LLMConfig(
                    base_url="https://api.example.com/v1",
                    api_key=API_KEY,
                    model="test-model",
                ),
                tools=[{"type": "function", "function": {"name": "submit_notebook_option_batch"}}],
                model_config={
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": "submit_notebook_option_batch"},
                    },
                    "thinking": {"type": "disabled"},
                    "max_tokens": 4096,
                },
            )
        ]

    asyncio.run(scenario())
    payload = json.loads(seen[0].content)
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_notebook_option_batch"},
    }
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 4096


def test_openai_adapter_retries_after_private_reasoning_only(monkeypatch, admitted_adapter) -> None:
    attempts = 0

    async def fake_stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        yield {"type": "provider_activity"}
        if attempts == 1:
            raise llm_client.LLMUpstreamError("stream ended without completion")
        yield {"type": "done", "finish_reason": "stop", "model": "deepseek-chat"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.test",
                api_key=API_KEY,
                model="deepseek-chat",
            )
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(messages=[{"role": "user", "content": "plan"}])
            )
        ]

    events = asyncio.run(scenario())
    assert attempts == 2
    assert events[-1].type == "done"


def test_openai_adapter_does_not_retry_after_partial_tool_call_activity(monkeypatch, admitted_adapter) -> None:
    seen = _install_async_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"submit_notebook_option_batch","arguments":"{\\"options\\":"}}]},"finish_reason":null}]}\n\n'
            ),
        ),
    )

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.com/v1",
                api_key=API_KEY,
                model="test-model",
            )
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(messages=[{"role": "user", "content": "submit"}])
            )
        ]

    events = asyncio.run(scenario())
    assert len(seen) == 1
    assert events[-1].type == "error"


def test_openai_adapter_never_retries_a_typed_agent_request(monkeypatch, admitted_adapter) -> None:
    """A typed request keeps its first provider failure as immutable evidence."""

    attempts = 0

    async def fake_stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise llm_client.LLMUpstreamError(
                "temporary outage",
                upstream_status=503,
            )
        yield {"type": "done", "finish_reason": "stop", "model": "test-model"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.test",
                api_key=API_KEY,
                model="test-model",
            )
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(
                    messages=[{"role": "user", "content": "propose an analysis"}],
                    tools=[
                        {
                            "tool_id": "propose_operation",
                            "input_schema": {"type": "object"},
                        }
                    ],
                )
            )
        ]

    events = asyncio.run(scenario())
    assert attempts == 1
    assert events[-1].type == "error"
    assert events[-1].error == "LLMUpstreamError:upstream_503"


def test_openai_adapter_retries_transient_provider_status_before_failing(monkeypatch, admitted_adapter) -> None:
    attempts = 0

    async def fake_stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise llm_client.LLMUpstreamError("temporary outage", upstream_status=503)
        yield {"type": "done", "finish_reason": "stop", "model": "test-model"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.test",
                api_key=API_KEY,
                model="test-model",
            )
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(messages=[{"role": "user", "content": "plan"}])
            )
        ]

    events = asyncio.run(scenario())
    assert attempts == 2
    assert events[-1].type == "done"


def test_openai_adapter_preserves_complete_non_object_tool_json_failure(monkeypatch, admitted_adapter) -> None:
    """A completed malformed tool call is not hidden by a second provider turn."""

    responses = iter(
        [
            httpx.Response(
                200,
                content=(
                    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-bad","function":{"name":"submit_notebook_option_batch","arguments":"[]"}}]},"finish_reason":"tool_calls"}]}'
                    b"\n\n"
                ),
            ),
        ]
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(responses)

    monkeypatch.setattr(
        llm_client,
        "_async_client_factory",
        lambda config: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=config.timeout_s
        ),
    )

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.com/v1",
                api_key=API_KEY,
                model="test-model",
            )
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(messages=[{"role": "user", "content": "submit"}])
            )
        ]

    events = asyncio.run(scenario())
    assert len(seen) == 1
    assert [event.type for event in events] == ["error"]
    assert events[0].error == "provider_tool_arguments_invalid"


def test_openai_adapter_stops_one_no_progress_stream_without_retry(monkeypatch, admitted_adapter) -> None:
    attempts = 0

    async def fake_stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.05)
        yield {"type": "done", "finish_reason": "stop", "model": "deepseek-v4-flash"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario():
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.deepseek.com",
                api_key=API_KEY,
                model="deepseek-v4-flash",
            ),
            idle_timeout_s=0.01,
        )
        return [
            event
            async for event in adapter.stream(
                ModelRequest(messages=[{"role": "user", "content": "plan"}])
            )
        ]

    events = asyncio.run(scenario())
    assert attempts == 1
    assert events[-1].type == "error"
    assert events[-1].error == "provider_no_progress"


def test_openai_adapter_abort_event_interrupts_a_hung_provider_stream(monkeypatch, admitted_adapter) -> None:
    started = asyncio.Event()

    async def fake_stream(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()
        yield {"type": "done", "finish_reason": "stop", "model": "test-model"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", fake_stream)

    async def scenario():
        abort_event = asyncio.Event()
        adapter = admitted_adapter(
            LLMConfig(
                base_url="https://api.example.com/v1",
                api_key=API_KEY,
                model="test-model",
            ),
            idle_timeout_s=1.0,
        )

        async def collect():
            return [
                event
                async for event in adapter.stream(
                    ModelRequest(
                        messages=[{"role": "user", "content": "cancel"}],
                        abort_event=abort_event,
                    )
                )
            ]

        task = asyncio.create_task(collect())
        await started.wait()
        abort_event.set()
        return await asyncio.wait_for(task, timeout=0.1)

    events = asyncio.run(scenario())
    assert events[-1].type == "error"
    assert events[-1].error == "aborted"


def test_deepseek_v4_adapter_does_not_advertise_named_tool_choice() -> None:
    adapter = OpenAICompatibleModelAdapter(
        LLMConfig(
            base_url="https://api.deepseek.com",
            api_key=API_KEY,
            model="deepseek-v4-flash",
            provider_name="DeepSeek",
        )
    )

    assert adapter.supports_named_tool_choice() is False
    assert adapter.planning_request_config() == {
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
    }


def test_probe_uses_models_endpoint_and_never_chat_completion(
    api, store_path, monkeypatch
):
    _create(api)
    seen = _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": []}),
    )

    def fail_chat(*_args, **_kwargs):
        raise AssertionError("probe must not call chat_completion")

    monkeypatch.setattr(llm_routes, "chat_completion", fail_chat)

    response = api.post("/llm/providers/deepseek/probe")

    assert response.status_code == 200, response.text
    assert str(seen[0].url) == "https://api.deepseek.com/v1/models"
    assert "api_key" not in response.json()


def test_fetch_models_invalid_timeout_is_sanitized(monkeypatch):
    def invalid_timeout_factory(config):
        assert config.timeout_s != config.timeout_s
        raise ValueError("invalid timeout detail")

    monkeypatch.setattr(llm_client, "_client_factory", invalid_timeout_factory)
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key=API_KEY,
        model="test-model",
        timeout_s=float("nan"),
    )

    with pytest.raises(LLMUpstreamError) as exc_info:
        llm_client.fetch_models(config)

    assert str(exc_info.value) == "LLM provider request failed: ValueError"
    assert "invalid timeout detail" not in str(exc_info.value)


def test_fetch_models_upstream_error_does_not_include_encoded_or_escaped_api_key(
    monkeypatch,
):
    api_key = "sk-secret/key?value"
    body = (
        '{"error":"Bearer sk-secret%2Fkey%3Fvalue; '
        'escaped Bearer sk-secret\\/key?value"}'
    )
    _install_upstream(monkeypatch, lambda request: httpx.Response(500, text=body))
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key=api_key,
        model="test-model",
    )

    with pytest.raises(LLMUpstreamError) as exc_info:
        llm_client.fetch_models(config)

    assert str(exc_info.value) == "LLM provider returned an error: 500"
    assert "sk-secret%2Fkey%3Fvalue" not in str(exc_info.value)
    assert "sk-secret\\/key?value" not in str(exc_info.value)


def test_probe_releases_provider_lock_and_rechecks_deleted_provider(
    api, store_path, monkeypatch
):
    _create(api)
    fetch_started = Event()
    release_fetch = Event()
    mutation_started = Event()
    mutation_finished = Event()
    probe_result = {}
    mutation_result = {}

    def fetch_and_block(_config):
        fetch_started.set()
        assert release_fetch.wait(1)
        return []

    def delete_provider():
        mutation_started.set()
        mutation_result["response"] = api.delete("/llm/providers/deepseek")
        mutation_finished.set()

    monkeypatch.setattr(llm_routes, "fetch_models", fetch_and_block)

    probe = Thread(
        target=lambda: probe_result.setdefault(
            "response", api.post("/llm/providers/deepseek/probe")
        )
    )
    probe.start()
    assert fetch_started.wait(1)

    mutation = Thread(target=delete_provider)
    mutation.start()
    assert mutation_started.wait(1)
    assert mutation_finished.wait(1)
    assert mutation_result["response"].status_code == 200

    release_fetch.set()
    probe.join(1)
    mutation.join(1)

    assert probe_result["response"].status_code == 404
    assert probe_result["response"].json()["error"]["code"] == "LLM_PROVIDER_NOT_FOUND"
    assert load_provider_store(store_path).providers == []


def test_probe_returns_conflict_if_provider_changes_during_fetch(
    api, store_path, monkeypatch
):
    _create(api)

    def fetch_and_update(_config):
        save_provider_store(
            ProviderStore(
                active_provider_id="deepseek",
                providers=[
                    ProviderRecord(
                        id="deepseek",
                        name="Changed DeepSeek",
                        base_url="https://api.deepseek.com/v1",
                        model="deepseek-chat",
                        api_key=API_KEY,
                    )
                ],
            )
        )
        return []

    monkeypatch.setattr(llm_routes, "fetch_models", fetch_and_update)

    response = api.post("/llm/providers/deepseek/probe")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "LLM_PROVIDER_CONFLICT"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "bad key"}),
        httpx.Response(500, text="upstream failure"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"data": [{"owned_by": "missing id"}]}),
        httpx.Response(200, json={"data": [{"id": ""}]}),
    ],
)
def test_fetch_models_sanitizes_upstream_failures(response, monkeypatch):
    _install_upstream(monkeypatch, lambda request: response)
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key=API_KEY,
        model="test-model",
    )

    with pytest.raises(LLMUpstreamError) as exc_info:
        llm_client.fetch_models(config)

    assert API_KEY not in str(exc_info.value)


def test_fetch_models_rejects_whitespace_model_ids(monkeypatch):
    _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": [{"id": " \t"}]}),
    )
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key=API_KEY,
        model="test-model",
    )

    with pytest.raises(LLMUpstreamError) as exc_info:
        llm_client.fetch_models(config)

    assert str(exc_info.value) == (
        "LLM provider returned an unexpected models response shape"
    )


def test_fetch_models_allows_missing_owned_by(monkeypatch):
    _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"data": [{"id": "deepseek-chat"}]},
        ),
    )
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key=API_KEY,
        model="test-model",
    )

    assert llm_client.fetch_models(config) == [
        {"id": "deepseek-chat", "owned_by": ""}
    ]


def test_refresh_models_preserves_operator_marked_vision_capability(
    api, store_path, monkeypatch
):
    """v1.7 G2: supports_vision is operator metadata, not upstream's.

    A model refresh must not silently un-mark a vision-capable model — that
    would quietly disable the chart-image opt-in with no visible cause.
    """
    _create(api)
    save_provider_store(
        ProviderStore(
            active_provider_id="deepseek",
            providers=[
                ProviderRecord(
                    id="deepseek",
                    name="DeepSeek",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                    api_key=API_KEY,
                    models=[
                        ModelRecord("DeepSeek Chat", "deepseek-chat", 128000, False, True),
                    ],
                )
            ],
        ),
        store_path,
    )
    _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"data": [{"id": "deepseek-chat", "owned_by": "deepseek"}]}
        ),
    )

    response = api.post("/llm/providers/deepseek/models/refresh")

    assert response.status_code == 200, response.text
    models = response.json()["models"]
    assert models[0]["request_model"] == "deepseek-chat"
    assert models[0]["supports_vision"] is True

    # a model the operator never marked stays text-only by default
    _install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-chat", "owned_by": "deepseek"},
                    {"id": "brand-new-model", "owned_by": "deepseek"},
                ]
            },
        ),
    )
    refreshed = api.post("/llm/providers/deepseek/models/refresh").json()["models"]
    by_id = {m["request_model"]: m for m in refreshed}
    assert by_id["deepseek-chat"]["supports_vision"] is True
    assert by_id["brand-new-model"]["supports_vision"] is False
