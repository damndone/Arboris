"""Node-level Ask AI route (v1.6.11 slice A).

``POST /llm/chat`` — advisory-only Q&A over the frontend's sanitized
``ask-ai-context/v1`` packet. The model sees exactly what the packet carries
(previews already truncated client-side); guardrails are restated server-side
in the system prompt. The response is text plus provenance
(``model`` + echoed ``context_fingerprint``) — the seed of the typed,
inspectable AI-operation record targeted for the report slice and v1.7.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..api_errors import WorkbenchAPIError
from ..llm import (
    LLMNotConfiguredError,
    LLMUpstreamError,
    chat_completion,
    load_llm_config,
)

router = APIRouter()

SUPPORTED_MODE = "workbench_node_context_v1"
REPORT_MODE = "workbench_report_v1"
MAX_QUESTION_CHARS = 4_000

# v1.6.11 slice C — cite-chip report generation. The packet carries a
# deterministic fact_table built client-side from the lineage contexts; the
# model may only reference numbers through [[c:ID]] markers, and the client
# renders every marker from ITS OWN table (never from model output), so a
# hallucinated number cannot become a chip.
_REPORT_PROMPT_HEADER = (
    "You are the report writer of a local econometrics workbench. The JSON "
    "packet below contains a fact_table: the ONLY numbers you may use. Each "
    "fact has an id.\n"
    "Hard rules (non-negotiable):\n"
    "- Write a structured empirical report in Markdown with these sections: "
    "Title (# heading), Data, Methods, Results, Limitations.\n"
    "- Every number, parameter value or decision you mention MUST come from "
    "the fact_table and MUST be immediately followed by its citation marker "
    "in the exact form [[c:ID]] (e.g. 'R² of 0.86 [[c:c12]]').\n"
    "- Never invent, round differently, or combine numbers not present in "
    "the fact_table. If something is missing, name the gap in Limitations "
    "instead of guessing.\n"
    "- Advisory text only: no executable actions, no code, no backend payloads.\n"
    "- Write in the language of the user's instruction."
)

_SYSTEM_PROMPT_HEADER = (
    "You are the node assistant of a local econometrics workbench. The user "
    "selected one node of a lineage graph (data -> cleaning -> model -> "
    "diagnostics); the JSON context packet below describes that node, its "
    "upstream path, parameters, metrics and artifact previews.\n"
    "Hard rules (non-negotiable):\n"
    "- Advisory text only. Never output executable actions, code to mutate "
    "the graph, or backend payloads.\n"
    "- Ground every number you cite in the packet. If the packet does not "
    "contain the answer, say so instead of guessing.\n"
    "- The packet holds truncated previews, not full datasets or reports. "
    "Disclose this limit whenever it affects your answer.\n"
    "- Answer in the language the user asked in."
)


class AskAIChatRequest(BaseModel):
    mode: str
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    packet: dict[str, Any]
    response_guardrails: dict[str, Any] | None = None


@router.post("/llm/chat")
def llm_chat(request: AskAIChatRequest) -> dict[str, Any]:
    if request.mode not in (SUPPORTED_MODE, REPORT_MODE):
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_UNSUPPORTED_MODE",
            message=f"Unsupported mode: {request.mode!r}",
            details={"supported_modes": [SUPPORTED_MODE, REPORT_MODE]},
        )
    if request.question.strip() == "":
        raise WorkbenchAPIError(
            status_code=422,
            code="LLM_CHAT_EMPTY_QUESTION",
            message="Question must not be blank",
        )

    config = load_llm_config()
    messages = [
        {"role": "system", "content": _build_system_prompt(request)},
        {"role": "user", "content": request.question},
    ]
    try:
        result = chat_completion(messages, config)
    except LLMNotConfiguredError as exc:
        raise WorkbenchAPIError(
            status_code=503, code="LLM_NOT_CONFIGURED", message=str(exc)
        ) from exc
    except LLMUpstreamError as exc:
        raise WorkbenchAPIError(
            status_code=502,
            code="LLM_UPSTREAM_ERROR",
            message=str(exc),
            details={"upstream_status": exc.upstream_status},
        ) from exc

    return {
        "text": result["text"],
        "model": result["model"],
        "context_fingerprint": request.packet.get("context_fingerprint"),
    }


def _build_system_prompt(request: AskAIChatRequest) -> str:
    header = _REPORT_PROMPT_HEADER if request.mode == REPORT_MODE else _SYSTEM_PROMPT_HEADER
    sections = [header]
    guardrails = request.response_guardrails or request.packet.get("response_guardrails")
    if guardrails:
        sections.append(
            "Client-declared guardrails (all must hold):\n"
            + json.dumps(guardrails, ensure_ascii=False, sort_keys=True)
        )
    sections.append(
        "Context packet:\n" + json.dumps(request.packet, ensure_ascii=False)
    )
    return "\n\n".join(sections)
