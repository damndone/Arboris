"""agent session routes: extracted HTTP responsibility."""
from __future__ import annotations
from typing import Any, Literal
from uuid import uuid4
from fastapi import Query, Response
from ..agent.audit_export import build_agent_audit, render_agent_audit_html, render_agent_audit_markdown
from ..agent.compaction import CompactionError, CompactionPolicy, compact as compact_session, estimate_messages_tokens
from ..agent.context import ContextBuilder
from ..agent.instructions import INSTRUCTIONS_NAME, compose as compose_instructions
from ..agent.recall import RECALL_NAME, conversation_index, index_text as recall_index_text
from ..agent.navigation import AgentNavigationProjector
from ..agent.operations import OperationRegistry
from ..agent.proposals import ProposalStore
from ..agent.session import EntryRef, JsonlSessionRepository
from ..api_errors import WorkbenchAPIError
from ..control_plane import control_plane_capability
from ..agent.protocol import chain_agent_protocol as _chain_agent_protocol
from .responses.agent import AgentActivity, AgentAuditExport, AgentCapabilities, AgentProposalList, AgentSession, AgentSessionChange, NavigationProjectionResponse
from .agent_route_context import (_authoritative_active_head, _canonicalize_chain_context_packet, _context_active_head, _context_serialized, _ensure_chain_scope, _ensure_current_global_protocol, _get_session, _project_root, _stores)
from .agent_route_projection import (_public_proposals, _public_session)
from .agent_route_requests import (AgentChapterRequest, AgentCompactRequest, AgentEntryRequest, AgentSessionCreateRequest)
from .agent_route_runtime import (_agent_llm_config, _agent_llm_configured, _agent_model_adapter, _release_turn, _reserve_turn)

from fastapi import APIRouter
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

#: Which tools answer for this kind of object; the rest of the Agent is the same everywhere.
FOCUS_HINTS = {
    "report": " read_reports shows this run's report and its versions; save_report_version saves a new one.",
    "plan": " inspect_notebook_state shows the options being compared.",
}

@router.post("/agent/sessions")
def create_agent_session(
    project_root: str,
    body: AgentSessionCreateRequest,
) -> AgentSession:
    root = _project_root(project_root)
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
        authoritative_active_head = _authoritative_active_head(
            root,
            chain_id=chain_id,
            requested_active_head_run_id=active_head_run_id,
        )
        context_packet = _canonicalize_chain_context_packet(
            root,
            chain_id=chain_id,
            packet=body.context_packet,
            active_head_run_id=authoritative_active_head,
        )
    else:
        context_packet = body.context_packet
    serialized, fingerprint = _context_serialized(context_packet)
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
    from ..agent.identity import identity_text

    identity_config = _agent_llm_config()
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_identity",
            "audience": "model",
            "name": "workbench_agent_identity",
            "content": identity_text("chain" if body.role == "chain" else "global", identity_config),
            "metadata": {"protocol_version": "agent/v1"},
        },
    )
    instruction_text, instruction_record = compose_instructions(root)
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_instructions",
            "audience": "model",
            "name": INSTRUCTIONS_NAME,
            "content": instruction_text,
            "metadata": instruction_record,
        },
    )
    earlier = conversation_index(repository, exclude=session_id)
    if earlier:
        repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "agent_recall",
                "audience": "model",
                "name": RECALL_NAME,
                "content": recall_index_text(earlier),
                "metadata": {"conversations": [item["session_id"] for item in earlier]},
            },
        )
    if body.focus is not None:
        repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "agent_focus",
                "audience": "model",
                "name": "workbench_agent_focus",
                "content": (
                    # The id, not only the label: tools take ids, and with the label
                    # alone the first call of 3 of 4 v1.9.1 smoke runs passed the label.
                    f"Focus: the person has the {body.focus.kind} '{body.focus.label}'"
                    + (f" (id {body.focus.id})" if body.focus.id and body.focus.id != body.focus.label else "")
                    + (f" in run {body.focus.run_id}" if body.focus.run_id else "")
                    + " selected. Use it for questions about it; it does not decide which analysis a question needs."
                    + FOCUS_HINTS.get(body.focus.kind, "")
                ),
                "metadata": {"focus": body.focus.model_dump()},
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
    else:
        _ensure_current_global_protocol(repository, session_id)
    events.emit(
        session_id,
        "session_created",
        {
            "role": body.role,
            "chain_id": chain_id,
            "run_id": body.run_id,
            "focus": body.focus.model_dump() if body.focus is not None else None,
            "context_fingerprint": fingerprint,
        },
    )
    return _public_session(
        repository,
        session_id,
        repository.get_metadata(session_id),
        _agent_llm_config(),
    )


