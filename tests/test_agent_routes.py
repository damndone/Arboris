from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from shutil import copytree

from fastapi.testclient import TestClient

from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.proposals import ProposalStore
from workbench.app import app
from workbench.llm.config import LLMConfig
from workbench.lineage.node_write_validation import build_rerun_operation_context


class FakeAgentAdapter:
    instances: list["FakeAgentAdapter"] = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent.text_delta(request.request_id, "已读取当前分析上下文。")
        yield ModelStreamEvent.done(request.request_id)


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
        "context_fingerprint": "fp-agent-1",
        "selection": {"forest_node_key": "node:ols"},
        "response_guardrails": {
            "advisory_text_only": True,
            "graph_mutations_allowed": False,
        },
    }


def test_chain_protocol_uses_notebook_receipt_evidence_directly() -> None:
    """Receipt projections are final bounded evidence, not operation records."""
    from workbench.http.agent_routes import CHAIN_AGENT_PROTOCOL

    assert "inspect_notebook_workflow_results" in CHAIN_AGENT_PROTOCOL
    assert "cite its returned post_estimation_evidence directly" in CHAIN_AGENT_PROTOCOL
    assert "never call inspect_operation_artifact for those ids" in CHAIN_AGENT_PROTOCOL


def test_agent_session_turn_is_durable_and_replayable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    FakeAgentAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200
        session = created.json()
        assert session["role"] == "chain"
        assert session["context_fingerprint"] == "fp-agent-1"
        session_id = session["session_id"]

        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "检查当前模型有什么风险？"},
        )
        assert turn.status_code == 200
        assert turn.json()["assistant"]["content"] == "已读取当前分析上下文。"
        assert turn.json()["status"] == "idle"

        loaded = client.get(
            f"/agent/sessions/{session_id}",
            params={"project_root": str(project_root)},
        )
        assert loaded.status_code == 200
        assert [item["role"] for item in loaded.json()["messages"]] == [
            "user",
            "assistant",
        ]
        assert "fp-agent-1" in FakeAgentAdapter.instances[-1].requests[0].messages[0]["content"]

        events = client.get(
            f"/agent/sessions/{session_id}/events",
            params={"project_root": str(project_root)},
        )
        assert events.status_code == 200
        assert {event["event_type"] for event in events.json()["events"]} >= {
            "session_created",
            "message_end",
        }

        # Design §10.1: Agent metadata lives under the project's workbench/
        # namespace, never at the project root next to runs/ and data/.
        assert (project_root / "workbench" / "agent-sessions" / f"{session_id}.jsonl").is_file()
        assert (project_root / "workbench" / "agent-events" / f"{session_id}.jsonl").is_file()
        assert not (project_root / "agent-sessions").exists()
        assert not (project_root / "agent-events").exists()


def test_chain_session_canonicalizes_client_head_against_durable_chain(
    tmp_path: Path,
) -> None:
    """A selected historical node keeps its owner while Chain head is server-owned."""

    from workbench.agent.chains import ChainStore

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    copytree(project_root / "runs" / "run-a", project_root / "runs" / "run-b")
    ChainStore(project_root / "workbench").create_root(
        chain_id="chain-a",
        run_family_id="legacy-family:run-a",
        active_head_run_id="run-b",
        agent_session_id="existing-chain-session",
    )

    packet = _context_packet()
    packet.update(
        {
            "context_fingerprint": "client-preview-fingerprint",
            "selection": {
                "forest_node_key": "hash-a::model:ols_1",
                "node_hash": "hash-a",
            },
            "operation_target": {
                "owner_run_id": "run-a",
                "op_node_id": "model:ols_1",
                "node_hash": "hash-a",
                "node_state": "materialized",
            },
            "ownership": {
                "active_head_run_id": "run-a",
                "owner_run_id": "run-a",
                "owner_resolution": "active_head_contains_node",
                "candidate_run_ids": ["run-a"],
                "shared_by_run_ids": ["run-a"],
            },
        }
    )

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-b",
                "context_packet": packet,
            },
        )

    assert created.status_code == 200, created.text
    assert created.json()["context_fingerprint"] != "client-preview-fingerprint"
    session_id = created.json()["session_id"]
    entries = [
        json.loads(line)
        for line in (project_root / "workbench" / "agent-sessions" / f"{session_id}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    context_entry = next(
        entry for entry in entries if entry["payload"].get("message_type") == "agent_context"
    )
    canonical_packet = json.loads(context_entry["payload"]["content"].split("\n", 1)[1])

    assert canonical_packet["ownership"]["active_head_run_id"] == "run-b"
    assert canonical_packet["ownership"]["owner_run_id"] == "run-a"
    assert canonical_packet["ownership"]["owner_resolution"] == "selected_run_hint"
    assert canonical_packet["operation_target"]["owner_run_id"] == "run-a"
    assert canonical_packet["context_fingerprint"] != "client-preview-fingerprint"
    assert any(
        "durable Chain active head" in warning
        for warning in canonical_packet["context_diagnostics"]["warnings"]
    )


def test_chain_session_rebuilds_minimal_forest_selection_context(
    tmp_path: Path,
) -> None:
    """The legacy surface must not make a Chain Agent guess node identity."""

    from workbench.agent.chains import ChainStore

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    copytree(project_root / "runs" / "run-a", project_root / "runs" / "run-b")
    ChainStore(project_root / "workbench").create_root(
        chain_id="chain-a",
        run_family_id="legacy-family:run-a",
        active_head_run_id="run-b",
        agent_session_id="existing-chain-session",
    )

    packet = _context_packet()
    packet.update(
        {
            "context_fingerprint": "client-preview-fingerprint",
            "selection": {"forest_node_key": "hash-a::model:ols_1"},
        }
    )

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-b",
                "context_packet": packet,
            },
        )

    assert created.status_code == 200, created.text
    assert created.json()["context_fingerprint"] != "client-preview-fingerprint"
    session_id = created.json()["session_id"]
    entries = [
        json.loads(line)
        for line in (project_root / "workbench" / "agent-sessions" / f"{session_id}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    context_entry = next(
        entry for entry in entries if entry["payload"].get("message_type") == "agent_context"
    )
    canonical_packet = json.loads(context_entry["payload"]["content"].split("\n", 1)[1])

    assert canonical_packet["ownership"]["active_head_run_id"] == "run-b"
    assert canonical_packet["ownership"]["owner_run_id"] == "run-b"
    assert canonical_packet["operation_target"] == {
        "owner_run_id": "run-b",
        "op_node_id": "model:ols_1",
        "node_hash": "hash-a",
    }


def test_agent_turn_abort_rejects_when_the_session_has_no_active_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Stop is explicit: it must never pretend to cancel an idle session."""

    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200

        stopped = client.post(
            f"/agent/sessions/{created.json()['session_id']}/abort",
            params={"project_root": str(project_root)},
        )

    assert stopped.status_code == 409
    assert stopped.json()["error"]["code"] == "AGENT_TURN_NOT_ACTIVE"


def test_agent_turn_abort_targets_only_the_live_session_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The stop route forwards cancellation to the exact live AgentCore."""

    from workbench.http import agent_routes

    class ActiveAgent:
        aborted = False

        async def abort(self) -> None:
            self.aborted = True

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    live = ActiveAgent()

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        monkeypatch.setitem(
            agent_routes._ACTIVE_TURNS,
            agent_routes._active_turn_key(project_root, session_id),
            live,
        )

        stopped = client.post(
            f"/agent/sessions/{session_id}/abort",
            params={"project_root": str(project_root)},
        )

    assert stopped.status_code == 200
    assert stopped.json()["status"] == "cancelling"
    assert live.aborted is True


def test_chain_turn_receives_structured_proposal_protocol(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    FakeAgentAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "如果需要修改，请提出结构化 proposal。"},
        )
        assert turn.status_code == 200

    first_request = FakeAgentAdapter.instances[-1].requests[0]
    protocol_messages = [
        message
        for message in first_request.messages
        if message.get("name") == "workbench_agent_protocol"
    ]
    assert len(protocol_messages) == 1
    protocol = protocol_messages[0]["content"]
    assert "must call propose_operation" in protocol
    assert "does not execute" in protocol
    assert "description does not execute a result" in protocol
    assert "model.joint_f_test" in protocol
    assert "model.quadratic_stationary_point" in protocol
    assert "stationary_point_within_observed_range" in protocol


