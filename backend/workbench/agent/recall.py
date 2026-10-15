"""Recall of this project's earlier conversations (no global memory).

Projects differ, so nothing learned in one is carried into another. Within a
project, a new conversation is told which earlier conversations exist (a
short index, as a standing message) and can search and read them with two
read-only tools -- Hermes' ``session_search``, scoped to the project, the way
Codex and Claude Code read what is on disk in the workspace.

Only what the person wrote, the Agent's replies and conversation summaries
are searchable. Tool results are not: they may hold data that the sharing
policy kept from the provider when they were produced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .session import JsonlSessionRepository, SessionTreeEntry

RECALL_NAME = "workbench_project_recall"
INDEX_LIMIT = 8
SEARCH_LIMIT = 8
SNIPPET_CHARS = 320
READ_CHARS = 8_000

_CJK_RUN = re.compile(r"[㐀-䶿一-鿿]+")
_WORD = re.compile(r"[A-Za-z0-9_.%-]+")


@dataclass(frozen=True)
class Passage:
    session_id: str
    entry_id: str
    role: str
    at: str
    text: str


def _passage(session_id: str, entry: SessionTreeEntry) -> Passage | None:
    payload = entry.payload
    if entry.entry_type == "message" and payload.get("role") in {"user", "assistant"}:
        text = payload.get("content")
        if isinstance(text, str) and text.strip():
            return Passage(session_id, entry.entry_id, str(payload["role"]), entry.created_at, text)
    if entry.entry_type == "compaction" and isinstance(payload.get("summary"), str):
        return Passage(session_id, entry.entry_id, "summary", entry.created_at, payload["summary"])
    return None


def _conversations(repository: JsonlSessionRepository) -> Iterable[tuple[dict[str, Any], list[Passage]]]:
    for metadata in repository.list_metadata():
        session_id = str(metadata.get("session_id") or "")
        try:
            branch = repository.get_branch(session_id)
        except (KeyError, ValueError, OSError):
            continue
        passages = [passage for entry in branch if (passage := _passage(session_id, entry)) is not None]
        if any(passage.role == "user" for passage in passages):
            yield metadata, passages


def _line(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def conversation_index(repository: JsonlSessionRepository, *, exclude: str | None = None, limit: int = INDEX_LIMIT) -> list[dict[str, Any]]:
    """Earlier conversations, most recently active first."""

    items: list[dict[str, Any]] = []
    for metadata, passages in _conversations(repository):
        session_id = str(metadata["session_id"])
        if session_id == exclude or metadata.get("archived"):
            continue  # archived: still searchable, no longer listed
        users = [passage for passage in passages if passage.role == "user" and passage.session_id == session_id] or [
            passage for passage in passages if passage.role == "user"
        ]
        items.append({
            "session_id": session_id,
            "role": metadata.get("role"),
            "started": str(metadata.get("created_at") or users[0].at)[:10],
            "last_active": passages[-1].at,
            "title": str(metadata.get("title") or "") or _line(users[0].text, 80),
            "last_question": _line(users[-1].text, 80),
            "messages": len(passages),
            "chapters": [str(chapter.get("title")) for chapter in metadata.get("chapters") or []][:5],
        })
    items.sort(key=lambda item: item["last_active"], reverse=True)
    return items[:limit]


def index_text(items: list[dict[str, Any]]) -> str:
    lines = [
        "Earlier conversations in this project, most recent first. They are not in your context. "
        "When one is relevant to the request, use search_project_conversations or read_project_conversation, "
        "say that you looked, and treat what it says as a record of what was said, not as verified results: "
        "inspect numbers again with the evidence tools."
    ]
    for item in items:
        chapters = f"; chapters: {', '.join(item['chapters'])}" if item["chapters"] else ""
        last = f'; last asked: "{item["last_question"]}"' if item["last_question"] != item["title"] else ""
        lines.append(f'- {item["started"]} "{item["title"]}" ({item["messages"]} messages{last}{chapters}) [{item["session_id"]}]')
    return "\n".join(lines)


def _terms(query: str) -> list[str]:
    terms = [word.casefold() for word in _WORD.findall(query) if len(word) > 1]
    for run in _CJK_RUN.findall(query):
        # Chinese has no spaces: two-character pieces match a phrase anywhere.
        terms.extend(run[index:index + 2] for index in range(max(len(run) - 1, 1)))
    return list(dict.fromkeys(terms))


def search(repository: JsonlSessionRepository, query: str, *, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
    """Passages that share the most terms with the query, newest first on ties."""

    terms = _terms(query)
    if not terms:
        return []
    seen: set[str] = set()
    scored: list[tuple[int, str, Passage]] = []
    for _, passages in _conversations(repository):
        for passage in passages:
            if passage.entry_id in seen:
                continue  # a forked conversation shares its parent's entries
            seen.add(passage.entry_id)
            folded = passage.text.casefold()
            score = sum(1 for term in terms if term in folded)
            if score:
                scored.append((score, passage.at, passage))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    hits = []
    for score, _, passage in scored[:limit]:
        folded = passage.text.casefold()
        first = min((folded.find(term) for term in terms if term in folded), default=0)
        start = max(first - SNIPPET_CHARS // 3, 0)
        snippet = passage.text[start:start + SNIPPET_CHARS]
        hits.append({
            "session_id": passage.session_id,
            "entry_id": passage.entry_id,
            "role": passage.role,
            "at": passage.at,
            "matched_terms": score,
            "snippet": ("…" if start else "") + " ".join(snippet.split()) + ("…" if start + SNIPPET_CHARS < len(passage.text) else ""),
        })
    return hits


def read(
    repository: JsonlSessionRepository,
    session_id: str,
    *,
    around_entry_id: str | None = None,
    before: int = 4,
    after: int = 4,
) -> dict[str, Any]:
    """Messages of one conversation, around an entry or from its start."""

    conversations = {str(metadata["session_id"]): passages for metadata, passages in _conversations(repository)}
    if session_id not in conversations:
        raise KeyError(f"no conversation {session_id!r} in this project")
    passages = conversations[session_id]
    centre = next((index for index, passage in enumerate(passages) if passage.entry_id == around_entry_id), None)
    if around_entry_id is not None and centre is None:
        raise KeyError(f"entry {around_entry_id!r} is not in conversation {session_id!r}")
    start = max((centre or 0) - before, 0) if centre is not None else 0
    end = min((centre if centre is not None else 0) + after + 1, len(passages)) if centre is not None else min(before + after + 1, len(passages))
    budget = READ_CHARS
    messages = []
    for passage in passages[start:end]:
        text = passage.text if len(passage.text) <= budget else passage.text[:budget] + " […cut]"
        budget -= len(text)
        messages.append({"entry_id": passage.entry_id, "role": passage.role, "at": passage.at, "content": text})
        if budget <= 0:
            break
    return {
        "session_id": session_id,
        "messages": messages,
        "earlier_messages": start,
        "later_messages": max(len(passages) - end, 0),
    }
