"""User-selected Notebook notes persist without an Agent or analysis mutation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_notebook_support import make_project
from workbench.agent.notebook import NotebookService
from workbench.analysis_ledger import ledger_path
from workbench.api import app
from workbench.jsonl_store import read_jsonl


def _notebook(tmp_path: Path):
    project = make_project(tmp_path)
    notebook = NotebookService(project).create_notebook(title="Selected claim", created_by="user")
    return project, notebook


def _body(notebook_id: str) -> dict[str, str]:
    return {
        "text": "Selected claim\n保留原文",
        "source_ref": f"narrative:{notebook_id}:title",
        "source_label": f"user entry {notebook_id}:title",
    }


def test_selected_note_reopens_with_original_text_and_source(tmp_path: Path) -> None:
    project, notebook = _notebook(tmp_path)
    params = {"project_root": str(project)}
    path = f"/notebooks/{notebook.notebook_id}/notes"
    before = NotebookService(project).get_notebook(notebook.notebook_id).to_dict()
    body = _body(notebook.notebook_id)
    saved = TestClient(app).post(path, params=params, json=body)
    assert saved.status_code == 200, saved.text
    note = saved.json()
    assert {key: note[key] for key in body} == body
    assert note["notebook_id"] == notebook.notebook_id
    assert note["note_id"].startswith("note_") and note["created_at"]
    assert TestClient(app).get(path, params=params).json() == [note]
    assert NotebookService(project).get_notebook(notebook.notebook_id).to_dict() == before
    ledger = read_jsonl(ledger_path(project))
    assert ledger[-1]["steps"][0]["operation_id"] == "notebook.note.save"
    assert ledger[-1]["steps"][0]["category"] == "metadata_change"
    assert body["text"] not in ledger[-1]["summary"]


@pytest.mark.parametrize("field,value", [
    ("text", " "), ("text", "x" * 20_001),
    ("source_ref", "narrative:another_notebook:title"),
    ("source_ref", "narrative:../outside:title"),
    ("source_label", "x" * 501),
], ids=["blank", "long-text", "other-notebook", "path-source", "long-label"])
def test_invalid_note_is_rejected_before_writing(tmp_path: Path, field: str, value: str) -> None:
    project, notebook = _notebook(tmp_path)
    body = {**_body(notebook.notebook_id), field: value}
    result = TestClient(app).post(f"/notebooks/{notebook.notebook_id}/notes",
                                  params={"project_root": str(project)}, json=body)
    assert result.status_code == 422, result.text
    assert not list(project.glob("notebooks/*/notes.jsonl"))


def test_unknown_notebook_cannot_receive_or_list_notes(tmp_path: Path) -> None:
    project, _notebook_record = _notebook(tmp_path)
    client = TestClient(app)
    path = "/notebooks/nb_missing/notes"
    params = {"project_root": str(project)}
    assert client.post(path, params=params, json=_body("nb_missing")).status_code == 404
    assert client.get(path, params=params).status_code == 404
    assert not (project / "notebooks" / "nb_missing").exists()


def test_failed_note_write_returns_an_error(tmp_path: Path, monkeypatch) -> None:
    from workbench.agent.notebook import notes

    project, notebook = _notebook(tmp_path)
    def fail_write(*_args, **_kwargs):
        raise OSError("note storage unavailable")
    monkeypatch.setattr(notes, "append_jsonl_atomic", fail_write)
    result = TestClient(app).post(f"/notebooks/{notebook.notebook_id}/notes",
                                  params={"project_root": str(project)}, json=_body(notebook.notebook_id))
    assert result.status_code == 500
    assert "note storage unavailable" in result.text
    assert not ledger_path(project).exists()
