"""User-selected passages kept with a Notebook, outside its analysis evidence."""

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ...jsonl_store import append_jsonl_atomic, read_jsonl
from .store import NotebookStore


@dataclass(frozen=True)
class NotebookNote:
    note_id: str
    notebook_id: str
    text: str
    source_ref: str
    source_label: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_NOTE_FIELDS = frozenset(field.name for field in fields(NotebookNote))


def _notes_path(store: NotebookStore, notebook_id: str) -> Path:
    path = store.notebook_dir(notebook_id) / "notes.jsonl"
    if not path.resolve().is_relative_to(store.project_root.resolve()):
        raise ValueError("Notebook notes must stay inside their project")
    return path


def list_notes(store: NotebookStore, notebook_id: str) -> list[NotebookNote]:
    with store.project_lock():
        store.get_notebook(notebook_id)
        notes = []
        for number, record in enumerate(read_jsonl(_notes_path(store, notebook_id)), start=1):
            if record.keys() != _NOTE_FIELDS or any(not isinstance(value, str) for value in record.values()):
                raise ValueError(f"Malformed Notebook note record {number}")
            notes.append(NotebookNote(**record))
        return notes


def save_note(
    store: NotebookStore, notebook_id: str, *, text: str, source_ref: str, source_label: str,
) -> NotebookNote:
    """Validate this explicit user save once, then append the original passage."""

    with store.project_lock():
        store.get_notebook(notebook_id)
        if not text.strip() or len(text) > 20_000:
            raise ValueError("Note text must contain 1 to 20000 characters")
        if not source_label.strip() or len(source_label) > 500:
            raise ValueError("Note source label must contain 1 to 500 characters")
        if source_ref not in {
            f"narrative:{notebook_id}:title", f"narrative:{notebook_id}:plan",
        }:
            raise ValueError("Note source must identify a narrative entry in this Notebook")
        note = NotebookNote(
            note_id=f"note_{uuid4().hex}", notebook_id=notebook_id,
            text=text, source_ref=source_ref, source_label=source_label,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        append_jsonl_atomic(_notes_path(store, notebook_id), note.to_dict())
        return note
