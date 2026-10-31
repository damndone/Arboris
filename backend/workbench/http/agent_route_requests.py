"""agent route requests: extracted HTTP responsibility."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from .agent_route_runtime import (MAX_QUESTION_CHARS)

class AgentFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["project", "dataset", "node", "plan", "report"]
    id: str = Field(max_length=512)
    run_id: str | None = Field(default=None, max_length=200)
    label: str = Field(max_length=300)


class AgentSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["main", "chain"] = "chain"
    chain_id: str | None = None
    run_id: str | None = None
    context_packet: dict[str, Any] = Field(default_factory=dict)
    # What the Agent is about (frontend agent/focus.ts): recorded with the
    # session and told to the model, so its answers name the same object the
    # panel's focus label shows.
    focus: AgentFocus | None = None


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    execution_policy: Literal["auto_read_only", "proposal_only"] = "auto_read_only"
    # v1.9.1: "ask" every step, or "auto" within the approved plan.
    execution_mode: Literal["ask", "auto"] = "ask"
    attachments: list[str] = Field(default_factory=list, max_length=8)
    # The panel's current project context. A Main session's overview was
    # written once, at creation, so runs made afterwards (a metadata edit, a
    # rerun) were invisible and the Agent kept reading the old run.
    context_packet: dict[str, Any] | None = None


class AgentContinueRequest(BaseModel):
    """Continue the Agent after something happened outside a turn (v1.9.1).

    In Ask every step a confirmed proposal runs between turns; this resumes the
    Agent with the outcome so the person never has to say "continue".
    """

    model_config = ConfigDict(extra="forbid")

    execution_policy: Literal["auto_read_only", "proposal_only"] = "auto_read_only"
    # v1.9.1: "ask" every step, or "auto" within the approved plan.
    execution_mode: Literal["ask", "auto"] = "ask"
    context_packet: dict[str, Any] | None = None


class AgentProposalConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    fingerprint: str = Field(min_length=1)
    active_head_run_id: str = Field(min_length=1)
    confirmed_payload_hash: str | None = Field(default=None, min_length=1)
    # v1.9.1 "don't ask again in this conversation": later proposals of the
    # same permission class run without a card. Never covers the safety floor.
    grant_session: bool = False


class AgentProposalDeclineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1_000)


class AgentProposalRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(gt=0)
    changes: dict[str, Any]
    expected_effect: list[str] | None = None
    risks: list[str] | None = None


class AgentForkProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    chain_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_ref: str = Field(min_length=1, max_length=300)
    source_session_entry_id: str | None = Field(default=None, min_length=1, max_length=200)
    active_head_run_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(
        default="Fork from verified graph context",
        min_length=1,
        max_length=1_000,
    )


class AnalysisLoopContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Keep this a string so the domain seam, rather than FastAPI's generic
    # validation error, owns the stable machine-readable scope code.
    scope: str = Field(min_length=1, max_length=32)
    source_context: dict[str, Any] = Field(default_factory=dict)
    plan_diff: dict[str, Any] | None = None
    validation_packet: dict[str, Any] | None = None
    compare_packet: dict[str, Any] | None = None


class AnalysisLoopIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # This is deliberately untrusted input. The route only classifies and
    # returns it; it never turns it into a proposal or operation record.
    intent: dict[str, Any] = Field(default_factory=dict)


class AnalysisLoopProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_ref: str = Field(min_length=1, max_length=300)
    active_head_run_id: str = Field(min_length=1, max_length=200)
    cluster_variable: str = Field(min_length=1, max_length=200)
    result_id: str | None = Field(default=None, min_length=1, max_length=300)


class AgentEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(min_length=1, max_length=128)


class AgentChapterRequest(AgentEntryRequest):
    title: str = Field(min_length=1, max_length=120)


class AgentCompactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What the summary should keep in particular ("the IV results", "my definitions").
    focus: str | None = Field(default=None, max_length=1000)


class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str = Field(min_length=1, max_length=200)


class AgentSteerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

