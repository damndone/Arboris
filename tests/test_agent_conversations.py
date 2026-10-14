"""The project's Agent conversations: list, rename, archive, delete."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workbench.agent.events import AgentEventStream
from workbench.agent.session import EntryRef, JsonlSessionRepository


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    repository = JsonlSessionRepository(root / "workbench")
    events = AgentEventStream(root / "workbench")
    for session_id, question, focus in [
        ("agent_chain_a", "## Is the education effect robust?\nmore", {"kind": "node", "id": "n1", "label": "ols_robust"}),
        ("agent_main_b", "Summarize the project", None),
    ]:
        repository.create_session(session_id, chain_id="chain:r1", role=session_id.split("_")[1])
        if focus:
            repository.append(session_id, "custom_message", {"audience": "model", "name": "workbench_agent_focus",
                                                             "content": "Focus", "metadata": {"focus": focus}})
        repository.append(session_id, "message", {"role": "user", "content": question})
        repository.append(session_id, "message", {"role": "assistant", "content": "answer"})
        events.emit(session_id, "message_end", {})
    repository.create_session("agent_main_empty", chain_id="c", role="main")
    return root


def client():
    from workbench.api import app

    return TestClient(app, base_url="http://127.0.0.1:8000")


def listing(root, **params):
    return client().get("/agent/conversations", params={"project_root": str(root), **params}).json()["conversations"]


def test_conversations_are_listed_with_title_and_what_they_are_about(project):
    items = {item["session_id"]: item for item in listing(project)}
    assert set(items) == {"agent_chain_a", "agent_main_b"}  # nobody wrote in the empty one
    assert items["agent_chain_a"]["title"] == "Is the education effect robust?"
    assert items["agent_chain_a"]["about"] == "ols_robust" and items["agent_main_b"]["about"] == "Project"
    assert items["agent_chain_a"]["messages"] == 2 and items["agent_chain_a"]["archived"] is False


def test_rename_archive_and_restore(project):
    http = client()
    params = {"project_root": str(project)}
    renamed = http.patch("/agent/conversations/agent_chain_a", params=params, json={"title": "Robustness"}).json()
    assert renamed["title"] == "Robustness" and renamed["titled"] is True
    http.patch("/agent/conversations/agent_chain_a", params=params, json={"archived": True})
    assert [item["session_id"] for item in listing(project)] == ["agent_main_b"]
    archived = [item for item in listing(project, include_archived=True) if item["archived"]]
    assert [item["session_id"] for item in archived] == ["agent_chain_a"]
    restored = http.patch("/agent/conversations/agent_chain_a", params=params, json={"archived": False, "title": ""}).json()
    assert restored["archived"] is False and restored["title"] == "Is the education effect robust?"


def test_delete_removes_the_conversation_and_its_events_only(project):
    http = client()
    sessions = project / "workbench" / "agent-sessions"
    (project / "workbench" / "operation-ledger.jsonl").write_text("{}\n")
    response = http.delete("/agent/conversations/agent_main_b", params={"project_root": str(project)})
    assert response.json() == {"session_id": "agent_main_b", "deleted": True}
    assert not (sessions / "agent_main_b.jsonl").exists() and not (sessions / "agent_main_b.meta.json").exists()
    assert not (project / "workbench" / "agent-events" / "agent_main_b.jsonl").exists()
    assert (project / "workbench" / "operation-ledger.jsonl").exists()
    assert http.get("/agent/sessions/agent_main_b", params={"project_root": str(project)}).status_code == 404


def test_a_conversation_others_continue_from_is_not_deleted(project):
    repository = JsonlSessionRepository(project / "workbench")
    first = repository.get_branch("agent_chain_a")[1]
    repository.create_session("agent_chain_fork", chain_id="chain:r1", role="chain",
                              inherited_parent_ref=EntryRef("agent_chain_a", first.entry_id))
    response = client().delete("/agent/conversations/agent_chain_a", params={"project_root": str(project)})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_CONVERSATION_HAS_BRANCHES"
    assert (project / "workbench" / "agent-sessions" / "agent_chain_a.jsonl").exists()


def test_a_running_conversation_is_not_deleted(project):
    JsonlSessionRepository(project / "workbench").update_status("agent_main_b", "running")
    response = client().delete("/agent/conversations/agent_main_b", params={"project_root": str(project)})
    assert response.status_code == 409
