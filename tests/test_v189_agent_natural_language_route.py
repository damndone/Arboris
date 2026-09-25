from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.api_errors import register_error_handlers
from workbench.app import (
    configure_agent_notebook_runtime,
    configure_notebook_cutover_identity_resolver,
)
from workbench.http import agent_routes
from workbench.http.agent_routes import (
    _server_project_ref,
    _server_session_ref,
    router as agent_router,
)
from workbench.llm.config import LLMConfig
from tests.test_v189_agent_notebook_runtime_bridge import _runtime
from tests.v189_cutover_test_host import make_test_identity_resolver


COMPILER_PREVIEW_TOOL_ID = "compile_natural_language"


def _config() -> LLMConfig:
    return LLMConfig(
        base_url="https://api.example.test",
        api_key="test-key",
        model="test-model",
        context_window_tokens=32_000,
        provider_id="test-provider",
        provider_name="Test provider",
        source="local",
    )


def _context_packet() -> dict[str, object]:
    return {
        "packet_version": "ask-ai-context/v1",
        "context_fingerprint": "fp-natural-language-route",
        "selection": {"forest_node_key": "node:test"},
        "response_guardrails": {
            "advisory_text_only": True,
            "graph_mutations_allowed": False,
        },
    }


class TextAdapter:
    instances: list["TextAdapter"] = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent.text_delta(request.request_id, "只读链路正常。")
        yield ModelStreamEvent.done(request.request_id)


class PreviewCallingAdapter:
    instances: list["PreviewCallingAdapter"] = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self.preview_payloads: list[dict[str, Any]] = []
        self.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-compiler-preview",
                    "tool_id": COMPILER_PREVIEW_TOOL_ID,
                    "arguments": {"normalized_fields": {}},
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return

        tool_message = next(
            message for message in request.messages if message.get("role") == "tool"
        )
        self.preview_payloads.append(json.loads(tool_message["content"]))
        yield ModelStreamEvent.text_delta(request.request_id, "已返回服务端澄清。")
        yield ModelStreamEvent.done(request.request_id)


