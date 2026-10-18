"""Append-once message identity and exact-intent crash recovery."""

from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from workbench.agent.context import ContextBuilder
from workbench.agent.session import EntryRef, JsonlSessionRepository, SessionTreeEntry


@pytest.fixture
def repository(tmp_path):
    repo = JsonlSessionRepository(tmp_path / "workbench")
    repo.create_session("session", chain_id="chain", role="chain")
    return repo


def _append(repository, *, key="invocation", stage="tool_result", payload=None):
    return repository.append_once("session", "message", payload or {
        "role": "tool", "tool_call_id": "call_1", "name": "inspect", "content": '{"result": 1}',
    }, key=key, stage=stage)


def _intent_path(repository):
    return repository.sessions_dir / "session.append-once.intent.json"


def _entries(repository):
    return [json.loads(line) for line in repository._session_path("session").read_text().splitlines()]


def test_retries_return_one_entry_with_private_top_level_identity(repository):
    first = _append(repository)
    rebuilt = JsonlSessionRepository(repository.root)
    assert _append(rebuilt) == first
    assert len(_entries(repository)) == 1
    assert first.idempotency["key"] == "invocation"
    assert first.idempotency["stage"] == "tool_result"
    assert len(first.idempotency["payload_sha256"]) == 64
    assert "idempotency" not in first.payload
    assert "idempotency" not in ContextBuilder(rebuilt).build("session").messages[0]
    assert not _intent_path(repository).exists()


def test_existing_entry_serialization_shape_and_regular_append_stay_unchanged(repository):
    assert hasattr(repository, "append_once"), "Missing durable append-once seam"
    entry = repository.append("session", "message", {"role": "user", "content": "old"})
    assert entry.idempotency is None
    assert set(entry.to_dict()) == {"schema_version", "entry_id", "session_id", "entry_type",
                                    "payload", "parent_ref", "created_at"}
    assert SessionTreeEntry.from_dict(entry.to_dict()).to_dict() == entry.to_dict()
    encoded = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    assert repository._session_path("session").read_text() == encoded


def test_full_json_content_conflicts_are_rejected_including_hidden_fields(repository):
    first = _append(repository, payload={"role": "tool", "content": "same", "evidence": {"a": [1, 2]}})
    assert _append(repository, payload={"evidence": {"a": [1, 2]}, "content": "same", "role": "tool"}) == first
    for payload in ({"role": "tool", "content": "same", "evidence": {"a": [1, 3]}},
                    {"role": "tool", "content": "same", "evidence": {"a": [1.0, 2]}},
                    {"role": "tool", "content": "same"}):
        with pytest.raises(ValueError, match="conflict"):
            _append(repository, payload=payload)
    with pytest.raises(ValueError, match="conflict"):
        repository.append_once("session", "custom_message", first.payload, key="invocation", stage="tool_result")
    assert len(_entries(repository)) == 1


def test_key_is_scoped_to_session_and_stage(repository):
    first = _append(repository)
    another_stage = _append(repository, stage="outcome")
    repository.create_session("other", chain_id="chain", role="chain")
    other = repository.append_once("other", "message", first.payload, key="invocation", stage="tool_result")
    assert len({first.entry_id, another_stage.entry_id, other.entry_id}) == 3


def test_rewind_does_not_reactivate_an_off_branch_idempotent_entry(repository):
    before = repository.append("session", "message", {"role": "user", "content": "before"})
    once = _append(repository)
    repository.rewind("session", EntryRef("session", before.entry_id))
    log = repository._session_path("session").read_bytes()
    with pytest.raises(ValueError, match="branch"):
        _append(JsonlSessionRepository(repository.root))
    assert repository.get_metadata("session")["leaf_entry_id"] == before.entry_id
    assert repository._session_path("session").read_bytes() == log
    replacement = _append(repository, key="new_invocation")
    assert replacement.parent_ref.entry_id == before.entry_id
    assert once.entry_id not in {entry.entry_id for entry in repository.get_branch("session")}