def test_agent_session_rejects_oversized_context_and_unknown_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app) as client:
        oversized = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={"context_packet": {"payload": "x" * 25_000}},
        )
        assert oversized.status_code == 422
        assert oversized.json()["error"]["code"] == "AGENT_CONTEXT_TOO_LARGE"

        missing = client.get(
            "/agent/sessions/not-a-real-session",
            params={"project_root": str(project_root)},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "AGENT_SESSION_NOT_FOUND"


def test_agent_session_never_returns_provider_secret(tmp_path: Path, monkeypatch) -> None:
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app) as client:
        response = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={"context_packet": _context_packet()},
        )
    assert response.status_code == 200
    assert "test-key" not in json.dumps(response.json())


def test_get_session_projection_returns_typed_links(tmp_path: Path) -> None:
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            f"/agent/sessions/{fixture.chain_session_id}/projection",
            params={"project_root": str(fixture.project_root)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["projection"]["subject"]["kind"] == "agent_session"
    assert any(
        link["href"].get("operation_record_id") == fixture.record_id
        for link in body["projection"]["links"]
    )
    child_run_link = next(
        link
        for link in body["projection"]["links"]
        if link["kind"] == "run" and link["id"] == fixture.child_run_id
    )
    # A child run is reachable through the child Chain Agent that produced it.
    # Preserve that verified session binding so selecting the output cannot
    # silently discard the execution transcript.
    assert child_run_link["href"]["session_id"] == fixture.child_session_id
    hierarchy = body["projection"]["hierarchy"]
    assert hierarchy["ref"]["id"] == "main-session"
    source_chain = next(
        child for child in hierarchy["children"]
        if child["ref"]["id"] == "chain-a"
    )
    assert any(
        child["ref"]["id"] == fixture.child_chain_id
        for child in source_chain["children"]
    )


def test_agent_audit_export_follows_confirmed_operation_into_child_terminal_result(
    tmp_path: Path,
) -> None:
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            f"/agent/sessions/{fixture.chain_session_id}/audit",
            params={"project_root": str(fixture.project_root)},
        )

    assert response.status_code == 200
    audit = response.json()["audit"]
    operation = next(item for item in audit["operations"] if item["record_id"] == fixture.record_id)
    assert operation["child_session"]["session_id"] == fixture.child_session_id
    assert operation["terminal_result"]["status"] == "completed"
    assert operation["terminal_result"]["source"] == "child_session"
    assert fixture.child_run_id in response.json()["markdown"]


def test_agent_audit_export_states_when_no_child_terminal_result_exists(tmp_path: Path) -> None:
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    child_log = (
        fixture.project_root
        / "workbench"
        / "agent-sessions"
        / f"{fixture.child_session_id}.jsonl"
    )
    child_log.write_text("", encoding="utf-8")
    with TestClient(app) as client:
        response = client.get(
            f"/agent/sessions/{fixture.chain_session_id}/audit",
            params={"project_root": str(fixture.project_root), "format": "markdown"},
        )

    assert response.status_code == 200
    assert "terminal result is absent" in response.text


