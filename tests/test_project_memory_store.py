from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from workbench.domain_memory.project_index_contract import ProjectContextIndex
from workbench.domain_memory.project_index_store import (
    ProjectIndexStoreConflict,
    ProjectIndexStoreError,
    ProjectContextIndexStore,
)
from test_project_memory_contract import _index


def test_store_is_append_only_idempotent_and_restartable(tmp_path: Path) -> None:
    first = ProjectContextIndexStore(tmp_path)
    index = _index()

    assert first.append(index) == index
    assert first.append(index) == index
    assert first.history(index.index_id) == (index,)

    reopened = ProjectContextIndexStore(tmp_path)
    assert reopened.read(index.index_id) == index
    assert reopened.latest(project_id=index.project_id, run_family_id=index.run_family_id) == index


def test_store_rejects_revision_gaps_and_conflicting_replay(tmp_path: Path) -> None:
    store = ProjectContextIndexStore(tmp_path)
    index = _index()
    store.append(index)

    with pytest.raises(ProjectIndexStoreConflict, match="content"):
        store.append(replace(index, facts=()))
    with pytest.raises(ProjectIndexStoreConflict, match="revision"):
        store.append(replace(index, revision=3, previous_index_hash="d" * 64))


def test_store_clear_is_explicit_and_rebuildable(tmp_path: Path) -> None:
    store = ProjectContextIndexStore(tmp_path)
    index = _index()
    store.append(index)
    store.clear()

    assert store.history(index.index_id) == ()
    assert store.latest(project_id=index.project_id, run_family_id=index.run_family_id) is None


def test_store_fails_closed_on_malformed_journal(tmp_path: Path) -> None:
    store = ProjectContextIndexStore(tmp_path)
    store.append(_index())
    store.journal_path.write_text('{"record_type":"wrong"}\n', encoding="utf-8")

    with pytest.raises(ProjectIndexStoreError, match="journal"):
        ProjectContextIndexStore(tmp_path).history("index_1")
