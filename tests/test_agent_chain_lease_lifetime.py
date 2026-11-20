"""A live native worker owns its Chain/head beyond the JSON lease deadline."""

from __future__ import annotations

from tests.operation_approval_fixtures import create_approved_operation

import asyncio
import json
import multiprocessing
import threading
from datetime import datetime, timedelta, timezone

import pytest

from workbench.agent import execution
from workbench.agent.execution import (
    ChainExecutionLease, OperationClaimConflict, OperationEffect, WorkbenchOperationLifecycle,
)
from workbench.agent.operations import OperationRecordStore, OperationRegistry
from tests.test_agent_operation_lifecycle import _confirmation


START = datetime(2026, 10, 18, tzinfo=timezone.utc)


def lease(root, key="first", **kwargs):
    return ChainExecutionLease(root, chain_id="chain-1", active_head_run_id="run-1",
                               execution_key=key, **kwargs)


def _live_process(root, ready, finish):
    execution._now = lambda: START
    owner = lease(root)
    owner.acquire()
    ready.set()
    finish.wait(15)
    owner.release()


def test_native_worker_and_cancel_drain_keep_chain_exclusive_after_default_ttl(tmp_path, monkeypatch):
    clock = [START]
    monkeypatch.setattr(execution, "_now", lambda: clock[0])
    started, finish, stopped = threading.Event(), threading.Event(), threading.Event()
    committed = []
    competitor = lease(tmp_path, "second")

    def native_worker():
        started.set()
        assert finish.wait(10), "native test worker was not released"
        stopped.set()
        return OperationEffect(bindings={"child_run_id": "child-1"})

    class Handler:
        def acquire_domain_lease(self, record, *, execution_key):
            owner = lease(tmp_path, execution_key)
            owner.acquire()
            return owner

        def release_domain_lease(self, record, *, execution_key, lease):
            lease.release()

        async def execute(self, record, *, execution_key, failpoint):
            return await asyncio.to_thread(native_worker)

        def commit_domain_state(self, record, *, execution_key, effect):
            assert stopped.is_set()
            committed.append(record.record_id)
            with pytest.raises(OperationClaimConflict):
                competitor.acquire()
            return effect

    store = OperationRecordStore(tmp_path)
    record = create_approved_operation(store, _confirmation())
    lifecycle = WorkbenchOperationLifecycle(operation_store=store, operation_registry=OperationRegistry(),
        handlers={"model.rerun": Handler()}, lease_owner="worker")

    async def scenario():
        task = asyncio.create_task(lifecycle.execute(record.record_id))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            clock[0] += timedelta(seconds=301)
            task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)
            assert not stopped.is_set()
            assert not task.done()
            with pytest.raises(OperationClaimConflict):
                competitor.acquire()
        finally:
            finish.set()
            await asyncio.gather(task, return_exceptions=True)
            competitor.release()
        with pytest.raises(asyncio.CancelledError):
            task.result()

    asyncio.run(scenario())
    assert committed == [record.record_id]
    assert store.get(record.record_id).status == "completed"
    competitor.acquire()
    competitor.release()


def test_same_object_acquire_is_idempotent_after_expiry(tmp_path, monkeypatch):
    clock = [START]
    monkeypatch.setattr(execution, "_now", lambda: clock[0])
    owner = lease(tmp_path)
    competitor = lease(tmp_path, "second")
    owner.acquire()
    before = owner._path.read_bytes()
    try:
        clock[0] += timedelta(seconds=301)
        owner.acquire()
        assert owner._path.read_bytes() == before
        with pytest.raises(OperationClaimConflict):
            competitor.acquire()
    finally:
        competitor.release()
        owner.release()


def test_fresh_same_key_cannot_release_a_live_owner(tmp_path):
    owner = lease(tmp_path)
    stranger = lease(tmp_path)
    competitor = lease(tmp_path, "second")
    owner.acquire()
    before = owner._path.read_bytes()
    try:
        stranger.release()
        assert owner._path.read_bytes() == before
        with pytest.raises(OperationClaimConflict):
            competitor.acquire()
    finally:
        competitor.release()
        owner.release()


def test_fresh_same_key_does_not_claim_the_live_owners_file_lock(tmp_path):
    owner, stranger = lease(tmp_path), lease(tmp_path)
    owner.acquire()
    try:
        with pytest.raises(OperationClaimConflict):
            stranger.acquire()
    finally:
        stranger.release()
        owner.release()


@pytest.mark.parametrize("recover_same_key", [False, True])
def test_process_death_unlocks_but_preserves_json_recovery_and_expiry_rules(tmp_path, monkeypatch, recover_same_key):
    clock = [START]
    monkeypatch.setattr(execution, "_now", lambda: clock[0])
    ctx = multiprocessing.get_context("spawn")
    ready, finish = ctx.Event(), ctx.Event()
    process = ctx.Process(target=_live_process, args=(str(tmp_path), ready, finish))
    process.start()
    contender = lease(tmp_path, "first" if recover_same_key else "second")
    try:
        assert ready.wait(10)
        clock[0] += timedelta(seconds=301)
        with pytest.raises(OperationClaimConflict):
            contender.acquire()
    finally:
        contender.release()
        process.terminate()
        process.join(10)
    assert not process.is_alive()
    original = json.loads(contender._path.read_text())
    assert original["status"] == "active"
    assert original["execution_key"] == "first"
    clock[0] = START
    if recover_same_key:
        contender.acquire()
        assert json.loads(contender._path.read_text()) == original
    else:
        with pytest.raises(OperationClaimConflict):
            contender.acquire()
        clock[0] += timedelta(seconds=301)
        contender.acquire()
        assert json.loads(contender._path.read_text())["execution_key"] == "second"
    contender.release()
