"""Forward confirmed Notebook workflows to the Agent operation lifecycle."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..chains import ensure_chain_root
from ..events import AgentEventStream
from ..operation_requests import OperationRequest
from ..operations import OperationRecord
from ..session import JsonlSessionRepository
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowExecutionState, WorkflowStateStore


@dataclass(frozen=True)
class NotebookWorkflowOperation:
    operation: OperationRecord
    state: WorkflowExecutionState


def execute_workflow_option(service, *, notebook, option_id, revision, proposal, workflow: WorkflowDraft, operation_record=None):
    """Notebook owns source/option approval; the common lifecycle owns effects."""
    from ..orchestrator import WorkbenchOrchestrator

    root = service.project_root
    repository = JsonlSessionRepository(root / "workbench")
    if operation_record is None:
        session_id = f"agent_notebook_{notebook.notebook_id}"
        chain_id = f"notebook:{notebook.notebook_id}"
        try:
            repository.get_metadata(session_id)
        except KeyError:
            repository.create_session(session_id, chain_id=chain_id, role="chain")
    else:
        session_id, chain_id = operation_record.agent_session_id, operation_record.chain_id
    orchestrator = WorkbenchOrchestrator(repository, AgentEventStream(repository.root),
        main_session_id=session_id, operation_registry=service.registry)
    if operation_record is None:
        source_run_id = str(proposal.target["run_id"])
        ensure_chain_root(repository.root, runs_root=root / "runs", chain_id=chain_id,
                          active_head_run_id=source_run_id, agent_session_id=session_id)
        admitted = orchestrator.admit_operation_request(
            OperationRequest(operation_id=proposal.operation_id, operation_version=proposal.operation_version,
                target=proposal.target, preconditions=proposal.preconditions, changes=proposal.changes,
                evidence_refs=(f"notebook:{notebook.notebook_id}:{option_id}:v{revision.option_revision}",),
                expected_effect=("Execute the explicitly confirmed Notebook workflow.",), risks=()),
            chain_id=chain_id, session_id=session_id,
            proposal_id=f"proposal_notebook_{workflow.workflow_id}",
        ).proposal
        record = orchestrator.confirm_proposal(admitted.proposal_id, revision=admitted.revision,
            fingerprint=admitted.fingerprint, actor_type="human_ui",
            current_context_fingerprint=admitted.preconditions.get("context_fingerprint"),
            current_active_head_run_id=admitted.preconditions.get("active_head_run_id"))
    else:
        record = operation_record
    record = orchestrator.operation_store.append_status(record.record_id, record.status,
        execution={**record.execution, "workflow_id":workflow.workflow_id,
                   "workflow_bindings":workflow.bindings})
    record = asyncio.run(orchestrator.execute_confirmed_operation(record.record_id, project_root=root,
        current_context_fingerprint=record.preconditions.get("context_fingerprint"),
        current_active_head_run_id=record.preconditions.get("active_head_run_id")))
    state = WorkflowStateStore(root, workflow.workflow_id).current()
    if state is None:
        raise WorkflowExecutionError("The confirmed operation produced no workflow state.")
    return NotebookWorkflowOperation(record, state)
