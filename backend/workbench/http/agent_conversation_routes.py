"""List, rename, archive and delete the project's Agent conversations."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..agent.conversations import list_conversations, summary
from ..agent.session import JsonlSessionRepository, SessionHasBranchesError
from ..api_errors import WorkbenchAPIError
from .agent_routes import (
    _ACTIVE_TURNS,
    _RESERVED_TURNS,
    _TURN_RESERVATION_LOCK,
    _active_turn_key,
    _get_session,
    _project_root,
)
from .responses.agent import AgentConversation, AgentConversationDeleted, AgentConversations
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


@router.get("/agent/conversations")
def list_agent_conversations(project_root: str, include_archived: bool = False) -> AgentConversations:
    """Conversations someone wrote in, most recently active first."""
    root = _project_root(project_root)
    repository = JsonlSessionRepository(root / "workbench", create=False)
    return {"conversations": list_conversations(repository, include_archived=include_archived)}


class AgentConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A new title; an empty one returns to the first-message title.
    title: str | None = Field(default=None, max_length=120)
    archived: bool | None = None


@router.patch("/agent/conversations/{session_id}")
def update_agent_conversation(session_id: str, project_root: str, body: AgentConversationUpdate) -> AgentConversation:
    """Rename, archive or restore a conversation; its messages are unchanged."""
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    fields: dict[str, object] = {}
    if "title" in body.model_fields_set:
        fields["title"] = (body.title or "").strip() or None
    if body.archived is not None:
        fields["archived"] = True if body.archived else None
    metadata = repository.update_metadata(session_id, **fields)
    item = summary(repository, metadata)
    if item is None:
        raise WorkbenchAPIError(status_code=409, code="AGENT_CONVERSATION_EMPTY",
                                message="This conversation has no messages yet.", details={"session_id": session_id})
    return item


@router.delete("/agent/conversations/{session_id}")
def delete_agent_conversation(session_id: str, project_root: str) -> AgentConversationDeleted:
    """Delete a conversation's messages and live event log.

    The analysis ledger, proposals and operation records stay: they record
    what changed in the data and models, whoever asked for it.
    """
    root = _project_root(project_root)
    repository, events, _metadata = _get_session(root, session_id)
    with _TURN_RESERVATION_LOCK:
        key = _active_turn_key(root, session_id)
        if key in _ACTIVE_TURNS or key in _RESERVED_TURNS:
            raise WorkbenchAPIError(status_code=409, code="AGENT_TURN_IN_PROGRESS",
                                    message="The Agent is still answering in this conversation; stop it first.",
                                    details={"session_id": session_id})
        try:
            repository.delete_session(session_id)
        except SessionHasBranchesError as exc:
            raise WorkbenchAPIError(
                status_code=409, code="AGENT_CONVERSATION_HAS_BRANCHES",
                message="Other conversations continue from this one. Archive it, or delete those first.",
                details={"session_id": session_id, "branches": exc.branches},
            ) from exc
        except ValueError as exc:
            raise WorkbenchAPIError(status_code=409, code="AGENT_TURN_IN_PROGRESS", message=str(exc),
                                    details={"session_id": session_id}) from exc
    events.delete(session_id)
    return {"session_id": session_id, "deleted": True}
