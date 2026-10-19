"""agent route proposals: extracted HTTP responsibility."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..agent.proposals import ProposalStore
from ..api_errors import WorkbenchAPIError
from ..agent.proposal_text import proposal_lines
from .agent_route_context import (_authoritative_active_head)
from .agent_route_projection import (_proposal_labels)

def _proposal_for_session(
    store: ProposalStore,
    *,
    proposal_id: str,
    session_id: str,
    chain_id: str | None,
):
    try:
        proposal = store.latest_revision(proposal_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_PROPOSAL_NOT_FOUND",
            message="Agent proposal was not found in this project.",
            details={"proposal_id": proposal_id},
        ) from exc
    if proposal.session_id != session_id or (
        chain_id is not None and proposal.chain_id != chain_id
    ):
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_PROPOSAL_NOT_FOUND",
            message="Agent proposal was not found in this session.",
            details={"proposal_id": proposal_id, "session_id": session_id},
        )
    return proposal


def _public_proposal(store: ProposalStore, proposal_id: str) -> dict[str, Any]:
    revision = store.latest_revision(proposal_id)
    proposal = revision.to_dict()
    proposal["status"] = store.latest_status(proposal_id)
    # What it will do, in sentences with the data's own variable labels; the
    # raw changes stay beside it for anyone who wants to check them.
    proposal["readable"] = proposal_lines(proposal, _proposal_labels(store, proposal))
    confirmation = store.latest_confirmation(proposal_id)
    if confirmation is not None:
        proposal["confirmation"] = confirmation.to_dict()
    decision = store.latest_decision(proposal_id)
    if decision is not None:
        proposal["decision"] = decision.to_dict()
    return proposal


def _current_data_columns_cast_fingerprint(root: Path, proposal) -> str:
    """Re-derive a data cast's *preview* fingerprint before confirmation.

    For model.rerun/graph.fork the freshness identity is the node-operation
    context (`nocv1:…`). A data cast's identity is its preview over the real
    data, so re-previewing here is the same check, expressed in this
    operation's own vocabulary — and it is the same fingerprint the manual UI
    path confirms against.
    """

    from ..data_operations import (
        DataCastItem,
        DataColumnCastValidationError,
        DataColumnsCastSpecV1,
        preview_data_columns_cast,
    )

    target = proposal.target
    try:
        spec = DataColumnsCastSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            casts=tuple(
                DataCastItem(str(item["column"]), str(item["target_dtype"]))
                for item in target["casts"]
            ),
            output_format=str(target.get("output_format", "csv")),
        )
        preview = preview_data_columns_cast(root, spec)
    except (DataColumnCastValidationError, KeyError, OSError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal target or source data changed before confirmation.",
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The cast preview has blocking conversion failures.",
            details={
                "proposal_id": proposal.proposal_id,
                "blocked_columns": [
                    item.column for item in preview.items if item.status != "ready"
                ],
            },
        )
    return preview.fingerprint


def _current_proposal_context_fingerprint(
    root: Path,
    proposal,
    *,
    active_head_run_id: str,
    notebook_service=None,
) -> str:
    """Re-derive the current node context before creating a confirmation record."""

    active_head_run_id = _authoritative_active_head(
        root,
        chain_id=str(proposal.chain_id),
        requested_active_head_run_id=active_head_run_id,
    )
    from ..agent.session import JsonlSessionRepository
    from ..agent.notebook.agent_bridge import find_binding, current_binding_context
    from ..agent.notebook import NotebookService
    from ..agent.notebook.errors import NotebookOptionError
    from ..lineage.upload_store import UploadHashMismatch, UploadBlobMissing

    binding = find_binding(JsonlSessionRepository(root / "workbench", create=False), proposal)
    if binding is not None:
        try:
            current_binding_context(notebook_service or NotebookService(root), binding, proposal)
        except NotebookOptionError as exc:
            raise WorkbenchAPIError(status_code=exc.status_code, code=exc.code,
                message=str(exc), details=exc.details) from exc
        except (UploadHashMismatch, UploadBlobMissing) as exc:
            raise WorkbenchAPIError(status_code=409, code="AGENT_PROPOSAL_STALE",
                message="The uploaded Notebook source changed or is unavailable.",
                details={"proposal_id":proposal.proposal_id}) from exc
        return str(proposal.preconditions["context_fingerprint"])
    if proposal.operation_id == "data.columns.cast":
        return _current_data_columns_cast_fingerprint(root, proposal)
    if proposal.operation_id not in {"model.rerun", "metadata.edit", "graph.fork", "operation.multi_step"}:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_PROPOSAL_OPERATION_UNSUPPORTED",
            message="This Agent endpoint does not confirm this operation.",
            details={"operation_id": proposal.operation_id},
        )
    target = proposal.target
    try:
        snapshot = NodeOperationContextProvider(root).inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"confirm:{proposal.proposal_id}",
                owner_run_id=str(target["run_id"]),
                op_node_id=str(target["node_ref"]),
                active_head_run_id=active_head_run_id,
            )
        )
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal target or active head changed before confirmation.",
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    if target.get("node_hash") is not None and snapshot.get("node_hash") != target.get("node_hash"):
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal target changed before confirmation.",
            details={"proposal_id": proposal.proposal_id, "reason": "node_hash"},
        )
    fingerprint = snapshot.get("context_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The current proposal context could not be verified.",
            details={"proposal_id": proposal.proposal_id},
        )
    return fingerprint