def test_agent_audit_html_is_a_document_not_markdown_in_a_pre(tmp_path: Path) -> None:
    """Found by a live browser session, not by the deterministic suite.

    The HTML format was the Markdown rendering escaped inside one ``<pre>``, so
    a reader who chose HTML got a wall of monospace text with literal ``#`` and
    ``**`` still in it. Nothing tested the rendering, only the JSON and
    Markdown payloads, so "exports as JSON, Markdown or HTML" stayed true by
    name while the third format carried none of the value.
    """
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            f"/agent/sessions/{fixture.chain_session_id}/audit",
            params={"project_root": str(fixture.project_root), "format": "html"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text

    # Structure a reader can move around, rather than one preformatted block.
    assert "<h1>Agent audit</h1>" in body
    assert "<h2>Transcript" in body
    assert "<h2>Operations" in body
    assert "<pre>" not in body.split("<h2>Transcript")[0], (
        "the header region should not be a preformatted dump"
    )

    # Markdown syntax must have been rendered away, not escaped and shipped.
    assert "# Agent audit" not in body
    assert "## Transcript" not in body

    # The evidence itself still has to be there.
    assert fixture.child_run_id in body
    assert fixture.child_session_id in body

    # Long machine payloads are folded, not dropped and not inlined whole.
    assert "<details>" in body


def test_agent_messages_include_durable_navigation_refs(tmp_path: Path) -> None:
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            f"/agent/sessions/{fixture.chain_session_id}",
            params={"project_root": str(fixture.project_root)},
        )

    assert response.status_code == 200
    messages = response.json()["messages"]
    user_message = next(message for message in messages if message["role"] == "user")
    assert any(
        link["href"].get("operation_record_id") == fixture.record_id
        for link in user_message["navigation"]
    )


def test_graph_projection_rejects_unknown_scope(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app) as client:
        response = client.get(
            "/agent/navigation/graph",
            params={
                "project_root": str(project_root),
                "run_id": "unknown-run",
                "node_ref": "model:ols_1",
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NAVIGATION_NOT_FOUND"


def test_get_operation_projection_is_read_only(tmp_path: Path) -> None:
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            f"/agent/sessions/{fixture.chain_session_id}/operations/{fixture.record_id}",
            params={"project_root": str(fixture.project_root)},
        )

    assert response.status_code == 200
    assert response.json()["operation"]["record_id"] == fixture.record_id


def test_get_activity_projection_returns_durable_operation_and_diff(tmp_path: Path) -> None:
    from test_agent_navigation import build_confirmed_rerun_fixture

    fixture = build_confirmed_rerun_fixture(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/agent/activity",
            params={"project_root": str(fixture.project_root)},
        )

    assert response.status_code == 200
    activities = response.json()["activities"]
    assert len(activities) == 1
    activity = activities[0]
    assert activity["kind"] == "operation"
    assert activity["activity_id"] == fixture.record_id
    assert activity["main"]["id"] == "main-session"
    assert activity["chain"]["id"] == "chain-a"
    assert activity["operation"]["id"] == fixture.record_id
    assert activity["status"] == "completed"
    assert activity["effect_status"] == "committed"
    assert activity["projection_status"] == "complete"
    assert activity["diff_ref"]["changed"] == ["covariance"]
    assert activity["verification"]["passed"] is True
    assert {link["kind"] for link in activity["links"]} >= {
        "proposal",
        "graph_node",
        "run",
        "fork",
        "chain",
        "agent_session",
        "diff",
    }
    assert activity["diff"]["href"]["diff"] == "1"
    hierarchy = response.json()["hierarchy"]
    assert hierarchy["ref"]["kind"] == "agent_session"
    assert any(
        child["ref"]["kind"] == "operation"
        and any(grandchild["ref"]["kind"] == "diff" for grandchild in child["children"])
        for child in hierarchy["children"][0]["children"]
    )
    assert {event["event_type"] for event in response.json()["events"]} >= {
        "proposal_ready",
        "proposal_confirmed",
        "operation_completed",
    }


def test_graph_fork_proposal_route_confirms_into_child_agent_without_child_run(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)

    with TestClient(app) as client:
        created = client.post(
            "/agent/fork-proposals",
            params={"project_root": str(project_root)},
            json={
                "source_run_id": "run-a",
                "source_node_ref": "model:ols_1",
                "active_head_run_id": "run-a",
                "reason": "从当前图节点开启新的 Agent 分支",
            },
        )

        assert created.status_code == 200, created.text
        body = created.json()
        assert body["proposal"]["operation_id"] == "graph.fork"
        assert body["navigation"]["kind"] == "proposal"
        session_id = body["session_id"]
        proposal = body["proposal"]

        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal['proposal_id']}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal["revision"],
                "fingerprint": proposal["fingerprint"],
                "active_head_run_id": "run-a",
            },
        )

        assert confirmed.status_code == 200, confirmed.text
        operation = confirmed.json()["operation"]
        assert operation["operation_id"] == "graph.fork"
        assert operation["status"] == "completed"
        assert operation["verification"]["passed"] is True
        assert operation["execution"]["execution_key"].startswith("exec_")
        assert operation["execution"]["bindings"]["fork_id"] == operation["outputs"]["fork_id"]
        assert operation["execution"]["bindings"]["child_chain_id"] == operation["outputs"]["child_chain_id"]
        assert "target_run_id" not in operation["outputs"]
        assert operation["outputs"]["fork_id"]
        assert operation["outputs"]["child_chain_id"]
        assert operation["outputs"]["child_session_id"]
        assert sorted(path.name for path in (project_root / "runs").iterdir()) == ["run-a"]
        assert (project_root / "workbench" / "forks").is_dir()


def test_graph_fork_proposal_rejects_a_request_head_outside_chain_scope(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    run_b = project_root / "runs" / "run-b"
    run_b.mkdir()
    (run_b / "run_manifest.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        session = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-b",
                "context_packet": {},
            },
        )
        assert session.status_code == 200, session.text

        proposal = client.post(
            "/agent/fork-proposals",
            params={"project_root": str(project_root)},
            json={
                "session_id": session.json()["session_id"],
                "source_run_id": "run-a",
                "source_node_ref": "model:ols_1",
                "active_head_run_id": "run-a",
            },
        )

    assert proposal.status_code == 409
    assert proposal.json()["error"]["code"] == "AGENT_PROPOSAL_STALE"


