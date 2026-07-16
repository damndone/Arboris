from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from workbench.agent.core import AgentCore
from workbench.agent.chains import (
    ChainStore,
    ForkStore,
    RerunExecutionRequest,
    RerunExecutionResult,
)
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.operations import (
    OperationDefinition,
    OperationRecordTransitionError,
    OperationRegistry,
    UnknownOperationError,
)
from workbench.agent.proposals import ProposalConfirmationError, ProposalStaleError
from workbench.agent.session import EntryRef, JsonlSessionRepository


class IdleAdapter:
    async def stream(self, request):
        if False:
            yield request


class ProposalToolAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-proposal-1",
                    "tool_id": "propose_operation",
                    "arguments": {
                        "operation_id": "model.rerun",
                        "target": {
                            "run_id": "run-1",
                            "node_ref": "model-ols",
                            "node_hash": "node-hash-1",
                            "forest_node_key": "node-hash-1",
                        },
                        "preconditions": {
                            "context_version": "node-operation-context/v1",
                            "context_fingerprint": "ctx-command",
                            "active_head_run_id": "run-1",
                            "owner_resolution": "active_head_contains_node",
                        },
                        "changes": {
                            "covariance": {"old": "nonrobust", "new": "HC1"},
                        },
                        "evidence_refs": ["diagnostic:heteroskedasticity"],
                        "expected_effect": ["standard errors may change"],
                        "risks": ["small samples may overinflate standard errors"],
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        yield ModelStreamEvent.text_delta(request.request_id, "proposal prepared")
        yield ModelStreamEvent.done(request.request_id)


def make_orchestrator(
    tmp_path: Path,
    adapter: object | None = None,
) -> WorkbenchOrchestrator:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    agent = AgentCore(
        repository,
        events,
        adapter or IdleAdapter(),
        session_id="chain-session",
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
    )
    orchestrator.register_chain("chain-a", "chain-session", agent)
    return orchestrator


def test_dispatch_executes_proposal_tool_without_workbench_mutation(
    tmp_path: Path,
) -> None:
    adapter = ProposalToolAdapter()
    orchestrator = make_orchestrator(tmp_path, adapter)
    command = orchestrator.dispatch_to_chain(
        "chain-a",
        objective="检查当前模型并提出修改",
        allowed_operations=["model.rerun"],
        budget={"max_steps": 4, "timeout_s": 30},
        context_fingerprint="ctx-command",
    )

    result = asyncio.run(orchestrator.execute(command.command_id))

    assert result == "proposal prepared"
    assert len(adapter.requests) == 2
    proposal_events = [
        event
        for event in orchestrator.events.replay("chain-session")
        if event.event_type == "proposal_ready"
    ]
    assert len(proposal_events) == 1
    proposal_id = proposal_events[0].payload["proposal_id"]
    proposal = orchestrator.proposal_store.latest_revision(proposal_id)
    assert proposal.command_id == command.command_id
    assert orchestrator.proposal_store.latest_status(proposal_id) == "pending"
    assert orchestrator.operation_store.list_records() == []
    assert not (tmp_path / "workbench" / "runs").exists()


def test_dispatch_rejects_unauthorized_proposal_tool_without_creating_proposal(
    tmp_path: Path,
) -> None:
    adapter = ProposalToolAdapter()
    orchestrator = make_orchestrator(tmp_path, adapter)
    command = orchestrator.dispatch_to_chain(
        "chain-a",
        objective="只检查当前模型",
        allowed_operations=["inspect"],
        budget={"max_steps": 4, "timeout_s": 30},
        context_fingerprint="ctx-command",
    )

    asyncio.run(orchestrator.execute(command.command_id))

    tool_entries = [
        entry
        for entry in orchestrator.repository.get_branch("chain-session")
        if entry.entry_type == "message" and entry.payload.get("role") == "tool"
    ]
    assert len(tool_entries) == 1
    tool_result = json.loads(tool_entries[0].payload["content"])
    assert tool_result["ok"] is False
    assert tool_result["error"] == "PermissionError"
    assert not [
        event
        for event in orchestrator.events.replay("chain-session")
        if event.event_type == "proposal_ready"
    ]
    assert orchestrator.operation_store.list_records() == []


def proposal_kwargs() -> dict:
    return {
        "chain_id": "chain-a",
        "operation_id": "model.rerun",
        "target": {
            "run_id": "run-1",
            "node_ref": "model-ols",
            "node_hash": "node-hash-1",
            "forest_node_key": "node-hash-1",
        },
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "ctx-1",
            "active_head_run_id": "run-1",
            "owner_resolution": "active_head_contains_node",
        },
        "changes": {
            "covariance": {"old": "nonrobust", "new": "HC3"},
        },
        "evidence_refs": ["diagnostic:heteroskedasticity"],
        "expected_effect": ["standard errors may change"],
        "risks": ["small samples may overinflate standard errors"],
        "command_id": "cmd-1",
    }


