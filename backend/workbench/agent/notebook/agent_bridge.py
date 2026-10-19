"""Bind source-verified Notebook options to ordinary Agent proposal cards."""
from __future__ import annotations

import hashlib

from ..chains import ChainStore
from ..operation_requests import OperationRequest
from .errors import OptionRevisionStale
from .freshness import assert_executable
from ...contracts.agent.notebook_option import NotebookOptionRevisionV12


def publish_option(service, orchestrator, *, session_id, notebook_id, revision):
    notebook = service.get_notebook(notebook_id)
    view = service.store.read_option(notebook_id, revision.option_id)
    proposal = view.current_stored_revision.proposal
    source = notebook.projection_source
    uploaded = (source is not None and source.kind == "dataset" and source.workflow_source is not None
                and source.workflow_source.source_kind == "dataset_upload")
    if uploaded or (isinstance(revision, NotebookOptionRevisionV12) and revision.capability_resolution_binding_ref is not None):
        identity = hashlib.sha256(f"{session_id}:{notebook_id}".encode()).hexdigest()[:24]
        chain_id = f"notebook_source_{identity}"
        store = ChainStore(orchestrator.repository.root)
        existing = {item["chain_id"] for item in store.list_records()}
        if chain_id not in existing:
            store.create_root(chain_id=chain_id, run_family_id=notebook.run_family_id,
                active_head_run_id=str(proposal.preconditions.get("active_head_run_id") or proposal.target.get("run_id") or notebook_id), agent_session_id=session_id)
    else:
        chain_id = orchestrator._operation_chain(session_id, proposal.target)
    proposal_id = None
    if isinstance(revision, NotebookOptionRevisionV12) and revision.capability_resolution_binding_ref is not None:
        from .capability_adapter import capability_proposal_id
        proposal_id = capability_proposal_id(notebook_id, revision.option_id, revision)
    common = orchestrator.admit_operation_request(OperationRequest(
        operation_id=proposal.operation_id, operation_version=proposal.operation_version,
        target=proposal.target, preconditions={**proposal.preconditions, "active_head_run_id":orchestrator.chain_store.resolve_active_head(chain_id)}, changes=proposal.changes,
        evidence_refs=(f"notebook:{notebook_id}:{revision.option_id}",),
        expected_effect=(revision.rationale,), risks=tuple(revision.assumptions)),
        chain_id=chain_id, session_id=session_id, proposal_id=proposal_id).proposal
    orchestrator.repository.append(session_id, "custom_message", {
        "message_type":"notebook_operation_binding", "audience":"audit",
        "proposal_id":common.proposal_id, "notebook_id":notebook_id, "option_id":revision.option_id,
        "option_revision":revision.option_revision, "typed_proposal_id":revision.typed_proposal_id,
        "typed_proposal_revision":revision.typed_proposal_revision,
    })
    return common


def find_binding(repository, proposal):
    for entry in reversed(repository.get_branch(proposal.session_id)):
        payload = entry.payload
        if (entry.entry_type == "custom_message" and payload.get("message_type") == "notebook_operation_binding"
                and payload.get("proposal_id") == proposal.proposal_id):
            return payload
    return None


def current_binding_context(service, binding, proposal):
    """Recheck the actual option and source at the HTTP confirmation boundary."""
    notebook_id, option_id = binding["notebook_id"], binding["option_id"]
    view = service.store.read_option(notebook_id, option_id)
    revision, typed = view.current_revision, view.current_stored_revision.proposal
    comparable_preconditions = dict(proposal.preconditions)
    if "active_head_run_id" not in typed.preconditions:
        comparable_preconditions.pop("active_head_run_id", None)
    if (revision.option_revision != binding["option_revision"]
            or typed.proposal_id != binding["typed_proposal_id"]
            or typed.proposal_revision != binding["typed_proposal_revision"]
            or (typed.operation_id, typed.target, typed.preconditions, typed.changes) !=
               (proposal.operation_id, proposal.target, comparable_preconditions, proposal.changes)):
        raise OptionRevisionStale("The Notebook option changed after the Agent proposal was published.")
    context = service.compile_context(notebook_id)
    service._assert_current_recommendation_source(notebook_id, revision)
    service._assert_current_capability_binding(revision)
    assert_executable(revision, context)
    if typed.operation_id != "operation.multi_step":
        return context
    pin = service._workflow_source_pin(service.get_notebook(notebook_id), context)
    if pin["target"] != typed.target or pin["preconditions"] != typed.preconditions:
        raise OptionRevisionStale("The Notebook source changed after planning.")
    return context


def execute_binding(service, binding, record):
    view = service.store.read_option(binding["notebook_id"], binding["option_id"])
    if isinstance(view.current_revision, NotebookOptionRevisionV12) and view.current_revision.capability_resolution_binding_ref is not None:
        return service.confirm_and_execute(binding["notebook_id"], binding["option_id"],
            context=service.compile_context(binding["notebook_id"]), operation_record=record)
    return service.confirm_and_execute_workflow(binding["notebook_id"], binding["option_id"],
        option_revision=binding["option_revision"], proposal_id=binding["typed_proposal_id"],
        proposal_revision=binding["typed_proposal_revision"],
        context=service.compile_context(binding["notebook_id"]), operation_record=record)
