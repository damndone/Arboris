"""Deterministic context construction for model requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .session import JsonlSessionRepository


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
        for entry in self.repository.get_branch(session_id, leaf_entry_id=leaf_entry_id):
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
                    messages.append({"role": "system", "content": content, "name": payload.get("name", "workbench")})
                    source_entry_ids.append(entry.entry_id)
            elif entry.entry_type == "compaction":
                summary = payload.get("summary")
                if isinstance(summary, str):
                    messages.append({"role": "system", "content": summary, "name": "context_compaction"})
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