class ToolCallingAdapter:
    """First turn asks for inspect_node_context, second turn summarizes."""

    instances: list["ToolCallingAdapter"] = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len([r for r in ToolCallingAdapter.instances[-1].requests]) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-inspect-1",
                    "tool_id": "inspect_node_context",
                    "arguments": {
                        "owner_run_id": "run-a",
                        "op_node_id": "model:ols_1",
                        "active_head_run_id": "run-a",
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        yield ModelStreamEvent.text_delta(request.request_id, "模型上下文已核对，无需变更。")
        yield ModelStreamEvent.done(request.request_id)


class ProposalCallingAdapter:
    """Use the structured proposal tool after one scoped inspection."""

    instances: list["ProposalCallingAdapter"] = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-inspect-for-proposal",
                    "tool_id": "inspect_node_context",
                    "arguments": {
                        "owner_run_id": "run-a",
                        "op_node_id": "model:ols_1",
                        "active_head_run_id": "run-a",
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return

        if len(self.requests) == 2:
            tool_messages = [
                message for message in request.messages if message.get("role") == "tool"
            ]
            context = json.loads(tool_messages[-1]["content"])["output"]
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-propose",
                    "tool_id": "propose_operation",
                    "arguments": {
                        "operation_id": "model.rerun",
                        "operation_version": "v1",
                        "target": {
                            "run_id": "run-a",
                            "node_ref": "model:ols_1",
                            "node_hash": context["node_hash"],
                            "forest_node_key": context["forest_node_key"],
                        },
                        "preconditions": {
                            "context_version": context["context_version"],
                            "context_fingerprint": context["context_fingerprint"],
                            "active_head_run_id": "run-a",
                            "owner_resolution": context["owner_resolution"],
                        },
                        "changes": {
                            "covariance": {"old": "robust", "new": "unadjusted"}
                        },
                        "evidence_refs": ["result:r_squared=1.0"],
                        "expected_effect": ["standard errors may change"],
                        "risks": ["unadjusted errors assume homoskedasticity"],
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return

        yield ModelStreamEvent.text_delta(request.request_id, "proposal is ready for confirmation")
        yield ModelStreamEvent.done(request.request_id)


def _write_inspectable_run(project_root: Path) -> None:
    import json as _json

    from workbench.graph_model import Graph, Node, NodeKind, Stage
    from workbench.graph_store import GraphStore

    runs_root = project_root / "runs"
    run_root = runs_root / "run-a"
    run_root.mkdir(parents=True)
    GraphStore(runs_root).write(
        Graph(
            schema_version=3,
            run_id="run-a",
            nodes={
                "model:ols_1": Node(
                    id="model:ols_1",
                    kind=NodeKind.MODEL,
                    display_label="OLS",
                    created_at="2026-07-14T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    stage=Stage.MODEL,
                )
            },
            edges={},
            branches={},
        )
    )
    (run_root / "node_index.json").write_text(
        _json.dumps({"model:ols_1": {"node_hash": "hash-a"}}), encoding="utf-8"
    )
    (run_root / "run_inputs.json").write_text(
        _json.dumps({"rerun_of": None, "form": {"model_type": "ols"}}),
        encoding="utf-8",
    )
    (run_root / "run_manifest.json").write_text(
        _json.dumps(
            {
                "status": "completed",
                "started_at": "2026-07-14T00:00:00+00:00",
                "model_routing": {
                    "requested_model_type": "ols",
                    "effective_model_type": "ols",
                },
            }
        ),
        encoding="utf-8",
    )


def test_chain_turn_persists_structured_proposal_from_tool_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    ProposalCallingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ProposalCallingAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "提出只修改 covariance 的结构化 proposal。"},
        )
        assert turn.status_code == 200, turn.text
        payload = turn.json()
        assert payload["session"]["proposals"]
        proposal = payload["session"]["proposals"][0]
        assert proposal["operation_id"] == "model.rerun"
        assert proposal["status"] == "pending"
        assert proposal["changes"] == {
            "covariance": {"old": "robust", "new": "unadjusted"}
        }
        assert payload["assistant"]["content"] == "proposal is ready for confirmation"

    assert not list((project_root / "runs").glob("run-b"))


def _snapshot(project_root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(project_root)): path.read_bytes()
        for path in sorted(project_root.rglob("*"))
        if path.is_file() and "workbench" not in path.parts
    }


def _create_route_proposal(
    project_root: Path,
    *,
    session_id: str,
    chain_id: str = "chain-a",
):
    context = build_rerun_operation_context(
        project_root / "runs",
        request_id="route-proposal-context",
        owner_run_id="run-a",
        op_node_id="model:ols_1",
        active_head_run_id="run-a",
    )
    return ProposalStore(project_root / "workbench").create(
        session_id=session_id,
        chain_id=chain_id,
        operation_id="model.rerun",
        target={
            "run_id": "run-a",
            "node_ref": "model:ols_1",
            "node_hash": context.node_hash,
            "forest_node_key": context.forest_node_key,
        },
        preconditions={
            "context_version": context.context_version,
            "context_fingerprint": context.context_fingerprint,
            "active_head_run_id": "run-a",
            "owner_resolution": context.owner_resolution,
        },
        changes={"covariance": {"old": "nonrobust", "new": "HC1"}},
        evidence_refs=["diagnostic:MODEL_DIAGNOSTIC_WARNING"],
        expected_effect=["standard errors may change"],
        risks=["small samples may overinflate standard errors"],
    )


def test_proposal_is_listed_and_confirmation_is_pending_without_rerun_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        proposal = _create_route_proposal(project_root, session_id=session_id)

        listed = client.get(
            f"/agent/sessions/{session_id}/proposals",
            params={"project_root": str(project_root)},
        )
        assert listed.status_code == 200
        assert listed.json()["proposals"] == [proposal.to_dict() | {"status": "pending"}]

        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal.revision,
                "fingerprint": proposal.fingerprint,
                "active_head_run_id": "run-a",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        payload = confirmed.json()
        assert payload["proposal"]["status"] == "confirmed"
        # Design §8.2: user confirmation IS the execution gate — the endpoint
        # runs the request-independent executor immediately. This fixture run
        # is not genuinely rerunnable, so the operation must land as a durable
        # `failed` record (never a fake success) and no ghost child run may
        # appear. The healthy end-to-end path is covered by
        # test_confirmed_proposal_executes_rerun_and_reconciles_to_completion.
        assert payload["operation"]["status"] == "failed"
        assert payload["operation"]["error"]
        assert payload["operation"]["proposal_id"] == proposal.proposal_id
        assert list((project_root / "runs").iterdir()) == [project_root / "runs" / "run-a"]


