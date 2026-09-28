from pathlib import Path
import asyncio

import pytest

from workbench.agent.operations import OperationRecordStore
from workbench.agent.proposals import ProposalConfirmation


def _confirmation() -> ProposalConfirmation:
    return ProposalConfirmation(
        proposal_id="proposal-lifecycle-1",
        operation_id="model.rerun",
        operation_version="v1",
        revision=1,
        fingerprint="fingerprint-1",
        session_id="session-1",
        chain_id="chain-1",
        command_id="command-1",
        target={"run_id": "run-1", "node_ref": "model:ols"},
        preconditions={"active_head_run_id": "run-1"},
        actor_type="user",
        confirmed_at="2026-07-15T00:00:00+00:00",
        status="confirmed",
    )


def test_execution_key_is_deterministic() -> None:
    from workbench.agent.execution import execution_key

    assert execution_key(
        proposal_id="proposal-1", revision=1, fingerprint="fingerprint-1"
    ) == execution_key(
        proposal_id="proposal-1", revision=1, fingerprint="fingerprint-1"
    )


def test_claim_execution_is_idempotent_and_rejects_different_key(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import OperationClaimConflict

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())

    claimed = store.claim_execution(
        record.record_id,
        execution_key="execution-1",
        lease_owner="worker-a",
    )
    repeated = store.claim_execution(
        record.record_id,
        execution_key="execution-1",
        lease_owner="worker-a",
    )

    assert claimed.execution["execution_key"] == "execution-1"
    assert repeated.execution["execution_key"] == "execution-1"
    with pytest.raises(OperationClaimConflict):
        store.claim_execution(
            record.record_id,
            execution_key="execution-2",
            lease_owner="worker-b",
        )
    with pytest.raises(OperationClaimConflict):
        store.claim_execution(
            record.record_id,
            execution_key="execution-1",
            lease_owner="worker-b",
        )


def test_terminal_operation_cannot_be_claimed_again(tmp_path: Path) -> None:
    from workbench.agent.execution import OperationClaimConflict

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    store.claim_execution(
        record.record_id,
        execution_key="execution-1",
        lease_owner="worker-a",
    )
    store.append_status(record.record_id, "completed")

    with pytest.raises(OperationClaimConflict):
        store.claim_execution(
            record.record_id,
            execution_key="execution-1",
            lease_owner="worker-a",
        )