def test_proposal_revision_and_confirmation_create_pending_audit_record_without_run(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)

    first = orchestrator.create_proposal(**proposal_kwargs())
    revised = orchestrator.revise_proposal(
        first.proposal_id,
        base_revision=first.revision,
        changes={"covariance": {"old": "nonrobust", "new": "HC1"}},
        expected_effect=["standard errors may change modestly"],
    )

    assert first.revision == 1
    assert revised.revision == 2
    assert revised.fingerprint != first.fingerprint

    with pytest.raises(ProposalConfirmationError):
        orchestrator.confirm_proposal(
            first.proposal_id,
            revision=first.revision,
            fingerprint=first.fingerprint,
            actor_type="user",
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
        )

    record = orchestrator.confirm_proposal(
        revised.proposal_id,
        revision=revised.revision,
        fingerprint=revised.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    duplicate = orchestrator.confirm_proposal(
        revised.proposal_id,
        revision=revised.revision,
        fingerprint=revised.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )

    assert record.record_id == duplicate.record_id
    assert record.status == "pending"
    assert record.proposal_id == revised.proposal_id
    assert record.proposal_revision == 2
    assert record.proposal_fingerprint == revised.fingerprint
    assert not (tmp_path / "workbench" / "runs").exists()


def test_stale_context_blocks_confirmation_and_leaves_no_pending_operation(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())

    with pytest.raises(ProposalStaleError):
        orchestrator.confirm_proposal(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="user",
            current_context_fingerprint="ctx-changed",
            current_active_head_run_id="run-1",
        )

    assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "stale"
    assert orchestrator.operation_store.list_records() == []


def test_proposal_and_confirmation_are_persisted_as_typed_session_messages(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )

    entries = orchestrator.repository.get_branch("chain-session")
    assert [entry.entry_type for entry in entries] == ["custom_message", "custom_message"]
    assert [entry.payload["message_type"] for entry in entries] == [
        "operation_proposal",
        "operation_confirmation",
    ]
    event_types = [event.event_type for event in orchestrator.events.replay("chain-session")]
    assert event_types == [
        "proposal_ready",
        "needs_confirmation",
        "proposal_confirmed",
    ]


def test_proposal_api_is_async_safe_when_confirmation_calls_are_repeated(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())

    async def confirm_twice():
        return await asyncio.gather(
            asyncio.to_thread(
                orchestrator.confirm_proposal,
                proposal.proposal_id,
                revision=proposal.revision,
                fingerprint=proposal.fingerprint,
                actor_type="user",
                current_context_fingerprint="ctx-1",
                current_active_head_run_id="run-1",
            ),
            asyncio.to_thread(
                orchestrator.confirm_proposal,
                proposal.proposal_id,
                revision=proposal.revision,
                fingerprint=proposal.fingerprint,
                actor_type="user",
                current_context_fingerprint="ctx-1",
                current_active_head_run_id="run-1",
            ),
        )

    first, second = asyncio.run(confirm_twice())
    assert first.record_id == second.record_id
    assert len(orchestrator.operation_store.list_records()) == 1


def test_operation_record_state_is_append_only_and_cannot_move_backwards(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )

    completed = orchestrator.operation_store.append_status(
        record.record_id,
        "completed",
        outputs={"child_run_id": "run-2"},
    )
    assert completed.status == "completed"
    assert completed.outputs == {"child_run_id": "run-2"}

    with pytest.raises(OperationRecordTransitionError):
        orchestrator.operation_store.append_status(record.record_id, "pending")

    assert len((tmp_path / "workbench" / "operation-records" / f"{record.record_id}.jsonl").read_text().splitlines()) == 2


def test_operation_record_idempotency_does_not_depend_on_dispatch_command_id(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    confirmation = orchestrator.proposal_store.confirm(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )

    first = orchestrator.operation_store.create_pending(confirmation, command_id="cmd-a")
    second = orchestrator.operation_store.create_pending(confirmation, command_id="cmd-b")

    assert first.record_id == second.record_id
    assert len(orchestrator.operation_store.list_records()) == 1


def test_operation_registry_rejects_unregistered_mutations_before_session_write(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    invalid = {**proposal_kwargs(), "operation_id": "arbitrary.file_write"}

    with pytest.raises(UnknownOperationError):
        orchestrator.create_proposal(**invalid)

    assert orchestrator.repository.get_branch("chain-session") == []


def test_operation_registry_can_extend_with_explicit_definition() -> None:
    registry = OperationRegistry()
    registry.register(
        OperationDefinition(
            operation_id="report.generate",
            operation_version="v1",
            effect_level="read_only",
            scope_requirements=("chain",),
        )
    )

    definition = registry.require("report.generate", "v1")
    assert definition.effect_level == "read_only"


def test_workbench_propose_operation_tool_creates_proposal_only(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)
    tool_registry = orchestrator.tool_registry("chain-a")

    result = asyncio.run(
        tool_registry.execute(
            {
                "tool_call_id": "call-proposal-1",
                "tool_id": "propose_operation",
                "arguments": {
                    key: value
                    for key, value in proposal_kwargs().items()
                    if key not in {"chain_id", "command_id"}
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    assert result.output["requires_confirmation"] is True
    assert result.output["proposal"]["operation_id"] == "model.rerun"
    assert orchestrator.operation_store.list_records() == []
    assert orchestrator.proposal_store.latest_status(result.output["proposal"]["proposal_id"]) == "pending"


class SuccessfulRerunExecutor:
    def __init__(self) -> None:
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return RerunExecutionResult(
            target_run_id="run-child",
            outputs={"status": "completed"},
        )


class SubmittedRerunExecutor:
    def __init__(self) -> None:
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return RerunExecutionResult(
            target_run_id="run-child",
            outputs={"status": "running"},
        )


class FailingRerunExecutor:
    def __init__(self) -> None:
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        raise RuntimeError("rerun failed")


def test_confirmed_proposal_creates_child_branch_and_is_idempotent(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    source_leaf_id = orchestrator.repository.get_metadata("chain-session")["leaf_entry_id"]
    executor = SuccessfulRerunExecutor()

    completed = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=executor,
        )
    )

    assert completed.status == "completed"
    assert completed.outputs["target_run_id"] == "run-child"
    assert len(executor.requests) == 1
    child_chain_id = completed.execution["child_chain_id"]
    fork_id = completed.execution["fork_id"]
    child_session_id = completed.execution["child_session_id"]
    chain_store = ChainStore(tmp_path / "workbench")
    fork_store = ForkStore(tmp_path / "workbench")
    assert chain_store.get(child_chain_id)["source_run_id"] == "run-1"
    assert chain_store.get(child_chain_id)["active_head_run_id"] == "run-child"
    assert fork_store.get(fork_id)["child_chain_id"] == child_chain_id
    assert orchestrator.repository.get_metadata(child_session_id)["chain_id"] == child_chain_id
    child_branch = orchestrator.repository.get_branch(child_session_id)
    assert child_branch[-1].parent_ref == EntryRef("chain-session", source_leaf_id)

    duplicate = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=executor,
        )
    )
    assert duplicate == completed
    assert len(executor.requests) == 1


def test_confirmed_proposal_rechecks_preconditions_before_creating_branch(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    executor = SuccessfulRerunExecutor()

    with pytest.raises(ProposalStaleError):
        asyncio.run(
            orchestrator.execute_confirmed_proposal(
                record.record_id,
                current_context_fingerprint="ctx-changed",
                current_active_head_run_id="run-1",
                executor=executor,
            )
        )

    assert orchestrator.operation_store.get(record.record_id).status == "pending"
    assert len(executor.requests) == 0
    assert not list((tmp_path / "workbench" / "chains").glob("*.json"))
    assert not list((tmp_path / "workbench" / "forks").glob("*.json"))


def test_confirmed_proposal_records_executor_failure_and_is_idempotent(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    executor = FailingRerunExecutor()

    failed = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=executor,
        )
    )

    assert failed.status == "failed"
    assert failed.error == {"type": "RuntimeError"}
    assert len(executor.requests) == 1
    chain_store = ChainStore(tmp_path / "workbench")
    fork_store = ForkStore(tmp_path / "workbench")
    assert chain_store.get(failed.execution["child_chain_id"])["status"] == "failed"
    assert fork_store.get(failed.execution["fork_id"])["status"] == "failed"
    child_entries = orchestrator.repository.get_branch(failed.execution["child_session_id"])
    assert child_entries[-1].payload["message_type"] == "operation_result"
    assert child_entries[-1].payload["operation_result"]["status"] == "failed"

    duplicate = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=executor,
        )
    )
    assert duplicate == failed
    assert len(executor.requests) == 1


def test_submitted_child_is_reconciled_before_operation_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconciliation_calls = []

    class CompletedRerunService:
        def __init__(self, project_root: Path) -> None:
            assert project_root == (tmp_path / "project").resolve()

        def reconcile_submission(self, request):
            reconciliation_calls.append(request)
            return type(
                "Reconciliation",
                (),
                {
                    "status": "completed",
                    "target_run_id": "run-child",
                    "outputs": {"status": "completed", "target_run_id": "run-child"},
                    "diff_ref": {"kind": "input_diff", "source_run_id": "run-1"},
                    "verification": {"passed": True, "checks": {"rerun_of": True}},
                    "error": None,
                },
            )()

    monkeypatch.setattr(
        "workbench.agent.orchestrator.RerunService", CompletedRerunService
    )
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )

    submitted = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=SubmittedRerunExecutor(),
        )
    )
    assert submitted.status == "running"
    assert submitted.outputs["target_run_id"] == "run-child"

    completed = asyncio.run(
        orchestrator.reconcile_confirmed_proposal(
            record.record_id,
            project_root=tmp_path / "project",
        )
    )

    assert completed.status == "completed"
    assert completed.verification["passed"] is True
    assert completed.diff_ref == {
        "kind": "input_diff",
        "source_run_id": "run-1",
    }
    assert len(reconciliation_calls) == 1
    assert reconciliation_calls[0].target_run_id == "run-child"
    assert orchestrator.chain_store.get(completed.execution["child_chain_id"])["status"] == "active"
    assert orchestrator.fork_store.get(completed.execution["fork_id"])["status"] == "active"


