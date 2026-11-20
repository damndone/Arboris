"""Malformed persisted note records use the Notebook request error envelope."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_notebook_support import make_project
from workbench.agent.notebook import NotebookService
from workbench.api import app


@pytest.mark.parametrize("damage", ["missing-field", "extra-field", "wrong-type"])
def test_a_malformed_stored_note_is_a_request_error(tmp_path, damage):
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Notes fixture", created_by="user")
    notebook_id = notebook.notebook_id
    valid = {
        "note_id": "note_valid",
        "notebook_id": notebook_id,
        "text": "First note",
        "source_ref": f"narrative:{notebook_id}:title",
        "source_label": "Notebook title",
        "created_at": "2026-11-18T00:00:00+00:00",
    }
    malformed = {**valid, "note_id": "note_damaged", "text": "Stored note content"}
    if damage == "missing-field":
        del malformed["source_label"]
    elif damage == "extra-field":
        malformed["extra"] = True
    else:
        malformed["created_at"] = [2026, 11, 18]
    records = service.store.notebook_dir(notebook_id) / "notes.jsonl"
    original = "".join(json.dumps(record) + "\n" for record in (valid, malformed)).encode()
    records.write_bytes(original)

    response = TestClient(app, raise_server_exceptions=False).get(
        f"/notebooks/{notebook_id}/notes", params={"project_root": str(project)}
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "NOTEBOOK_REQUEST_INVALID"
    assert response.json()["error"]["details"]["reason"] == "Malformed Notebook note record 2"
    assert "Stored note content" not in response.text
    assert records.read_bytes() == original
