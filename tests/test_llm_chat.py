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


def _ok_upstream(text: str = "This node runs OLS.") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-chat",
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
