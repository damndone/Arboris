"""Conversation compaction for the Agent (design: specs/2026-10-14-v1.9.0-agent-context-design.md).

The Agent resends its conversation every step. When the estimate nears the
model's window, the older part of the conversation is replaced by a summary
written by the model and the newest part is kept verbatim (after pi's
compaction). Standing messages -- protocol, identity, focus, instructions,
the Workbench context -- are never summarized.

What is specific to statistics: a summary's numbers become evidence for the
numeric check on later turns, so the summary is checked against the messages
it replaces. A summary that keeps an unsupported number after one rewrite is
stored as unverified and does not count as evidence.

Nothing is deleted. A ``compaction`` entry records the summary and the first
entry kept; :class:`ContextBuilder` projects the branch through it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from . import numeric_grounding
from .model import ModelAdapter, ModelRequest
from .session import JsonlSessionRepository, SessionTreeEntry

# pi's defaults: room for the reply, and the newest part kept word for word.
RESERVE_TOKENS = 16_384
KEEP_RECENT_TOKENS = 20_000
# Used only when the configured model declares no window; reported as an
# assumption, never as the model's real window. 64 000 left ~10 000 tokens for
# the conversation once the protocol (~21 000) and tools were in, so a live
# five-turn conversation compacted twice (2026-10-14). Current models take at
# least 128 000; a smaller real window is caught by the provider's refusal,
# which compacts and retries once.
ASSUMED_WINDOW_TOKENS = 128_000
# Compact well before a very large window fills: a request near DeepSeek's
# 1 048 576-token limit took 19 s just to read (measured 2026-10-14), every
# step pays for all of it, and answers degrade in very long contexts.
WORKING_BUDGET_TOKENS = 200_000
WORKING_BUDGET_ENV = "WORKBENCH_AGENT_COMPACT_AT"
TOOL_RESULT_CHARS = 2_000
SUMMARY_MAX_TOKENS = 4_096

SUMMARY_NAME = "context_compaction"
UNVERIFIED_SUMMARY_NAME = numeric_grounding.UNVERIFIED_SUMMARY_NAME

# Messages that state the Agent's standing situation rather than the
# conversation. Each is superseded by its own latest copy.
STANDING_NAMES = frozenset({
    "workbench_agent_protocol",
    "workbench_global_agent_protocol",
    "workbench_agent_identity",
    "workbench_agent_focus",
    "workbench_context",
    "workbench_instructions",
    "workbench_project_recall",
})

_CJK = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")


def estimate_text_tokens(text: str) -> int:
    """A deliberately high estimate: one token per CJK character, ~3.5
    characters per token otherwise (JSON and numbers tokenise densely)."""

    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    return cjk + math.ceil((len(text) - cjk) / 3.5)


def estimate_message_tokens(message: Mapping[str, Any]) -> int:
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    total = estimate_text_tokens(text) + 4
    if message.get("tool_calls"):
        total += estimate_text_tokens(json.dumps(message["tool_calls"], ensure_ascii=False))
    return total


def estimate_messages_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


ONE_MILLION = 1_000_000


def declared_window(window_tokens: int | None, supports_1m: bool) -> int | None:
    """A model's window as configured: the number, else the 1M flag."""

    return window_tokens or (ONE_MILLION if supports_1m else None)