def test_reconciled_child_failure_marks_operation_and_branch_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedRerunService:
        def __init__(self, project_root: Path) -> None:
            assert project_root == (tmp_path / "project").resolve()

        def reconcile_submission(self, request):
            return type(
                "Reconciliation",
                (),
                {
                    "status": "failed",
                    "target_run_id": "run-child",
                    "outputs": {"status": "failed", "target_run_id": "run-child"},
                    "diff_ref": None,
                    "verification": {"passed": False},
                    "error": {"type": "ChildRunFailed", "status": "failed"},
                },
            )()

    monkeypatch.setattr(
        "workbench.agent.orchestrator.RerunService", FailedRerunService
    )
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    submitted = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=SubmittedRerunExecutor(),
        )
    )
    failed = asyncio.run(
        orchestrator.reconcile_confirmed_proposal(
            submitted.record_id,
            project_root=tmp_path / "project",
        )
    )

    assert failed.status == "failed"
    assert failed.error == {"type": "ChildRunFailed", "status": "failed"}
    assert orchestrator.chain_store.get(failed.execution["child_chain_id"])["status"] == "failed"
    assert orchestrator.fork_store.get(failed.execution["fork_id"])["status"] == "failed"


def test_recover_operations_reconciles_interrupted_child_without_resubmitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconciliation_calls = []

    class CompletedRerunService:
        def __init__(self, project_root: Path) -> None:
            assert project_root == (tmp_path / "project").resolve()

        def reconcile_submission(self, request):
            reconciliation_calls.append(request)
            return type(
                "Reconciliation",
                (),
                {
                    "status": "completed",
                    "target_run_id": "run-child",
                    "outputs": {"status": "completed", "target_run_id": "run-child"},
                    "diff_ref": {"kind": "input_diff", "source_run_id": "run-1"},
                    "verification": {"passed": True},
                    "error": None,
                },
            )()

    monkeypatch.setattr(
        "workbench.agent.orchestrator.RerunService", CompletedRerunService
    )
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    submitted = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=SubmittedRerunExecutor(),
        )
    )

    recovered = asyncio.run(
        orchestrator.recover_operations(project_root=tmp_path / "project")
    )

    assert recovered == [
        orchestrator.operation_store.get(submitted.record_id)
    ]
    assert recovered[0].status == "completed"
    assert len(reconciliation_calls) == 1

    recovered_again = asyncio.run(
        orchestrator.recover_operations(project_root=tmp_path / "project")
    )
    assert recovered_again == []
    assert len(reconciliation_calls) == 1


