"""Local session execution ownership outlives the renewable JSON lease."""

import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from workbench.agent.turn_store import TurnStore, TurnStoreError


def _running(store, session='session'):
    record = store.create(session, 'input', budget={'max_steps': 10, 'timeout_s': 300})
    record = store.claim(record.turn_id, expected_version=record.version, owner='worker', lease_seconds=10)
    return store.transition(record.turn_id, 'running', expected_version=record.version,
                            owner=record.lease_owner, fence=record.lease_epoch)


def _owned(record):
    return {'expected_version': record.version, 'owner': record.lease_owner, 'fence': record.lease_epoch}


def test_session_guard_excludes_same_and_other_instances_without_blocking_other_sessions(tmp_path):
    store = TurnStore(tmp_path)
    with store.execution_guard('session'):
        for contender in (store, TurnStore(tmp_path)):
            with pytest.raises(TurnStoreError):
                with contender.execution_guard('session'):
                    pytest.fail('duplicate session acquired')
        with TurnStore(tmp_path).execution_guard('independent'):
            pass
    with TurnStore(tmp_path).execution_guard('session'):
        pass


def _hold_guard(root, ready):
    store = TurnStore(root)
    with store.execution_guard('session'):
        ready.put('held')
        time.sleep(15)


def test_process_guard_excludes_even_expired_json_lease_and_death_releases_it(tmp_path):
    now = [100.0]
    store = TurnStore(tmp_path, clock=lambda: now[0])
    record = _running(store)
    context = multiprocessing.get_context('spawn')
    ready = context.Queue()
    process = context.Process(target=_hold_guard, args=(tmp_path, ready))
    process.start()
    try:
        assert ready.get(timeout=10) == 'held'
        now[0] = 111
        assert store.get(record.turn_id).lease_expires_at < now[0]
        with pytest.raises(TurnStoreError):
            with store.execution_guard('session'):
                pytest.fail('JSON lease expiry stole a live process guard')
        process.terminate()
        process.join(timeout=5)
        assert not process.is_alive()
        with store.execution_guard('session'):
            pass
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        ready.close()


