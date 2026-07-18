"""HTTP seam for the project-scoped Workbench Agent surface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from ..agent.analysis_loop_driver import forward_analysis_intent
from ..agent.context_tools import (
    AnalysisLoopContextError,
    inspect_analysis_loop_context,
    parse_analysis_loop_packet_payloads,
)
from ..agent.chains import (
    ChainHeadConflict,
    ChainHeadUnavailable,
    ChainStore,
    ensure_chain_root,
)
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..analysis_loop.compare import ComparePacket
from ..analysis_loop.lifecycle import (
    AnalysisLoopProposalError,
    confirm_analysis_loop_proposal,
    create_analysis_loop_proposal,
)
from ..analysis_loop.plan import PlanBindingError, PlanDiff, PlanValidationError
from ..analysis_loop.recovery import RECOVERY_ACTIONS
from ..analysis_loop.resolver import (
    AnalysisLoopSourceResolutionError,
    resolve_analysis_loop_inputs,
    resolve_analysis_loop_run,
)
from ..analysis_loop.storage import (
    ComparePacketStore,
    PlanDiffStore,
    ValidationPacketStore,
)
from ..analysis_loop.validation import ValidationPacket
from ..agent.core import AgentCore
from ..agent.events import AgentEventStream
from ..agent.model import OpenAICompatibleModelAdapter
from ..agent.navigation import AgentNavigationProjector, AgentNavigationRef
from ..agent.operations import (
    OperationRecordStore,
    OperationRegistry,
    OperationValidationError,
)
from ..agent.execution import OperationClaimConflict
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..agent.session import EntryRef, JsonlSessionRepository
from ..api_errors import WorkbenchAPIError
from ..control_plane import control_plane_capability
from ..llm.config import load_llm_config

router = APIRouter()

MAX_CONTEXT_CHARS = 24_000
MAX_QUESTION_CHARS = 4_000
# One step = one provider call. A read-only inspection sweep is typically
# question → 5 inspect tools → summary, so 4 blocked legitimate turns in the
# live DeepSeek smoke; 8 leaves headroom without unbounding the loop.
DEFAULT_MAX_STEPS = 8
DEFAULT_TIMEOUT_S = 120.0

CHAIN_AGENT_PROTOCOL = """Workbench Chain Agent workflow protocol (agent/v1):
- Read-only inspection tools are the evidence source for this turn.
- When the user asks for an OLS conventional-to-clustered Analysis Loop proposal, call propose_analysis_loop with the exact source_run_id, source_node_ref, active_head_run_id, cluster_variable, and (when supplied) result_id. This typed tool resolves the source facts and creates the PlanDiff binding.
- For other registered mutations, you must call propose_operation with a complete structured payload; a JSON or Markdown proposal in ordinary text is not a submitted proposal.
- propose_operation creates a reviewable pending proposal only; it does not execute a Workbench mutation. Never claim that a run, graph, or data change was executed from this tool.
- propose_analysis_loop also creates a reviewable pending proposal only; it never confirms or executes the rerun.
- Use the exact operation_id and operation_version returned by inspect_operation_contract. For model.rerun, target contains run_id, node_ref, node_hash, and forest_node_key; map the inspection field op_node_id to node_ref, and do not put active_head_run_id in target. For graph.fork, the backend binds target.source_session_entry_id to the current Chain leaf; do not invent an Agent entry id. In preconditions, include exactly context_version, context_fingerprint, active_head_run_id, and owner_resolution.
- graph.fork creates a durable fork, child Chain, and child Agent session after confirmation. It does not submit a child statistical run and does not automatically continue with model.rerun.
- Include changes as the requested field-level change (prefer {"old": ..., "new": ...}), plus evidence_refs, expected_effect, and risks.
- Never copy a displayed editable-schema value or model narrative as the source fact when a typed Analysis Loop tool returns canonical source facts, PlanDiff, and expected invariants; explain only those backend-owned facts.
- If evidence or a required field is missing, inspect more or explain what is missing instead of inventing it.
"""


def _chain_agent_protocol(registry: OperationRegistry) -> str:
    """Add the registry's current executable operation ids to the protocol."""

    operation_ids = registry.natural_language_operation_ids(
        scope_requirements=("chain", "active_head")
    )
    return (
        CHAIN_AGENT_PROTOCOL
        + "- The currently registered executable operation ids are: "
        + ", ".join(operation_ids)
        + ". Do not propose an id outside this registry.\n"
        + "- For an unsupported request, explain the boundary explicitly; never translate it into a nearby operation.\n"
    )


class AgentSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["main", "chain"] = "chain"
    chain_id: str | None = None
    run_id: str | None = None
    context_packet: dict[str, Any] = Field(default_factory=dict)


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class AgentProposalConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    fingerprint: str = Field(min_length=1)
    active_head_run_id: str = Field(min_length=1)
    confirmed_payload_hash: str | None = Field(default=None, min_length=1)


class AgentProposalDeclineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1_000)


class AgentProposalRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(gt=0)
    changes: dict[str, Any]
    expected_effect: list[str] | None = None
    risks: list[str] | None = None


class AgentForkProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    chain_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_ref: str = Field(min_length=1, max_length=300)
    source_session_entry_id: str | None = Field(default=None, min_length=1, max_length=200)
    active_head_run_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(
        default="Fork from verified graph context",
        min_length=1,
        max_length=1_000,
    )


class AnalysisLoopContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Keep this a string so the domain seam, rather than FastAPI's generic
    # validation error, owns the stable machine-readable scope code.
    scope: str = Field(min_length=1, max_length=32)
    source_context: dict[str, Any] = Field(default_factory=dict)
    plan_diff: dict[str, Any] | None = None
    validation_packet: dict[str, Any] | None = None
    compare_packet: dict[str, Any] | None = None


class AnalysisLoopIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # This is deliberately untrusted input. The route only classifies and
    # returns it; it never turns it into a proposal or operation record.
    intent: dict[str, Any] = Field(default_factory=dict)


class AnalysisLoopProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_ref: str = Field(min_length=1, max_length=300)
    active_head_run_id: str = Field(min_length=1, max_length=200)
    cluster_variable: str = Field(min_length=1, max_length=200)
    result_id: str | None = Field(default=None, min_length=1, max_length=300)


def _project_root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _stores(root: Path) -> tuple[JsonlSessionRepository, AgentEventStream]:
    # Design §10.1: all Agent-managed metadata (sessions, events, and later
    # chains/forks/operation-records) lives under the project-local
    # `workbench/` namespace, kept out of the runs/graph scanners' inputs.
    storage_root = root / "workbench"
    return JsonlSessionRepository(storage_root), AgentEventStream(storage_root)


def _context_active_head(packet: dict[str, Any]) -> str | None:
    direct = packet.get("active_head_run_id")
    if isinstance(direct, str) and direct:
        return direct
    ownership = packet.get("ownership")
    if isinstance(ownership, dict):
        nested = ownership.get("active_head_run_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _ensure_chain_scope(
    root: Path,
    *,
    chain_id: str,
    active_head_run_id: str,
    agent_session_id: str,
) -> dict[str, Any]:
    try:
        return ensure_chain_root(
            root / "workbench",
            runs_root=root / "runs",
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=agent_session_id,
        )
    except ChainHeadConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CHAIN_SCOPE_CONFLICT",
            message="The Chain session is outside the durable active-head scope.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _authoritative_active_head(
    root: Path,
    *,
    chain_id: str,
    requested_active_head_run_id: str | None,
) -> str:
    try:
        return ChainStore(root / "workbench", create=False).resolve_active_head(
            chain_id,
            requested_active_head_run_id=requested_active_head_run_id,
        )
    except KeyError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CHAIN_NOT_MANAGED",
            message="The Chain has no durable active-head record.",
            details={"chain_id": chain_id},
        ) from exc
    except (ChainHeadConflict, ChainHeadUnavailable) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The durable Chain active head changed before this operation.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _context_serialized(packet: dict[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized) > MAX_CONTEXT_CHARS:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_TOO_LARGE",
            message="Agent context exceeds the bounded context budget.",
            details={"max_chars": MAX_CONTEXT_CHARS, "actual_chars": len(serialized)},
        )
    fingerprint = str(packet.get("context_fingerprint") or "")
    if not fingerprint:
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return serialized, fingerprint