def test_generic_lifecycle_dispatches_by_registry_hook_and_persists_effect(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import (
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRecord, OperationRegistry

    class Handler:
        def __init__(self) -> None:
            self.execute_calls = 0
            self.reconcile_calls = 0

        async def execute(self, record, *, execution_key, failpoint):
            self.execute_calls += 1
            return OperationEffect(
                outputs={"status": "completed"},
                bindings={"child_run_id": "run-child-1"},
                verification={"passed": True},
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            self.reconcile_calls += 1
            return OperationEffect(
                outputs={"status": "completed"},
                bindings=dict(record.execution["bindings"]),
                verification={"passed": True},
            )

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    handler = Handler()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": handler},
        lease_owner="test-worker",
    )

    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert completed.execution["bindings"] == {"child_run_id": "run-child-1"}
    assert completed.verification["passed"] is True
    assert handler.execute_calls == 1


def test_async_effect_stays_nonterminal_until_reconcile(
    tmp_path: Path,
) -> None:
    """A submitted child is not a failed effect or a completed projection."""

    from workbench.agent.execution import (
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRegistry

    class Handler:
        def __init__(self) -> None:
            self.execute_calls = 0
            self.reconcile_calls = 0

        async def execute(self, record, *, execution_key, failpoint):
            self.execute_calls += 1
            return OperationEffect(
                outputs={"status": "running", "target_run_id": "run-child-async"},
                bindings={"child_run_id": "run-child-async"},
                status="running",
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            self.reconcile_calls += 1
            return OperationEffect(
                outputs={"status": "completed", "target_run_id": "run-child-async"},
                bindings=dict(record.execution["bindings"]),
                status="completed",
                verification={"passed": True},
            )

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    handler = Handler()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": handler},
        lease_owner="test-worker",
    )

    submitted = asyncio.run(lifecycle.execute(record.record_id))

    assert submitted.status == "running"
    assert submitted.effect_status == "pending"
    assert submitted.projection_status == "pending"
    assert submitted.error is None
    assert handler.execute_calls == 1
    assert handler.reconcile_calls == 0

    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert completed.effect_status == "committed"
    assert completed.projection_status == "complete"
    assert completed.verification["passed"] is True
    assert handler.execute_calls == 1
    assert handler.reconcile_calls == 1


def test_generic_lifecycle_commits_domain_state_before_terminalizing(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import (
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRecord, OperationRegistry

    class Handler:
        def __init__(self) -> None:
            self.commit_calls = 0

        async def execute(self, record, *, execution_key, failpoint):
            return OperationEffect(
                outputs={"status": "completed"},
                bindings={"child_run_id": "run-child-1"},
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            return OperationEffect(
                outputs={"status": "completed"},
                bindings=dict(record.execution["bindings"]),
            )

        async def commit_domain_state(
            self,
            record,
            *,
            execution_key,
            effect,
        ):
            self.commit_calls += 1
            return OperationEffect(
                outputs={**effect.outputs, "domain_committed": True},
                bindings=dict(effect.bindings),
                verification={"domain_committed": True},
            )

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    handler = Handler()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": handler},
        lease_owner="test-worker",
    )

    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert completed.outputs["domain_committed"] is True
    assert completed.verification == {"domain_committed": True}
    assert handler.commit_calls == 1


def test_generic_lifecycle_owns_domain_lease_until_terminal_or_crash(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import (
        InjectedOperationCrash,
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRegistry

    class Lease:
        def __init__(self) -> None:
            self.released = False

        def release(self) -> None:
            self.released = True

    class Handler:
        def __init__(self) -> None:
            self.lease = Lease()
            self.order: list[str] = []

        def acquire_domain_lease(self, record, *, execution_key):
            self.order.append("acquire")
            return self.lease

        def release_domain_lease(self, record, *, execution_key, lease) -> None:
            self.order.append("release")
            lease.release()

        async def execute(self, record, *, execution_key, failpoint):
            self.order.append("execute")
            return OperationEffect(
                outputs={"status": "completed"},
                bindings={"child_run_id": "run-child-1"},
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            raise AssertionError("first execution should not reconcile")

        async def commit_domain_state(
            self,
            record,
            *,
            execution_key,
            effect,
        ):
            self.order.append("commit")
            return effect

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    handler = Handler()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": handler},
        lease_owner="test-worker",
    )

    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert handler.order == ["acquire", "execute", "commit", "release"]
    assert handler.lease.released is True

    class CrashOnce:
        def hit(self, point: str, record) -> None:
            if point == "before_child_effect":
                raise InjectedOperationCrash(point)

    crashed_record = store.create_pending(
        ProposalConfirmation(
            **{
                **_confirmation().__dict__,
                "proposal_id": "proposal-lifecycle-crash",
            }
        )
    )
    crash_handler = Handler()
    crash_lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": crash_handler},
        lease_owner="test-worker",
        failpoint=CrashOnce(),
    )

    with pytest.raises(InjectedOperationCrash):
        asyncio.run(crash_lifecycle.execute(crashed_record.record_id))
    assert crash_handler.order == ["acquire", "release"]
    assert crash_handler.lease.released is True


@pytest.mark.parametrize(
    "crash_point",
    [
        "after_claim",
        "before_child_effect",
        "after_child_effect",
        "after_effect_binding",
        "before_domain_commit",
        "after_domain_commit",
        "before_terminal_reconcile",
    ],
)
def test_failpoint_retry_converges_to_one_effect(
    tmp_path: Path,
    crash_point: str,
) -> None:
    from workbench.agent.execution import (
        InjectedOperationCrash,
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRegistry

    class CrashOnce:
        def __init__(self) -> None:
            self.triggered = False

        def hit(self, point: str, record) -> None:
            if point == crash_point and not self.triggered:
                self.triggered = True
                raise InjectedOperationCrash(point)

    class IdempotentHandler:
        def __init__(self) -> None:
            self.effects: dict[str, str] = {}

        async def execute(self, record, *, execution_key, failpoint):
            child_id = self.effects.setdefault(execution_key, "run-child-1")
            return OperationEffect(
                outputs={"status": "completed"},
                bindings={"child_run_id": child_id},
                verification={"passed": True},
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            return OperationEffect(
                outputs={"status": "completed"},
                bindings=dict(record.execution["bindings"]),
                verification={"passed": True},
            )

        async def commit_domain_state(
            self,
            record,
            *,
            execution_key,
            effect,
        ):
            return effect

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    handler = IdempotentHandler()
    failpoint = CrashOnce()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": handler},
        lease_owner="test-worker",
        failpoint=failpoint,
    )

    with pytest.raises(InjectedOperationCrash):
        asyncio.run(lifecycle.execute(record.record_id))
    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert completed.execution["bindings"] == {"child_run_id": "run-child-1"}
    assert len(handler.effects) == 1


def test_effect_commit_and_projection_terminalization_are_separate(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import (
        InjectedOperationCrash,
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRegistry

    class CrashAfterCommit:
        triggered = False

        def hit(self, point: str, record) -> None:
            if point == "after_domain_commit" and not self.triggered:
                self.triggered = True
                raise InjectedOperationCrash(point)

    class Handler:
        def __init__(self) -> None:
            self.execute_calls = 0
            self.commit_calls = 0

        async def execute(self, record, *, execution_key, failpoint):
            self.execute_calls += 1
            return OperationEffect(
                outputs={"target_run_id": "run-child-1"},
                bindings={"child_run_id": "run-child-1"},
                verification={"passed": True},
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            return OperationEffect(
                outputs={"target_run_id": "run-child-1"},
                bindings=dict(record.execution["bindings"]),
                verification={"passed": True},
            )

        async def commit_domain_state(self, record, *, execution_key, effect):
            self.commit_calls += 1
            return effect

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())
    handler = Handler()
    failpoint = CrashAfterCommit()
    lifecycle = WorkbenchOperationLifecycle(
        operation_store=store,
        operation_registry=OperationRegistry(),
        handlers={"model.rerun": handler},
        lease_owner="test-worker",
        failpoint=failpoint,
    )

    with pytest.raises(InjectedOperationCrash):
        asyncio.run(lifecycle.execute(record.record_id))

    interrupted = store.get(record.record_id)
    assert interrupted.status == "submitted"
    assert interrupted.effect_status == "committed"
    assert interrupted.projection_status == "pending"
    assert interrupted.execution["bindings"] == {"child_run_id": "run-child-1"}

    completed = asyncio.run(lifecycle.execute(record.record_id))

    assert completed.status == "completed"
    assert completed.effect_status == "committed"
    assert completed.projection_status == "complete"
    assert handler.execute_calls == 1
    assert handler.commit_calls == 2


def test_concurrent_same_execution_claims_fail_closed_across_owners(tmp_path: Path) -> None:
    from workbench.agent.execution import OperationClaimConflict

    store = OperationRecordStore(tmp_path)
    record = store.create_pending(_confirmation())

    async def claim(owner: str, key: str):
        return store.claim_execution(
            record.record_id,
            execution_key=key,
            lease_owner=owner,
        )

    async def gather_same_key():
        return await asyncio.gather(
            claim("worker-a", "execution-1"),
            claim("worker-b", "execution-1"),
            return_exceptions=True,
        )

    same_key = asyncio.run(gather_same_key())
    assert sum(isinstance(item, OperationClaimConflict) for item in same_key) == 1

    async def gather_different_keys():
        return await asyncio.gather(
            claim("worker-a", "execution-2"),
            claim("worker-b", "execution-3"),
            return_exceptions=True,
        )

    different_key = asyncio.run(gather_different_keys())
    assert sum(isinstance(item, OperationClaimConflict) for item in different_key) == 2


def test_chain_execution_lease_rejects_competing_active_head_and_releases_after_completion(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import ChainExecutionLease, OperationClaimConflict

    first = ChainExecutionLease(
        tmp_path,
        chain_id="chain-1",
        active_head_run_id="run-1",
        execution_key="execution-1",
    )
    second = ChainExecutionLease(
        tmp_path,
        chain_id="chain-1",
        active_head_run_id="run-1",
        execution_key="execution-2",
    )

    first.acquire()
    with pytest.raises(OperationClaimConflict):
        second.acquire()
    first.release()
    second.acquire()


def test_jsonl_store_ignores_only_a_partial_trailing_record(tmp_path: Path) -> None:
    from workbench.agent.storage import read_jsonl

    path = tmp_path / "records.jsonl"
    path.write_text('{"status":"submitted"}\n{"status":"incomplete"', encoding="utf-8")

    assert read_jsonl(path) == [{"status": "submitted"}]

    path.write_text(
        '{"status":"submitted"}\n{"status":"broken"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        read_jsonl(path)


def test_shared_lifecycle_rejects_two_different_proposals_on_one_chain(
    tmp_path: Path,
) -> None:
    from workbench.agent.execution import (
        ChainExecutionLease,
        OperationClaimConflict,
        OperationEffect,
        WorkbenchOperationLifecycle,
    )
    from workbench.agent.operations import OperationRecord, OperationRegistry

    first_confirmation = _confirmation()
    second_confirmation = ProposalConfirmation(
        **{
            **first_confirmation.__dict__,
            "proposal_id": "proposal-lifecycle-competition",
        }
    )
    store = OperationRecordStore(tmp_path)
    first_record = store.create_pending(first_confirmation)
    second_record = store.create_pending(second_confirmation)
    gate = asyncio.Event()
    started = asyncio.Event()

    class Handler:
        def __init__(self, child_id: str) -> None:
            self.child_id = child_id
            self.effects = 0

        def acquire_domain_lease(self, record, *, execution_key):
            lease = ChainExecutionLease(
                tmp_path,
                chain_id=record.chain_id,
                active_head_run_id="run-1",
                execution_key=execution_key,
            )
            lease.acquire()
            return lease

        def release_domain_lease(self, record, *, execution_key, lease) -> None:
            lease.release()

        async def execute(self, record, *, execution_key, failpoint):
            self.effects += 1
            started.set()
            await gate.wait()
            return OperationEffect(
                outputs={"target_run_id": self.child_id, "status": "completed"},
                bindings={"child_run_id": self.child_id},
            )

        async def reconcile(self, record, *, execution_key, failpoint):
            raise AssertionError("the competing proposal must not reach reconcile")

        async def commit_domain_state(
            self,
            record,
            *,
            execution_key,
            effect,
        ):
            return effect

    first_handler = Handler("run-child-1")
    second_handler = Handler("run-child-2")
    registry = OperationRegistry()

    async def run() -> tuple[OperationRecord, BaseException | None]:
        first = WorkbenchOperationLifecycle(
            operation_store=store,
            operation_registry=registry,
            handlers={"model.rerun": first_handler},
            lease_owner="worker-a",
        )
        second = WorkbenchOperationLifecycle(
            operation_store=store,
            operation_registry=registry,
            handlers={"model.rerun": second_handler},
            lease_owner="worker-b",
        )
        first_task = asyncio.create_task(first.execute(first_record.record_id))
        await started.wait()
        second_result = await asyncio.gather(
            second.execute(second_record.record_id),
            return_exceptions=True,
        )
        gate.set()
        completed = await first_task
        return completed, second_result[0]

    completed, conflict = asyncio.run(run())

    assert completed.status == "completed"
    assert isinstance(conflict, OperationClaimConflict)
    assert first_handler.effects == 1
    assert second_handler.effects == 0