def test_recover_operations_fails_interrupted_submission_without_retry(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    orchestrator.operation_store.append_status(
        record.record_id,
        "submitted",
        execution={
            "source_run_id": "run-1",
            "source_node_ref": "model-ols",
            "source_session_id": "chain-session",
            "active_head_run_id": "run-1",
            "fork_id": "fork-missing",
            "child_chain_id": "chain-missing",
            "child_session_id": "session-missing",
        },
    )

    recovered = asyncio.run(
        orchestrator.recover_operations(project_root=tmp_path / "project")
    )

    assert len(recovered) == 1
    assert recovered[0].status == "failed"
    assert recovered[0].error == {"type": "ChildRunMissing", "phase": "submit"}
    assert not recovered[0].outputs
    evidence = orchestrator.repository.get_branch("chain-session")[-1]
    assert evidence.payload["message_type"] == "operation_result"
    assert evidence.payload["operation_result"]["error"] == {
        "type": "ChildRunMissing",
        "phase": "submit",
    }

    assert asyncio.run(
        orchestrator.recover_operations(project_root=tmp_path / "project")
    ) == []


def test_recover_operations_fails_when_recorded_child_is_missing(
    tmp_path: Path,
) -> None:
    orchestrator = make_orchestrator(tmp_path)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    submitted = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
            executor=SubmittedRerunExecutor(),
        )
    )

    recovered = asyncio.run(
        orchestrator.recover_operations(project_root=tmp_path / "project")
    )

    assert recovered[0].record_id == submitted.record_id
    assert recovered[0].status == "failed"
    assert recovered[0].error == {
        "type": "ChildRunMissing",
        "target_run_id": "run-child",
    }
    assert orchestrator.chain_store.get(
        recovered[0].execution["child_chain_id"]
    )["status"] == "failed"


