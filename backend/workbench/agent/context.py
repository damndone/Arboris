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


def _project(branch: list[SessionTreeEntry]) -> list[SessionTreeEntry]:
    """The branch as the model sees it after the latest compaction.

    Without one, every entry (unchanged behaviour). With one: the latest copy
    of each standing message that precedes the kept part, then the summary,
    then everything from the first kept entry on. Older conversation and
    earlier summaries are on record but not resent.
    """

    found = latest_compaction(branch)
    if found is None:
        return branch
    _, compaction_entry = found
    start = live_start(branch)
    latest_standing: dict[str, SessionTreeEntry] = {}
    for entry in branch:
        if is_standing(entry):
            latest_standing[str(entry.payload.get("name"))] = entry
    position = {entry.entry_id: index for index, entry in enumerate(branch)}
    head = sorted(
        (entry for entry in latest_standing.values() if position[entry.entry_id] < start),
        key=lambda entry: position[entry.entry_id],
    )
    tail = [
        entry for entry in branch[start:]
        if entry.entry_type != "compaction"
        and not (is_standing(entry) and latest_standing.get(str(entry.payload.get("name"))) is not entry)
    ]
    return [*head, compaction_entry, *tail]
