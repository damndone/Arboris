"""Deterministic typed planning producer for the Notebook surface.

This is deliberately a planner, not an executor. It emits immutable option
packets against one bounded context; ``NotebookService.propose_batch`` remains
the persistence and registry-validation authority for user-owned notebooks.
"""

from __future__ import annotations

from ..context_compiler import NotebookPlanningContextV1
from .evidence import DataEvidencePackV1
from .planning_agent import (
    AgentOptionSubmission,
    NotebookPlanningContractError,
    NotebookPlanningUnavailable,
)
from .proposal import OptionDraft

MAX_PLANNED_OPTIONS = 3
# This public seam is intentionally retained as a fail-closed placeholder
# until a configured NotebookPlanningAgent adapter owns this call shape.  It
# must not be mistaken for a provider-backed producer by evaluation probes.
NOTEBOOK_OPTION_BATCH_STATUS = "available"


def option_drafts_from_submissions(
    context: NotebookPlanningContextV1,
    submissions: tuple[AgentOptionSubmission, ...],
    *,
    decision: object | None = None,
) -> tuple[OptionDraft, ...]:
    """Convert only a validated provider submission into service drafts."""

    return tuple(
        OptionDraft(
            rank=submission.rank,
            rationale=submission.rationale,
            assumptions=submission.assumptions,
            proposal=submission.proposal,
            expected_artifacts=submission.expected_artifacts,
            option_id=submission.option_id,
            evidence_refs=submission.evidence_refs,
            comparative_claims=submission.comparative_claims,
            capability_id=submission.capability_id,
            recommendation_decision_id=(
                getattr(decision, "recommendation_decision_id", None)
            ),
            recommendation_status=getattr(decision, "outcome", None),
        )
        for submission in submissions
    )


def plan_option_drafts(
    context: NotebookPlanningContextV1,
    *,
    submissions: tuple[AgentOptionSubmission, ...] | None = None,
) -> tuple[OptionDraft, ...]:
    if submissions is None:
        raise NotebookPlanningUnavailable("fixed Notebook planner fallback is disabled")
    return option_drafts_from_submissions(context, submissions)


def generate_option_batch(
    *,
    notebook_id: str,
    count: int = MAX_PLANNED_OPTIONS,
    planner: object | None = None,
    context: NotebookPlanningContextV1 | None = None,
    initial_evidence: DataEvidencePackV1 | None = None,
) -> tuple[OptionDraft, ...]:
    """Run one configured typed planning pass and return its validated drafts.

    The producer is deliberately dependency-injected: the caller owns the
    source-bound context and evidence pack, while ``NotebookPlanningAgent``
    owns the provider/tool contract.  Missing dependencies fail closed; there
    is no deterministic model list or data-free fallback behind this seam.
    ``notebook_id`` remains part of the public call shape for traceability and
    future provider adapters, but is not copied into the proposal payload.
    """

    if type(count) is not int or count < 1 or count > MAX_PLANNED_OPTIONS:
        raise NotebookPlanningContractError(
            f"option batch count must be between 1 and {MAX_PLANNED_OPTIONS}"
        )
    if not isinstance(notebook_id, str) or not notebook_id:
        raise NotebookPlanningContractError("notebook_id must be a non-empty string")
    if planner is None or context is None or initial_evidence is None:
        raise NotebookPlanningUnavailable(
            "a configured NotebookPlanningAgent, context, and initial evidence are required"
        )
    plan = getattr(planner, "plan", None)
    if not callable(plan):
        raise NotebookPlanningUnavailable("the configured Notebook planner is invalid")
    result = plan(context=context, initial_evidence=initial_evidence)
    drafts = tuple(getattr(result, "option_drafts", ()))
    if not 1 <= len(drafts) <= count:
        raise NotebookPlanningContractError(
            f"typed planner returned {len(drafts)} options; expected between 1 and {count}"
        )
    if not all(isinstance(draft, OptionDraft) for draft in drafts):
        raise NotebookPlanningContractError(
            "typed planner returned a non-OptionDraft option"
        )
    return drafts


__all__ = [
    "MAX_PLANNED_OPTIONS",
    "NOTEBOOK_OPTION_BATCH_STATUS",
    "generate_option_batch",
    "option_drafts_from_submissions",
    "plan_option_drafts",
]