def _ensure_main_session(repository: JsonlSessionRepository, root: Path) -> str:
    """Durable per-project Main session anchor for the HTTP orchestrator.

    The read-only inspection slice never dispatches Main→Chain commands, but
    the orchestrator identity must be a real session so future command entries
    have a home instead of a made-up id.
    """
    main_session_id = "agent_main"
    try:
        repository.get_metadata(main_session_id)
    except (KeyError, ValueError):
        repository.create_session(
            main_session_id, chain_id=f"project:{root}", role="main"
        )
    return main_session_id


def _get_session(
    root: Path,
    session_id: str,
) -> tuple[JsonlSessionRepository, AgentEventStream, dict[str, Any]]:
    repository, events = _stores(root)
    try:
        metadata = repository.get_metadata(session_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_SESSION_NOT_FOUND",
            message="Agent session was not found in this project.",
            details={"session_id": session_id},
        ) from exc
    return repository, events, metadata


def _messages(repository: JsonlSessionRepository, session_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    projector = AgentNavigationProjector(repository.root.parent)
    for entry in repository.get_branch(session_id):
        if entry.entry_type != "message":
            continue
        role = entry.payload.get("role")
        content = entry.payload.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        message = {
            "entry_id": entry.entry_id,
            "role": role,
            "content": content,
            # Tool entries carry the tool id in `name`; the panel projects
            # it as the typed status label instead of a generic "tool".
            "name": entry.payload.get("name"),
            "stop_reason": entry.payload.get("stop_reason"),
            "error": entry.payload.get("error"),
        }
        try:
            message["navigation"] = [
                link.to_dict()
                for link in projector.entry(session_id, entry.entry_id).links
            ]
        except (KeyError, ValueError):
            # A legacy/corrupt entry must not make the whole session unreadable.
            message["navigation"] = []
        result.append(message)
    return result


def _context_fingerprint(repository: JsonlSessionRepository, session_id: str) -> str | None:
    for entry in repository.get_branch(session_id):
        if entry.entry_type != "custom_message":
            continue
        metadata = entry.payload.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("context_fingerprint"), str):
            return metadata["context_fingerprint"]
    return None


def _public_session(
    repository: JsonlSessionRepository,
    session_id: str,
    metadata: dict[str, Any],
    config,
) -> dict[str, Any]:
    proposal_store = ProposalStore(repository.root)
    return {
        "session_id": session_id,
        "role": metadata.get("role"),
        "chain_id": metadata.get("chain_id"),
        "status": metadata.get("status"),
        "context_fingerprint": _context_fingerprint(repository, session_id),
        "model": config.model or None,
        "provider_id": config.provider_id or None,
        "context_window_tokens": config.context_window_tokens,
        "messages": _messages(repository, session_id),
        "proposals": _public_proposals(proposal_store, session_id),
    }


def _public_proposals(store: ProposalStore, session_id: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for revision in store.latest_revisions_for_session(session_id):
        proposal = revision.to_dict()
        proposal["status"] = store.latest_status(revision.proposal_id)
        confirmation = store.latest_confirmation(revision.proposal_id)
        if confirmation is not None:
            proposal["confirmation"] = confirmation.to_dict()
        decision = store.latest_decision(revision.proposal_id)
        if decision is not None:
            proposal["decision"] = decision.to_dict()
        proposals.append(proposal)
    return proposals


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
) -> str:
    """Re-derive the current node context before creating a confirmation record."""

    active_head_run_id = _authoritative_active_head(
        root,
        chain_id=str(proposal.chain_id),
        requested_active_head_run_id=active_head_run_id,
    )
    if proposal.operation_id == "data.columns.cast":
        return _current_data_columns_cast_fingerprint(root, proposal)
    if proposal.operation_id not in {"model.rerun", "graph.fork"}:
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
    if snapshot.get("node_hash") != target.get("node_hash"):
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


