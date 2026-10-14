"""Instructions the Agent reads: built-in guide, personal and project AGENTS.md."""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from workbench.agent import instructions


@pytest.fixture
def personal(tmp_path, monkeypatch):
    path = tmp_path / "home" / "AGENTS.md"
    monkeypatch.setenv(instructions.PERSONAL_PATH_ENV, str(path))
    return path


def test_layers_join_general_to_specific_and_skip_what_is_absent(tmp_path, personal):
    project = tmp_path / "project"
    project.mkdir()
    text, record = instructions.compose(project)
    assert "Built-in Arboris analysis guide" in text and "no look-ahead" in text
    assert [layer["present"] for layer in record["layers"]] == [True, False, False]
    personal.parent.mkdir()
    personal.write_text("Answer in Chinese.")
    (project / "AGENTS.md").write_text("Outcome is log wages.")
    text, record = instructions.compose(project)
    assert text.index("Answer in Chinese.") < text.index("Outcome is log wages.")
    assert "the later one wins" in text and not record["truncated"]


def test_oversized_instructions_are_cut_and_say_so(tmp_path, personal):
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("x" * (instructions.MAX_BYTES + 100))
    text, record = instructions.compose(project)
    assert record["truncated"] and "was cut" in text
    assert len(text.encode("utf-8")) <= instructions.MAX_BYTES + 400


def test_the_draft_fills_in_the_projects_data_without_a_model(tmp_path):
    run = tmp_path / "runs" / "20261001_000000_000000_aaaaaaaa"
    (run / "staged").mkdir(parents=True)
    (run / "run_inputs.json").write_text(json.dumps({"upload": {"sha256": "s1", "filename": "wages.csv"},
                                                     "form": {"model_type": "ols", "y": "wage", "x": "educ"}}))
    (run / "staged" / "data_profile.json").write_text(json.dumps({"row_count": 40, "columns": {
        "wage": {"dtype": "float64", "missing_rate": 0.05}, "educ": {"dtype": "int64", "missing_rate": 0.0}}}))
    (run / "staged" / "metadata_registry.json").write_text(json.dumps({"variable_labels": {"wage": "Hourly wage"}}))
    text = instructions.draft(tmp_path)
    assert "`wages.csv` (40 rows, 2 columns)" in text
    assert "wage - Hourly wage - float64, 5.0% missing" in text and "educ - meaning? - int64" in text
    assert "Fitted so far: ols: wage ~ educ" in text and text.startswith("# Project instructions")


def test_routes_read_save_and_draft(tmp_path, personal):
    from workbench.api import app

    project = tmp_path / "project"
    project.mkdir()
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    view = client.get("/agent/instructions", params={"project_root": str(project)}).json()
    assert [layer["kind"] for layer in view["layers"]] == ["guide", "personal", "project"]
    assert view["layers"][0]["editable"] is False and "Purpose" in view["templates"]["project"]
    saved = client.put("/agent/instructions", params={"project_root": str(project)},
                       json={"kind": "project", "content": "# Project instructions\nQuestion: returns to schooling"})
    assert saved.status_code == 200 and saved.json()["layers"][2]["exists"] is True
    assert (project / "AGENTS.md").read_text().endswith("returns to schooling")
    refused = client.put("/agent/instructions", params={"project_root": str(project)}, json={"kind": "guide", "content": "x"})
    assert refused.status_code == 422
    assert client.get("/agent/instructions/draft", params={"project_root": str(project)}).json()["content"].startswith("# Project instructions")


def test_a_new_conversation_reads_the_instructions_once(tmp_path, personal):
    from workbench.api import app

    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("Cluster by firm.")
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    created = client.post("/agent/sessions", params={"project_root": str(project)},
                          json={"role": "main", "context_packet": {"packet_version": "x"}})
    assert created.status_code == 200, created.text
    log = (project / "workbench" / "agent-sessions" / f"{created.json()['session_id']}.jsonl").read_text()
    entries = [json.loads(line) for line in log.splitlines()]
    standing = [entry for entry in entries if entry["payload"].get("name") == "workbench_instructions"]
    assert len(standing) == 1 and "Cluster by firm." in standing[0]["payload"]["content"]