@dataclass(frozen=True)
class CompactionPolicy:
    """When to compact, from the configured model's window."""

    window_tokens: int | None
    reserve_tokens: int = RESERVE_TOKENS
    keep_recent_tokens: int = KEEP_RECENT_TOKENS
    enabled: bool = True
    budget_tokens: int = WORKING_BUDGET_TOKENS

    @classmethod
    def from_config(cls, window_tokens: int | None, *, supports_1m: bool = False) -> "CompactionPolicy":
        """The policy for a configured model: its declared window, else the
        1M flag the model carries in Settings (as the context ring reads it),
        with the working budget from the environment when set (a whole number
        of tokens, at least 8 000)."""

        import os

        raw = os.environ.get(WORKING_BUDGET_ENV, "").strip().replace("_", "")
        budget = int(raw) if raw.isdigit() and int(raw) >= 8_000 else WORKING_BUDGET_TOKENS
        return cls(declared_window(window_tokens, supports_1m), budget_tokens=budget)

    @property
    def window(self) -> int:
        return self.window_tokens or ASSUMED_WINDOW_TOKENS

    @property
    def window_declared(self) -> bool:
        return bool(self.window_tokens)

    @property
    def reserve(self) -> int:
        # A small window still needs room for the reply and for what is kept.
        return min(self.reserve_tokens, self.window // 4)

    @property
    def keep_recent(self) -> int:
        return min(self.keep_recent_tokens, self.window // 4)

    @property
    def threshold(self) -> int:
        return min(self.window - self.reserve, self.budget_tokens)

    def should_compact(self, context_tokens: int) -> bool:
        return self.enabled and context_tokens > self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_tokens": self.window,
            "window_declared": self.window_declared,
            "reserve_tokens": self.reserve,
            "keep_recent_tokens": self.keep_recent,
            "working_budget_tokens": self.budget_tokens,
            "threshold_tokens": self.threshold,
        }


# ---------------------------------------------------------------------------
# Projection


def is_standing(entry: SessionTreeEntry) -> bool:
    return entry.entry_type == "custom_message" and entry.payload.get("name") in STANDING_NAMES


def latest_compaction(branch: Sequence[SessionTreeEntry]) -> tuple[int, SessionTreeEntry] | None:
    for index in range(len(branch) - 1, -1, -1):
        if branch[index].entry_type == "compaction":
            return index, branch[index]
    return None


def live_start(branch: Sequence[SessionTreeEntry]) -> int:
    """Index of the first entry the latest compaction kept (0 without one)."""

    found = latest_compaction(branch)
    if found is None:
        return 0
    index, entry = found
    first_kept = entry.payload.get("first_kept_entry_id")
    for position, candidate in enumerate(branch):
        if candidate.entry_id == first_kept:
            return position
    return index + 1


# ---------------------------------------------------------------------------
# Choosing what to summarize


@dataclass(frozen=True)
class CutPlan:
    """Entries ``summarize`` are replaced by the summary; ``first_kept`` onward stay."""

    summarize: tuple[SessionTreeEntry, ...]
    first_kept: SessionTreeEntry | None
    previous_summary: str | None
    previous_verified: bool


def _entry_message(entry: SessionTreeEntry) -> dict[str, Any] | None:
    payload = entry.payload
    if entry.entry_type == "message" and isinstance(payload.get("content"), str):
        return {key: value for key, value in payload.items() if key not in {"stop_reason", "command_id"}}
    if entry.entry_type == "custom_message" and payload.get("audience", "model") == "model":
        content = payload.get("content")
        if isinstance(content, str):
            return {"role": "system", "content": content, "name": payload.get("name", "workbench")}
    return None


def plan_cut(branch: Sequence[SessionTreeEntry], keep_recent_tokens: int) -> CutPlan | None:
    """Keep the newest ``keep_recent_tokens`` and cut at a user message before them.

    A user message is the only cut point, so an assistant's tool call never
    loses its result. Without a user message to cut at, there is nothing to
    compact.
    """

    start = live_start(branch)
    found = latest_compaction(branch)
    previous_summary = found[1].payload.get("summary") if found else None
    previous_verified = bool(found[1].payload.get("verified", True)) if found else True
    live = [entry for entry in branch[start:] if not is_standing(entry) and entry.entry_type != "compaction"]
    user_positions = [
        position for position, entry in enumerate(live)
        if entry.entry_type == "message" and entry.payload.get("role") == "user"
    ]
    if len(user_positions) < 2:
        return None
    kept_tokens = 0
    cut = None
    for position in range(len(live) - 1, -1, -1):
        message = _entry_message(live[position])
        kept_tokens += estimate_message_tokens(message) if message else 0
        if kept_tokens >= keep_recent_tokens:
            later = [user for user in user_positions if user > position]
            cut = later[0] if later else None
            break
    if cut is None:
        # Everything fits in the recent budget: keep only the latest exchange.
        cut = user_positions[-1]
    if cut <= 0:
        # The kept part would start at the first message: nothing older to summarize.
        cut = user_positions[-1] if user_positions[-1] > 0 else None
    if not cut:
        return None
    return CutPlan(
        summarize=tuple(live[:cut]),
        first_kept=live[cut],
        previous_summary=str(previous_summary) if isinstance(previous_summary, str) else None,
        previous_verified=previous_verified,
    )


# ---------------------------------------------------------------------------
# Writing the summary

SUMMARY_SYSTEM = """You write a checkpoint of a statistical analysis conversation between a person and the Workbench Agent, so that the Agent can continue it with only your summary and the most recent messages. You are not continuing the conversation: do not answer questions in it.

Write in the language the person writes in. Use exactly these sections, as Markdown headings, and leave a section out only when it has nothing:

## Research question and goal
What the person is trying to find out or build, in their terms, and what would count as done.
## Data and variables
Datasets and nodes in use (name and id), unit of observation, variables and how they are defined or transformed, known data issues.
## Analyses and results
What was run and what it showed. Every number must be copied exactly as it appears in the conversation, next to the id of the run, model, step or artifact it came from. Do not round, convert, or compute new numbers. If you are unsure of a number, leave it out and name where it can be inspected again.
## Decisions and preferences
Choices made and why (specification, covariance, sample, validation scheme), and the person's stated preferences and constraints.
## Proposals
Each proposal or operation: id, what it changes, and whether it is pending, confirmed, executed, declined or failed.
## Open questions and next steps
What is unresolved, and what the person asked to do next.
## Critical context
Anything else the Agent must not lose (warnings given, limits stated, things the person corrected)."""


def serialize_for_summary(entries: Sequence[SessionTreeEntry]) -> str:
    """The conversation as a transcript, not as messages to continue (pi)."""

    lines: list[str] = []
    for entry in entries:
        payload = entry.payload
        if entry.entry_type == "message":
            role = payload.get("role")
            content = str(payload.get("content") or "")
            if role == "user":
                lines.append(f"[User]: {content}")
            elif role == "assistant":
                if payload.get("stop_reason") in {"aborted", "error"} and not content.strip():
                    continue
                if content.strip():
                    lines.append(f"[Assistant]: {content}")
                for call in payload.get("tool_calls") or []:
                    arguments = call.get("arguments")
                    lines.append(f"[Assistant tool call]: {call.get('tool_id') or call.get('name')} {json.dumps(arguments, ensure_ascii=False) if arguments is not None else ''}".rstrip())
            elif role == "tool":
                text = content
                if len(text) > TOOL_RESULT_CHARS:
                    text = f"{text[:TOOL_RESULT_CHARS]} [... {len(text) - TOOL_RESULT_CHARS} more characters; inspect again by id]"
                lines.append(f"[Tool result {payload.get('name') or ''}]: {text}")
        elif entry.entry_type == "custom_message" and payload.get("audience", "model") == "model":
            lines.append(f"[Workbench]: {payload.get('content')}")
    return "\n".join(lines)


def summary_request(plan: CutPlan, *, focus: str | None = None) -> list[dict[str, Any]]:
    parts: list[str] = []
    if plan.previous_summary:
        parts.append(
            "<previous-summary>\n"
            + plan.previous_summary
            + "\n</previous-summary>\nThe conversation below continues from that summary. Write one summary that covers both."
        )
    parts.append("<conversation>\n" + serialize_for_summary(plan.summarize) + "\n</conversation>")
    if focus:
        parts.append(f"The person asked the summary to keep in particular: {focus}")
    parts.append("Write the checkpoint summary now.")
    return [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]


def evidence_for(plan: CutPlan, standing: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What a summary's numbers may rest on: the replaced messages, a verified
    previous summary, and the standing context (the Agent's own replies are
    never evidence -- numeric_grounding drops them)."""

    messages = [message for entry in plan.summarize if (message := _entry_message(entry)) is not None]
    if plan.previous_summary and plan.previous_verified:
        messages.append({"role": "system", "content": plan.previous_summary, "name": SUMMARY_NAME})
    return list(standing) + messages


@dataclass
class CompactionResult:
    summary: str
    verified: bool
    unverified_numbers: list[str] = field(default_factory=list)
    attempts: int = 1


async def _complete(adapter: ModelAdapter, messages: list[dict[str, Any]], model_config: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    request = ModelRequest(messages=messages, tools=[], model_config=dict(model_config))
    async for event in adapter.stream(request):
        if event.type == "text_delta":
            chunks.append(event.delta)
        elif event.type == "error":
            raise CompactionError(event.error or "provider_error")
        elif event.type == "done":
            break
    text = "".join(chunks).strip()
    if not text:
        raise CompactionError("empty_summary")
    return text


class CompactionError(RuntimeError):
    """The summary could not be written; the conversation is left as it was."""


def summary_model_config(adapter: ModelAdapter) -> dict[str, Any]:
    """A bounded, non-thinking request where the provider supports it."""

    config = getattr(adapter, "planning_request_config", None)
    base = dict(config()) if callable(config) else {}
    base.setdefault("max_tokens", SUMMARY_MAX_TOKENS)
    return base


async def write_summary(
    adapter: ModelAdapter,
    plan: CutPlan,
    *,
    standing: Sequence[Mapping[str, Any]] = (),
    focus: str | None = None,
) -> CompactionResult:
    """Ask the model for the summary and check its numbers; one rewrite."""

    config = summary_model_config(adapter)
    messages = summary_request(plan, focus=focus)
    evidence = evidence_for(plan, standing)
    summary = await _complete(adapter, messages, config)
    findings = _unsupported(summary, evidence)
    if not findings:
        return CompactionResult(summary, True)
    retry = messages + [
        {"role": "assistant", "content": summary},
        {
            "role": "user",
            "content": (
                "These numbers in your summary do not appear in the conversation: "
                + ", ".join(findings)
                + ". Rewrite the summary copying numbers exactly from the conversation, or leave a number out and say where to inspect it."
            ),
        },
    ]
    summary = await _complete(adapter, retry, config)
    findings = _unsupported(summary, evidence)
    return CompactionResult(summary, not findings, findings, attempts=2)


def _unsupported(summary: str, evidence: Sequence[Mapping[str, Any]]) -> list[str]:
    # Only numbers: comparing groups is a rule for answers, not for a record of them.
    return [finding.text for finding in numeric_grounding.check(summary, evidence) if finding.kind == "number"]


def standing_messages(branch: Sequence[SessionTreeEntry]) -> list[dict[str, Any]]:
    latest: dict[str, SessionTreeEntry] = {}
    for entry in branch:
        if is_standing(entry):
            latest[str(entry.payload.get("name"))] = entry
    return [message for entry in latest.values() if (message := _entry_message(entry)) is not None]


async def compact(
    repository: JsonlSessionRepository,
    session_id: str,
    adapter: ModelAdapter,
    policy: CompactionPolicy,
    *,
    trigger: str,
    tokens_before: int,
    focus: str | None = None,
    model: str | None = None,
) -> SessionTreeEntry | None:
    """Summarize the older conversation and append a compaction entry.

    Returns None when there is nothing older than the kept part to summarize.
    """

    branch = repository.get_branch(session_id)
    plan = plan_cut(branch, policy.keep_recent)
    if plan is None or not plan.summarize or plan.first_kept is None:
        return None
    result = await write_summary(adapter, plan, standing=standing_messages(branch), focus=focus)
    entry = repository.append(
        session_id,
        "compaction",
        {
            "summary": result.summary,
            "first_kept_entry_id": plan.first_kept.entry_id,
            "summarized_entry_ids": [item.entry_id for item in plan.summarize],
            "tokens_before": tokens_before,
            "trigger": trigger,
            "verified": result.verified,
            "unverified_numbers": result.unverified_numbers,
            "attempts": result.attempts,
            "focus": focus,
            "model": model,
            "policy": policy.to_dict(),
        },
    )
    return entry