@router.post("/agent/sessions")
def create_agent_session(
    project_root: str,
    body: AgentSessionCreateRequest,
) -> dict[str, Any]:
    root = _project_root(project_root)
    serialized, fingerprint = _context_serialized(body.context_packet)
    repository, events = _stores(root)
    session_id = f"agent_{body.role}_{uuid4().hex}"
    chain_id = body.chain_id or f"project:{root}"
    active_head_run_id = body.run_id or _context_active_head(body.context_packet)
    if body.role == "chain" and active_head_run_id:
        try:
            _authoritative_active_head(
                root,
                chain_id=chain_id,
                requested_active_head_run_id=active_head_run_id,
            )
        except WorkbenchAPIError as exc:
            if exc.code != "AGENT_CHAIN_NOT_MANAGED":
                raise
    repository.create_session(session_id, chain_id=chain_id, role=body.role)
    if body.role == "chain" and active_head_run_id:
        _ensure_chain_scope(
            root,
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=session_id,
        )
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_context",
            "audience": "model",
            "name": "workbench_context",
            "content": (
                "Workbench read-only context. Do not invent facts or execute actions.\n"
                + serialized
            ),
            "metadata": {
                "context_fingerprint": fingerprint,
                "run_id": body.run_id,
            },
        },
    )
    if body.role == "chain":
        registry = OperationRegistry()
        repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "agent_protocol",
                "audience": "model",
                "name": "workbench_agent_protocol",
                "content": _chain_agent_protocol(registry),
                "metadata": {"protocol_version": "agent/v1"},
            },
        )
    events.emit(
        session_id,
        "session_created",
        {
            "role": body.role,
            "chain_id": chain_id,
            "run_id": body.run_id,
            "context_fingerprint": fingerprint,
        },
    )
    return _public_session(
        repository,
        session_id,
        repository.get_metadata(session_id),
        load_llm_config(),
    )


@router.get("/agent/sessions/{session_id}")
def get_agent_session(session_id: str, project_root: str) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, _events, metadata = _get_session(root, session_id)
    return _public_session(repository, session_id, metadata, load_llm_config())


@router.get("/agent/sessions/{session_id}/proposals")
def get_agent_proposals(session_id: str, project_root: str) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    return {"proposals": _public_proposals(ProposalStore(repository.root), session_id)}


@router.get("/agent/sessions/{session_id}/projection")
def get_agent_session_projection(
    session_id: str,
    project_root: str,
) -> dict[str, Any]:
    root = _project_root(project_root)
    _repository, _events, _metadata = _get_session(root, session_id)
    try:
        projection = AgentNavigationProjector(root).session(session_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Agent navigation projection was not found.",
            details={"session_id": session_id},
        ) from exc
    return {"projection": projection.to_dict()}


@router.get("/agent/navigation/graph")
def get_agent_graph_navigation(
    project_root: str,
    run_id: str = Query(min_length=1),
    node_ref: str | None = Query(default=None),
    forest_node_key: str | None = Query(default=None),
) -> dict[str, Any]:
    root = _project_root(project_root)
    projection = AgentNavigationProjector(root).graph(
        run_id=run_id,
        node_ref=node_ref,
        forest_node_key=forest_node_key,
    )
    if not projection.subject.available:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Graph navigation projection was not found.",
            details={"run_id": run_id, "node_ref": node_ref},
        )
    return {"projection": projection.to_dict()}


@router.get("/agent/activity")
def get_agent_activity(project_root: str) -> dict[str, Any]:
    """Return the durable, read-only operation projection for AI Activity."""

    root = _project_root(project_root)
    projection = AgentNavigationProjector(root)
    hierarchy = projection.activity_hierarchy()
    return {
        "activities": [item.to_dict() for item in projection.activity()],
        "events": [item.to_dict() for item in projection.activity_events()],
        "hierarchy": hierarchy.to_dict() if hierarchy is not None else None,
    }