@pytest.mark.parametrize("crash_point", ["after_child_effect", "after_domain_commit"])
def test_graph_fork_recovery_after_durable_lifecycle_crash_binds_one_effect(
    tmp_path: Path,
    crash_point: str,
) -> None:
    class CrashOnce:
        def __init__(self) -> None:
            self.triggered = False

        def hit(self, point: str, record) -> None:
            from workbench.agent.execution import InjectedOperationCrash

            if point == crash_point and not self.triggered:
                self.triggered = True
                raise InjectedOperationCrash(point)

    orchestrator = make_orchestrator(tmp_path)
    source_entry = orchestrator.repository.append(
        "chain-session",
        "custom_message",
        {"message_type": "agent_context", "content": "verified"},
    )
    proposal = orchestrator.create_proposal(
        chain_id="chain-a",
        operation_id="graph.fork",
        target={
            "run_id": "run-1",
            "node_ref": "model-ols",
            "node_hash": "node-hash-1",
            "forest_node_key": "node-hash-1",
            "source_session_entry_id": source_entry.entry_id,
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "ctx-1",
            "active_head_run_id": "run-1",
            "owner_resolution": "active_head_contains_node",
        },
        changes={"reason": "try another covariance"},
        evidence_refs=["graph:run-1:model-ols"],
        expected_effect=["create child Chain"],
        risks=["no child run yet"],
    )
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )
    orchestrator.failpoint = CrashOnce()

    from workbench.agent.execution import InjectedOperationCrash

    with pytest.raises(InjectedOperationCrash):
        asyncio.run(
            orchestrator.execute_confirmed_fork(
                record.record_id,
                current_context_fingerprint="ctx-1",
                current_active_head_run_id="run-1",
            )
        )

    restarted = WorkbenchOrchestrator(
        orchestrator.repository,
        orchestrator.events,
        main_session_id="main-session",
    )
    recovered = asyncio.run(
        restarted.recover_operations(project_root=tmp_path / "project")
    )[0]

    assert recovered.status == "completed"
    assert recovered.execution["bindings"]["fork_id"] == recovered.execution["fork_id"]
    assert len(restarted.fork_store.list_records()) == 1
    assert len(restarted.chain_store.list_records()) == 1
    child_entries = restarted.repository.get_branch(
        recovered.execution["child_session_id"]
    )
    assert len(
        [
            entry
            for entry in child_entries
            if entry.payload.get("message_type") == "fork_context"
        ]
    ) == 1