def _branch_message(repository: JsonlSessionRepository, session_id: str, entry_id: str):
    """A message entry on the session's current branch, or 404."""
    for entry in repository.get_branch(session_id):
        if entry.entry_id == entry_id and entry.entry_type == "message":
            return entry
    raise WorkbenchAPIError(
        status_code=404,
        code="AGENT_ENTRY_NOT_FOUND",
        message="That message is not part of this conversation.",
        details={"session_id": session_id, "entry_id": entry_id},
    )


def _refuse_while_running(metadata: dict[str, Any], action: str) -> None:
    if metadata.get("status") == "running":
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_TURN_RUNNING",
            message=f"The Agent is still answering; stop it or wait before you {action}.",
            details={},
        )


def _before(entry) -> EntryRef:
    if entry.parent_ref is None:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_ENTRY_IS_FIRST",
            message="There is nothing before this message to go back to.",
            details={"entry_id": entry.entry_id},
        )
    return entry.parent_ref


@router.post("/agent/sessions/{session_id}/rewind")
def rewind_agent_session(session_id: str, project_root: str, body: AgentEntryRequest) -> AgentSessionChange:
    """Restore the conversation and analysis head together on a retained branch."""
    from ..agent.analysis_history import rewind_analysis
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    _refuse_while_running(metadata, "rewind")
    entry = _branch_message(repository, session_id, body.entry_id)
    if entry.payload.get("role") != "user":
        raise WorkbenchAPIError(status_code=422, code="AGENT_REWIND_TARGET",
                                message="Rewind goes back to one of your own messages.", details={})
    try:
        restored = rewind_analysis(repository, session_id, body.entry_id)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise WorkbenchAPIError(status_code=409, code="AGENT_REWIND_REFUSED", message=str(exc), details={}) from exc
    restored_id = restored["session_id"]
    return {"session": _public_session(repository, restored_id, repository.get_metadata(restored_id), _agent_llm_config()),
            "restored_prompt": restored["restored_prompt"], "lineage": restored["lineage"]}


@router.post("/agent/sessions/{session_id}/fork")
def fork_agent_session(session_id: str, project_root: str, body: AgentEntryRequest) -> AgentSessionChange:
    """Start a new conversation that shares this one up to a message.

    From a reply, the new conversation includes that reply; from one of your
    messages, it stops just before it and the message returns to the input.
    The original conversation is unchanged.
    """
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    _refuse_while_running(metadata, "fork")
    entry = _branch_message(repository, session_id, body.entry_id)
    from_user = entry.payload.get("role") == "user"
    point = _before(entry) if from_user else EntryRef(session_id, entry.entry_id)
    role = str(metadata.get("role") or "chain")
    fork_id = f"agent_{role}_{uuid4().hex}"
    repository.create_session(fork_id, chain_id=str(metadata.get("chain_id")), role=role, inherited_parent_ref=point)
    events.emit(session_id, "session_forked", {"fork_session_id": fork_id, "at_entry": point.to_dict()})
    events.emit(fork_id, "session_created", {"role": role, "chain_id": metadata.get("chain_id"),
                                             "forked_from": {"session_id": session_id, **point.to_dict()}})
    return {"session": _public_session(repository, fork_id, repository.get_metadata(fork_id), _agent_llm_config()),
            "restored_prompt": str(entry.payload.get("content") or "") if from_user else None}


@router.post("/agent/sessions/{session_id}/chapters")
def pin_agent_chapter(session_id: str, project_root: str, body: AgentChapterRequest) -> AgentSession:
    """Pin a message as a chapter: a named place to jump back to."""
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    entry = _branch_message(repository, session_id, body.entry_id)
    chapters = [chapter for chapter in metadata.get("chapters") or [] if chapter.get("entry_id") != entry.entry_id]
    chapters.append({"entry_id": entry.entry_id, "title": body.title.strip(), "at": entry.created_at})
    order = {item.entry_id: index for index, item in enumerate(repository.get_branch(session_id))}
    chapters.sort(key=lambda chapter: order.get(chapter["entry_id"], 0))
    metadata = repository.set_chapters(session_id, chapters)
    events.emit(session_id, "chapter_pinned", {"entry_id": entry.entry_id, "title": body.title.strip()})
    return _public_session(repository, session_id, metadata, _agent_llm_config())


