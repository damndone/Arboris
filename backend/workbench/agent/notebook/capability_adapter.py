"""CF4 domain execution under the common policy, approval and operation lifecycle."""
from __future__ import annotations

import asyncio
import hashlib
import json

from ...jsonl_store import read_jsonl
from ...operation_approvals import OperationApprovalStore
from ..events import AgentEventStream
from ..execution import ChainExecutionLease, OperationEffect
from ..operation_requests import OperationRequest
from ..orchestration_operation_handler import _OrchestratorOperationHandler
from ..session import JsonlSessionRepository
from .errors import OptionExecutionGatewayUnavailable


def capability_proposal_id(notebook_id, option_id, revision):
    identity = hashlib.sha256(json.dumps([notebook_id, option_id, revision.option_revision,
                                         revision.typed_proposal_id, revision.typed_proposal_revision]).encode()).hexdigest()
    return f"proposal_capability_{identity}"


def prepare_operation(service, notebook_id, option_id):
    from ..orchestrator import WorkbenchOrchestrator

    view = service.store.read_option(notebook_id, option_id)
    typed, revision = view.current_stored_revision.proposal, view.current_revision
    repository = JsonlSessionRepository(service.project_root / "workbench")
    session_id, chain_id = f"agent_notebook_{notebook_id}", f"notebook:{notebook_id}"
    try:
        repository.get_metadata(session_id)
    except KeyError:
        repository.create_session(session_id, chain_id=chain_id, role="chain")
    orchestrator = WorkbenchOrchestrator(repository, AgentEventStream(repository.root),
        main_session_id=session_id, operation_registry=service.registry)
    proposal_id = capability_proposal_id(notebook_id, option_id, revision)
    try:
        proposal = orchestrator.proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = orchestrator.admit_operation_request(OperationRequest(
            operation_id=typed.operation_id, operation_version=typed.operation_version,
            target=typed.target, preconditions=typed.preconditions, changes=typed.changes,
            evidence_refs=(f"notebook:{notebook_id}:{option_id}",), expected_effect=(revision.rationale,),
            risks=revision.assumptions), chain_id=chain_id, session_id=session_id, proposal_id=proposal_id).proposal
    record = orchestrator.confirm_proposal(proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type="human_ui",
        current_context_fingerprint=typed.preconditions.get("context_fingerprint"),
        current_active_head_run_id=typed.preconditions.get("active_head_run_id"))
    record = orchestrator.operation_store.append_status(record.record_id, record.status,
        execution={**record.execution, "capability_notebook_id":notebook_id,
                   "capability_option_id":option_id, "capability_option_revision":revision.option_revision})
    return orchestrator, record


def confirm_and_execute(service, notebook_id, option_id, *, context, trace, operation_record=None):
    from ..orchestrator import WorkbenchOrchestrator
    from ...capability_factory.notebook_bridge import NotebookExecutionDispatch

    if service.execution_gateway is None:
        raise OptionExecutionGatewayUnavailable("explicit capability execution is unavailable on this host",
            option_id=option_id, reason="trusted_execution_gateway_unavailable")
    if operation_record is None:
        orchestrator, record = prepare_operation(service, notebook_id, option_id)
    else:
        repository = JsonlSessionRepository(service.project_root / "workbench")
        orchestrator = WorkbenchOrchestrator(repository, AgentEventStream(repository.root),
            main_session_id=operation_record.agent_session_id, operation_registry=service.registry)
        record = orchestrator.operation_store.append_status(operation_record.record_id, operation_record.status,
            execution={**operation_record.execution, "capability_notebook_id":notebook_id,
                       "capability_option_id":option_id})
    record = asyncio.run(orchestrator.execute_confirmed_operation(record.record_id,
        project_root=service.project_root, current_context_fingerprint=record.preconditions.get("context_fingerprint"),
        current_active_head_run_id=record.preconditions.get("active_head_run_id"), notebook_service=service))
    raw = record.outputs.get("capability_dispatch")
    if raw is None:
        raise OptionExecutionGatewayUnavailable("The capability operation has no original dispatch receipt.",
            option_id=option_id, reason="original_dispatch_receipt_required")
    return NotebookExecutionDispatch(**raw)