@router.get("/agent/capabilities")
def get_agent_capabilities(
    project_root: str,
    scope: str | None = None,
) -> dict[str, Any]:
    """Return registry-owned operation capabilities without creating storage."""

    root = _project_root(project_root)
    capabilities = OperationRegistry().capabilities()
    if scope is not None:
        capabilities = [item for item in capabilities if item["scope"] == scope]
    return {
        "project_root": str(root),
        "scope": scope,
        **control_plane_capability(),
        "capabilities": capabilities,
        "boundary": OperationRegistry().boundary(),
    }


def _analysis_loop_run_facts(resolved) -> dict[str, Any]:
    """Expose bounded persisted OLS facts for the read-only detail surface."""

    result = resolved.result if isinstance(resolved.result, dict) else {}
    sample = result.get("analysis_sample")
    fingerprints = {
        key: result.get(key)
        for key in (
            "dataset_snapshot_fingerprint",
            "analysis_sample_fingerprint",
            "point_estimation_fingerprint",
            "coefficient_schema_fingerprint",
            "inference_config_fingerprint",
        )
        if result.get(key) is not None
    }
    return {
        "run_id": resolved.run_id,
        "status": resolved.manifest.get("status"),
        "model": result.get("model"),
        "contract_version": result.get("contract_version"),
        "covariance": result.get("covariance"),
        "covariance_product": (
            "conventional"
            if result.get("covariance") == "unadjusted"
            else result.get("covariance")
        ),
        "covariance_wire": result.get("covariance_wire"),
        "entity_col": result.get("entity_col"),
        "stable_result_ids": list(result.get("stable_result_ids") or []),
        "primary_estimand": result.get("primary_estimand"),
        "analysis_sample": {
            "row_count": sample.get("row_count"),
            "row_order": list(sample.get("row_order") or []),
        } if isinstance(sample, dict) else None,
        "fingerprints": fingerprints,
    }


def _analysis_loop_packet_bundle(
    *,
    validation_packet,
    compare_packets: list[ComparePacket],
    plan_packets,
) -> dict[str, Any]:
    compare = next(
        (
            packet
            for packet in compare_packets
            if packet.child_run_id == validation_packet.child_run_id
            and packet.source_run_id == validation_packet.source_run_id
        ),
        None,
    )
    plan = next(
        (
            packet.plan_diff
            for packet in plan_packets
            if packet.plan_diff.plan_hash == validation_packet.plan_hash
        ),
        None,
    )
    return {
        "child_run_id": validation_packet.child_run_id,
        "source_run_id": validation_packet.source_run_id,
        "plan_diff": plan.to_dict() if plan is not None else None,
        "validation_packet": validation_packet.to_dict(),
        "compare_packet": compare.to_dict() if compare is not None else None,
    }


