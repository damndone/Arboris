"""agent fork routes: extracted HTTP responsibility."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from uuid import uuid4
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..agent.events import AgentEventStream
from ..agent.navigation import AgentNavigationRef
from ..contracts.common.errors import OperationValidationError
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.operation_requests import OperationRequest
from ..agent.session import EntryRef, JsonlSessionRepository
from ..api_errors import WorkbenchAPIError
from .responses.agent import ForkProposal
from .agent_route_context import (_authoritative_active_head, _context_serialized, _ensure_chain_scope, _ensure_main_session, _get_session, _project_root, _stores)
from .agent_route_proposals import (_public_proposal)
from .agent_route_requests import (AgentForkProposalRequest)

from fastapi import APIRouter
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

def _ensure_fork_source_session(
    root: Path,
    body: AgentForkProposalRequest,
    snapshot: dict[str, Any],
) -> tuple[JsonlSessionRepository, AgentEventStream, dict[str, Any], str]:
    """Resolve a chain session and a reachable source entry for a fork proposal."""

    if body.session_id:
        repository, events, metadata = _get_session(root, body.session_id)
        if metadata.get("role") != "chain":
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_FORK_SCOPE_INVALID",
                message="A graph fork proposal must belong to a Chain Agent session.",
                details={"session_id": body.session_id},
            )
        if body.chain_id and metadata.get("chain_id") != body.chain_id:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_FORK_SCOPE_INVALID",
                message="The Agent session is outside the requested Chain scope.",
                details={"session_id": body.session_id, "chain_id": body.chain_id},
            )
    else:
        repository, events = _stores(root)
        session_id = f"agent_chain_fork_{uuid4().hex}"
        chain_id = body.chain_id or f"chain:{body.source_run_id}"
        try:
            _authoritative_active_head(
                root,
                chain_id=chain_id,
                requested_active_head_run_id=body.active_head_run_id,
            )
        except WorkbenchAPIError as exc:
            if exc.code != "AGENT_CHAIN_NOT_MANAGED":
                raise
        metadata = repository.create_session(session_id, chain_id=chain_id, role="chain")
        _ensure_chain_scope(
            root,
            chain_id=chain_id,
            active_head_run_id=body.active_head_run_id,
            agent_session_id=session_id,
        )
        context = {
            "packet_version": "agent/fork-context/v1",
            "context_fingerprint": snapshot.get("context_fingerprint"),
            "source": {
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
                "active_head_run_id": body.active_head_run_id,
            },
        }
        serialized, fingerprint = _context_serialized(context)
        context_entry = repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "agent_context",
                "audience": "model",
                "name": "workbench_context",
                "content": (
                    "Workbench verified fork context. Do not invent graph facts.\n"
                    + serialized
                ),
                "metadata": {
                    "context_fingerprint": fingerprint,
                    "run_id": body.source_run_id,
                },
            },
        )
        events.emit(
            session_id,
            "session_created",
            {
                "role": "chain",
                "chain_id": chain_id,
                "run_id": body.source_run_id,
                "context_fingerprint": fingerprint,
            },
        )
        metadata = repository.get_metadata(session_id)
        if body.source_session_entry_id and body.source_session_entry_id != context_entry.entry_id:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_FORK_ENTRY_NOT_FOUND",
                message="The requested source Agent entry is not present in the new session.",
                details={"entry_id": body.source_session_entry_id},
            )

    source_entry_id = body.source_session_entry_id or metadata.get("leaf_entry_id")
    if not isinstance(source_entry_id, str) or not source_entry_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_FORK_ENTRY_NOT_FOUND",
            message="The Chain Agent session has no durable source entry.",
            details={"session_id": metadata.get("session_id")},
        )
    try:
        repository.get_entry(EntryRef(str(metadata["session_id"]), source_entry_id))
        branch_ids = {
            entry.entry_id for entry in repository.get_branch(str(metadata["session_id"]))
        }
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_FORK_ENTRY_NOT_FOUND",
            message="The source Agent entry is not reachable from the current Chain head.",
            details={"entry_id": source_entry_id},
        ) from exc
    if source_entry_id not in branch_ids:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_FORK_ENTRY_NOT_FOUND",
            message="The source Agent entry is not reachable from the current Chain head.",
            details={"entry_id": source_entry_id},
        )
    return repository, events, metadata, source_entry_id


@router.post("/agent/fork-proposals")
def create_agent_fork_proposal(
    project_root: str,
    body: AgentForkProposalRequest,
) -> ForkProposal:
    """Create a confirmation-gated graph.fork proposal from verified context."""

    root = _project_root(project_root)
    authoritative_active_head_run_id = body.active_head_run_id
    if body.session_id:
        _repository, _events, metadata = _get_session(root, body.session_id)
        authoritative_active_head_run_id = _authoritative_active_head(
            root,
            chain_id=str(metadata.get("chain_id")),
            requested_active_head_run_id=body.active_head_run_id,
        )
    try:
        snapshot = NodeOperationContextProvider(root).inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"fork-proposal:{body.source_run_id}:{body.source_node_ref}",
                owner_run_id=body.source_run_id,
                op_node_id=body.source_node_ref,
                active_head_run_id=authoritative_active_head_run_id,
            )
        )
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The graph node or active head could not be verified.",
            details={"run_id": body.source_run_id, "node_ref": body.source_node_ref},
        ) from exc

    repository, events, metadata, source_entry_id = _ensure_fork_source_session(
        root,
        body,
        snapshot,
    )
    session_id = str(metadata["session_id"])
    chain_id = str(metadata["chain_id"])
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    try:
        receipt = orchestrator.admit_operation_request(
            OperationRequest(
                operation_id="graph.fork",
                target={
                    "run_id": body.source_run_id,
                    "node_ref": body.source_node_ref,
                    "node_hash": snapshot["node_hash"],
                    "forest_node_key": snapshot["forest_node_key"],
                    "source_session_entry_id": source_entry_id,
                },
                preconditions={
                    "context_version": snapshot["context_version"],
                    "context_fingerprint": snapshot["context_fingerprint"],
                    "active_head_run_id": snapshot["active_head_run_id"],
                    "owner_resolution": snapshot["owner_resolution"],
                },
                changes={"reason": body.reason},
                evidence_refs=[
                    f"graph:{body.source_run_id}:{body.source_node_ref}",
                    f"agent_entry:{session_id}:{source_entry_id}",
                ],
                expected_effect=["create a durable child Chain and Agent session"],
                risks=["no child statistical run is submitted by graph.fork"],
            ),
            chain_id=chain_id,
            session_id=session_id,
        )
        proposal = receipt.proposal
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_PROPOSAL_INVALID",
            message="The graph fork proposal is not valid for this context.",
            details={"reason": str(exc)},
        ) from exc
    navigation = AgentNavigationRef(
        kind="proposal",
        id=proposal.proposal_id,
        label=f"Proposal {proposal.proposal_id}",
        relation="audit",
        available=True,
        href={
            "view": "agent",
            "session_id": session_id,
            "proposal_id": proposal.proposal_id,
            "run_id": body.source_run_id,
            "forest_node_key": snapshot["forest_node_key"],
        },
    )
    return {
        "session_id": session_id,
        "source_session_entry_id": source_entry_id,
        "proposal": _public_proposal(orchestrator.proposal_store, proposal.proposal_id),
        "navigation": navigation.to_dict(),
        "status": "pending",
    }

