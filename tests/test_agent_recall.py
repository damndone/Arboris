"""Recall of this project's earlier conversations."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from workbench.agent.recall import conversation_index, index_text, read, search
from workbench.agent.session import EntryRef, JsonlSessionRepository


def conversation(repository, session_id, *pairs, tool=None):
    repository.create_session(session_id, chain_id="c", role="chain")
    for question, answer in pairs:
        repository.append(session_id, "message", {"role": "user", "content": question})
        if tool:
            repository.append(session_id, "message", {"role": "tool", "name": "show_dataset_rows", "content": tool})
        repository.append(session_id, "message", {"role": "assistant", "content": answer})


@pytest.fixture
def repository(tmp_path):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    conversation(repository, "a", ("工资对教育的回报是多少？", "教育系数为 2,564（run r1）。"), tool="secret row 42")
    conversation(repository, "b", ("Forecast GDP with ARIMA", "ARIMA(1,1,1) chosen by AIC."), ("Check residual autocorrelation", "Ljung-Box shows none."))
    return repository


def test_the_index_lists_earlier_conversations_newest_first(repository):
    items = conversation_index(repository, exclude="b")
    assert [item["session_id"] for item in items] == ["a"]
    items = conversation_index(repository)
    assert items[0]["session_id"] == "b" and items[0]["title"] == "Forecast GDP with ARIMA"
    assert items[0]["last_question"] == "Check residual autocorrelation" and items[0]["messages"] == 4
    text = index_text(items)
    assert "not as verified results" in text and "[b]" in text and "[a]" in text


def test_search_finds_chinese_and_english_but_never_tool_results(repository):
    hits = search(repository, "教育回报")
    assert hits and hits[0]["session_id"] == "a" and hits[0]["role"] == "user"
    assert search(repository, "residual autocorrelation")[0]["snippet"].startswith("Check residual")
    assert search(repository, "secret row") == []


def test_search_counts_a_forked_conversation_once(repository):
    first = repository.get_branch("b")[0]
    repository.create_session("fork", chain_id="c", role="chain", inherited_parent_ref=EntryRef("b", first.entry_id))
    assert [hit["session_id"] for hit in search(repository, "Forecast GDP")].count("b") + \
        [hit["session_id"] for hit in search(repository, "Forecast GDP")].count("fork") == 1


def test_read_returns_messages_around_an_entry(repository):
    hit = search(repository, "Ljung-Box")[0]
    result = read(repository, "b", around_entry_id=hit["entry_id"], before=1, after=0)
    assert [message["content"] for message in result["messages"]] == ["Check residual autocorrelation", "Ljung-Box shows none."]
    assert result["earlier_messages"] == 2 and result["later_messages"] == 0
    with pytest.raises(KeyError):
        read(repository, "missing")


def test_a_new_conversation_is_told_about_earlier_ones(tmp_path, monkeypatch):
    from workbench.api import app

    monkeypatch.setenv("WORKBENCH_AGENT_INSTRUCTIONS_PATH", str(tmp_path / "none.md"))
    project = tmp_path / "project"
    project.mkdir()
    conversation(JsonlSessionRepository(project / "workbench"), "agent_main_old", ("Which instrument for schooling?", "Distance to college."))
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    created = client.post("/agent/sessions", params={"project_root": str(project)},
                          json={"role": "main", "context_packet": {"packet_version": "x"}}).json()
    entries = [json.loads(line) for line in (project / "workbench" / "agent-sessions" / f"{created['session_id']}.jsonl").read_text().splitlines()]
    recall = [entry["payload"] for entry in entries if entry["payload"].get("name") == "workbench_project_recall"]
    assert len(recall) == 1 and "Which instrument for schooling?" in recall[0]["content"]