def test_proposal_confirmation_is_scoped_and_stale_context_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)

    with TestClient(app) as client:
        first = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": {},
            },
        ).json()["session_id"]
        second = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-b",
                "run_id": "run-a",
                "context_packet": {},
            },
        ).json()["session_id"]
        proposal = _create_route_proposal(project_root, session_id=first)

        other_scope = client.get(
            f"/agent/sessions/{second}/proposals",
            params={"project_root": str(project_root)},
        )
        assert other_scope.status_code == 200
        assert other_scope.json()["proposals"] == []

        crossed = client.post(
            f"/agent/sessions/{second}/proposals/{proposal.proposal_id}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal.revision,
                "fingerprint": proposal.fingerprint,
                "active_head_run_id": "run-a",
            },
        )
        assert crossed.status_code == 404
        assert crossed.json()["error"]["code"] == "AGENT_PROPOSAL_NOT_FOUND"

        stale = client.post(
            f"/agent/sessions/{first}/proposals/{proposal.proposal_id}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal.revision,
                "fingerprint": proposal.fingerprint,
                "active_head_run_id": "run-no-longer-current",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "AGENT_PROPOSAL_STALE"
        assert not list((project_root / "workbench" / "operation-records").glob("*.jsonl"))


def test_proposal_confirmation_uses_chain_store_active_head(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A request must not replace the ChainStore's authoritative active head."""
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    run_b = project_root / "runs" / "run-b"
    run_b.mkdir()
    (run_b / "run_manifest.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-b",
                "context_packet": _context_packet(),
            },
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]

        proposal = _create_route_proposal(project_root, session_id=session_id)
        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal.revision,
                "fingerprint": proposal.fingerprint,
                "active_head_run_id": "run-a",
            },
        )

    assert confirmed.status_code == 409
    assert confirmed.json()["error"]["code"] == "AGENT_PROPOSAL_STALE"


def test_proposal_decline_is_a_scoped_append_only_decision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Declining a proposal records the user's decision without executing it."""
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)

    with TestClient(app) as client:
        session_id = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": {},
            },
        ).json()["session_id"]
        proposal = _create_route_proposal(project_root, session_id=session_id)

        declined = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/decline",
            params={"project_root": str(project_root)},
            json={"reason": "保留当前模型设定"},
        )

        assert declined.status_code == 200, declined.text
        payload = declined.json()
        assert payload["status"] == "declined"
        assert payload["proposal"]["status"] == "declined"
        assert payload["proposal"]["decision"]["reason"] == "保留当前模型设定"
        assert not list((project_root / "workbench" / "operation-records").glob("*.jsonl"))
        assert not list((project_root / "runs").glob("run-child*"))

        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal.revision,
                "fingerprint": proposal.fingerprint,
                "active_head_run_id": "run-a",
            },
        )
        assert confirmed.status_code == 409
        assert confirmed.json()["error"]["code"] == "AGENT_PROPOSAL_CONFLICT"