@router.delete("/agent/sessions/{session_id}/chapters/{entry_id}")
def unpin_agent_chapter(session_id: str, entry_id: str, project_root: str) -> AgentSession:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    chapters = [chapter for chapter in metadata.get("chapters") or [] if chapter.get("entry_id") != entry_id]
    metadata = repository.set_chapters(session_id, chapters)
    events.emit(session_id, "chapter_unpinned", {"entry_id": entry_id})
    return _public_session(repository, session_id, metadata, _agent_llm_config())


def require_agent_session(session_id: str, project_root: str) -> None:
    """The checks and errors of ``get_agent_session`` without projecting the transcript."""
    _get_session(_project_root(project_root), session_id)


@router.get("/agent/sessions/{session_id}")
def get_agent_session(session_id: str, project_root: str) -> AgentSession:
    root = _project_root(project_root)
    repository, _events, metadata = _get_session(root, session_id)
    return _public_session(repository, session_id, metadata, _agent_llm_config())


@router.get("/agent/sessions/{session_id}/audit", response_model=None)
def get_agent_audit_export(
    session_id: str,
    project_root: str,
    format: Literal["json", "markdown", "html"] = Query("json"),
) -> AgentAuditExport | Response:
    root = _project_root(project_root)
    _get_session(root, session_id)
    audit = build_agent_audit(root, session_id)
    markdown = render_agent_audit_markdown(audit)
    if format == "markdown":
        return Response(markdown, media_type="text/markdown")
    html = render_agent_audit_html(audit)
    if format == "html":
        return Response(html, media_type="text/html")
    return {"audit": audit, "markdown": markdown, "html": html}


@router.get("/agent/sessions/{session_id}/proposals")
def get_agent_proposals(session_id: str, project_root: str) -> AgentProposalList:
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    return {"proposals": _public_proposals(ProposalStore(repository.root), session_id)}


@router.get("/agent/sessions/{session_id}/projection")
def get_agent_session_projection(
    session_id: str,
    project_root: str,
) -> NavigationProjectionResponse:
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
) -> NavigationProjectionResponse:
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
def get_agent_activity(project_root: str) -> AgentActivity:
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
) -> AgentCapabilities:
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


@router.post("/agent/sessions/{session_id}/compact")
async def compact_agent_session(
    session_id: str,
    project_root: str,
    body: AgentCompactRequest,
) -> AgentSession:
    """Summarize the earlier conversation now, keeping the latest part verbatim.

    The same summary the Agent writes on its own when the conversation nears
    the model's window; nothing is deleted from the session log.
    """
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    _refuse_while_running(metadata, "compact the conversation")
    turn_key = _reserve_turn(root, session_id)
    try:
        config = _agent_llm_config()
        if not _agent_llm_configured(config):
            raise WorkbenchAPIError(status_code=503, code="LLM_NOT_CONFIGURED",
                                    message=config.configuration_error_message())
        policy = CompactionPolicy.from_config(config.context_window_tokens, supports_1m=config.supports_1m,
            explicit_limit=getattr(config, "context_limit_tokens", None))
        tokens = estimate_messages_tokens(ContextBuilder(repository).build(session_id).messages)
        events.emit(session_id, "compaction_start", {"trigger": "manual", "tokens_before": tokens, **policy.to_dict()})
        try:
            entry = await compact_session(
                repository, session_id, _agent_model_adapter(config), policy,
                trigger="manual", tokens_before=tokens, focus=body.focus, model=config.model,
            )
        except CompactionError as exc:
            events.emit(session_id, "compaction_end", {"trigger": "manual", "compacted": False, "error": str(exc)})
            raise WorkbenchAPIError(status_code=502, code="AGENT_COMPACTION_FAILED",
                                    message="The summary could not be written; the conversation is unchanged.",
                                    details={"reason": str(exc)}) from exc
        if entry is None:
            events.emit(session_id, "compaction_end", {"trigger": "manual", "compacted": False})
            raise WorkbenchAPIError(status_code=409, code="AGENT_NOTHING_TO_COMPACT",
                                    message="There is no earlier part of this conversation to summarize yet.",
                                    details={})
        events.emit(session_id, "compaction_end", {
            "trigger": "manual", "compacted": True, "entry_id": entry.entry_id, "tokens_before": tokens,
            "tokens_after": estimate_messages_tokens(ContextBuilder(repository).build(session_id).messages),
            "verified": entry.payload.get("verified"),
        })
    finally:
        _release_turn(turn_key)
    return _public_session(repository, session_id, repository.get_metadata(session_id), config)

