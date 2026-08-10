from __future__ import annotations

import asyncio

from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator, _workflow_failure_message
from workbench.agent.workflow_contracts import workflow_authorization
from workbench.agent.operations import OperationRecordStore
from workbench.agent.proposals import ProposalConfirmation
from workbench.agent.session import JsonlSessionRepository
from tests.workflow_fixtures import composed_plan, compile_fixture_workflow
from workbench.agent.workflow import WorkflowExecutionState, WorkflowStepState


def test_failed_workflow_error_preserves_step_diagnostics() -> None:
    """A failed workflow must tell the Agent which step and guard fired."""

    state = WorkflowExecutionState(
        workflow_id="wf-failed",
        plan_fingerprint="sha256:plan",
        status="failed",
        steps={
            "vif": WorkflowStepState(
                step_id="vif",
                fingerprint="sha256:step",
                status="failed",
                error=(
                    "P7 pack diagnostics.vif failed closed: "
                    "DIAGNOSTICS_INVALID_INPUT: missing model_metadata"
                ),
            )
        },
    )

    assert _workflow_failure_message(state) == (
        "workflow did not complete; failed steps: vif: "
        "P7 pack diagnostics.vif failed closed: "
        "DIAGNOSTICS_INVALID_INPUT: missing model_metadata"
    )


def test_workflow_authorization_is_explicit_and_auditable() -> None:
    binding = workflow_authorization(
        workflow_id="wf-1",
        confirmation_id="confirmation-1",
        step_id="step-8",
        plan_fingerprint="sha256:plan-1",
    )

    assert binding == {
        "workflow_id": "wf-1",
        "workflow_confirmation_id": "confirmation-1",
        "workflow_step_id": "step-8",
        "workflow_plan_fingerprint": "sha256:plan-1",
        "confirmation_mode": "single_workflow_confirmation",
    }


def test_child_operation_record_persists_workflow_authorization(tmp_path) -> None:
    authorization = workflow_authorization(
        workflow_id="wf-1",
        confirmation_id="confirmation-1",
        step_id="step-8",
        plan_fingerprint="sha256:plan-1",
    )
    confirmation = ProposalConfirmation(
        proposal_id="proposal-1",
        operation_id="statistical.explore",
        operation_version="v1",
        revision=1,
        fingerprint="sha256:proposal-1",
        session_id="session-1",
        chain_id="chain-1",
        command_id=None,
        target={"run_id": "run-1", "node_ref": "stage:raw", "artifact_id": "raw-1"},
        preconditions={"active_head_run_id": "run-1"},
        actor_type="workflow",
        confirmed_at="2026-07-25T00:00:00+00:00",
        status="confirmed",
    )

    record = OperationRecordStore(tmp_path).create_pending(
        confirmation,
        workflow_authorization=authorization,
    )

    assert record.workflow_id == "wf-1"
    assert record.workflow_confirmation_id == "confirmation-1"
    assert record.workflow_step_id == "step-8"
    assert record.workflow_plan_fingerprint == "sha256:plan-1"
    assert record.confirmation_mode == "single_workflow_confirmation"
    assert OperationRecordStore(tmp_path).get(record.record_id) == record


def test_completed_workflow_persists_authorized_child_records(tmp_path, monkeypatch) -> None:
    repository = JsonlSessionRepository(tmp_path)
    events = AgentEventStream(tmp_path)
    repository.create_session("main", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-1", role="chain")
    agent = AgentCore(repository, events, object(), session_id="chain-session")
    orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="main")
    orchestrator.register_chain("chain-1", "chain-session", agent)
    steps = composed_plan()
    draft = compile_fixture_workflow(
        workflow_id="wf-audit", source_fingerprint="ctx-1", steps=steps
    )
    state = WorkflowExecutionState(
        workflow_id=draft.workflow_id,
        plan_fingerprint=draft.plan_fingerprint,
        status="completed",
        steps={
            step.step_id: WorkflowStepState(
                step_id=step.step_id,
                fingerprint=step.fingerprint,
                status="completed",
                artifact_ids=(f"artifact-{step.step_id}",),
                row_counts={"source": 4110},
            )
            for step in draft.steps
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_compile_workflow_record",
        lambda record, project_root: draft,
    )
    import workbench.agent.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "execute_workflow", lambda root, compiled: state)
    proposal = orchestrator.create_proposal(
        chain_id="chain-1",
        operation_id="operation.multi_step",
        target=draft.target,
        preconditions=draft.preconditions,
        changes={"steps": steps},
        evidence_refs=["schema:raw-1"],
        expected_effect=[f"{len(steps)} workflow steps"],
        risks=["creates model runs and report artifacts"],
    )
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="ctx-1",
        current_active_head_run_id="run-1",
    )

    completed = asyncio.run(
        orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=tmp_path,
            current_context_fingerprint="ctx-1",
            current_active_head_run_id="run-1",
        )
    )

    assert completed.status == "completed"
    children = [item for item in orchestrator.operation_store.list_records() if item.record_id != record.record_id]
    assert len(children) == len(steps)
    assert all(item.workflow_id == "wf-audit" for item in children)
    assert all(item.workflow_confirmation_id == f"confirmation_{record.record_id}" for item in children)
    assert all(item.workflow_plan_fingerprint == draft.plan_fingerprint for item in children)
    assert all(item.execution["workflow_step_status"] == "completed" for item in children)