def test_proposal_revision_route_preserves_scope_and_rejects_stale_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Revision edits only the allowlisted proposal payload, never its target."""
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)

    with TestClient(app) as client:
        session_id = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={"role": "chain", "chain_id": "chain-a", "context_packet": {}},
        ).json()["session_id"]
        proposal = _create_route_proposal(project_root, session_id=session_id)

        revised = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/revise",
            params={"project_root": str(project_root)},
            json={
                "base_revision": proposal.revision,
                "changes": {"covariance": {"old": "robust", "new": "unadjusted"}},
                "expected_effect": ["standard errors change"],
            },
        )

        assert revised.status_code == 200, revised.text
        payload = revised.json()
        assert payload["status"] == "pending"
        assert payload["proposal"]["revision"] == 2
        assert payload["proposal"]["changes"]["covariance"]["new"] == "unadjusted"
        assert payload["proposal"]["target"] == proposal.target
        assert payload["proposal"]["preconditions"] == proposal.preconditions

        stale = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/revise",
            params={"project_root": str(project_root)},
            json={"base_revision": proposal.revision, "changes": {"covariance": "HC1"}},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "AGENT_PROPOSAL_CONFLICT"

        invalid = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal.proposal_id}/revise",
            params={"project_root": str(project_root)},
            json={"base_revision": 2, "changes": {}},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "AGENT_PROPOSAL_INVALID"


def test_chain_turn_wires_scoped_read_only_tools_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    ToolCallingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ToolCallingAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    before = _snapshot(project_root)

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={"role": "chain", "chain_id": "chain-a", "run_id": "run-a",
                  "context_packet": _context_packet()},
        )
        session_id = created.json()["session_id"]

        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "检查这个模型节点的上下文。"},
        )
        assert turn.status_code == 200
        assert turn.json()["assistant"]["content"] == "模型上下文已核对，无需变更。"

        # The route (not the model) attached the chain-scoped tool descriptors.
        adapter = ToolCallingAdapter.instances[-1]
        tool_ids = {
            tool.get("tool_id") or tool.get("function", {}).get("name")
            for tool in adapter.requests[0].tools
        }
        assert "inspect_node_context" in tool_ids
        assert "propose_operation" in tool_ids
        proposal_tool = next(
            tool for tool in adapter.requests[0].tools if tool.get("tool_id") == "propose_operation"
        )
        proposal_schema = proposal_tool["input_schema"]
        # The envelope stays shape-agnostic: a `oneOf` is an AND with its
        # parent, so requiring model.rerun's target here would make every other
        # operation unproposable (it did — data.columns.cast could not be
        # proposed at all). Each operation's real shape lives in its branch.
        assert proposal_schema["properties"]["target"] == {"type": "object"}
        assert proposal_schema["properties"]["preconditions"] == {"type": "object"}

        rerun_branch = next(
            item
            for item in proposal_schema["oneOf"]
            if item["properties"]["operation_id"]["const"] == "model.rerun"
        )
        assert rerun_branch["properties"]["target"]["required"] == [
            "run_id",
            "node_ref",
            "node_hash",
            "forest_node_key",
        ]
        assert rerun_branch["properties"]["preconditions"]["required"] == [
            "context_version",
            "context_fingerprint",
            "active_head_run_id",
            "owner_resolution",
        ]

        # The tool result is durable typed evidence in the session transcript.
        messages = turn.json()["session"]["messages"]
        tool_messages = [m for m in messages if m["role"] == "tool"]
        assert len(tool_messages) == 1
        payload = json.loads(tool_messages[0]["content"])
        assert payload["ok"] is True
        assert payload["output"]["context_version"] == "node-operation-context/v1"
        assert payload["output"]["owner_run_id"] == "run-a"

        # Tool lifecycle is observable and replayable through the event cursor.
        events = client.get(
            f"/agent/sessions/{session_id}/events",
            params={"project_root": str(project_root)},
        ).json()["events"]
        types = [event["event_type"] for event in events]
        assert "tool_execution_start" in types
        assert "tool_execution_end" in types
        seqs = [event["seq"] for event in events]
        assert seqs == sorted(seqs)

    # Read-only inspection: nothing outside workbench/ metadata changed.
    assert _snapshot(project_root) == before


def test_main_role_turn_exposes_only_read_only_project_evidence_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    FakeAgentAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={"role": "main", "context_packet": _context_packet()},
        )
        session_id = created.json()["session_id"]
        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "总结项目状态。"},
        )
    assert turn.status_code == 200
    tool_ids = {
        tool["tool_id"] for tool in FakeAgentAdapter.instances[-1].requests[0].tools
    }
    assert tool_ids == {
        "inspect_project_model_coefficients",
        "inspect_project_coefficient_transforms",
        "inspect_project_dataset_schema",
        "inspect_project_model_figure_evidence",
        "inspect_project_linear_interaction_effects",
        "inspect_project_notebook_workflow_results",
        "inspect_project_numeric_summary",
        "inspect_project_statistical_evidence",
    }
    descriptor = next(
        tool
        for tool in FakeAgentAdapter.instances[-1].requests[0].tools
        if tool["tool_id"] == "inspect_project_dataset_schema"
    )
    assert descriptor["side_effect"] == "none"
    assert descriptor["scope_requirements"] == ["project"]
    protocol_messages = [
        message
        for message in FakeAgentAdapter.instances[-1].requests[0].messages
        if message.get("name") == "workbench_global_agent_protocol"
    ]
    assert len(protocol_messages) == 1
    assert "project-level advisory Agent" in protocol_messages[0]["content"]
    assert "never invent" in protocol_messages[0]["content"].lower()
    assert "inspect_project_model_coefficients" in protocol_messages[0]["content"]
    assert "at most four exact persisted term names per call" in protocol_messages[0]["content"]
    assert "inspect_project_coefficient_transforms" in protocol_messages[0]["content"]
    assert "inspect_project_dataset_schema" in protocol_messages[0]["content"]
    assert "inspect_project_model_figure_evidence" in protocol_messages[0]["content"]
    assert "inspect_project_notebook_workflow_results" in protocol_messages[0]["content"]
    assert "one receipt lookup with up to sixteen visible candidate run ids" in protocol_messages[0]["content"]
    assert "do not inspect a dataset schema merely to restate a declared model specification" in protocol_messages[0]["content"].lower()
    assert "inspect_project_numeric_summary" in protocol_messages[0]["content"]
    assert "inspect_project_linear_interaction_effects" in protocol_messages[0]["content"]
    assert "one recorded unit" in protocol_messages[0]["content"]
    assert "overlap" in protocol_messages[0]["content"]
    assert "exact sign" in protocol_messages[0]["content"]
    assert "mechanically copy those returned fields" in protocol_messages[0]["content"]
    assert "contradicts the returned p value" in protocol_messages[0]["content"]
    assert "nonrobust significance is false" in protocol_messages[0]["content"]
    assert "inference changes under the two covariance assumptions" in protocol_messages[0]["content"]
    assert "caused by heteroskedasticity" in protocol_messages[0]["content"]
    assert "standard-error size alone does not establish" in protocol_messages[0]["content"]
    assert "a signal, an indication, a hint, or a suggestion" in protocol_messages[0]["content"]
    assert "conditional association, not a causal effect" in protocol_messages[0]["content"]
    assert "variable's real-world meaning" in protocol_messages[0]["content"]
    assert "unique counts do not establish whether a covariate changes within entities" in protocol_messages[0]["content"]
    workflow_descriptor = next(
        tool
        for tool in FakeAgentAdapter.instances[-1].requests[0].tools
        if tool["tool_id"] == "inspect_project_notebook_workflow_results"
    )
    assert workflow_descriptor["input_schema"]["properties"]["run_ids"]["maxItems"] == 16


def test_main_turn_refreshes_protocol_for_existing_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    FakeAgentAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={"role": "main", "context_packet": _context_packet()},
        )
        session_id = created.json()["session_id"]
        marker = "PROTOCOL_UPGRADE_MARKER"
        monkeypatch.setattr(
            agent_routes,
            "MAIN_AGENT_PROTOCOL",
            f"{agent_routes.MAIN_AGENT_PROTOCOL}\n- {marker}",
        )
        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "读取现有证据。"},
        )

    assert turn.status_code == 200
    protocol_messages = [
        message
        for message in FakeAgentAdapter.instances[-1].requests[0].messages
        if message.get("name") == "workbench_global_agent_protocol"
    ]
    assert any(marker in message["content"] for message in protocol_messages)


class ProposingAdapter:
    """Emits one propose_operation call built from real project state."""

    instances: list["ProposingAdapter"] = []
    proposal_arguments: dict = {}

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        ProposingAdapter.instances.append(self)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-propose-1",
                    "tool_id": "propose_operation",
                    "arguments": ProposingAdapter.proposal_arguments,
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        yield ModelStreamEvent.text_delta(request.request_id, "已生成待确认的 rerun 提议。")
        yield ModelStreamEvent.done(request.request_id)


def test_natural_language_turn_can_propose_registry_enabled_graph_fork(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    ProposingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ProposingAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    ProposingAdapter.proposal_arguments = {
        "operation_id": "graph.fork",
        "operation_version": "v1",
        "target": {
            "run_id": "run-a",
            "node_ref": "model:ols_1",
            "node_hash": "model-hash-from-model",
            "forest_node_key": "forest-key-from-model",
        },
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "fingerprint-from-model",
            "active_head_run_id": "run-a",
            "owner_resolution": "model-guess",
        },
        "changes": {"reason": "尝试另一套稳健标准误"},
        "evidence_refs": ["node:model:ols_1"],
        "expected_effect": ["创建一个新的 Agent 分支"],
        "risks": ["分支尚未执行新的统计 run"],
    }

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        session_id = created.json()["session_id"]
        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "从当前节点创建一个新分支。"},
        )

    assert turn.status_code == 200, turn.text
    proposals = turn.json()["session"]["proposals"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["operation_id"] == "graph.fork"
    assert proposal["target"]["node_hash"] != "model-hash-from-model"
    assert proposal["target"]["forest_node_key"] != "forest-key-from-model"
    assert proposal["target"]["source_session_entry_id"]

    with TestClient(app) as client:
        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal['proposal_id']}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal["revision"],
                "fingerprint": proposal["fingerprint"],
                "active_head_run_id": "run-a",
            },
        )

    assert confirmed.status_code == 200, confirmed.text
    operation = confirmed.json()["operation"]
    assert operation["operation_id"] == "graph.fork"
    assert operation["status"] == "completed"
    assert "target_run_id" not in operation["outputs"]
    assert operation["execution"]["bindings"]["fork_id"] == operation["outputs"]["fork_id"]
    assert operation["verification"]["checks"] == {
        "fork_record": True,
        "child_chain": True,
        "child_session": True,
    }
    assert not list((project_root / "runs").glob("run-*child*"))


def test_unsupported_natural_language_operation_creates_no_proposal_or_effect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from workbench.http import agent_routes

    ProposingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ProposingAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_inspectable_run(project_root)
    ProposingAdapter.proposal_arguments = {
        "operation_id": "data.cleaning",
        "operation_version": "v1",
        "target": {
            "run_id": "run-a",
            "node_ref": "model:ols_1",
            "node_hash": "model-hash-from-model",
            "forest_node_key": "forest-key-from-model",
        },
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "fingerprint-from-model",
            "active_head_run_id": "run-a",
            "owner_resolution": "model-guess",
        },
        "changes": {"rule": "drop missing values"},
        "evidence_refs": [],
        "expected_effect": ["change data"],
        "risks": [],
    }

    with TestClient(app) as client:
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(project_root)},
            json={
                "role": "chain",
                "chain_id": "chain-a",
                "run_id": "run-a",
                "context_packet": _context_packet(),
            },
        )
        session_id = created.json()["session_id"]
        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project_root)},
            json={"question": "直接修改缺失值清洗规则。"},
        )

    assert turn.status_code == 200, turn.text
    assert turn.json()["session"]["proposals"] == []
    assert not list((project_root / "workbench" / "operation-records").glob("*.jsonl"))
    assert not list((project_root / "runs").glob("run-*child*"))


def test_confirmed_proposal_executes_rerun_and_reconciles_to_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Design §8.2 over HTTP: user confirmation is the mutation gate — the
    confirm endpoint must execute through the request-independent rerun
    executor (child chain/fork/run), and the reconcile endpoint must complete
    the operation record with deterministic verification once the child run is
    terminal. Idempotent on repeat."""
    import io
    import time

    from workbench.http import agent_routes
    from workbench.lineage.node_write_validation import (
        NodeWriteOperationRequestV1,
        compute_context_fingerprint,
    )
    from workbench.projects import create_project

    ProposingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ProposingAdapter)

    with TestClient(app) as client:
        project = create_project(tmp_path, "demo")
        rows = "\n".join(f"{1 + 2 * i},{i},{i * 3}" for i in range(35))
        created_run = client.post(
            "/runs",
            data={
                "project_root": str(project.root),
                "mode": "auto",
                "model_type": "ols",
                "y": "y",
                "x": "x1,x2",
            },
            files={"file": ("d.csv", io.BytesIO(("y,x1,x2\n" + rows + "\n").encode()), "text/csv")},
        )
        parent_run_id = created_run.json()["run_id"]
        for _ in range(150):
            status = client.get(
                f"/runs/{parent_run_id}", params={"project_root": str(project.root)}
            ).json().get("status")
            if status in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert status == "completed"

        node_index = json.loads(
            (project.root / "runs" / parent_run_id / "node_index.json").read_text()
        )
        model_node_id = next(k for k in node_index if k.startswith("model:"))
        node_hash = node_index[model_node_id]["node_hash"]
        fingerprint = compute_context_fingerprint(
            project.root / "runs",
            NodeWriteOperationRequestV1(
                request_id="test-confirm",
                operation="rerun",
                context_version="node-operation-context/v1",
                context_fingerprint="pending",
                owner_run_id=parent_run_id,
                op_node_id=model_node_id,
                node_hash=node_hash,
                forest_node_key=node_hash,
                owner_resolution="active_head_contains_node",
                active_head_run_id=parent_run_id,
            ),
        )
        ProposingAdapter.proposal_arguments = {
            "operation_id": "model.rerun",
            "target": {
                "run_id": parent_run_id,
                "node_ref": model_node_id,
                "node_hash": node_hash,
                "forest_node_key": node_hash,
            },
            "preconditions": {
                "context_version": "node-operation-context/v1",
                "context_fingerprint": fingerprint,
                "active_head_run_id": parent_run_id,
                "owner_resolution": "active_head_contains_node",
            },
            "changes": {"covariance": {"old": "robust", "new": "unadjusted"}},
            "evidence_refs": ["diagnostic:none"],
            "expected_effect": ["standard errors change"],
            "risks": ["nonrobust SEs under heteroskedasticity"],
        }

        session = client.post(
            "/agent/sessions",
            params={"project_root": str(project.root)},
            json={"role": "chain", "chain_id": "chain-a", "run_id": parent_run_id,
                  "context_packet": _context_packet()},
        ).json()
        session_id = session["session_id"]
        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project.root)},
            json={"question": "请提议把 covariance 改为 unadjusted。"},
        )
        assert turn.status_code == 200
        proposals = turn.json()["session"]["proposals"]
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal["status"] == "pending"

        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal['proposal_id']}/confirm",
            params={"project_root": str(project.root)},
            json={
                "revision": proposal["revision"],
                "fingerprint": proposal["fingerprint"],
                "active_head_run_id": parent_run_id,
            },
        )
        assert confirmed.status_code == 200
        operation = confirmed.json()["operation"]
        # Confirmation EXECUTES: the child run is submitted through the
        # request-independent rerun service before the response returns.
        assert operation["status"] == "running"
        assert operation["execution"]["execution_key"].startswith("exec_")
        child_run_id = operation["outputs"]["target_run_id"]
        assert operation["execution"]["bindings"]["child_run_id"] == child_run_id
        assert child_run_id and child_run_id != parent_run_id
        child_inputs = json.loads(
            (project.root / "runs" / child_run_id / "run_inputs.json").read_text()
        )
        assert child_inputs["rerun_of"] == parent_run_id
        assert child_inputs["workbench_context"]["proposal_id"] == proposal["proposal_id"]
        assert child_inputs["form"]["covariance"] == "unadjusted"

        for _ in range(150):
            status = client.get(
                f"/runs/{child_run_id}", params={"project_root": str(project.root)}
            ).json().get("status")
            if status in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert status == "completed"

        record_id = operation["record_id"]
        reconciled = client.post(
            f"/agent/sessions/{session_id}/operations/{record_id}/reconcile",
            params={"project_root": str(project.root)},
        )
        assert reconciled.status_code == 200
        final = reconciled.json()["operation"]
        assert final["status"] == "completed"
        assert final["verification"]
        again = client.post(
            f"/agent/sessions/{session_id}/operations/{record_id}/reconcile",
            params={"project_root": str(project.root)},
        )
        assert again.status_code == 200
        assert again.json()["operation"]["status"] == "completed"

        unknown = client.post(
            f"/agent/sessions/{session_id}/operations/oprec_missing/reconcile",
            params={"project_root": str(project.root)},
        )
        assert unknown.status_code == 404


