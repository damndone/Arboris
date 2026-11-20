"""Durable turn state, fencing, restart and filesystem boundary contracts."""

from __future__ import annotations

import importlib
import importlib.util
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest


def _module():
    assert importlib.util.find_spec("workbench.agent.turn_store") is not None, "Missing persistent turn store"
    return importlib.import_module("workbench.agent.turn_store")


@pytest.fixture
def store(tmp_path):
    return _module().TurnStore(tmp_path, clock=lambda: 100.0)


def _create(store, **kwargs):
    return store.create("session", "entry_question", budget={"max_steps": 10, "timeout_s": 300.0}, **kwargs)


def _running(store):
    record = _create(store)
    record = store.claim(record.turn_id, expected_version=record.version, owner="worker", lease_seconds=10)
    return store.transition(record.turn_id, "running", expected_version=record.version,
                            owner="worker", fence=record.lease_epoch)


def _owned(record):
    return {"expected_version": record.version, "owner": record.lease_owner, "fence": record.lease_epoch}


def test_acceptance_survives_reconstruction_with_stable_identity(tmp_path, store):
    record = _create(store, turn_id="turn_explicit")
    loaded = _module().TurnStore(tmp_path).get(record.turn_id)
    assert loaded == record
    assert loaded.status == "accepted" and loaded.command_id
    assert store.create("session", record.input_entry_id, turn_id=record.turn_id,
                        budget=record.budget) == record
    with pytest.raises(_module().TurnStoreError):
        _create(store, turn_id="another_turn")
    loaded.budget["max_steps"] = 1
    assert store.get(record.turn_id).budget["max_steps"] == 10


def test_running_and_terminal_transitions_cannot_revive_a_turn(store):
    record = _running(store)
    record = store.transition(record.turn_id, "completed", **_owned(record))
    assert record.lease_owner is None
    with pytest.raises(_module().TurnStoreError):
        store.claim(record.turn_id, expected_version=record.version, owner="other", lease_seconds=10)
    with pytest.raises(_module().TurnStoreError):
        store.transition(record.turn_id, "running", **_owned(record))
    assert _create(store).turn_id != record.turn_id


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_each_terminal_state_is_immutable(store, terminal):
    record = _running(store)
    record = store.transition(record.turn_id, terminal, **_owned(record))
    with pytest.raises(_module().TurnStoreError):
        store.request_cancel(record.turn_id, expected_version=record.version)
    with pytest.raises(_module().TurnStoreError):
        store.enqueue(record.turn_id, "steer", "change", expected_version=record.version)


def test_pause_releases_lease_and_can_be_explicitly_resumed(store):
    record = _running(store)
    record = store.transition(record.turn_id, "awaiting_approval", **_owned(record))
    assert record.lease_owner is None
    record = store.claim(record.turn_id, expected_version=record.version, owner="approved-worker", lease_seconds=10)
    record = store.transition(record.turn_id, "running", **_owned(record))
    assert record.status == "running"


def test_cumulative_budget_never_rolls_back_and_records_overruns(store):
    record = _running(store)
    record = store.checkpoint(record.turn_id, steps_used=3, wall_s_used=20,
                              checkpoint={"entry_id": "entry_1"}, **_owned(record))
    for steps, wall in [(2, 20), (3, 19), (-1, 20), (3, float("nan")), (True, 20)]:
        with pytest.raises(_module().TurnStoreError):
            store.checkpoint(record.turn_id, steps_used=steps, wall_s_used=wall,
                             checkpoint={"entry_id": "entry_2"}, **_owned(record))
    record = store.checkpoint(record.turn_id, steps_used=11, wall_s_used=301,
                              checkpoint={"entry_id": "entry_2"}, **_owned(record))
    assert record.steps_used == 11 and record.wall_s_used == 301
    record = store.transition(record.turn_id, "awaiting_approval", **_owned(record))
    record = store.claim(record.turn_id, expected_version=record.version, owner="worker", lease_seconds=10)
    with pytest.raises(_module().TurnStoreError, match="budget"):
        store.transition(record.turn_id, "running", **_owned(record))