class CapabilityOperationHandler(_OrchestratorOperationHandler):
    def __init__(self, *args, service, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = service

    async def validate(self, record):
        self.orchestrator.proposal_store.validate_confirmation_preconditions(record.proposal_id,
            current_context_fingerprint=self.current_context_fingerprint,
            current_active_head_run_id=self.current_active_head_run_id)
        notebook_id, option_id = record.execution["capability_notebook_id"], record.execution["capability_option_id"]
        typed = self.service.store.read_option(notebook_id, option_id).current_stored_revision.proposal
        comparable_preconditions = dict(record.preconditions)
        if "active_head_run_id" not in typed.preconditions:
            comparable_preconditions.pop("active_head_run_id", None)
        if (typed.operation_id, typed.target, typed.preconditions, typed.changes) != (
                record.operation_id, record.target, comparable_preconditions, record.changes):
            raise ValueError("capability option changed after operation approval")

    def acquire_domain_lease(self, record, *, execution_key):
        lease = ChainExecutionLease(self.orchestrator.repository.root, chain_id=record.chain_id,
            active_head_run_id=str(record.preconditions.get("active_head_run_id") or record.execution["capability_notebook_id"]),
            execution_key=execution_key)
        lease.acquire()
        return lease

    async def prepare(self, record, *, execution_key, failpoint):
        execution = dict(record.execution)
        if execution.get("capability_dispatch_started"):
            execution["bindings"] = {"capability_option_id":execution["capability_option_id"]}
        return OperationEffect(execution=execution, status="submitted")

    async def execute(self, record, *, execution_key, failpoint):
        notebook_id, option_id = record.execution["capability_notebook_id"], record.execution["capability_option_id"]
        record = self.orchestrator.operation_store.append_status(record.record_id, record.status,
            execution={**record.execution, "capability_dispatch_started":True})
        dispatch = await asyncio.to_thread(self.service._dispatch_capability_option, notebook_id, option_id,
            context=self.service.compile_context(notebook_id), operation_record=record)
        return self._dispatch_effect(record, dispatch.to_dict())

    def restore_receipt_binding(self, record):
        raw = self._original_receipt(record)
        if raw is None:
            return record
        return self.orchestrator.operation_store.append_status(record.record_id, record.status,
            execution={**record.execution, "bindings":{"capability_option_id":record.execution["capability_option_id"]}},
            outputs={**record.outputs, "capability_dispatch":raw})

    def _original_receipt(self, record):
        notebook_id, option_id = record.execution["capability_notebook_id"], record.execution["capability_option_id"]
        rows = read_jsonl(self.service.store._option_path(notebook_id, option_id))
        for row in reversed(rows):
            if (row.get("record_type") == "capability_dispatch_receipt"
                    and row.get("operation_record_id") == record.record_id
                    and row.get("approval_id") == record.execution["approval_id"]):
                return row["dispatch"]
        return None

    async def reconcile(self, record, *, execution_key, failpoint):
        raw = self._original_receipt(record)
        if raw is not None:
            return self._dispatch_effect(record, raw)
        return OperationEffect(status="running", execution=record.execution,
            error={"code":"CF4_ORIGINAL_DISPATCH_RECEIPT_REQUIRED"})

    def _dispatch_effect(self, record, dispatch):
        status = dispatch["status"]
        terminal = status in {"completed", "failed", "unsupported"}
        return OperationEffect(outputs={"capability_dispatch":dispatch, **({"target_run_id":dispatch["run_id"]} if dispatch.get("run_id") else {})}, execution=record.execution,
            bindings={"capability_option_id":record.execution["capability_option_id"]},
            status=("failed" if status == "unsupported" else status) if terminal else "running", verification={"passed":status == "completed"},
            error={"code":"CF4_" + status.upper()} if status in {"failed", "unsupported", "dispatch_unknown"} else None)

    async def commit_domain_state(self, record, *, execution_key, effect):
        return effect