def test_retry_of_an_ancestor_returns_it_without_rewinding_newer_messages(repository):
    first = _append(repository)
    later = repository.append("session", "message", {"role": "assistant", "content": "later"})
    assert _append(repository) == first
    assert repository.get_metadata("session")["leaf_entry_id"] == later.entry_id


def test_multiple_repository_instances_append_the_same_key_once(repository):
    barrier = Barrier(2)
    def append(_):
        rebuilt = JsonlSessionRepository(repository.root)
        barrier.wait()
        return _append(rebuilt).entry_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(append, range(2)))
    assert len(set(ids)) == 1
    assert len(_entries(repository)) == 1


def _append_in_process(root, barrier, queue):
    repository = JsonlSessionRepository(root)
    barrier.wait(timeout=10)
    queue.put(_append(repository).entry_id)


def test_processes_share_the_same_append_identity(repository):
    assert hasattr(repository, "append_once"), "Missing durable append-once seam"
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(2), context.Queue()
    processes = [context.Process(target=_append_in_process, args=(repository.root, barrier, queue)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        ids = [queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert len(set(ids)) == 1 and len(_entries(repository)) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


@pytest.mark.parametrize("window", ["intent_before", "intent_after", "log_before", "log_after",
                                   "metadata_before", "metadata_after", "clear_before", "clear_after"])
def test_each_write_window_recovers_only_the_intended_entry(repository, monkeypatch, window):
    assert hasattr(repository, "append_once"), "Missing durable append-once seam"
    original_json = repository._atomic_write_json
    original_log = repository._atomic_append
    original_clear = repository._clear_append_intent
    intent = None

    def write_json(path, value):
        nonlocal intent
        kind = "intent" if path == _intent_path(repository) else "metadata"
        if kind == "intent":
            intent = dict(value)
        if window == kind + "_before":
            raise OSError("injected before write")
        original_json(path, value)
        if window == kind + "_after":
            raise OSError("injected after write")

    def write_log(path, value):
        if window == "log_before":
            raise OSError("injected before log")
        original_log(path, value)
        if window == "log_after":
            raise OSError("injected after log")

    def clear(session_id):
        if window == "clear_before":
            raise OSError("injected before cleanup")
        original_clear(session_id)
        if window == "clear_after":
            raise OSError("injected after cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_atomic_write_json", write_json)
        patch.setattr(repository, "_atomic_append", write_log)
        patch.setattr(repository, "_clear_append_intent", clear)
        with pytest.raises(OSError):
            _append(repository)
    rebuilt = JsonlSessionRepository(repository.root)
    if window in {"intent_after", "log_before"}:
        with pytest.raises(ValueError, match="payload"):
            rebuilt.recover_append_once("session")
    elif window not in {"intent_before", "clear_after"}:
        rebuilt.recover_append_once("session")
    result = _append(rebuilt)
    if window != "intent_before":
        assert result.entry_id == intent["entry_id"]
        assert result.created_at == intent["created_at"]
    assert [entry.entry_id for entry in rebuilt.get_branch("session")] == [result.entry_id]
    assert len(_entries(rebuilt)) == 1
    assert not _intent_path(rebuilt).exists()


def _leave_log_pending(repository, monkeypatch):
    assert hasattr(repository, "append_once"), "Missing durable append-once seam"
    original = repository._atomic_write_json
    def fail_metadata(path, value):
        if path == repository._metadata_path("session"):
            raise OSError("metadata failed")
        original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(repository, "_atomic_write_json", fail_metadata)
        with pytest.raises(OSError):
            _append(repository)


def test_pending_intent_blocks_unrelated_append_rewind_and_delete(repository, monkeypatch):
    before = repository.append("session", "message", {"role": "user", "content": "before"})
    _leave_log_pending(repository, monkeypatch)
    for action in (lambda: repository.append("session", "message", {"content": "skip"}),
                   lambda: repository.rewind("session", EntryRef("session", before.entry_id)),
                   lambda: repository.delete_session("session"),
                   lambda: _append(repository, key="different")):
        with pytest.raises(ValueError, match="pending"):
            action()
    assert _intent_path(repository).exists()
    recovered = repository.recover_append_once("session")
    assert recovered.parent_ref.entry_id == before.entry_id


def test_unknown_or_mismatched_pending_is_never_guessed_or_discarded(repository, monkeypatch):
    _leave_log_pending(repository, monkeypatch)
    original_log = repository._session_path("session").read_bytes()
    intent_path = _intent_path(repository)
    intent = json.loads(intent_path.read_text())
    intent["entry_id"] = "unknown_entry"
    intent_path.write_text(json.dumps(intent))
    with pytest.raises(ValueError):
        repository.recover_append_once("session")
    with pytest.raises(ValueError):
        _append(repository)
    assert repository._session_path("session").read_bytes() == original_log
    assert repository.get_metadata("session")["leaf_entry_id"] is None
    assert intent_path.exists()


def test_pending_cannot_cross_a_different_metadata_branch(repository, monkeypatch):
    _leave_log_pending(repository, monkeypatch)
    metadata = repository.get_metadata("session")
    metadata["leaf_entry_id"] = "external_leaf"
    repository._atomic_write_json(repository._metadata_path("session"), metadata)
    with pytest.raises(ValueError, match="pending"):
        repository.recover_append_once("session")
    assert repository.get_metadata("session")["leaf_entry_id"] == "external_leaf"


def test_inherited_parent_is_preserved_when_recovering_first_local_entry(repository, monkeypatch):
    ancestor = repository.append("session", "message", {"role": "user", "content": "parent"})
    repository.create_session("child", chain_id="child-chain", role="chain",
                              inherited_parent_ref=EntryRef("session", ancestor.entry_id))
    original = repository._atomic_write_json
    def fail_metadata(path, value):
        if path == repository._metadata_path("child"):
            raise OSError("child metadata failed")
        original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(repository, "_atomic_write_json", fail_metadata)
        with pytest.raises(OSError):
            repository.append_once("child", "message", {"role": "user", "content": "child"},
                                    key="child_input", stage="input")
    entry = JsonlSessionRepository(repository.root).recover_append_once("child")
    assert entry.parent_ref == EntryRef("session", ancestor.entry_id)
    assert [item.entry_id for item in repository.get_branch("child")] == [ancestor.entry_id, entry.entry_id]


@pytest.mark.parametrize("failure_number", range(1, 8))
def test_real_fsync_failures_leave_one_recoverable_message(repository, monkeypatch, failure_number):
    from workbench.agent import session as module
    original_fsync = module.os.fsync
    calls = 0
    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == failure_number:
            raise OSError("injected fsync failure")
        original_fsync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", fsync)
        with pytest.raises(OSError):
            _append(repository)
    rebuilt = JsonlSessionRepository(repository.root)
    entry = _append(rebuilt)
    assert [value["entry_id"] for value in _entries(rebuilt)] == [entry.entry_id]
    assert rebuilt.get_metadata("session")["leaf_entry_id"] == entry.entry_id
    assert not _intent_path(rebuilt).exists()


def test_recovery_uses_the_intended_identity_instead_of_the_last_log_line(repository, monkeypatch):
    _leave_log_pending(repository, monkeypatch)
    intended = _entries(repository)[0]
    unrelated = SessionTreeEntry("unrelated_tail", "session", "message", {"role": "user", "content": "unrelated"},
                                  None, "2026-10-18T00:00:00+00:00")
    repository._atomic_append(repository._session_path("session"), unrelated.to_dict())
    recovered = JsonlSessionRepository(repository.root).recover_append_once("session")
    assert recovered.entry_id == intended["entry_id"]
    assert repository.get_metadata("session")["leaf_entry_id"] != unrelated.entry_id
    assert len(_entries(repository)) == 2


def test_malformed_pending_is_kept_and_blocks_mutation(repository):
    assert hasattr(repository, "append_once"), "Missing durable append-once seam"
    path = _intent_path(repository)
    path.write_text('{"entry_id": "a", "entry_id": "b"}')
    for action in (lambda: _append(repository), lambda: repository.recover_append_once("session"),
                   lambda: repository.append("session", "message", {"content": "skip"})):
        with pytest.raises(ValueError, match="pending"):
            action()
    assert path.exists() and _entries(repository) == []
