"""v1.9.1: the Agent resumes after a confirmation without the person saying "continue"."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from test_agent_routes import FakeAgentAdapter, _config, _context_packet
from workbench.app import app


def _session(client, project_root: Path) -> str:
    created = client.post(
        "/agent/sessions",
        params={"project_root": str(project_root)},
        json={"role": "chain", "chain_id": "chain-a", "run_id": "run-a", "context_packet": _context_packet()},
    )
    assert created.status_code == 200
    return created.json()["session_id"]


def test_continue_resumes_the_agent_with_a_workbench_note(tmp_path: Path, monkeypatch) -> None:
    from workbench.http import agent_routes

    FakeAgentAdapter.instances.clear()
    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session_id = _session(client, project_root)
        first = client.post(f"/agent/sessions/{session_id}/turns", params={"project_root": str(project_root)},
                            json={"question": "请提出下一步。"})
        assert first.status_code == 200

        resumed = client.post(f"/agent/sessions/{session_id}/continue", params={"project_root": str(project_root)},
                              json={"execution_policy": "proposal_only"})
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["assistant"]["content"] == "已读取当前分析上下文。"

    request = FakeAgentAdapter.instances[-1].requests[-1]
    last = request.messages[-1]
    # The model is resumed from a user-role Workbench note, not a fabricated user message.
    assert last["role"] == "user" and last["content"] == agent_routes.CONTINUATION_NOTE
    assert "Confirmation is how your proposals run" in last["content"]
    # The person's visible transcript still has only the person's own words.
    loaded = TestClient(app, base_url="http://127.0.0.1").get(f"/agent/sessions/{session_id}",
                                                              params={"project_root": str(project_root)})
    assert [m["role"] for m in loaded.json()["messages"]] == ["user", "assistant", "assistant"]


def test_continue_refuses_while_a_turn_is_running(tmp_path: Path, monkeypatch) -> None:
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session_id = _session(client, project_root)
        key = agent_routes._active_turn_key(project_root.resolve(), session_id)
        agent_routes._RESERVED_TURNS.add(key)
        try:
            busy = client.post(f"/agent/sessions/{session_id}/continue", params={"project_root": str(project_root)},
                               json={})
        finally:
            agent_routes._RESERVED_TURNS.discard(key)
        assert busy.status_code == 409
        assert busy.json()["error"]["code"] == "AGENT_TURN_IN_PROGRESS"


def test_session_grants_and_project_rules_are_read_from_their_stores(tmp_path: Path) -> None:
    import json

    from workbench.agent.permissions import PermissionClass, Rule
    from workbench.agent.session import JsonlSessionRepository
    from workbench.http import agent_routes

    root = tmp_path / "project"
    (root / "workbench").mkdir(parents=True)
    (root / "workbench" / "agent-permissions.json").write_text(json.dumps({
        "allow": [{"class": "derive", "operation_id": "model.genesis"}],
        "deny": [{"class": "external"}],
        "ask": [{"class": "nonsense"}],
    }), encoding="utf-8")
    rules = agent_routes._project_permission_rules(root)
    assert rules.allow == (Rule(PermissionClass.DERIVE, "model.genesis"),)
    assert rules.deny == (Rule(PermissionClass.EXTERNAL),) and rules.ask == ()

    repository = JsonlSessionRepository(root / "workbench")
    repository.create_session("s1", chain_id="c", role="chain")
    repository.update_metadata("s1", permission_grants=[{"class": "derive"}, {"class": "external"}])
    grants = agent_routes._session_grants(repository, "s1")
    # External is never grantable, whatever the metadata says.
    assert grants.entries == frozenset({Rule(PermissionClass.DERIVE)})
