"""agent operation routes: extracted HTTP responsibility."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..agent.context_tools import NodeOperationContextProvider
from ..analysis_loop.lifecycle import confirm_analysis_loop_proposal
from ..analysis_loop.plan import PlanBindingError
from ..analysis_loop.resolver import resolve_analysis_loop_inputs
from ..analysis_loop.storage import PlanDiffStore
from ..agent.operation_outcome import OUTCOME_NAME, TERMINAL as OUTCOME_TERMINAL, outcome as operation_outcome, outcome_text as operation_outcome_text, unfinished_outcomes
from ..agent.navigation import AgentNavigationProjector
from ..agent.operations import OperationRecordStore
from ..contracts.common.errors import OperationValidationError
from ..agent.execution import OperationClaimConflict
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..api_errors import WorkbenchAPIError
from .responses.agent import AgentOperationProjection, OperationReconciled, ProposalConfirmed, ProposalStatus
from .agent_route_context import (_authoritative_active_head, _ensure_main_session, _get_session, _project_root)
from .agent_route_permissions import (_grant_for_session)
from .agent_route_proposals import (_current_proposal_context_fingerprint, _proposal_for_session, _public_proposal)
from .agent_route_requests import (AgentProposalConfirmRequest, AgentProposalDeclineRequest, AgentProposalRevisionRequest)

from fastapi import APIRouter
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

@router.get("/agent/sessions/{session_id}/operations/{record_id}")
def get_agent_operation_projection(
    session_id: str,
    record_id: str,
    project_root: str,
) -> AgentOperationProjection:
    root = _project_root(project_root)
    repository, _events, metadata = _get_session(root, session_id)
    store = OperationRecordStore(repository.root)
    try:
        record = store.get(record_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Agent operation projection was not found.",
            details={"record_id": record_id},
        ) from exc
    if record.agent_session_id != session_id or record.chain_id != metadata.get("chain_id"):
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Agent operation projection was not found in this scope.",
            details={"record_id": record_id, "session_id": session_id},
        )
    projection = AgentNavigationProjector(root).operation(record_id)
    return {"operation": record.to_dict(), "projection": projection.to_dict()}


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/decline")
def decline_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalDeclineRequest | None = None,
) -> ProposalStatus:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = ProposalStore(repository.root)
    _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    try:
        decision = orchestrator.decline_proposal(
            proposal_id,
            actor_type="user",
            reason=body.reason if body is not None else None,
        )
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal is no longer declinable.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": _public_proposal(store, proposal_id),
        "status": decision.status,
    }


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/revise")
def revise_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalRevisionRequest,
) -> ProposalStatus:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = ProposalStore(repository.root)
    _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    try:
        revised = orchestrator.revise_proposal(
            proposal_id,
            base_revision=body.base_revision,
            changes=body.changes,
            expected_effect=body.expected_effect,
            risks=body.risks,
        )
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_PROPOSAL_INVALID",
            message="The revised proposal changes are not valid for this operation.",
            details={"proposal_id": proposal_id, "reason": str(exc)},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal revision is no longer current or editable.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": _public_proposal(store, revised.proposal_id),
        "status": "pending",
    }


async def _run_read_only_proposal(root: Path, orchestrator: WorkbenchOrchestrator, proposal,
                                  actor: str | None = None) -> Any:
    """Confirm and execute a read-only workflow under the read-only policy.

    The same checks as a user's confirmation -- current context fingerprint
    and authoritative active head -- with the policy as the actor, so the
    operation record says who allowed it."""

    from ..agent.read_only_policy import ACTOR

    active_head_run_id = _authoritative_active_head(
        root,
        chain_id=str(proposal.chain_id),
        requested_active_head_run_id=proposal.preconditions.get("active_head_run_id"),
    )
    fingerprint = _current_proposal_context_fingerprint(
        root, proposal, active_head_run_id=active_head_run_id
    )
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type=actor or ACTOR,
        current_context_fingerprint=fingerprint,
        current_active_head_run_id=active_head_run_id,
    )
    return await orchestrator.execute_confirmed_operation(
        record.record_id,
        project_root=root,
        current_context_fingerprint=fingerprint,
        current_active_head_run_id=active_head_run_id,
    )


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/confirm")
async def confirm_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalConfirmRequest,
) -> ProposalConfirmed:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = ProposalStore(repository.root)
    proposal = _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
    )
    authoritative_active_head_run_id = _authoritative_active_head(
        root,
        chain_id=str(proposal.chain_id),
        requested_active_head_run_id=body.active_head_run_id,
    )
    current_context_fingerprint = _current_proposal_context_fingerprint(
        root,
        proposal,
        active_head_run_id=authoritative_active_head_run_id,
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    is_analysis_loop = isinstance(proposal.preconditions.get("analysis_loop"), dict)
    try:
        if is_analysis_loop:
            cluster_variable = proposal.changes.get("entity_col")
            if type(cluster_variable) is not str or not cluster_variable:
                raise PlanBindingError(
                    "analysis-loop proposal has no exact cluster variable",
                    code="STALE_PLAN",
                )
            resolved = resolve_analysis_loop_inputs(
                root,
                run_id=str(proposal.target["run_id"]),
                cluster_variable=cluster_variable,
            )
            confirmed_payload_hash = (
                body.confirmed_payload_hash
                or proposal.preconditions.get("confirmed_payload_hash")
            )
            if type(confirmed_payload_hash) is not str or not confirmed_payload_hash:
                raise PlanBindingError(
                    "analysis-loop confirmation has no canonical payload hash",
                    code="CONFIRMED_PAYLOAD_MISMATCH",
                )
            record = confirm_analysis_loop_proposal(
                orchestrator=orchestrator,
                plan_store=PlanDiffStore(repository.root, create=False),
                proposal_id=proposal_id,
                current_source=resolved.source,
                current_source_context_fingerprint=current_context_fingerprint,
                current_active_head_run_id=authoritative_active_head_run_id,
                revision=body.revision,
                fingerprint=body.fingerprint,
                confirmed_payload_hash=confirmed_payload_hash,
            )
        else:
            record = orchestrator.confirm_proposal(
                proposal_id,
                revision=body.revision,
                fingerprint=body.fingerprint,
                actor_type="user",
                current_context_fingerprint=current_context_fingerprint,
                current_active_head_run_id=authoritative_active_head_run_id,
            )
    except PlanBindingError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code=exc.code,
            message=str(exc),
            details=getattr(exc, "details", {"proposal_id": proposal_id}),
        ) from exc
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal is stale and must be regenerated.",
            details={"proposal_id": proposal_id},
        ) from exc
    except (ProposalConfirmationError, KeyError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal revision or fingerprint is no longer confirmable.",
            details={"proposal_id": proposal_id},
        ) from exc
    if body.grant_session:
        _grant_for_session(repository, session_id, orchestrator, proposal)
    # Design §8.2: the user confirmation IS the execution gate. The registry
    # selects the request-independent operation handler; no model text
    # participates in execution.
    try:
        record = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=root,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=authoritative_active_head_run_id,
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal became stale before execution.",
            details={"proposal_id": proposal_id},
        ) from exc
    except OperationClaimConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_OPERATION_CONFLICT",
            message="Another confirmed operation is already executing against this Chain head.",
            details={"proposal_id": proposal_id},
        ) from exc
    _tell_agent_the_outcome(root, session_id, record.to_dict())
    return {
        "proposal": _public_proposal(store, proposal_id),
        "operation": record.to_dict(),
        "status": record.status,
    }


def _tell_agent_finished_outcomes(root: Path, session_id: str) -> None:
    """Before a turn: report operations that finished since the Agent was told
    they were still running (a confirmed rerun returns while it runs)."""

    try:
        repository, _events, _metadata = _get_session(root, session_id)
        pending = unfinished_outcomes(repository.get_branch(session_id))
    except (WorkbenchAPIError, KeyError, OSError, ValueError):
        return
    if not pending:
        return
    store = OperationRecordStore(root / "workbench", create=False)
    for record_id in pending:
        try:
            record = store.get(record_id).to_dict()
        except (KeyError, OSError, ValueError):
            continue
        if record.get("status") in OUTCOME_TERMINAL:
            _tell_agent_the_outcome(root, session_id, record)


def _tell_agent_the_outcome(root: Path, session_id: str, record: dict[str, Any]) -> None:
    """The Agent's next turn knows what its confirmed proposal produced."""

    facts = operation_outcome(root, record)
    try:
        repository, _events, _metadata = _get_session(root, session_id)
        repository.append(session_id, "custom_message", {
            "message_type": "agent_operation_result",
            "audience": "model",
            "name": OUTCOME_NAME,
            "content": operation_outcome_text(facts),
            "metadata": facts,
        })
    except (WorkbenchAPIError, KeyError, OSError, ValueError):
        # The execution is recorded in the ledger either way; the message is a courtesy.
        return


@router.post("/agent/sessions/{session_id}/operations/{record_id}/reconcile")
async def reconcile_agent_operation(
    session_id: str,
    record_id: str,
    project_root: str,
) -> OperationReconciled:
    """Idempotently reconcile one confirmed operation against its child run.

    Non-terminal children leave the record `running` unchanged; a terminal
    child produces the deterministic diff/verification, the completed (or
    failed) record, and the child chain/fork activation. Safe to poll.
    """
    root = _project_root(project_root)
    repository, events, _metadata = _get_session(root, session_id)
    store = OperationRecordStore(repository.root)
    try:
        record = store.get(record_id)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_OPERATION_NOT_FOUND",
            message="Agent operation record was not found in this project.",
            details={"record_id": record_id},
        ) from exc
    if record.agent_session_id != session_id:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_OPERATION_NOT_FOUND",
            message="Agent operation record was not found in this session.",
            details={"record_id": record_id, "session_id": session_id},
        )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    if record.operation_id != "graph.fork":
        record = await orchestrator.reconcile_confirmed_proposal(
            record_id, project_root=root
        )
    return {"operation": record.to_dict(), "status": record.status}