def test_expired_running_requires_reconciliation_before_resume(tmp_path):
    now = [100.0]
    store = _module().TurnStore(tmp_path, clock=lambda: now[0])
    original = _running(store)
    with pytest.raises(_module().TurnStoreError):
        store.interrupt_expired(original.turn_id, expected_version=original.version)
    now[0] = 111
    restarted = _module().TurnStore(tmp_path, clock=lambda: now[0])
    with pytest.raises(_module().TurnStoreError):
        restarted.claim(original.turn_id, expected_version=original.version, owner="new", lease_seconds=10)
    record = restarted.interrupt_expired(original.turn_id, expected_version=original.version)
    assert record.status == "interrupted" and record.requires_reconcile
    assert (record.turn_id, record.command_id, record.input_entry_id) == (
        original.turn_id, original.command_id, original.input_entry_id)
    record = restarted.claim(record.turn_id, expected_version=record.version, owner="new", lease_seconds=10)
    with pytest.raises(_module().TurnStoreError, match="reconcil"):
        restarted.transition(record.turn_id, "running", **_owned(record))
    with pytest.raises(_module().TurnStoreError):
        restarted.mark_reconciled(record.turn_id, evidence={}, **_owned(record))
    record = restarted.mark_reconciled(record.turn_id, evidence={"checked_entry": "entry_1"}, **_owned(record))
    record = restarted.transition(record.turn_id, "running", **_owned(record))
    assert record.lease_epoch > original.lease_epoch
    with pytest.raises(_module().TurnStoreError):
        restarted.checkpoint(record.turn_id, steps_used=1, wall_s_used=1, checkpoint={},
                             expected_version=record.version, owner=original.lease_owner, fence=original.lease_epoch)


def test_unknown_pending_execution_cannot_be_cleared_or_changed(store):
    record = _running(store)
    record = store.record_tool_call(record.turn_id, "call_1", operation_key=None,
                                    checkpoint={"entry_id": "assistant_1"}, **_owned(record))
    with pytest.raises(_module().TurnStoreError):
        store.resolve_tool_call(record.turn_id, "call_1", operation_key="invented",
                                evidence={"receipt": "receipt_1"}, **_owned(record))
    with pytest.raises(_module().TurnStoreError):
        store.transition(record.turn_id, "completed", **_owned(record))
    record = store.transition(record.turn_id, "interrupted", **_owned(record))
    record = store.claim(record.turn_id, expected_version=record.version, owner="reconciler", lease_seconds=10)
    with pytest.raises(_module().TurnStoreError):
        store.mark_reconciled(record.turn_id, evidence={"checked": "entry_1"}, **_owned(record))
    record = store.bind_tool_operation(record.turn_id, "call_1", operation_key="exec_original", **_owned(record))
    with pytest.raises(_module().TurnStoreError):
        store.bind_tool_operation(record.turn_id, "call_1", operation_key="exec_other", **_owned(record))
    record = store.resolve_tool_call(record.turn_id, "call_1", operation_key="exec_original",
                                    evidence={"receipt": "receipt_1"}, **_owned(record))
    record = store.mark_reconciled(record.turn_id, evidence={"checked": "entry_1"}, **_owned(record))
    assert record.tool_calls["call_1"]["status"] == "resolved"
    assert record.tool_calls["call_1"]["checkpoint"] == {"entry_id": "assistant_1"}


def test_cancel_and_queue_consumption_survive_reconstruction(tmp_path, store):
    record = _running(store)
    for kind in ("steer", "follow_up"):
        record = store.enqueue(record.turn_id, kind, "use logs", message_id=kind,
                               expected_version=record.version)
    record = store.consume_queue(record.turn_id, "steer", **_owned(record))
    record = store.request_cancel(record.turn_id, expected_version=record.version)
    loaded = _module().TurnStore(tmp_path).get(record.turn_id)
    assert loaded.cancel_requested
    assert [m["consumed"] for m in loaded.queue] == [True, False]
    with pytest.raises(_module().TurnStoreError):
        store.consume_queue(record.turn_id, "steer", **_owned(record))
    record = store.transition(record.turn_id, "interrupted", **_owned(record))
    record = store.claim(record.turn_id, expected_version=record.version, owner="worker", lease_seconds=10)
    record = store.mark_reconciled(record.turn_id, evidence={"checked": "entry_1"}, **_owned(record))
    with pytest.raises(_module().TurnStoreError, match="cancel"):
        store.transition(record.turn_id, "running", **_owned(record))


