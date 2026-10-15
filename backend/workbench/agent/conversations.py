"""The project's Agent conversations as a list a person manages.

A conversation is a session log (agent/session.py). Titles and the archived
flag live in its metadata; deleting removes the log and its live event log
but never the analysis ledger, proposals or operation records, which are the
record of what changed in the data and models.
"""

from __future__ import annotations

from typing import Any

from .session import JsonlSessionRepository

TITLE_CHARS = 60


def _title_from(text: str) -> str:
    line = next((part.strip(" #>*-") for part in text.splitlines() if part.strip(" #>*-")), "")
    flat = " ".join(line.split())
    return flat if len(flat) <= TITLE_CHARS else flat[: TITLE_CHARS - 1] + "…"


def summary(repository: JsonlSessionRepository, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """One conversation for the list; None for a session nobody wrote in."""

    session_id = str(metadata.get("session_id") or "")
    try:
        branch = repository.get_branch(session_id)
    except (KeyError, ValueError, OSError):
        return None
    own = [entry for entry in branch if entry.session_id == session_id]
    users = [entry for entry in branch if entry.entry_type == "message" and entry.payload.get("role") == "user"]
    if not users:
        return None
    replies = [entry for entry in own if entry.entry_type == "message" and entry.payload.get("role") == "assistant"]
    focus = None
    for entry in branch:
        if entry.entry_type == "custom_message" and entry.payload.get("name") == "workbench_agent_focus":
            value = (entry.payload.get("metadata") or {}).get("focus")
            if isinstance(value, dict):
                focus = value
    role = metadata.get("role")
    # A whole-project conversation is "Project", not the focus's internal label
    # ("Global Agent · 2 runs · 1 families").
    about = (
        "Project" if (focus and focus.get("kind") == "project") or (role == "main" and not focus)
        else str(focus.get("label")) if focus and focus.get("label")
        else str(metadata.get("chain_id") or "").removeprefix("chain:") or "Analysis"
    )
    parent = metadata.get("inherited_parent_ref") or None
    return {
        "session_id": session_id,
        "role": role,
        "title": str(metadata.get("title") or "") or _title_from(str(users[0].payload.get("content") or "")),
        "titled": bool(metadata.get("title")),
        "about": about,
        "focus": focus,
        "created_at": str(metadata.get("created_at") or branch[0].created_at),
        "last_active": branch[-1].created_at,
        "messages": sum(1 for entry in own if entry.entry_type == "message" and entry.payload.get("role") in {"user", "assistant"}),
        "replies": len(replies),
        "archived": bool(metadata.get("archived")),
        "status": metadata.get("status"),
        "forked_from": parent.get("session_id") if isinstance(parent, dict) else None,
    }


def list_conversations(repository: JsonlSessionRepository, *, include_archived: bool = False) -> list[dict[str, Any]]:
    items = []
    for metadata in repository.list_metadata():
        if metadata.get("archived") and not include_archived:
            continue
        item = summary(repository, metadata)
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: item["last_active"], reverse=True)
    return items