@router.get("/analysis-loop/packets/{run_id}")
def get_analysis_loop_packets(
    run_id: str,
    project_root: str,
) -> dict[str, Any]:
    """Read persisted Analysis Loop facts for one graph run.

    This endpoint is deliberately read-only.  It never builds a packet or
    infers a comparison.  Terminal packets are selected by their durable
    child/source IDs; the UI receives the backend's exact packet payloads.
    """

    root = _project_root(project_root)
    try:
        resolved = resolve_analysis_loop_run(root, run_id=run_id, require_result=False)
    except AnalysisLoopSourceResolutionError as exc:
        status_code = 404 if exc.code == "SOURCE_RUN_NOT_FOUND" else 422
        raise WorkbenchAPIError(
            status_code=status_code,
            code=("ANALYSIS_LOOP_RUN_NOT_FOUND" if status_code == 404 else exc.code),
            message=str(exc),
            details={"run_id": run_id},
        ) from exc

    validation_store = ValidationPacketStore(root, create=False)
    compare_store = ComparePacketStore(root, create=False)
    plan_store = PlanDiffStore(root, create=False)
    validations = validation_store.list_terminal_packets()
    compares = compare_store.list_terminal_packets()
    plans = plan_store.list_terminal_packets()

    current = [packet for packet in validations if packet.child_run_id == run_id]
    current.sort(key=lambda packet: packet.logical_key)
    current_bundle = (
        _analysis_loop_packet_bundle(
            validation_packet=current[0],
            compare_packets=compares,
            plan_packets=plans,
        )
        if current
        else None
    )
    child_bundles = [
        _analysis_loop_packet_bundle(
            validation_packet=packet,
            compare_packets=compares,
            plan_packets=plans,
        )
        for packet in sorted(
            (item for item in validations if item.source_run_id == run_id),
            key=lambda item: item.logical_key,
        )
    ]

    source_run = None
    source_run_id = (
        current[0].source_run_id
        if current
        else str(
            resolved.run_inputs.get("rerun_of")
            or resolved.manifest.get("source_run_id")
            or run_id
        )
    )
    try:
        source_resolved = resolve_analysis_loop_run(
            root,
            run_id=source_run_id,
            require_result=False,
        )
        source_run = _analysis_loop_run_facts(source_resolved)
    except AnalysisLoopSourceResolutionError:
        # The packet remains inspectable even if a historical source has been
        # removed or became unreadable; do not hide the durable child evidence.
        source_run = {"run_id": source_run_id, "status": "unavailable"}

    lifecycle_status = str(resolved.manifest.get("status") or "")
    status = (
        current[0].status
        if current
        else "pending"
        if lifecycle_status in {"queued", "running", "pending"}
        else "absent"
    )
    return {
        "status": status,
        "run": _analysis_loop_run_facts(resolved),
        "source_run": source_run,
        "packet": current_bundle,
        "children": child_bundles,
    }


def _analysis_loop_packets_from_request(
    body: AnalysisLoopContextRequest,
) -> tuple[PlanDiff | None, ValidationPacket | None, ComparePacket | None]:
    """Parse packet payloads without reading or mutating project state."""

    try:
        return parse_analysis_loop_packet_payloads(
            plan_diff=body.plan_diff,
            validation_packet=body.validation_packet,
            compare_packet=body.compare_packet,
        )
    except AnalysisLoopContextError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message="The analysis-loop packet payload is invalid.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/agent/sessions/{session_id}/analysis-loop/context")
def inspect_agent_analysis_loop_context(
    session_id: str,
    project_root: str,
    body: AnalysisLoopContextRequest,
) -> dict[str, Any]:
    """Return one scope of typed analysis-loop context, read-only.

    The HTTP seam intentionally accepts already-structured packet payloads so
    fixture clients and future backend resolvers share one strict domain
    boundary. It does not calculate packets, read arbitrary files, create a
    proposal, or execute an operation.
    """

    root = _project_root(project_root)
    _get_session(root, session_id)
    plan_diff, validation_packet, compare_packet = _analysis_loop_packets_from_request(body)
    try:
        context = inspect_analysis_loop_context(
            source_context=body.source_context,
            scope=body.scope,
            plan_diff=plan_diff,
            validation_packet=validation_packet,
            compare_packet=compare_packet,
        )
    except AnalysisLoopContextError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details={"scope": body.scope},
        ) from exc
    return {
        "status": context["status"],
        "context": context,
        "registered_actions": [action.to_dict() for action in RECOVERY_ACTIONS.values()],
    }


@router.post("/agent/sessions/{session_id}/analysis-loop/intents")
def submit_agent_analysis_loop_intent(
    session_id: str,
    project_root: str,
    body: AnalysisLoopIntentRequest,
) -> dict[str, Any]:
    """Classify one untrusted intent without creating a proposal or effect."""

    root = _project_root(project_root)
    _get_session(root, session_id)
    decision = forward_analysis_intent(body.intent)
    return {
        "status": "accepted" if decision.accepted else "rejected",
        "decision": decision.to_dict(),
        "registered_actions": [action.to_dict() for action in RECOVERY_ACTIONS.values()],
    }


