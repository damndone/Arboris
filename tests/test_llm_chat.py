"""POST /llm/chat — provider-agnostic Ask AI route (v1.6.11 slice A).

All tests run offline: the OpenAI-compatible upstream is an httpx.MockTransport
injected through the ``workbench.llm.client._client_factory`` seam.
"""
from __future__ import annotations

import asyncio
import json
import time

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


@pytest.fixture(autouse=True)
def isolated_provider_store(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the default provider path from the developer's real home.

    Without this, a REAL local provider configuration (written by the
    Settings UI into ~/.config/econometrics-workbench/llm-providers.json)
    leaks into the "not configured" expectations — the suite went red on
    2026-07-15 the first time a developer machine had an active provider
    saved. Tests must never read the user's real LLM configuration.

    Tests that need explicit-pin semantics set WORKBENCH_LLM_CONFIG_PATH
    themselves. Ordinary chat tests exercise the default path, where
    environment fallback remains supported.
    """
    monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
    monkeypatch.setattr(
        "workbench.llm.provider_store.Path.home", lambda: tmp_path
    )


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

    def test_async_chat_completion_cancels_the_inflight_http_request(
        self, monkeypatch
    ):
        started = asyncio.Event()
        closed = False

        class SlowAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                nonlocal closed
                closed = True
                return False

            async def post(self, *_args, **_kwargs):
                started.set()
                await asyncio.Event().wait()
                raise AssertionError("cancelled request resumed")

        monkeypatch.setattr(
            llm_client,
            "_async_client_factory",
            lambda config: SlowAsyncClient(),
            raising=False,
        )

        async def scenario() -> None:
            task = asyncio.create_task(
                llm_client.async_chat_completion(
                    [],
                    llm_client.LLMConfig(
                        base_url="https://api.example.com/v1",
                        api_key=API_KEY,
                        model="test-model",
                        timeout_s=120,
                    ),
                )
            )
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        assert closed is True

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
        assert error["details"]["transport_retry_attempted"] is False

    def test_non_report_transient_transport_failure_is_not_retried(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(
            monkeypatch,
            lambda request: (_ for _ in ()).throw(httpx.ReadError("connection reset")),
        )

        response = api.post("/llm/chat", json=_chat_body())

        assert response.status_code == 502
        details = response.json()["error"]["details"]
        assert details["transport_retry_attempted"] is False
        assert details["transport_retry_count"] == 0
        assert details["retryable"] is True
        assert len(seen) == 1

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
                "figures": [
                    {
                        "artifact_id": "coef_plot",
                        "chart_type": "coefficient plot",
                        "source": {"estimate": 0.42, "se": 0.08},
                    }
                ],
            },
            "response_guardrails": {"advisory_text_only": True},
        }

    def test_report_mode_accepted(self, api: TestClient, configured_env, monkeypatch):
        _install_upstream(
            monkeypatch,
            lambda request: _ok_upstream("# Report [[c:c1]]"),
        )
        response = api.post("/llm/chat", json=self._report_body())
        assert response.status_code == 200
        assert response.json()["text"] == "# Report [[c:c1]]\n\n[[fig:coef_plot]]"

    def test_invalid_report_is_retried_once_with_contract_correction(
        self, api: TestClient, configured_env, monkeypatch
    ):
        responses = iter(
            [
                _ok_upstream("# Report [[c:source:coef_plot]]"),
                _ok_upstream("# Report [[c:c1]]"),
            ]
        )
        seen = _install_upstream(monkeypatch, lambda request: next(responses))

        response = api.post("/llm/chat", json=self._report_body())

        assert response.status_code == 200, response.text
        assert response.json()["text"] == "# Report [[c:c1]]\n\n[[fig:coef_plot]]"
        assert len(seen) == 2
        retry_messages = json.loads(seen[1].content)["messages"]
        assert "contract" in retry_messages[-1]["content"].lower()
        assert "do not emit or repeat any figure marker" in retry_messages[-1]["content"].lower()
        assert "delete the entire sentence" in retry_messages[-1]["content"].lower()
        assert "evidence boundary" in retry_messages[-1]["content"].lower()

    def test_report_mode_retries_one_transient_transport_failure(
        self, api, configured_env, monkeypatch
    ):
        attempts = 0

        def handler(request: httpx.Request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ReadError("connection reset")
            return _ok_upstream("# Report [[c:c1]]")

        _install_upstream(monkeypatch, handler)

        response = api.post("/llm/chat", json=self._report_body())

        assert response.status_code == 200, response.text
        assert response.json()["text"] == "# Report [[c:c1]]\n\n[[fig:coef_plot]]"
        assert attempts == 2

    def test_report_mode_bounds_deepseek_v4_reasoning_and_output(
        self, api, monkeypatch
    ):
        """Report prose must not spend the whole deadline in hidden reasoning."""

        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://api.deepseek.com/v1")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", API_KEY)
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-v4-pro")
        seen = _install_upstream(
            monkeypatch,
            lambda request: _ok_upstream("# Report [[c:c1]]", model="deepseek-v4-pro"),
        )

        response = api.post("/llm/chat", json=self._report_body())

        assert response.status_code == 200, response.text
        payload = json.loads(seen[0].content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 8192

    def test_report_mode_exhausts_one_transient_transport_retry(
        self, api, configured_env, monkeypatch
    ):
        seen = _install_upstream(
            monkeypatch,
            lambda request: (_ for _ in ()).throw(httpx.ReadError("connection reset")),
        )

        response = api.post("/llm/chat", json=self._report_body())

        assert response.status_code == 502
        details = response.json()["error"]["details"]
        assert details["transport_retry_attempted"] is True
        assert details["transport_retry_count"] == 1
        assert details["retryable"] is True
        assert len(seen) == 2

    def test_report_mode_uses_one_deadline_across_all_corrective_calls(
        self, api: TestClient, configured_env, monkeypatch
    ) -> None:
        """Corrective rounds consume one wall-clock budget instead of resetting it."""

        monkeypatch.setattr(
            "workbench.http.llm_routes.REPORT_MODE_TIMEOUT_S",
            0.05,
        )
        body = self._report_body()
        body["packet"].update(
            {
                "report_standard": "journal_full_v1",
                "required_capabilities": ["regression", "diagnostics.robustness"],
                "excluded_fact_ids": [],
                "capability_manifest": [
                    {
                        "capability_id": "regression",
                        "provider_id": "evidence.regression.v1",
                    },
                    {
                        "capability_id": "diagnostics.robustness",
                        "provider_id": "evidence.diagnostics.v1",
                    },
                ],
            }
        )

        def slow_invalid(_request: httpx.Request) -> httpx.Response:
            time.sleep(0.03)
            return _ok_upstream(
                "# Title\n\n## Results\nThe estimate is 240 and lacks a citation."
            )

        seen = _install_upstream(monkeypatch, slow_invalid)

        response = api.post("/llm/chat", json=body)

        assert response.status_code == 504
        error = response.json()["error"]
        assert error["code"] == "LLM_REPORT_DEADLINE_EXCEEDED"
        assert error["details"]["provider_call_count"] == len(seen)
        assert error["details"]["deadline_seconds"] == pytest.approx(0.05)
        assert error["details"]["phase"] in {
            "contract_correction",
            "final_correction",
        }
        assert len(seen) < 3

    def test_invalid_report_after_retry_fails_closed(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(
            monkeypatch,
            lambda request: _ok_upstream("# Report [[c:c99]]"),
        )

        response = api.post("/llm/chat", json=self._report_body())

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "LLM_RESPONSE_CONTRACT_INVALID"
        assert len(seen) == 2

    def test_invalid_journal_report_after_retry_exposes_quality_details(
        self, api: TestClient, configured_env, monkeypatch
    ):
        body = self._report_body()
        body["packet"].update(
            {
                "report_standard": "journal_full_v1",
                "required_capabilities": ["model.estimation", "diagnostics.robustness"],
                "capability_manifest": [],
            }
        )
        seen = _install_upstream(
            monkeypatch,
            lambda request: _ok_upstream("# Title\nIncomplete 0.86 [[c:c1]]; 240 observations"),
        )

        response = api.post("/llm/chat", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LLM_REPORT_PACKET_INVALID"
        assert "capability manifest" in response.json()["error"]["message"]
        assert seen == []

    def test_report_prompt_carries_cite_rule_and_fact_table(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(
            monkeypatch,
            lambda request: _ok_upstream("# Report [[c:c1]]"),
        )
        api.post("/llm/chat", json=self._report_body())
        system_prompt = json.loads(seen[0].content)["messages"][0]["content"]
        assert "[[c:ID]]" in system_prompt
        assert "fact_table" in system_prompt
        assert "\"c1\"" in system_prompt and "0.86" in system_prompt
        assert "do not emit any figure marker" in system_prompt.lower()
        assert "workbench appends each supplied figure marker" in system_prompt.lower()
        assert "[[fig:artifact_id]]" not in system_prompt
        assert "coef_plot" in system_prompt
        assert "numeric source summary" in system_prompt
        # the node-context header must NOT leak into report mode
        assert "node assistant" not in system_prompt

    def test_journal_profile_is_enforced_and_returns_quality_status(
        self, api: TestClient, configured_env, monkeypatch
    ):
        body = self._report_body()
        body["packet"].update(
            {
                "report_standard": "journal_full_v1",
                "required_capabilities": ["regression", "diagnostics.robustness"],
                "excluded_fact_ids": [],
                "capability_manifest": [
                    {
                        "capability_id": "regression",
                        "provider_id": "evidence.regression.v1",
                    },
                    {
                        "capability_id": "diagnostics.robustness",
                        "provider_id": "evidence.diagnostics.v1",
                    },
                ],
            }
        )
        journal_filler = " ".join(
            f"The interpretation remains conditional because the supplied {topic} and {qualifier} limit what this run can establish."
            for topic in [
                "sample definition", "measurement choices", "variable coding", "missingness review",
                "model specification", "uncertainty reporting", "diagnostic scope", "lineage context",
                "comparison baseline", "outcome definition", "predictor interpretation", "data coverage",
                "reference category", "estimation assumptions", "robustness checks", "artifact provenance",
                "research question", "practical interpretation",
            ]
            for qualifier in ("measurement choices", "evidence boundary")
        )
        complete = """# Title

## Abstract
The research question, data, method, principal result 0.86 [[c:c1]], and limitation are stated in this evidence-bound abstract.

## Research question and scope
This section states the research question and scope.

## Data
The data are described from the supplied evidence.

## Variables and transformations
Variables and transformations are described.

## Methods
The regression method is described.

## Results
### Main estimate
Regression estimate 0.86 [[c:c1]] and covariance HC1 [[c:c2]]. The positive association is conditional on the supplied model.

### Interpretation and implications
The findings indicate an empirical association, not a causal effect, and the implication is limited to the supplied evidence.

## Diagnostics and robustness
Diagnostics and robustness are discussed.

## Limitations
Evidence and scope limitations are stated.

## Conclusion
The conclusion remains conditional on the supplied evidence.
    """ + journal_filler
        responses = iter([
            _ok_upstream("# Title\n\n## Results\nIncomplete 0.86 [[c:c1]]"),
            _ok_upstream(complete),
        ])
        seen = _install_upstream(monkeypatch, lambda request: next(responses))

        response = api.post("/llm/chat", json=body)

        assert response.status_code == 200, response.text
        assert response.json()["report_quality"]["status"] == "exportable"
        assert len(seen) == 2
        prompt = json.loads(seen[0].content)["messages"][0]["content"]
        assert "journal_full_v1" in prompt
        assert "Abstract" in prompt
        assert "required capabilities" in prompt.lower()
        assert "exactly these markdown headings" in prompt.lower()
        assert "before returning, verify" in prompt.lower()
        assert "model.estimation" in prompt
        assert "diagnostics.robustness" in prompt
        assert "literal phrases" in prompt.lower()
        assert "never round" in prompt.lower()
        assert "evidence boundary" in prompt.lower()

    def test_final_journal_correction_names_valid_citations_and_exempts_marker_ids(
        self, api: TestClient, configured_env, monkeypatch
    ) -> None:
        """The conservative retry must still make a cited Results section possible."""

        from workbench import report_quality

        monkeypatch.setattr(report_quality, "JOURNAL_MIN_LATIN_WORDS", 1)
        body = self._report_body()
        body["packet"].update(
            {
                "report_standard": "journal_full_v1",
                "required_capabilities": ["regression", "diagnostics.robustness"],
                "excluded_fact_ids": [],
                "capability_manifest": [
                    {
                        "capability_id": "regression",
                        "provider_id": "evidence.regression.v1",
                    },
                    {
                        "capability_id": "diagnostics.robustness",
                        "provider_id": "evidence.diagnostics.v1",
                    },
                ],
            }
        )
        valid_report = """# Evidence-bounded report

## Abstract
The research question uses the supplied data and regression method. The principal result is an association grounded in evidence [[c:c1]], and the limitation is the bounded design.

## Research question and scope
The research question concerns a conditional association within the supplied run and no broader population claim.

## Data
The data description is restricted to the server-supplied evidence packet and its recorded lineage.

## Variables and transformations
Variables and transformations are described only where the supplied evidence establishes their meaning.

## Methods
The regression method is interpreted as an associational model under the recorded specification and covariance evidence.

## Results
The regression finding indicates a positive conditional association supported by the supplied result [[c:c1]].

## Diagnostics and robustness
Diagnostics and robustness are discussed only to the extent represented in the supplied evidence packet.

## Limitations
The evidence boundary limits interpretation, and the report does not establish causal effects or unsupported generalization.

## Conclusion
The conclusion remains conditional on the supplied evidence, model specification, and recorded diagnostic scope.
"""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls < 3:
                return _ok_upstream(
                    "# Title\n\n## Results\nThe estimate is 240 and lacks a citation."
                )
            final_prompt = json.loads(request.content)["messages"][-1]["content"]
            if (
                "[[c:c1]]" in final_prompt
                and "citation marker" in final_prompt.lower()
                and "exempt" in final_prompt.lower()
            ):
                return _ok_upstream(valid_report)
            return _ok_upstream(
                valid_report.replace(" [[c:c1]]", "").replace(" [[c:c1]]", "")
            )

        seen = _install_upstream(monkeypatch, handler)

        response = api.post("/llm/chat", json=body)

        assert response.status_code == 200, response.text
        assert response.json()["report_quality"]["status"] == "exportable"
        assert len(seen) == 3
        final_prompt = json.loads(seen[-1].content)["messages"][-1]["content"]
        assert "[[c:c1]]" in final_prompt
        assert "citation marker" in final_prompt.lower()
        assert "exempt" in final_prompt.lower()

    def test_invalid_report_packet_is_rejected_before_provider_call(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(
            monkeypatch,
            lambda request: pytest.fail("invalid packet reached provider"),
        )
        body = self._report_body()
        body["packet"]["fact_table"].append(body["packet"]["fact_table"][0])

        response = api.post("/llm/chat", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LLM_REPORT_PACKET_INVALID"
        assert seen == []

    def test_figure_mode_prompt_forbids_pixels_and_isolates_headers(
        self, api: TestClient, configured_env, monkeypatch
    ):
        """G2: figure mode must interpret from the numeric source, never pixels."""
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream("reading the numbers"))
        body = {
            "mode": "workbench_figure_context_v1",
            "question": "What does this coefficient plot show?",
            "packet": {
                "figure_context_version": "figure-ai-context/v1",
                "figure": {"artifact_id": "coef_plot", "chart_type": "coefficient plot"},
                "source": {"artifact_id": "ols_1", "kind": "model", "preview_json": "{\"education\": 1.23}"},
            },
        }
        response = api.post("/llm/chat", json=body)
        assert response.status_code == 200

        system_prompt = json.loads(seen[0].content)["messages"][0]["content"]
        assert "figure assistant" in system_prompt
        assert "CANNOT see the image" in system_prompt
        # the numeric source must travel with the packet
        assert "education" in system_prompt
        # neither the node-context nor the report header may leak into figure mode
        assert "node assistant" not in system_prompt
        assert "[[c:ID]]" not in system_prompt

    def test_unknown_mode_lists_every_supported_mode(self, api: TestClient, configured_env):
        response = api.post("/llm/chat", json={**self._report_body(), "mode": "bogus"})
        assert response.status_code == 422
        assert response.json()["error"]["details"]["supported_modes"] == [
            "workbench_node_context_v1",
            "workbench_report_v1",
            "workbench_figure_context_v1",
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

    def test_missing_explicit_store_fails_closed_never_environment_fallback(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        """The incident this closes: an offline smoke config file vanished and
        load_llm_config silently fell back to the operator's REAL provider —
        one real DeepSeek call left the machine. An explicitly pinned config
        path that does not exist is a configuration error, not permission to
        guess another source. This test used to assert the fallback; it now
        asserts the refusal.
        """

        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "missing.json"))
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")

        config = load_llm_config()

        assert config.is_configured() is False
        assert config.source == "explicit_config_missing"
        assert config.base_url == ""
        assert config.api_key == ""
        assert "WORKBENCH_LLM_CONFIG_PATH" in config.configuration_error_message()
        assert "does not exist" in config.configuration_error_message()

    def test_incomplete_explicit_provider_fails_closed_never_environment_fallback(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        """A valid pinned store with an unusable active provider is still a pin."""

        store = tmp_path / "pinned.json"
        store.write_text(
            json.dumps(
                {
                    "version": 1,
                    "active_provider_id": "offline",
                    "providers": [
                        {
                            "id": "offline",
                            "name": "Offline",
                            "base_url": "http://127.0.0.1:9/v1",
                            "model": "offline-model",
                            "api_key": "",
                            "timeout_s": 60.0,
                            "models": [],
                            "website_url": "",
                            "icon": "",
                            "notes": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(store))
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "sk-test-env-only")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")

        config = load_llm_config()

        assert config.is_configured() is False
        assert config.source == "explicit_config_unconfigured"
        assert config.base_url == ""
        assert config.api_key == ""
        assert "Refusing to fall back" in config.configuration_error_message()

    def test_invalid_explicit_store_fails_closed_never_environment_fallback(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(broken))
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")

        config = load_llm_config()

        assert config.is_configured() is False
        assert config.source == "explicit_config_invalid"
        assert "not a valid" in config.configuration_error_message()

    def test_missing_explicit_store_refuses_chat_with_the_true_reason(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, api: TestClient
    ):
        """The call-out endpoint must error loudly — and truthfully."""

        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "missing.json"))
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")

        response = api.post("/llm/chat", json=_chat_body())

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "LLM_NOT_CONFIGURED"
        assert "WORKBENCH_LLM_CONFIG_PATH" in error["message"]
        assert "Refusing to fall back" in error["message"]

    def test_environment_fallback_still_works_on_the_default_path(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        """Fail-closed is scoped to the pinned path; a fresh machine with only
        env vars and no store file anywhere keeps working."""

        monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
        monkeypatch.setattr(
            "workbench.llm.provider_store.Path.home", lambda: tmp_path
        )
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")
        monkeypatch.setenv("WORKBENCH_LLM_TIMEOUT_S", "not-a-number")

        config = load_llm_config()

        assert config.base_url == "https://env.example.com"
        assert config.api_key == "env-secret"
        assert config.model == "env-model"
        assert config.timeout_s == 60.0
        assert config.source == "environment"
        assert config.provider_id == "environment"
        assert config.provider_name == "Environment"
        assert config.source == "environment"
        assert config.context_window_tokens is None
        assert config.supports_1m is False

    def test_default_path_falls_back_when_active_provider_is_unconfigured(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        """Fail-closed is scoped to the pinned path.

        On the default path a store whose active provider lost its key (the
        Settings-UI "clear key" / "delete active provider" flow) must still
        fall back to the environment. The tests that used to cover this were
        correctly converted to pinned fail-closed semantics; this keeps the
        default-path behaviour pinned.
        """

        monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
        monkeypatch.setattr(
            "workbench.llm.provider_store.Path.home", lambda: tmp_path
        )
        default_store = (
            tmp_path / ".config" / "econometrics-workbench" / "llm-providers.json"
        )
        default_store.parent.mkdir(parents=True)
        default_store.write_text(
            json.dumps(
                {
                    "version": 1,
                    "active_provider_id": "local",
                    "providers": [
                        {
                            "id": "local",
                            "name": "Local",
                            "base_url": "https://local.example.com",
                            "model": "local-model",
                            "api_key": "",
                            "timeout_s": 60.0,
                            "models": [],
                            "website_url": "",
                            "icon": "",
                            "notes": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://env.example.com/")
        monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "env-secret")
        monkeypatch.setenv("WORKBENCH_LLM_MODEL", "env-model")

        config = load_llm_config()

        assert config.source == "environment"
        assert config.is_configured() is True
        assert config.base_url == "https://env.example.com"

    def test_configured_env_reports_provider_without_key(
        self, api: TestClient, configured_env, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        # This test exercises the default environment path. Keep it isolated
        # from both the autouse explicit empty store and the developer's home.
        monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
        monkeypatch.setattr(
            "workbench.llm.provider_store.Path.home", lambda: tmp_path
        )
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


class TestFigureVisionOptIn:
    """v1.7 G2 step 2 — sending the rendered chart is opt-in and capability-gated."""

    PNG = "data:image/png;base64,iVBORw0KGgo="

    def _figure_body(self, **overrides):
        body = {
            "mode": "workbench_figure_context_v1",
            "question": "Interpret this chart.",
            "packet": {
                "figure_context_version": "figure-ai-context/v1",
                "figure": {"artifact_id": "coef_plot", "chart_type": "coefficient plot"},
                "source": {"artifact_id": "ols_1", "kind": "model", "preview_json": "{\"education\": 1.23}"},
            },
        }
        body.update(overrides)
        return body

    def _vision_provider(self, tmp_path, monkeypatch, *, vision: bool):
        monkeypatch.setenv("WORKBENCH_LLM_CONFIG_PATH", str(tmp_path / "providers.json"))
        provider = ProviderRecord(
            id="p1",
            name="Vision Provider",
            base_url="https://vision.example.com",
            model="vmodel",
            api_key="secret",
            models=[ModelRecord("V", "vmodel", 128_000, False, vision)],
        )
        save_provider_store(ProviderStore(active_provider_id="p1", providers=[provider]))

    def test_text_only_by_default_no_image_part(
        self, api: TestClient, configured_env, monkeypatch
    ):
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream("ok"))
        api.post("/llm/chat", json=self._figure_body())
        payload = json.loads(seen[0].content)
        # default request carries a plain string content — no image travels
        assert payload["messages"][1]["content"] == "Interpret this chart."
        assert "image_url" not in seen[0].content.decode()
        assert "CANNOT see the image" in payload["messages"][0]["content"]

    def test_opt_in_image_sent_as_multimodal_part_with_vision_header(
        self, api: TestClient, tmp_path, monkeypatch
    ):
        self._vision_provider(tmp_path, monkeypatch, vision=True)
        seen = _install_upstream(monkeypatch, lambda request: _ok_upstream("ok"))

        response = api.post("/llm/chat", json=self._figure_body(image_data_url=self.PNG))
        assert response.status_code == 200

        payload = json.loads(seen[0].content)
        content = payload["messages"][1]["content"]
        assert content[0] == {"type": "text", "text": "Interpret this chart."}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == self.PNG
        header = payload["messages"][0]["content"]
        # the text-only "cannot see" rule must NOT be claimed once an image is sent
        assert "CANNOT see the image" not in header
        assert "chose to send you the rendered" in header
        # numbers must still come from the numeric source, not the pixels
        assert "never read off the image" in header

    def test_image_rejected_when_model_is_not_vision_capable(
        self, api: TestClient, tmp_path, monkeypatch
    ):
        self._vision_provider(tmp_path, monkeypatch, vision=False)
        response = api.post("/llm/chat", json=self._figure_body(image_data_url=self.PNG))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LLM_CHAT_VISION_UNSUPPORTED"

    def test_image_rejected_outside_figure_mode(
        self, api: TestClient, tmp_path, monkeypatch
    ):
        self._vision_provider(tmp_path, monkeypatch, vision=True)
        response = api.post(
            "/llm/chat",
            json=self._figure_body(mode="workbench_node_context_v1", image_data_url=self.PNG),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LLM_CHAT_IMAGE_NOT_ALLOWED"

    def test_non_png_data_url_rejected(self, api: TestClient, tmp_path, monkeypatch):
        self._vision_provider(tmp_path, monkeypatch, vision=True)
        response = api.post(
            "/llm/chat",
            json=self._figure_body(image_data_url="https://evil.example.com/x.png"),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "LLM_CHAT_IMAGE_INVALID"

    def test_llm_config_exposes_vision_capability(
        self, api: TestClient, tmp_path, monkeypatch
    ):
        self._vision_provider(tmp_path, monkeypatch, vision=True)
        assert api.get("/llm/config").json()["supports_vision"] is True
