from tests.operation_approval_fixtures import create_approved_operation
"""Cancellation must not release ownership while a native worker still runs."""

import asyncio
from pathlib import Path
import threading

import pytest

from workbench.agent.execution import OperationEffect, WorkbenchOperationLifecycle
from workbench.agent.operations import OperationRecordStore, OperationRegistry
from tests.test_agent_operation_lifecycle import _confirmation


@pytest.mark.parametrize("worker_fails", [False, True])
def test_cancellation_drains_effect_and_commit_before_releasing_lease(
    tmp_path: Path, worker_fails: bool,
) -> None:
    started = threading.Event()
    finish = threading.Event()
    stopped = threading.Event()
    order: list[str] = []

    def worker():
        started.set()
        assert finish.wait(5), "test worker was not released"
        stopped.set()
        if worker_fails:
            raise ValueError("native worker failed")
        return OperationEffect(bindings={"child_run_id": "child-1"})

    class Handler:
        def acquire_domain_lease(self, record, *, execution_key):
            order.append("acquire")
            return object()

        def release_domain_lease(self, record, *, execution_key, lease):
            order.append("release")

        async def execute(self, record, *, execution_key, failpoint):
            return await asyncio.to_thread(worker)

        async def commit_domain_state(self, record, *, execution_key, effect):
            order.append("commit")
            return effect

    store = OperationRecordStore(tmp_path)
    record = create_approved_operation(store, _confirmation())
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": Handler()},
        lease_owner="test-worker",
    )

    async def scenario():
        task = asyncio.create_task(lifecycle.execute(record.record_id))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            # Cancellation is delivered before these later event-loop callbacks.
            for _ in range(3):
                await asyncio.sleep(0)
            assert not stopped.is_set()
            assert order == ["acquire"]
            assert not task.done()
            # Repeated aborts must not cancel the owned effect or its commit.
            task.cancel()
            await asyncio.sleep(0)
        finally:
            finish.set()
            await asyncio.gather(task, return_exceptions=True)
        with pytest.raises(asyncio.CancelledError):
            task.result()

    asyncio.run(scenario())
    assert stopped.is_set()
    assert order == ["acquire", "commit", "release"]
    completed = store.get(record.record_id)
    if worker_fails:
        assert completed.status == "failed"
        assert completed.error == {"type": "ValueError", "message": "native worker failed"}
        assert not completed.execution.get("bindings")
    else:
        assert completed.status == "completed"
        assert completed.execution["bindings"] == {"child_run_id": "child-1"}