@router.post("/agent/sessions/{session_id}/analysis-loop/proposals")
def create_agent_analysis_loop_proposal(
    session_id: str,
    project_root: str,
    body: AnalysisLoopProposalRequest,
) -> dict[str, Any]:
    """Resolve persisted OLS facts and create one confirmation-gated proposal."""

    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    if metadata.get("role") != "chain":
        raise WorkbenchAPIError(
            status_code=409,
            code="ANALYSIS_LOOP_SCOPE_INVALID",
            message="An analysis-loop proposal must belong to a Chain Agent session.",
            details={"session_id": session_id},
        )
    chain_id = str(metadata.get("chain_id") or "")
    authoritative_active_head_run_id = _authoritative_active_head(
        root,
        chain_id=chain_id,
        requested_active_head_run_id=body.active_head_run_id,
    )
    provider = NodeOperationContextProvider(root)
    context_started = perf_counter()
    try:
        snapshot = provider.inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"analysis-loop-proposal:{body.source_run_id}:{body.source_node_ref}",
                owner_run_id=body.source_run_id,
                op_node_id=body.source_node_ref,
                active_head_run_id=authoritative_active_head_run_id,
            )
        )
        context_ms = round((perf_counter() - context_started) * 1000, 3)
        resolved = resolve_analysis_loop_inputs(
            root,
            run_id=body.source_run_id,
            cluster_variable=body.cluster_variable,
        )
    except AnalysisLoopSourceResolutionError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details={"run_id": body.source_run_id},
        ) from exc
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The selected OLS node or active head could not be verified.",
            details={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
            },
        ) from exc
    if resolved.source.run_id != body.source_run_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="SOURCE_IDENTITY_MISMATCH",
            message="The resolved source does not match the requested run.",
            details={"run_id": body.source_run_id},
        )
    if snapshot.get("active_head_run_id") != authoritative_active_head_run_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The selected source is outside the current active head.",
            details={"run_id": body.source_run_id},
        )

    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=provider,
    )
    # Proposal creation needs a registered Chain identity but does not invoke
    # an LLM. The adapter is constructed locally; this read/plan path makes no
    # provider call.
    agent = AgentCore(
        repository,
        events,
        OpenAICompatibleModelAdapter(load_llm_config()),
        session_id=session_id,
    )
    orchestrator.register_chain(chain_id, session_id, agent)
    plan_started = perf_counter()
    try:
        proposal = create_analysis_loop_proposal(
            orchestrator=orchestrator,
            chain_id=chain_id,
            plan_store=PlanDiffStore(repository.root, create=False),
            source=resolved.source,
            intent={
                "action_id": "ols.use_clustered_covariance_v1",
                "patch": {
                    "covariance": "clustered",
                    "cluster_variable": body.cluster_variable,
                },
            },
            cluster_values=resolved.cluster_values,
            model_row_ids=resolved.model_row_ids,
            requested_result_id=body.result_id,
            source_context_fingerprint=str(snapshot["context_fingerprint"]),
            source_identity={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
                "node_hash": str(snapshot["node_hash"]),
                "forest_node_key": str(snapshot["forest_node_key"]),
            },
            active_head_run_id=authoritative_active_head_run_id,
            owner_resolution=str(snapshot["owner_resolution"]),
        )
        plan_ms = round((perf_counter() - plan_started) * 1000, 3)
    except AnalysisLoopProposalError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        ) from exc
    except PlanValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        ) from exc
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="ANALYSIS_LOOP_PROPOSAL_INVALID",
            message="The canonical analysis-loop proposal was rejected by the operation registry.",
            details={"reason": str(exc)},
        ) from exc
    plan_store = PlanDiffStore(repository.root, create=False)
    logical_key = proposal.preconditions.get("plan_logical_key")
    packet = plan_store.get_terminal_packet(str(logical_key)) if logical_key else None
    if packet is None:
        raise WorkbenchAPIError(
            status_code=500,
            code="ANALYSIS_LOOP_PLAN_MISSING",
            message="The analysis-loop proposal has no persisted PlanDiff.",
            details={"proposal_id": proposal.proposal_id},
        )
    return {
        "session_id": session_id,
        "proposal": _public_proposal(orchestrator.proposal_store, proposal.proposal_id),
        "plan_diff": packet.plan_diff.to_dict(),
        "registered_action": RECOVERY_ACTIONS["ols.use_clustered_covariance_v1"].to_dict(),
        "timings_ms": {
            "node_operation_context_ms": context_ms,
            "plan_diff_ms": plan_ms,
        },
        "status": "pending",
    }


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
) -> dict[str, Any]:
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
    agent = AgentCore(
        repository,
        events,
        OpenAICompatibleModelAdapter(load_llm_config()),
        session_id=session_id,
    )
    orchestrator.register_chain(chain_id, session_id, agent)
    try:
        proposal = orchestrator.create_proposal(
            chain_id=chain_id,
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
        )
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
        },
    )
    return {
        "session_id": session_id,
        "source_session_entry_id": source_entry_id,
        "proposal": _public_proposal(orchestrator.proposal_store, proposal.proposal_id),
        "navigation": navigation.to_dict(),
        "status": "pending",
    }


