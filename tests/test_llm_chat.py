"""POST /llm/chat — provider-agnostic Ask AI route (v1.6.11 slice A).

All tests run offline: the OpenAI-compatible upstream is an httpx.MockTransport
injected through the ``workbench.llm.client._client_factory`` seam.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.llm import client as llm_client
from workbench.llm.config import load_llm_config
from workbench.llm.provider_store import (
    DEFAULT_TIMEOUT_S,
    ModelRecord,
    ProviderRecord,
    ProviderStore,
    save_provider_store,
)

API_KEY = "sk-test-secret-key"


@pytest.fixture
def api() -> TestClient:
    return TestClient(app)


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://llm.example.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", API_KEY)
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-chat")


def _install_upstream(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(_recording_handler)
    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda config: httpx.Client(transport=transport, timeout=config.timeout_s),
    )
    return seen


def _chat_body(**overrides) -> dict:
    body = {
        "mode": "workbench_node_context_v1",
        "question": "Explain this node and its risks.",
        "packet": {
            "packet_version": "ask-ai-context/v1",
            "context_fingerprint": "fp-123",
            "node_summary": {"params": {"covariance": "HC1"}},
            "response_guardrails": {"advisory_text_only": True},
        },
        "response_guardrails": {"advisory_text_only": True},
    }
    body.update(overrides)
    return body


def _ok_upstream(
    text: str = "This node runs OLS.", model: object = "deepseek-chat"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}}],
        },
    )


class TestNotConfigured:
    def test_503_when_env_missing(self, api: TestClient, monkeypatch: pytest.MonkeyPatch):
        for name in (
            "WORKBENCH_LLM_BASE_URL",
            "WORKBENCH_LLM_API_KEY",
            "WORKBENCH_LLM_MODEL",
        ):
            monkeypatch.delenv(name, raising=False)
        response = api.post("/llm/chat", json=_chat_body())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"

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
    def test_503_when_legacy_env_base_url_is_unsafe(
        self, api, monkeypatch: pytest.MonkeyPatch, base_url
    ):
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", base_url)
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", API_KEY)
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-chat")
        seen = _install_upstream(
            monkeypatch,
            lambda request: pytest.fail("unsafe environment URL reached upstream"),
        )

        response = api.post("/llm/chat", json=_chat_body())

        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
        assert seen == []

    @pytest.mark.parametrize("field", ["base_url", "api_key", "model"])
    def test_whitespace_config_value_does_not_configure_llm(self, field):
        values = {
            "base_url": "https://llm.example.com",
            "api_key": API_KEY,
            "model": "deepseek-chat",
        }
        values[field] = " \t\n"

        config = llm_client.LLMConfig(**values)

        assert config.is_configured() is False


class TestHappyPath:
    def test_returns_text_model_and_fingerprint(
        self, api: TestClient, configured_env, monkeypatch
    ):
        _install_upstream(monkeypatch, lambda request: _ok_upstream("Answer text."))
        response = api.post("/llm/chat", json=_chat_body())
        assert response.status_code == 200
        assert response.json() == {
            "text": "Answer text.",
            "model": "deepseek-chat",
            "context_fingerprint": "fp-123",
        }

    def test_upstream_request_shape(self, api: TestClient, configured_env, monkeypatch):
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream())
        api.post("/llm/chat", json=_chat_body())
        assert len(seen) == 1
        request = seen[0]
        assert str(request.url) == "https://llm.example.com/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-chat"
        assert payload["stream"] is False
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]

    def test_chat_completion_passes_explicit_timeout_to_post(self, monkeypatch):
        calls = []

        class SpyClient:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def post(self, *args, **kwargs):
                calls.append(kwargs)
                return _ok_upstream()

        monkeypatch.setattr(
            llm_client,
            "_client_factory",
            lambda config: SpyClient(),
        )

        llm_client.chat_completion(
            [],
            llm_client.LLMConfig(
                base_url="https://api.example.com/v1",
                api_key=API_KEY,
                model="test-model",
                timeout_s=12.5,
            ),
        )

        assert calls[0]["timeout"] == 12.5

    def test_system_prompt_carries_guardrails_and_packet(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream())
        api.post("/llm/chat", json=_chat_body())
        system_prompt = json.loads(seen[0].content)["messages"][0]["content"]
        assert "Advisory text only" in system_prompt
        assert "advisory_text_only" in system_prompt
        assert "fp-123" in system_prompt
        assert "HC1" in system_prompt

    def test_user_message_is_the_question(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream())
        api.post("/llm/chat", json=_chat_body(question="为什么标准误变大了?"))
        messages = json.loads(seen[0].content)["messages"]
        assert messages[1] == {"role": "user", "content": "为什么标准误变大了?"}

    @pytest.mark.parametrize("upstream_model", [None, {"unexpected": "object"}])
    def test_non_string_upstream_model_falls_back_to_config_model(
        self, api, configured_env, monkeypatch, upstream_model
    ):
        _install_upstream(
            monkeypatch,
            lambda request: _ok_upstream(model=upstream_model),
        )

        response = api.post("/llm/chat", json=_chat_body())

        assert response.status_code == 200, response.text
        assert response.json()["model"] == "deepseek-chat"


class TestUpstreamFailures:
    @pytest.mark.parametrize("status", [401, 429, 500])
    def test_upstream_error_maps_to_502(
        self, api: TestClient, configured_env, monkeypatch, status: int
    ):
        _install_upstream(
            monkeypatch,
            lambda request: httpx.Response(status, json={"error": "upstream boom"}),
        )
        response = api.post("/llm/chat", json=_chat_body())
        assert response.status_code == 502
        error = response.json()["error"]
        assert error["code"] == "LLM_UPSTREAM_ERROR"
        assert error["details"]["upstream_status"] == status

    def test_api_key_never_leaks_into_error(
        self, api: TestClient, configured_env, monkeypatch
    ):
        _install_upstream(
            monkeypatch, lambda request: httpx.Response(401, json={"error": "bad key"})
        )
        response = api.post("/llm/chat", json=_chat_body())
        assert API_KEY not in response.text

    def test_malformed_upstream_json_maps_to_502(
        self, api: TestClient, configured_env, monkeypatch
    ):
        _install_upstream(
            monkeypatch, lambda request: httpx.Response(200, json={"unexpected": True})
        )
        response = api.post("/llm/chat", json=_chat_body())
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "LLM_UPSTREAM_ERROR"

    def test_network_error_maps_to_502(
        self, api: TestClient, configured_env, monkeypatch
    ):
        def _raise(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        _install_upstream(monkeypatch, _raise)
        response = api.post("/llm/chat", json=_chat_body())
        assert response.status_code == 502

    def test_invalid_timeout_falls_back_before_sanitized_runtime_error(
        self, api: TestClient, configured_env, monkeypatch
    ):
        monkeypatch.setenv("WORKBENCH_LLM_TIMEOUT_S", "nan")

        def invalid_timeout_factory(config):
            assert config.timeout_s == DEFAULT_TIMEOUT_S
            raise ValueError("invalid timeout detail")

        monkeypatch.setattr(llm_client, "_client_factory", invalid_timeout_factory)

        response = api.post("/llm/chat", json=_chat_body())

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "LLM_UPSTREAM_ERROR"
        assert "invalid timeout detail" not in response.text
        assert "ValueError" in response.text


class TestRequestValidation:
    def test_unsupported_mode_is_422(self, api: TestClient, configured_env):
        response = api.post("/llm/chat", json=_chat_body(mode="freeform_chat"))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LLM_CHAT_UNSUPPORTED_MODE"

    def test_blank_question_is_422(self, api: TestClient, configured_env):
        response = api.post("/llm/chat", json=_chat_body(question="   "))
        assert response.status_code == 422

    def test_missing_packet_is_422(self, api: TestClient, configured_env):
        body = _chat_body()
        del body["packet"]
        response = api.post("/llm/chat", json=body)
        assert response.status_code == 422


class TestReportMode:
    def _report_body(self) -> dict:
        return {
            "mode": "workbench_report_v1",
            "question": "写一份实证报告",
            "packet": {
                "report_scope": {"run_id": "run1", "node_count": 3},
                "fact_table": [
                    {"id": "c1", "node_key": "k1", "label": "R²", "value": 0.86},
                    {"id": "c2", "node_key": "k2", "label": "covariance", "value": "HC1"},
                ],
            },
            "response_guardrails": {"advisory_text_only": True},
        }

    def test_report_mode_accepted(self, api: TestClient, configured_env, monkeypatch):
        _install_upstream(monkeypatch, lambda request: _ok_upstream("# Report [[c:c1]]"))
        response = api.post("/llm/chat", json=self._report_body())
        assert response.status_code == 200
        assert response.json()["text"].startswith("# Report")

    def test_report_prompt_carries_cite_rule_and_fact_table(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream())
        api.post("/llm/chat", json=self._report_body())
        system_prompt = json.loads(seen[0].content)["messages"][0]["content"]
        assert "[[c:ID]]" in system_prompt
        assert "fact_table" in system_prompt
        assert "\"c1\"" in system_prompt and "0.86" in system_prompt
        # the node-context header must NOT leak into report mode
        assert "node assistant" not in system_prompt

    def test_unknown_mode_lists_both_supported(self, api: TestClient, configured_env):
        response = api.post("/llm/chat", json={**self._report_body(), "mode": "bogus"})
        assert response.status_code == 422
        assert response.json()["error"]["details"]["supported_modes"] == [
            "workbench_node_context_v1",
            "workbench_report_v1",
        ]


class TestLlmConfigEndpoint:
    """v1.6.12 T5 (A4) — GET /llm/config: read-only provider visibility."""

    def test_active_local_provider_overrides_environment(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "llm-providers.json"))
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")

        provider = ProviderRecord(
            id="local-provider",
            name="Local Provider",
            base_url="https://local.example.com/",
            model="local-model",
            api_key="local-secret",
            timeout_s=12.5,
            models=[
                ModelRecord("Other", "other-model", 32_000, False),
                ModelRecord("Local", "local-model", 1_000_000, True),
            ],
        )
        save_provider_store(
            ProviderStore(active_provider_id="local-provider", providers=[provider])
        )

        config = load_llm_config()

        assert config.base_url == "https://local.example.com/"
        assert config.api_key == "local-secret"
        assert config.model == "local-model"
        assert config.timeout_s == 12.5
        assert config.provider_id == "local-provider"
        assert config.provider_name == "Local Provider"
        assert config.source == "local"
        assert config.context_window_tokens == 1_000_000
        assert config.supports_1m is True

    def test_missing_local_storage_preserves_environment_fallback(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "missing.json"))
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")
        monkeypatch.setenv("WORKBENCH_LLM_TIMEOUT_S", "not-a-number")

        config = load_llm_config()

        assert config.base_url == "https://env.example.com"
        assert config.api_key == "env-secret"
        assert config.model == "env-model"
        assert config.timeout_s == 60.0
        assert config.provider_id == "environment"
        assert config.provider_name == "Environment"
        assert config.source == "environment"
        assert config.context_window_tokens is None
        assert config.supports_1m is False

    def test_configured_env_reports_provider_without_key(
        self, api: TestClient, configured_env
    ):
        r = api.get("/llm/config")
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert body["base_url"] == "https://llm.example.com"
        assert body["model"] == "deepseek-chat"
        assert body["key_present"] is True
        # the key never leaves the server — not even masked or by prefix
        assert API_KEY not in r.text
        assert "api_key" not in body

    def test_unconfigured_env_reports_missing(
        self, api: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        for name in (
            "WORKBENCH_LLM_BASE_URL",
            "WORKBENCH_LLM_API_KEY",
            "WORKBENCH_LLM_MODEL",
        ):
            monkeypatch.delenv(name, raising=False)
        body = api.get("/llm/config").json()
        assert body["configured"] is False
        assert body["base_url"] is None
        assert body["model"] is None
        assert body["key_present"] is False
