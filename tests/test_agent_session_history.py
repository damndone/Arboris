"""Rewind, fork and chapters on an Agent conversation (v1.9.0 user review 3).

The session log is append-only: rewinding moves the session's leaf back and
keeps the later entries on file; a fork is a new session inheriting the
conversation up to a message; chapters are named messages to jump to.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_routes import FakeAgentAdapter, _config, _context_packet
from workbench.app import app


@pytest.fixture()
def conversation(tmp_path: Path, monkeypatch):
    from workbench.http import agent_routes

    monkeypatch.setattr(agent_routes, "load_llm_config", _config)
    monkeypatch.setattr(agent_routes, "OpenAICompatibleModelAdapter", FakeAgentAdapter)
    project_root = tmp_path / "project"
    project_root.mkdir()
    params = {"project_root": str(project_root)}
    with TestClient(app) as client:
        session = client.post("/agent/sessions", params=params, json={
            "role": "chain", "chain_id": "chain-a", "run_id": "run-a", "context_packet": _context_packet()}).json()
        session_id = session["session_id"]
        for question in ("First question", "Second question"):
            assert client.post(f"/agent/sessions/{session_id}/turns", params=params,
                               json={"question": question}).status_code == 200
        yield client, params, session_id, project_root


def _messages(client, params, session_id):
    return client.get(f"/agent/sessions/{session_id}", params=params).json()["messages"]


def test_messages_carry_their_time(conversation):
    client, params, session_id, _ = conversation
    messages = _messages(client, params, session_id)
    assert all(message["at"].endswith("+00:00") or message["at"].endswith("Z") for message in messages)


def test_rewind_goes_back_before_a_message_and_keeps_the_log(conversation):
    client, params, session_id, project_root = conversation
    messages = _messages(client, params, session_id)
    second = next(m for m in messages if m["content"] == "Second question")
    response = client.post(f"/agent/sessions/{session_id}/rewind", params=params, json={"entry_id": second["entry_id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restored_prompt"] == "Second question"
    assert [m["content"] for m in body["session"]["messages"]] == ["First question", "已读取当前分析上下文。"]
    # Nothing was deleted: the undone turn is still in the session log.
    log = (project_root / "workbench" / "agent-sessions" / f"{session_id}.jsonl").read_text()
    assert "Second question" in log
    # The next message continues from the rewound point.
    assert client.post(f"/agent/sessions/{session_id}/turns", params=params, json={"question": "Instead"}).status_code == 200
    assert [m["content"] for m in _messages(client, params, session_id) if m["role"] == "user"] == ["First question", "Instead"]


def test_rewind_only_to_your_own_messages_on_this_branch(conversation):
    client, params, session_id, _ = conversation
    reply = next(m for m in _messages(client, params, session_id) if m["role"] == "assistant")
    assert client.post(f"/agent/sessions/{session_id}/rewind", params=params, json={"entry_id": reply["entry_id"]}).status_code == 422
    assert client.post(f"/agent/sessions/{session_id}/rewind", params=params, json={"entry_id": "nope"}).status_code == 404


def test_fork_from_a_reply_shares_the_conversation_up_to_it(conversation):
    client, params, session_id, _ = conversation
    messages = _messages(client, params, session_id)
    first_reply = [m for m in messages if m["role"] == "assistant"][0]
    response = client.post(f"/agent/sessions/{session_id}/fork", params=params, json={"entry_id": first_reply["entry_id"]})
    assert response.status_code == 200, response.text
    fork = response.json()["session"]
    assert fork["session_id"] != session_id and response.json()["restored_prompt"] is None
    assert [m["content"] for m in fork["messages"]] == ["First question", "已读取当前分析上下文。"]
    assert client.post(f"/agent/sessions/{fork['session_id']}/turns", params=params, json={"question": "Branch"}).status_code == 200
    # The original conversation is unchanged.
    assert [m["content"] for m in _messages(client, params, session_id) if m["role"] == "user"] == ["First question", "Second question"]
    assert [m["content"] for m in _messages(client, params, fork["session_id"]) if m["role"] == "user"] == ["First question", "Branch"]


def test_fork_from_your_message_stops_before_it_and_returns_it(conversation):
    client, params, session_id, _ = conversation
    second = next(m for m in _messages(client, params, session_id) if m["content"] == "Second question")
    body = client.post(f"/agent/sessions/{session_id}/fork", params=params, json={"entry_id": second["entry_id"]}).json()
    assert body["restored_prompt"] == "Second question"
    assert [m["content"] for m in body["session"]["messages"]][-1] == "已读取当前分析上下文。"


def test_chapters_pin_and_unpin_and_follow_a_rewind(conversation):
    client, params, session_id, _ = conversation
    messages = _messages(client, params, session_id)
    first, second = [m for m in messages if m["role"] == "user"]
    for message, title in ((first, "Start"), (second, "Follow-up")):
        session = client.post(f"/agent/sessions/{session_id}/chapters", params=params,
                              json={"entry_id": message["entry_id"], "title": title}).json()
    assert [chapter["title"] for chapter in session["chapters"]] == ["Start", "Follow-up"]
    session = client.delete(f"/agent/sessions/{session_id}/chapters/{second['entry_id']}", params=params).json()
    assert [chapter["title"] for chapter in session["chapters"]] == ["Start"]
    client.post(f"/agent/sessions/{session_id}/chapters", params=params, json={"entry_id": second["entry_id"], "title": "Follow-up"})
    body = client.post(f"/agent/sessions/{session_id}/rewind", params=params, json={"entry_id": second["entry_id"]}).json()
    assert [chapter["title"] for chapter in body["session"]["chapters"]] == ["Start"], "a chapter after the rewind point goes"