def test_model_rerun_executor_adapts_proposal_changes_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    class RecordingRerunService:
        def __init__(self, project_root: Path) -> None:
            assert project_root == (tmp_path / "project").resolve()

        def submit(self, request):
            captured.append(request)
            return type("Result", (), {"run_id": "run-child", "status": "running"})()

    monkeypatch.setattr(
        "workbench.agent.orchestrator.RerunService", RecordingRerunService
    )
    orchestrator = make_orchestrator(tmp_path)
    executor = orchestrator.model_rerun_executor(tmp_path / "project")

    result = asyncio.run(
        executor(
            RerunExecutionRequest(
                operation_id="model.rerun",
                operation_version="v1",
                operation_record_id="oprec-1",
                proposal_id="proposal-1",
                source_chain_id="chain-a",
                source_session_id="chain-session",
                source_run_id="run-1",
                source_node_ref="model-ols",
                context_version="node-operation-context/v1",
                context_fingerprint="ctx-1",
                owner_run_id="run-1",
                op_node_id="model-ols",
                node_hash="node-hash-1",
                forest_node_key="node-hash-1",
                owner_resolution="active_head_contains_node",
                active_head_run_id="run-1",
                changes={
                    "covariance": {"old": "nonrobust", "new": "HC3"},
                    "x": {"old": ["x1", "x2"], "new": ["x1"]},
                },
                fork_id="fork-1",
                child_chain_id="chain-child",
                child_session_id="session-child",
            )
        )
    )

    assert result == RerunExecutionResult(
        target_run_id="run-child",
        outputs={"status": "running"},
    )
    request = captured[0]
    assert request.op_overrides == {"covariance": "HC3", "x": ["x1"]}
    assert request.rerun_from == {
        "owner_run_id": "run-1",
        "op_node_id": "model-ols",
        "node_hash": "node-hash-1",
        "forest_node_key": "node-hash-1",
    }
    assert request.workbench_context == {
        "operation_id": "model.rerun",
        "operation_version": "v1",
        "operation_record_id": "oprec-1",
        "proposal_id": "proposal-1",
        "source_chain_id": "chain-a",
        "source_session_id": "chain-session",
        "source_run_id": "run-1",
        "source_node_ref": "model-ols",
        "context_version": "node-operation-context/v1",
        "context_fingerprint": "ctx-1",
        "owner_run_id": "run-1",
        "op_node_id": "model-ols",
        "node_hash": "node-hash-1",
        "forest_node_key": "node-hash-1",
        "owner_resolution": "active_head_contains_node",
        "active_head_run_id": "run-1",
        "fork_id": "fork-1",
        "child_chain_id": "chain-child",
        "child_session_id": "session-child",
    }