def test_separate_instances_allow_exactly_one_claim_and_reject_stale_cas(tmp_path, store):
    record = _create(store)
    barrier = Barrier(2)

    def claim(owner):
        candidate = _module().TurnStore(tmp_path, clock=lambda: 100.0)
        barrier.wait()
        try:
            return candidate.claim(record.turn_id, expected_version=record.version,
                                   owner=owner, lease_seconds=10).lease_owner
        except _module().TurnStoreError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("one", "two")))
    assert results.count("conflict") == 1
    latest = store.get(record.turn_id)
    with pytest.raises(_module().TurnStoreError):
        store.request_cancel(record.turn_id, expected_version=record.version)
    with pytest.raises(_module().TurnStoreError):
        store.claim(record.turn_id, expected_version=latest.version, owner="three", lease_seconds=10)
    renewed = store.renew(record.turn_id, lease_seconds=20, **_owned(latest))
    assert renewed.lease_expires_at == 120.0


def _process_claim(root, turn_id, version, barrier, queue):
    from workbench.agent.turn_store import TurnStore, TurnStoreError
    store = TurnStore(root, clock=lambda: 100.0)
    barrier.wait(timeout=10)
    try:
        store.claim(turn_id, expected_version=version, owner=str(multiprocessing.current_process().pid), lease_seconds=10)
        queue.put("claimed")
    except TurnStoreError:
        queue.put("conflict")


def test_process_lock_fences_independent_workers(tmp_path, store):
    record = _create(store)
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(2), context.Queue()
    processes = [context.Process(target=_process_claim, args=(tmp_path, record.turn_id, record.version, barrier, queue))
                 for _ in range(2)]
    try:
        for process in processes:
            process.start()
        assert sorted(queue.get(timeout=15) for _ in processes) == ["claimed", "conflict"]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


@pytest.mark.parametrize("session_id", ["../escape", "a/b", "a\\b", ".", "..", "", "nul\x00id"])
def test_unsafe_session_identifiers_are_rejected(store, session_id):
    with pytest.raises(_module().TurnStoreError):
        store.create(session_id, "question", budget={"max_steps": 1, "timeout_s": 1})


@pytest.mark.parametrize("turn_id", ["", "../escape", "/absolute", "a\\b"])
def test_explicit_unsafe_turn_identity_is_not_replaced_with_a_generated_id(store, turn_id):
    with pytest.raises(_module().TurnStoreError):
        _create(store, turn_id=turn_id)


@pytest.mark.parametrize("component", ["root", "workbench", "agent-turns", "turn_explicit.json", ".state.lock"])
def test_symlink_components_are_rejected(tmp_path, component):
    module = _module()
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    if component == "root":
        project.rmdir()
        project.symlink_to(outside, target_is_directory=True)
    elif component in {"workbench", "agent-turns"}:
        parent = project if component == "workbench" else project / "workbench"
        parent.mkdir(exist_ok=True)
        (parent / component).symlink_to(outside, target_is_directory=True)
    else:
        directory = project / "workbench" / "agent-turns"
        directory.mkdir(parents=True)
        target = outside / component
        target.write_text("sentinel")
        (directory / component).symlink_to(target)
    with pytest.raises(module.TurnStoreError):
        candidate = module.TurnStore(project)
        _create(candidate, turn_id="turn_explicit")
    assert not (outside / "turn_explicit.json").exists() or (outside / "turn_explicit.json").read_text() == "sentinel"


def test_atomic_replace_failure_preserves_previous_snapshot(tmp_path, store, monkeypatch):
    module = _module()
    record = _create(store)
    def fail_replace(*args, **kwargs):
        raise OSError("injected replace failure")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", fail_replace)
        with pytest.raises(module.TurnStoreError):
            store.request_cancel(record.turn_id, expected_version=record.version)
    assert module.TurnStore(tmp_path).get(record.turn_id) == record
    assert not list((tmp_path / "workbench" / "agent-turns").glob("*.tmp"))