@router.get("/agent/sessions/{session_id}/operations/{record_id}")
def get_agent_operation_projection(
    session_id: str,
    record_id: str,
    project_root: str,
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/confirm")
async def confirm_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalConfirmRequest,
) -> dict[str, Any]:
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
    return {
        "proposal": _public_proposal(store, proposal_id),
        "operation": record.to_dict(),
        "status": record.status,
    }


@router.post("/agent/sessions/{session_id}/operations/{record_id}/reconcile")
async def reconcile_agent_operation(
    session_id: str,
    record_id: str,
    project_root: str,
) -> dict[str, Any]:
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


@router.post("/agent/sessions/{session_id}/turns")
async def run_agent_turn(
    session_id: str,
    project_root: str,
    body: AgentTurnRequest,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    config = load_llm_config()
    if not config.is_configured():
        raise WorkbenchAPIError(
            status_code=503,
            code="LLM_NOT_CONFIGURED",
            # A broken explicit store must say so — "configure a provider" is
            # the wrong advice when the operator already did and the pinned
            # file is missing.
            message=config.configuration_error_message(),
        )
    agent = AgentCore(
        repository,
        events,
        OpenAICompatibleModelAdapter(config),
        session_id=session_id,
    )
    tool_context: dict[str, Any] | None = None
    if metadata.get("role") == "chain":
        # Handoff §7 slice: the ROUTE registers the chain-scoped read-only
        # tools through the existing orchestrator boundary — the model never
        # discovers Workbench capabilities on its own, and a plain inspection
        # turn performs zero Workbench mutation. Proposals stay allowlisted to
        # registry-enabled operations and remain confirmation-gated audit records.
        operation_registry = OperationRegistry()
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id=_ensure_main_session(repository, root),
            operation_registry=operation_registry,
            context_provider=NodeOperationContextProvider(root),
        )
        orchestrator.register_chain(str(metadata.get("chain_id")), session_id, agent)
        tool_context = {
            "allowed_operations": operation_registry.natural_language_operation_ids(
                scope_requirements=("chain", "active_head")
            )
        }
    await agent.prompt(
        body.question.strip(),
        budget={"max_steps": DEFAULT_MAX_STEPS, "timeout_s": DEFAULT_TIMEOUT_S},
        tool_context=tool_context,
    )
    messages = _messages(repository, session_id)
    assistant = next(
        (message for message in reversed(messages) if message["role"] == "assistant"),
        None,
    )
    if assistant is None:
        raise WorkbenchAPIError(
            status_code=502,
            code="AGENT_NO_ASSISTANT_MESSAGE",
            message="Agent completed without producing an assistant message.",
        )
    return {
        "session": _public_session(repository, session_id, metadata, config),
        "assistant": assistant,
        "status": repository.get_metadata(session_id).get("status"),
    }


@router.get("/agent/sessions/{session_id}/events")
def get_agent_events(
    session_id: str,
    project_root: str,
    after_seq: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    root = _project_root(project_root)
    _repository, events, _metadata = _get_session(root, session_id)
    return {
        "events": [
            event.to_dict()
            for event in events.replay(session_id, after_seq=after_seq)
        ]
    }
