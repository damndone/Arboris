"""v1.9.1: the Agent resumes after a confirmation without the person saying "continue"."""

from __future__ import annotations
from workbench.http import agent_route_permissions, agent_route_runtime

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
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", _config)
    monkeypatch.setattr(agent_route_runtime, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
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

    monkeypatch.setattr(agent_route_runtime, "load_llm_config", _config)
    monkeypatch.setattr(agent_route_runtime, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
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
        "ask": [],
    }), encoding="utf-8")
    rules = agent_route_permissions._project_permission_rules(root)
    assert rules.allow == (Rule(PermissionClass.DERIVE, "model.genesis"),)
    assert rules.deny == (Rule(PermissionClass.EXTERNAL),) and rules.ask == ()

    repository = JsonlSessionRepository(root / "workbench")
    repository.create_session("s1", chain_id="c", role="chain")
    repository.update_metadata("s1", permission_grants=[{"class": "derive"}, {"class": "external"}])
    grants = agent_route_permissions._session_grants(repository, "s1")
    # External is never grantable, whatever the metadata says.
    assert grants.entries == frozenset({Rule(PermissionClass.DERIVE)})


def test_review_every_step_does_not_offer_a_class_grant_for_a_mixed_workflow(tmp_path: Path) -> None:
    from tests.test_read_only_analysis import _Fixture, _recode, _t_test

    fixture = _Fixture(tmp_path)
    receipt = fixture.propose([_recode(), _t_test("test")])
    proposal = fixture.orchestrator.proposal_store.latest_revision(receipt["proposal"]["proposal_id"])
    registry = fixture.orchestrator.operation_registry
    assert agent_route_permissions._session_grant_class(fixture.repository, registry, proposal,
        {"execution_mode": "ask", "execution_policy": "proposal_only"}) is None
    assert agent_route_permissions._session_grant_class(fixture.repository, registry, proposal,
        {"execution_mode": "ask", "execution_policy": "auto_read_only"}) == "derive"


def test_concurrent_grants_preserve_both_classes(tmp_path: Path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from workbench.agent.session import JsonlSessionRepository

    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s1", chain_id="c", role="chain")
    previous_update = repository.update_metadata
    synchronized = Barrier(2, timeout=2)

    def write_after_both_reads(session_id, **fields):
        synchronized.wait()
        return previous_update(session_id, **fields)

    monkeypatch.setattr(repository, "update_metadata", write_after_both_reads)
    with ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(agent_route_permissions._grant_for_session, repository, "s1", cls)
                   for cls in ("analyze", "derive")]
        for future in futures:
            future.result(timeout=4)
    assert {entry["class"] for entry in repository.get_metadata("s1")["permission_grants"]} == {"analyze", "derive"}


def test_the_turn_budget_follows_the_execution_mode(tmp_path: Path, monkeypatch) -> None:
    from workbench.agent.core import AgentCore
    from workbench.http import agent_routes

    seen: list[dict] = []
    original = AgentCore.prompt

    async def recording_prompt(self, text, *, budget=None, **kwargs):
        seen.append(dict(budget or {}))
        return await original(self, text, budget=budget, **kwargs)

    monkeypatch.setattr(AgentCore, "prompt", recording_prompt)
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", _config)
    monkeypatch.setattr(agent_route_runtime, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session_id = _session(client, project_root)
        for mode in ("ask", "auto"):
            response = client.post(f"/agent/sessions/{session_id}/turns", params={"project_root": str(project_root)},
                                   json={"question": "请提出下一步。", "execution_mode": mode})
            assert response.status_code == 200, response.text
    assert seen == [agent_routes.MODE_BUDGETS["ask"], agent_routes.MODE_BUDGETS["auto"]]
    assert seen[1]["max_steps"] > seen[0]["max_steps"] > agent_routes.DEFAULT_MAX_STEPS


def test_the_focus_message_gives_the_node_id(tmp_path: Path) -> None:
    import json

    project_root = tmp_path / "project"
    project_root.mkdir()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/agent/sessions", params={"project_root": str(project_root)},
            json={"role": "chain", "chain_id": "chain-a", "run_id": "run-a", "context_packet": _context_packet(),
                  "focus": {"kind": "node", "id": "model:ols_1", "run_id": "run-a",
                            "label": "Imported data and first model"}},
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]
    entries = [json.loads(line) for line in
               (project_root / "workbench" / "agent-sessions" / f"{session_id}.jsonl").read_text().splitlines()]
    focus = next(e["payload"]["content"] for e in entries if e["payload"].get("name") == "workbench_agent_focus")
    assert "'Imported data and first model' (id model:ols_1) in run run-a" in focus
    # binary_logit.goal (M5, 2026-11-07): "Act on it" made the model answer from the imported OLS
    # instead of fitting the binary model the question needed. The focus names a selection only.
    assert "Act on it" not in focus and "does not decide which analysis a question needs" in focus