def test_guard_does_not_hold_short_state_lock_or_prevent_queue_cancel(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    other = TurnStore(tmp_path, clock=lambda: 100)
    def control():
        assert other.get(record.turn_id) == record
        assert other.list_active() == [record]
        queued = other.enqueue(record.turn_id, 'steer', 'queue-entry', expected_version=record.version)
        return other.request_cancel(record.turn_id, expected_version=queued.version)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with store.execution_guard('session'):
            result = pool.submit(control).result(timeout=2)
            assert result.cancel_requested and len(result.queue) == 1
    finally:
        pool.shutdown(wait=True)


def test_orphan_interrupt_before_lease_expiry_preserves_usage_pending_results_and_queue(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    record = store.checkpoint(record.turn_id, steps_used=3, wall_s_used=12,
                              checkpoint={'provider': 'step-entry'}, **_owned(record))
    record = store.record_tool_call(record.turn_id, 'resolved', operation_key='exec-done',
                                    checkpoint={'assistant': 'assistant-entry'}, **_owned(record))
    record = store.resolve_tool_call(record.turn_id, 'resolved', operation_key='exec-done',
                                     evidence={'tool_result': 'result-entry'}, **_owned(record))
    record = store.record_tool_call(record.turn_id, 'pending', operation_key='exec-pending',
                                    checkpoint={'assistant': 'pending-entry'}, **_owned(record))
    record = store.enqueue(record.turn_id, 'follow_up', 'follow-entry', expected_version=record.version)
    record = store.request_cancel(record.turn_id, expected_version=record.version)
    with store.execution_guard('session') as guard:
        interrupted = store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
    assert interrupted.status == 'interrupted' and interrupted.requires_reconcile
    assert interrupted.lease_owner is None and interrupted.lease_expires_at is None
    assert interrupted.lease_epoch == record.lease_epoch + 1
    assert interrupted.version == record.version + 1
    for field in ('turn_id', 'command_id', 'input_entry_id', 'budget', 'steps_used', 'wall_s_used',
                  'checkpoint', 'tool_calls', 'queue', 'cancel_requested', 'reconciliation'):
        assert getattr(interrupted, field) == getattr(record, field)
    assert interrupted.tool_calls['pending']['status'] == 'pending'
    assert interrupted.tool_calls['resolved']['evidence'] == {'tool_result': 'result-entry'}


def test_interrupt_rejects_wrong_store_session_released_and_unknown_guard(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    other = TurnStore(tmp_path, clock=lambda: 100)
    with store.execution_guard('session') as guard:
        with pytest.raises(TurnStoreError):
            other.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
    with pytest.raises(TurnStoreError):
        store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
    with store.execution_guard('other-session') as other_guard:
        with pytest.raises(TurnStoreError):
            store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=other_guard)
    with pytest.raises(TurnStoreError):
        store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=object())
    assert store.get(record.turn_id) == record


def test_closed_guard_descriptor_is_rejected_without_changing_record(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    with store.execution_guard('session') as guard:
        os.close(guard._fd)
        with pytest.raises(TurnStoreError):
            store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
    assert store.get(record.turn_id) == record


@pytest.mark.parametrize('replaced', ['directory', 'lockfile'])
def test_guard_is_bound_to_original_directory_and_lock_inode(tmp_path, replaced):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    directory = tmp_path / 'workbench/agent-turns'
    with store.execution_guard('session') as guard:
        if replaced == 'directory':
            directory.rename(tmp_path / 'old-turns')
            directory.mkdir()
        else:
            lock = directory / guard._filename
            lock.unlink()
            lock.touch()
        with pytest.raises(TurnStoreError):
            store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)


def _use_inherited_guard(store, record, guard, queue):
    try:
        store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
    except TurnStoreError:
        queue.put('rejected')
    else:
        queue.put('accepted')


def test_inherited_guard_is_rejected_in_child_pid_without_unlocking_parent(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    with store.execution_guard('session') as guard:
        child = context.Process(target=_use_inherited_guard, args=(store, record, guard, queue))
        child.start()
        try:
            assert queue.get(timeout=5) == 'rejected'
            child.join(timeout=5)
            assert child.exitcode == 0
            with pytest.raises(TurnStoreError):
                with TurnStore(tmp_path).execution_guard('session'):
                    pytest.fail('child released its parent execution guard')
            assert store.get(record.turn_id) == record
        finally:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
            queue.close()


@pytest.mark.parametrize('status', ['accepted', 'awaiting_approval', 'interrupted', 'completed'])
def test_orphan_interrupt_only_accepts_running_turns(tmp_path, status):
    store = TurnStore(tmp_path, clock=lambda: 100)
    if status == 'accepted':
        record = store.create('session', 'input', budget={'max_steps': 2, 'timeout_s': 10})
    else:
        record = _running(store)
        record = store.transition(record.turn_id, status, **_owned(record))
    with store.execution_guard('session') as guard:
        with pytest.raises(TurnStoreError):
            store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
    assert store.get(record.turn_id) == record


def test_orphan_interrupt_keeps_cas_and_old_expiry_contract(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    with store.execution_guard('session') as guard:
        with pytest.raises(TurnStoreError):
            store.interrupt_expired(record.turn_id, expected_version=record.version)
        with pytest.raises(TurnStoreError):
            store.interrupt_orphaned(record.turn_id, expected_version=record.version - 1, guard=guard)
    assert store.get(record.turn_id) == record


def test_create_binds_explicit_command_and_checks_it_on_same_turn_retry(tmp_path):
    store = TurnStore(tmp_path)
    arguments = {'budget': {'max_steps': 3, 'timeout_s': 20}, 'turn_id': 'turn-fixed'}
    record = store.create('session', 'input', command_id='command-core', **arguments)
    assert record.command_id == 'command-core'
    assert store.get(record.turn_id).command_id == 'command-core'
    assert store.create('session', 'input', command_id='command-core', **arguments) == record
    assert store.create('session', 'input', **arguments) == record
    with pytest.raises(TurnStoreError):
        store.create('session', 'input', command_id='command-other', **arguments)
    assert store.get(record.turn_id) == record


def test_create_rejects_invalid_explicit_commands_and_preserves_random_default(tmp_path):
    store = TurnStore(tmp_path)
    for invalid in ('', '../escape', 'a/b', 'a\\b', 'nul\x00id', '.', '..', False, 42):
        with pytest.raises(TurnStoreError):
            store.create('session', 'input', command_id=invalid,
                         budget={'max_steps': 3, 'timeout_s': 20})
        assert store.list_active() == []
    record = store.create('session', 'input', budget={'max_steps': 3, 'timeout_s': 20})
    assert record.command_id.startswith('command_')
    assert len(record.command_id) == len('command_') + 32


def test_orphaned_recovery_claim_can_be_released_before_expiry_without_losing_pending(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = _running(store)
    record = store.checkpoint(record.turn_id, steps_used=4, wall_s_used=17,
                              checkpoint={'provider': 'original-step'}, **_owned(record))
    record = store.record_tool_call(record.turn_id, 'pending', operation_key='exec-original',
                                    checkpoint={'assistant': 'original-assistant'}, **_owned(record))
    record = store.enqueue(record.turn_id, 'steer', 'queued-entry', expected_version=record.version)
    with store.execution_guard('session') as guard:
        record = store.interrupt_orphaned(record.turn_id, expected_version=record.version, guard=guard)
        record = store.claim(record.turn_id, expected_version=record.version, owner='dead-reconciler', lease_seconds=100)
    restarted = TurnStore(tmp_path, clock=lambda: 100)
    with restarted.execution_guard('session') as guard:
        with pytest.raises(TurnStoreError, match='live owner'):
            restarted.claim(record.turn_id, expected_version=record.version, owner='new-reconciler', lease_seconds=100)
        released = restarted.release_orphaned_claim(record.turn_id, expected_version=record.version, guard=guard)
        assert released.status == 'interrupted' and released.requires_reconcile
        assert released.lease_owner is None and released.lease_expires_at is None
        assert released.lease_epoch == record.lease_epoch + 1
        assert released.version == record.version + 1
        for field in ('turn_id', 'command_id', 'input_entry_id', 'budget', 'steps_used', 'wall_s_used',
                      'checkpoint', 'queue', 'tool_calls', 'requires_reconcile', 'status'):
            assert getattr(released, field) == getattr(record, field)
        reclaimed = restarted.claim(record.turn_id, expected_version=released.version,
                                     owner='new-reconciler', lease_seconds=100)
        assert reclaimed.lease_owner == 'new-reconciler'
        assert reclaimed.tool_calls['pending']['operation_key'] == 'exec-original'
        assert reclaimed.requires_reconcile


def test_orphaned_claim_release_requires_matching_live_guard_and_cannot_steal_a_runtime(tmp_path):
    store = TurnStore(tmp_path, clock=lambda: 100)
    record = store.create('session', 'input', budget={'max_steps': 4, 'timeout_s': 30})
    record = store.claim(record.turn_id, expected_version=record.version, owner='worker', lease_seconds=100)
    other = TurnStore(tmp_path, clock=lambda: 100)
    with store.execution_guard('session') as guard:
        with pytest.raises(TurnStoreError):
            with other.execution_guard('session'):
                pytest.fail('live runtime lost execution ownership')
        with pytest.raises(TurnStoreError):
            other.release_orphaned_claim(record.turn_id, expected_version=record.version, guard=guard)
    with pytest.raises(TurnStoreError):
        store.release_orphaned_claim(record.turn_id, expected_version=record.version, guard=guard)
    with store.execution_guard('other-session') as wrong_guard:
        with pytest.raises(TurnStoreError):
            store.release_orphaned_claim(record.turn_id, expected_version=record.version, guard=wrong_guard)
    assert store.get(record.turn_id) == record


@pytest.mark.parametrize('status', ['running', 'completed', 'accepted-unowned'])
def test_orphaned_claim_release_does_not_replace_running_interrupt_or_allow_empty_claims(tmp_path, status):
    store = TurnStore(tmp_path, clock=lambda: 100)
    if status == 'accepted-unowned':
        record = store.create('session', 'input', budget={'max_steps': 4, 'timeout_s': 30})
    else:
        record = _running(store)
        if status == 'completed':
            record = store.transition(record.turn_id, 'completed', **_owned(record))
    with store.execution_guard('session') as guard:
        with pytest.raises(TurnStoreError):
            store.release_orphaned_claim(record.turn_id, expected_version=record.version, guard=guard)
    assert store.get(record.turn_id) == record