def test_proposal_canonicalizes_model_supplied_target_references(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Design §5.3: the model supplies REFERENCES; the backend re-derives the
    canonical node_hash / forest_node_key / fingerprint / owner_resolution.
    Live DeepSeek copied the forest projection key (`<hash>::<node_id>`) from
    the UI packet, which the rerun validator correctly rejects at execution —
    the proposal must be canonicalized at creation instead of failing later."""
    import io
    import time

    from workbench.http import agent_routes
    from workbench.projects import create_project

    ProposingAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", ProposingAdapter)

    with TestClient(app) as client:
        project = create_project(tmp_path, "demo")
        rows = "\n".join(f"{1 + 2 * i},{i},{i * 3}" for i in range(35))
        parent_run_id = client.post(
            "/runs",
            data={
                "project_root": str(project.root),
                "mode": "auto",
                "model_type": "ols",
                "y": "y",
                "x": "x1,x2",
            },
            files={"file": ("d.csv", io.BytesIO(("y,x1,x2\n" + rows + "\n").encode()), "text/csv")},
        ).json()["run_id"]
        for _ in range(150):
            status = client.get(
                f"/runs/{parent_run_id}", params={"project_root": str(project.root)}
            ).json().get("status")
            if status in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert status == "completed"
        node_index = json.loads(
            (project.root / "runs" / parent_run_id / "node_index.json").read_text()
        )
        model_node_id = next(k for k in node_index if k.startswith("model:"))
        node_hash = node_index[model_node_id]["node_hash"]

        # The model hands back UI-projection references, not canonical ones.
        ProposingAdapter.proposal_arguments = {
            "operation_id": "model.rerun",
            "target": {
                "run_id": parent_run_id,
                "node_ref": model_node_id,
                "node_hash": node_hash,
                "forest_node_key": f"{node_hash}::{model_node_id}",
            },
            "preconditions": {
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "made-up-by-model",
                "active_head_run_id": parent_run_id,
                "owner_resolution": "selected_run_hint",
            },
            "changes": {"covariance": {"old": "robust", "new": "unadjusted"}},
            "evidence_refs": [],
            "expected_effect": [],
            "risks": [],
        }
        session_id = client.post(
            "/agent/sessions",
            params={"project_root": str(project.root)},
            json={"role": "chain", "chain_id": "chain-a", "run_id": parent_run_id,
                  "context_packet": _context_packet()},
        ).json()["session_id"]
        turn = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(project.root)},
            json={"question": "提议改 covariance。"},
        )
        assert turn.status_code == 200
        proposal = turn.json()["session"]["proposals"][0]
        assert proposal["target"]["forest_node_key"] == node_hash
        assert proposal["target"]["node_hash"] == node_hash
        assert proposal["preconditions"]["context_fingerprint"].startswith("nocv1:")
        assert proposal["preconditions"]["owner_resolution"] == "active_head_contains_node"