class ReadyCallingAdapter:
    instances: list["ReadyCallingAdapter"] = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent.tool_call_delta(
            request.request_id,
            {
                "tool_call_id": "call-compiler-ready",
                "tool_id": COMPILER_PREVIEW_TOOL_ID,
                "arguments": {
                    "normalized_fields": {
                        "capability_id": "fixture.contracts.capability",
                        "target_ref": "dataset:runtime-route:1",
                        "data_snapshot_ref": "dataset:snapshot:runtime-route",
                        "data_snapshot_digest": "a" * 64,
                        "requested_effect": "read",
                        "sensitivity": "public",
                    }
                },
            },
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


def _host_app() -> FastAPI:
    host_app = FastAPI()
    register_error_handlers(host_app)
    host_app.include_router(agent_router)
    return host_app


def _create_chain_session(client: TestClient, project_root: Path) -> str:
    response = client.post(
        "/agent/sessions",
        params={"project_root": str(project_root)},
        json={
            "role": "chain",
            "chain_id": "chain-natural-language",
            "run_id": "run-natural-language",
            "context_packet": _context_packet(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


@contextmanager
def _bound_runtime(
    host_app: FastAPI,
    project_root: Path,
    session_id: str,
    *,
    identity: bool,
) -> Iterator[Any]:
    runtime = _runtime()
    project_ref = _server_project_ref(project_root)
    configure_agent_notebook_runtime(
        project_ref=project_ref,
        session_ref=_server_session_ref(session_id),
        compiler=runtime.compiler,
        app_instance=host_app,
    )
    if identity:
        configure_notebook_cutover_identity_resolver(
            make_test_identity_resolver(
                lambda _request, _project_ref, _claimed_session_ref, _notebook_id: (
                    f"principal:agent:{session_id}",
                    _server_session_ref(session_id),
                    project_ref,
                )
            ),
            app_instance=host_app,
        )
    try:
        yield runtime
    finally:
        configure_agent_notebook_runtime(
            project_ref=project_ref,
            session_ref=_server_session_ref(session_id),
            compiler=None,
            app_instance=host_app,
        )
        configure_notebook_cutover_identity_resolver(None, app_instance=host_app)


def test_bound_compiler_turn_exposes_preview_tool_without_legacy_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TextAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", TextAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    host_app = _host_app()

    with TestClient(host_app) as client:
        session_id = _create_chain_session(client, project_root)
        with _bound_runtime(host_app, project_root, session_id, identity=True):
            response = client.post(
                f"/agent/sessions/{session_id}/turns",
                params={"project_root": str(project_root)},
                json={"question": "请说明当前请求还缺少哪些信息。"},
            )

    assert response.status_code == 200, response.text
    tool_ids = {
        tool.get("tool_id") or tool.get("function", {}).get("name")
        for tool in TextAdapter.instances[-1].requests[0].tools
    }
    assert COMPILER_PREVIEW_TOOL_ID in tool_ids
    assert "propose_operation" not in tool_ids


def test_preview_tool_uses_exact_question_and_returns_typed_clarification_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PreviewCallingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(
        agent_routes,
        "OpenAICompatibleModelAdapter",
        PreviewCallingAdapter,
    )
    project_root = tmp_path / "project"
    project_root.mkdir()
    host_app = _host_app()
    question = "请说明当前请求还缺少哪些信息。"

    with TestClient(host_app) as client:
        session_id = _create_chain_session(client, project_root)
        with _bound_runtime(host_app, project_root, session_id, identity=True) as runtime:
            compiler_calls: list[tuple[str, dict[str, Any]]] = []
            original_compile = runtime.compiler.compile_natural_language

            def compile_spy(text: str, **kwargs: Any) -> Any:
                compiler_calls.append((text, dict(kwargs)))
                return original_compile(text, **kwargs)

            execute_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

            def execute_spy(*args: Any, **kwargs: Any) -> Any:
                execute_calls.append((args, kwargs))
                raise AssertionError("natural-language preview must not execute")

            monkeypatch.setattr(runtime.compiler, "compile_natural_language", compile_spy)
            monkeypatch.setattr(runtime.compiler, "execute", execute_spy)
            response = client.post(
                f"/agent/sessions/{session_id}/turns",
                params={"project_root": str(project_root)},
                json={"question": question},
            )

    assert response.status_code == 200, response.text
    assert compiler_calls
    assert compiler_calls[0][0] == question
    assert compiler_calls[0][1]["entrypoint"] == "agent"
    assert execute_calls == []

    tool_payload = PreviewCallingAdapter.instances[-1].preview_payloads[-1]
    assert tool_payload["ok"] is True
    assert tool_payload["output"]["status"] == "clarification_required"
    preview = tool_payload["output"]["preview"]
    assert preview["schema_version"] == "cutover-compilation-preview.v1"
    assert preview["plan_diff"]["status"] == "clarification_required"
    assert preview["clarifications"]
    assert preview["compilation_record_id"] is None


def test_bound_compiler_without_http_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TextAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", TextAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    host_app = _host_app()

    with TestClient(host_app) as client:
        session_id = _create_chain_session(client, project_root)
        with _bound_runtime(host_app, project_root, session_id, identity=False):
            response = client.post(
                f"/agent/sessions/{session_id}/turns",
                params={"project_root": str(project_root)},
                json={"question": "请说明当前请求还缺少哪些信息。"},
            )

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "AGENT_NOTEBOOK_IDENTITY_NOT_BOUND"
    assert TextAdapter.instances
    assert TextAdapter.instances[-1].requests == []


def test_ready_natural_language_preview_creates_server_bound_proposal_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ReadyCallingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ReadyCallingAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    host_app = _host_app()

    with TestClient(host_app) as client:
        session_id = _create_chain_session(client, project_root)
        with _bound_runtime(host_app, project_root, session_id, identity=True) as runtime:
            execute_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

            def execute_spy(*args: Any, **kwargs: Any) -> Any:
                execute_calls.append((args, kwargs))
                raise AssertionError("preview tool must not execute")

            monkeypatch.setattr(runtime.compiler, "execute", execute_spy)
            response = client.post(
                f"/agent/sessions/{session_id}/turns",
                params={"project_root": str(project_root)},
                json={"question": "请对 dataset:runtime-route:1 做分类分析。"},
            )

    assert response.status_code == 200, response.text
    tool_payload = next(
            json.loads(message["content"])
            for message in response.json()["session"]["messages"]
            if message["role"] == "tool"
        )
    assert tool_payload["ok"] is True
    assert tool_payload["output"]["status"] == "proposal_ready"
    assert tool_payload["output"]["requires_confirmation"] is True
    proposal = tool_payload["output"]["proposal"]
    assert proposal["compilation_record_id"].startswith("compilation-record:")
    assert proposal["proposal_id"].startswith("proposal_")
    assert execute_calls == []
