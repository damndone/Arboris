"""Deterministic context construction for model requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .compaction import SUMMARY_NAME, UNVERIFIED_SUMMARY_NAME, is_standing, latest_compaction, live_start
from .session import JsonlSessionRepository, SessionTreeEntry


@dataclass(frozen=True)
class CustomAgentMessage:
    """A durable message that can be projected into model context."""

    content: str
    audience: str = "model"
    name: str = "workbench"
    metadata: dict[str, Any] | None = None

    def to_entry_payload(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "audience": self.audience,
            "name": self.name,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class ContextSnapshot:
    messages: list[dict[str, Any]]
    fingerprint: str
    source_entry_ids: list[str]


class ContextBuilder:
    """Build model messages from a resolved branch without hidden truncation."""

    def __init__(self, repository: JsonlSessionRepository) -> None:
        self.repository = repository

    def build(
        self,
        session_id: str,
        *,
        leaf_entry_id: str | None = None,
        workbench_context: dict[str, Any] | None = None,
        include_failed_assistant_messages: bool = False,
    ) -> ContextSnapshot:
        messages: list[dict[str, Any]] = []
        source_entry_ids: list[str] = []
        shown_proposals: dict[str, dict[str, Any]] = {}
        branch = self.repository.get_branch(session_id, leaf_entry_id=leaf_entry_id)
        for entry in _project(branch):
            payload = dict(entry.payload)
            if entry.entry_type == "message":
                role = payload.get("role")
                content = payload.get("content")
                if not isinstance(role, str) or not isinstance(content, str):
                    continue
                if (
                    role == "assistant"
                    and payload.get("stop_reason") in {"aborted", "error"}
                    and not include_failed_assistant_messages
                ):
                    continue
                if role == "tool" and '"proposal_id"' in content:
                    _note_tool_proposal(content, shown_proposals)
                messages.append({
                    key: value
                    for key, value in payload.items()
                    if key not in {"stop_reason", "command_id"}
                })
                source_entry_ids.append(entry.entry_id)
            elif entry.entry_type == "custom_message":
                if payload.get("audience", "model") != "model":
                    continue
                content = payload.get("content")
                if isinstance(content, str):
                    # A server message that asks the model to act now (e.g. the
                    # numeric check's rewrite request) opens a new turn as a user
                    # message: providers with private reasoning refuse a second
                    # answer inside a turn that already used tools.
                    role = "user" if payload.get("model_role") == "user" else "system"
                    content = _proposal_record_content(payload, content, shown_proposals)
                    messages.append({"role": role, "content": content, "name": payload.get("name", "workbench")})
                    source_entry_ids.append(entry.entry_id)
            elif entry.entry_type == "compaction":
                summary = payload.get("summary")
                if isinstance(summary, str):
                    verified = payload.get("verified", True) is not False
                    messages.append({
                        "role": "system",
                        "content": (
                            "Summary of the earlier part of this conversation (the messages it replaces "
                            "are still on record; inspect results again by id when you need detail):\n"
                            + summary
                            if verified
                            else "Summary of the earlier part of this conversation. Some numbers in it could "
                            "not be matched to the conversation, so do not cite numbers from it: inspect "
                            "them again by id.\n" + summary
                        ),
                        "name": SUMMARY_NAME if verified else UNVERIFIED_SUMMARY_NAME,
                    })
                    source_entry_ids.append(entry.entry_id)

        if workbench_context:
            messages.append(
                {
                    "role": "system",
                    "content": json.dumps(workbench_context, ensure_ascii=False, sort_keys=True),
                    "name": "workbench_context",
                }
            )
        serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return ContextSnapshot(messages=messages, fingerprint=fingerprint, source_entry_ids=source_entry_ids)


# Proposal audit messages repeat the proposal the model already received in its
# run_operation tool result (the changes up to four times per confirmation). The
# projection keeps every field whose value is new for that proposal and names
# the rest; the stored audit record stays complete.
_PROPOSAL_RECORD_FIELDS = {"operation_proposal": "proposal", "operation_proposal_revision": "proposal",
                           "operation_confirmation": "confirmation"}
_PROPOSAL_IDENTITY = ("record_type", "proposal_id", "revision", "fingerprint", "status")


def _note_tool_proposal(content: str, shown: dict[str, dict[str, Any]]) -> None:
    try:
        output = json.loads(content).get("output")
    except (ValueError, AttributeError):
        return
    proposal = output.get("proposal") if isinstance(output, dict) else None
    if isinstance(proposal, dict) and isinstance(proposal.get("proposal_id"), str):
        shown[proposal["proposal_id"]] = {**shown.get(proposal["proposal_id"], {}), **proposal}


def _proposal_record_content(payload: dict[str, Any], content: str, shown: dict[str, dict[str, Any]]) -> str:
    record = payload.get(_PROPOSAL_RECORD_FIELDS.get(payload.get("message_type"), ""))
    if not isinstance(record, dict) or not isinstance(record.get("proposal_id"), str):
        return content
    if content != json.dumps(record, ensure_ascii=False, sort_keys=True):
        return content  # already bounded to a summary
    prior = shown.get(record["proposal_id"])
    shown[record["proposal_id"]] = {**(prior or {}), **record}
    if prior is None or prior.get("fingerprint") != record.get("fingerprint"):
        return content
    compact = {key: value for key, value in record.items() if key in _PROPOSAL_IDENTITY or prior.get(key) != value}
    if len(compact) == len(record):
        return content
    compact["repeated_fields"] = sorted(set(record) - set(compact))
    compact["repeated_fields_note"] = "Same values as already shown above for this proposal and fingerprint."
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)


_STANDING_ORDER = {name: index for index,name in enumerate([
    "workbench_global_agent_protocol", "workbench_agent_protocol", "workbench_agent_identity",
    "workbench_instructions", "workbench_context", "workbench_agent_focus", "workbench_project_recall",
])}


def _project(branch: list[SessionTreeEntry]) -> list[SessionTreeEntry]:
    """Latest standing layers lead a stable prefix; dialogue keeps its order."""
    latest = {str(entry.payload.get("name")):entry for entry in branch if is_standing(entry)}
    head = sorted(latest.values(),key=lambda entry:_STANDING_ORDER[str(entry.payload["name"])])
    found = latest_compaction(branch)
    start = live_start(branch) if found is not None else 0
    tail = [entry for entry in branch[start:] if entry.entry_type != "compaction" and not is_standing(entry)]
    return [*head,*([found[1]] if found is not None else []),*tail]
