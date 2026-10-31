"""agent route projection: extracted HTTP responsibility."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..agent.compaction import CompactionPolicy, estimate_messages_tokens
from ..agent.context import ContextBuilder
from ..agent.navigation import AgentNavigationProjector
from ..agent.proposals import ProposalStore
from ..agent.session import JsonlSessionRepository
from ..agent.proposal_text import proposal_lines
from ..services.dataset_view import run_labels

def _messages(repository: JsonlSessionRepository, session_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    projector = AgentNavigationProjector(repository.root.parent)
    branch = repository.get_branch(session_id)
    try:
        links = projector.entry_links(session_id, [entry for entry in branch if entry.entry_type == "message"])
    except (KeyError, ValueError):
        links = {}
    for entry in branch:
        if entry.entry_type == "compaction" and isinstance(entry.payload.get("summary"), str):
            result.append({
                "entry_id": entry.entry_id,
                "at": entry.created_at,
                "role": "summary",
                "content": entry.payload["summary"],
                "name": "context_compaction",
                "stop_reason": None,
                "error": None,
                "navigation": [],
                "compaction": {
                    "trigger": str(entry.payload.get("trigger") or "auto"),
                    "tokens_before": int(entry.payload.get("tokens_before") or 0),
                    "verified": entry.payload.get("verified") is not False,
                    "unverified_numbers": [str(item) for item in entry.payload.get("unverified_numbers") or []],
                    "summarized_messages": len(entry.payload.get("summarized_entry_ids") or []),
                },
            })
            continue
        if entry.entry_type != "message":
            continue
        role = entry.payload.get("role")
        content = entry.payload.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        message = {
            "entry_id": entry.entry_id,
            "at": entry.created_at,
            "role": role,
            "content": content,
            # Tool entries carry the tool id in `name`; the panel projects
            # it as the typed status label instead of a generic "tool".
            "name": entry.payload.get("name"),
            "stop_reason": entry.payload.get("stop_reason"),
            "error": entry.payload.get("error"),
        }
        if isinstance(entry.payload.get("reasoning_content"), str) and entry.payload["reasoning_content"].strip():
            # Folded beside its step at the person's request (2026-10-31); events never carry it.
            message["reasoning"] = entry.payload["reasoning_content"]
        if isinstance(entry.payload.get("numeric_check"), dict):
            message["numeric_check"] = entry.payload["numeric_check"]
        # A legacy/corrupt entry must not make the whole session unreadable.
        message["navigation"] = [link.to_dict() for link in links.get(entry.entry_id) or ()]
        result.append(message)
    return result


def _context_usage(repository: JsonlSessionRepository, session_id: str, config) -> dict[str, Any]:
    """The next request's size as the server builds it (tools not included)."""

    policy = CompactionPolicy.from_config(config.context_window_tokens, supports_1m=config.supports_1m)
    try:
        messages = ContextBuilder(repository).build(session_id).messages
    except (KeyError, ValueError):
        messages = []
    return {
        "estimated_tokens": estimate_messages_tokens(messages),
        "window_tokens": policy.window,
        "window_declared": policy.window_declared,
        "compact_at_tokens": policy.threshold,
    }


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
        "execution_mode": metadata.get("execution_mode", "ask"),
        "role": metadata.get("role"),
        "chain_id": metadata.get("chain_id"),
        "status": metadata.get("status"),
        "context_fingerprint": _context_fingerprint(repository, session_id),
        "model": config.model or None,
        "provider_id": config.provider_id or None,
        "context_window_tokens": config.context_window_tokens,
        "context": _context_usage(repository, session_id, config),
        "messages": _messages(repository, session_id),
        "proposals": _public_proposals(proposal_store, session_id),
        "chapters": [
            {"entry_id": str(chapter["entry_id"]), "title": str(chapter["title"]), "at": str(chapter["at"])}
            for chapter in metadata.get("chapters") or []
        ],
    }


def _public_proposals(store: ProposalStore, session_id: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for revision in store.latest_revisions_for_session(session_id):
        proposal = revision.to_dict()
        proposal["status"] = store.latest_status(revision.proposal_id)
        # The session's list is what the transcript cards show, confirmed and
        # executed ones included: sentences there too, not raw steps.
        proposal["readable"] = proposal_lines(proposal, _proposal_labels(store, proposal))
        confirmation = store.latest_confirmation(revision.proposal_id)
        if confirmation is not None:
            proposal["confirmation"] = confirmation.to_dict()
        decision = store.latest_decision(revision.proposal_id)
        if decision is not None:
            proposal["decision"] = decision.to_dict()
        proposals.append(proposal)
    return proposals


def _proposal_labels(store: ProposalStore, proposal: dict[str, Any]) -> dict[str, str]:
    run_id = (proposal.get("target") or {}).get("run_id")
    if not run_id:
        return {}
    try:
        # ProposalStore lives under <project>/workbench.
        labels = run_labels(Path(store.root).parent, str(run_id))
    except (OSError, ValueError):
        return {}
    variable_labels = labels.get("variable_labels")
    return dict(variable_labels) if isinstance(variable_labels, dict) else {}

