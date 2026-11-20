"""agent route projection: extracted HTTP responsibility."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any
from ..agent.compaction import CompactionPolicy, estimate_messages_tokens, estimate_text_tokens
from ..agent.context import ContextBuilder
from ..agent.navigation import AgentNavigationProjector
from ..agent.operations import OperationRegistry, UnknownOperationError
from ..agent.proposals import ProposalStore
from ..agent.session import JsonlSessionRepository
from ..agent.proposal_text import proposal_lines
from ..agent.tool_activity import describe_tool_call
from ..api_errors import WorkbenchAPIError
from ..services.dataset_view import run_labels
from .agent_route_permissions import _session_grant_class

def _seconds_between(start: Any, end: str) -> float | None:
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


#: The only entry types whose payloads the transcript reads; checkpoints and receipts
#: (most of a long log) are not parsed for it.
_TRANSCRIPT_PAYLOAD_TYPES = frozenset({"tool_intent", "compaction", "custom_message", "message"})
_CUSTOM_MESSAGE = frozenset({"custom_message"})


def _messages(repository: JsonlSessionRepository, session_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []  # shown on the message they came with
    projector = AgentNavigationProjector(repository.root.parent)
    branch = repository.get_branch(session_id, payload_entry_types=_TRANSCRIPT_PAYLOAD_TYPES)
    try:
        links = projector.entry_links(session_id, [entry for entry in branch if entry.entry_type == "message"])
    except (KeyError, ValueError):
        links = {}
    calls: dict[str, Any] = {}  # tool_call_id -> the call, for describing its result
    started: dict[str, Any] = {}  # tool_call_id -> when the tool began
    for entry in branch:
        if entry.entry_type == "tool_intent" and isinstance(entry.payload.get("tool_call"), dict):
            started[str(entry.payload["tool_call"].get("tool_call_id"))] = entry.created_at
            continue
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
        if entry.entry_type == "custom_message" and isinstance(entry.payload.get("attachment"), dict):
            attachments.append(entry.payload["attachment"])
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
        for call in entry.payload.get("tool_calls") or ():
            if isinstance(call, dict):
                calls[str(call.get("tool_call_id"))] = call
        if role == "tool":
            call_id = str(entry.payload.get("tool_call_id"))
            message["activity"] = {
                "target": describe_tool_call(str(entry.payload.get("name")), (calls.get(call_id) or {}).get("arguments")),
                "seconds": _seconds_between(started.get(call_id), entry.created_at),
            }
        if role == "user" and attachments:
            message["attachments"] = attachments
            attachments = []
        if isinstance(entry.payload.get("reasoning_content"), str) and entry.payload["reasoning_content"].strip():
            # Folded beside its step at the person's request (2026-10-31); events never carry it.
            message["reasoning"] = entry.payload["reasoning_content"]
        for check in ("numeric_check", "method_check"):
            if isinstance(entry.payload.get(check), dict):
                message[check] = entry.payload[check]
        # A legacy/corrupt entry must not make the whole session unreadable.
        message["navigation"] = [link.to_dict() for link in links.get(entry.entry_id) or ()]
        result.append(message)
    return result


def _context_breakdown(messages) -> list[dict[str, Any]]:
    """What the next request holds, by kind, for the context panel."""

    totals: dict[str, int] = {}

    def add(label: str, tokens: int) -> None:
        if tokens > 0:
            totals[label] = totals.get(label, 0) + tokens

    for message in messages:
        tokens = estimate_messages_tokens([message])
        name = str(message.get("name") or "")
        thinking = message.get("reasoning_content")
        if isinstance(thinking, str):
            used = estimate_text_tokens(thinking)
            add("Thinking", used)
            tokens -= used
        if message.get("role") == "tool":
            add("Tool results", tokens)
        elif "protocol" in name:
            add("System prompt", tokens)
        elif "skill" in name:
            add("Skills", tokens)
        elif "memory" in name:
            add("Memory", tokens)
        elif name:
            add("Workbench context", tokens)
        else:
            add("Messages", tokens)
    return [{"label": label, "tokens": tokens} for label, tokens in sorted(totals.items(), key=lambda kv: -kv[1])]


def _context_usage(repository: JsonlSessionRepository, session_id: str, config) -> dict[str, Any]:
    """The next request's size as the server builds it (tools not included)."""

    policy = CompactionPolicy.from_config(config.context_window_tokens, supports_1m=config.supports_1m,
                                         explicit_limit=getattr(config, "context_limit_tokens", None))
    try:
        messages = ContextBuilder(repository).build(session_id).messages
    except (KeyError, ValueError):
        messages = []
    return {
        "breakdown": _context_breakdown(messages),
        "estimated_tokens": estimate_messages_tokens(messages),
        "window_tokens": policy.window,
        "window_declared": policy.window_declared,
        "compact_at_tokens": policy.threshold,
    }


def _context_fingerprint(repository: JsonlSessionRepository, session_id: str) -> str | None:
    for entry in repository.get_branch(session_id, payload_entry_types=_CUSTOM_MESSAGE):
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
    *,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``messages`` is ``_messages(repository, session_id)`` when the caller has just built it."""
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
        "messages": _messages(repository, session_id) if messages is None else messages,
        "proposals": _public_proposals(proposal_store, session_id),
        "chapters": [
            {"entry_id": str(chapter["entry_id"]), "title": str(chapter["title"]), "at": str(chapter["at"])}
            for chapter in metadata.get("chapters") or []
        ],
    }


def _public_proposals(store: ProposalStore, session_id: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    registry = None
    for revision in store.latest_revisions_for_session(session_id):
        status = store.latest_status(revision.proposal_id)
        if status == "plan_prepared":
            continue
        if status == "pending" and registry is None:
            registry = OperationRegistry()
        proposals.append(_proposal_view(store, revision, status, registry))
    return proposals


def _proposal_view(store, revision, status, registry=None):
    proposal = revision.to_dict()
    proposal["status"] = status
    proposal["readable"] = proposal_lines(proposal, _proposal_labels(store, proposal))
    confirmation = store.latest_confirmation(revision.proposal_id)
    if confirmation is not None:
        proposal["confirmation"] = confirmation.to_dict()
    decision = store.latest_decision(revision.proposal_id)
    if decision is not None:
        proposal["decision"] = decision.to_dict()
    if status == "pending":
        repository = JsonlSessionRepository(store.root, create=False)
        try:
            cls = _session_grant_class(repository, registry or OperationRegistry(), revision,
                                       repository.get_metadata(revision.session_id))
        except (UnknownOperationError, KeyError, ValueError, WorkbenchAPIError):
            cls = None
        if cls is not None:
            proposal["session_grant_class"] = cls
    return proposal


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