def test_reconciliation_preserves_the_last_execution_checkpoint(store):
    record = _running(store)
    record = store.checkpoint(record.turn_id, steps_used=2, wall_s_used=3,
                              checkpoint={"entry_id": "last_committed"}, **_owned(record))
    record = store.transition(record.turn_id, "interrupted", **_owned(record))
    record = store.claim(record.turn_id, expected_version=record.version, owner="reconciler", lease_seconds=10)
    record = store.mark_reconciled(record.turn_id, evidence={"receipt": "operation_receipt"}, **_owned(record))
    assert record.checkpoint == {"entry_id": "last_committed"}
    assert record.reconciliation == {"receipt": "operation_receipt"}


def test_fencing_rejects_boolean_epoch_even_when_equal_to_one(store):
    record = _create(store)
    record = store.claim(record.turn_id, expected_version=record.version, owner="worker", lease_seconds=10)
    assert record.lease_epoch == 1
    with pytest.raises(_module().TurnStoreError):
        store.renew(record.turn_id, lease_seconds=10, expected_version=record.version, owner="worker", fence=True)


@pytest.mark.parametrize("after_replace", [False, True])
def test_fsync_failure_reports_if_replacement_was_visible(tmp_path, store, monkeypatch, after_replace):
    module = _module()
    record = _create(store)
    original_fsync = module.os.fsync
    count = 0
    def fail_fsync(fd):
        nonlocal count
        count += 1
        if count == (2 if after_replace else 1):
            raise OSError("injected fsync failure")
        original_fsync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", fail_fsync)
        with pytest.raises(module.TurnStoreWriteError) as error:
            store.request_cancel(record.turn_id, expected_version=record.version)
    assert error.value.replacement_visible is after_replace
    loaded = module.TurnStore(tmp_path).get(record.turn_id)
    assert loaded.version == record.version + int(after_replace)
    assert loaded.cancel_requested is after_replace


def test_document_corruption_is_not_silently_replaced(tmp_path, store):
    record = _create(store)
    path = tmp_path / "workbench" / "agent-turns" / f"{record.turn_id}.json"
    path.write_text('{"turn_id": "duplicate", "turn_id": "again"}')
    with pytest.raises(_module().TurnStoreError):
        store.get(record.turn_id)
    with pytest.raises(_module().TurnStoreError):
        store.request_cancel(record.turn_id, expected_version=record.version)
    assert path.read_text() == '{"turn_id": "duplicate", "turn_id": "again"}'


def test_concurrent_first_open_handles_directory_creation_race(tmp_path, monkeypatch):
    module = _module()
    barrier = Barrier(2)
    original_mkdir = module.os.mkdir
    def synchronized_mkdir(name, *args, **kwargs):
        if name == "workbench":
            barrier.wait(timeout=5)
        return original_mkdir(name, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "mkdir", synchronized_mkdir)
        with ThreadPoolExecutor(max_workers=2) as pool:
            stores = list(pool.map(lambda _: module.TurnStore(tmp_path), range(2)))
    assert all(candidate.list_active() == [] for candidate in stores)


def test_oversized_numeric_budget_is_a_validation_error(store):
    with pytest.raises(_module().TurnStoreError):
        store.create("session", "entry_1", budget={"max_steps": 10**1000, "timeout_s": 10})


def test_active_listing_excludes_compact_terminal_history_and_stores_only_refs(tmp_path, store):
    record = _running(store)
    store.transition(record.turn_id, "completed", **_owned(record))
    next_record = _create(store)
    assert store.list_active() == [next_record]
    assert len(list((tmp_path / "workbench" / "agent-turns").glob("*.json"))) == 2
    snapshot = store.get(next_record.turn_id).to_dict()
    assert snapshot["input_entry_id"] == "entry_question"
    assert not {"question", "prompt", "messages", "result"} & snapshot.keys()
