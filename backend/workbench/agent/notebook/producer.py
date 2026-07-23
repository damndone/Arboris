"""Deterministic typed planning producer for the Notebook surface.

This is deliberately a planner, not an executor. It emits immutable option
packets against one bounded context; ``NotebookService.propose_batch`` remains
the persistence and registry-validation authority for user-owned notebooks.
"""

from __future__ import annotations

from ..context_compiler import NotebookPlanningContextV1
from .planning_agent import AgentOptionSubmission, NotebookPlanningUnavailable
from .proposal import OptionDraft

MAX_PLANNED_OPTIONS = 3


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


def generate_option_batch(*, notebook_id: str, count: int = MAX_PLANNED_OPTIONS) -> tuple[OptionDraft, ...]:
    del notebook_id, count
    raise NotebookPlanningUnavailable("a configured NotebookPlanningAgent is required")


__all__ = ["MAX_PLANNED_OPTIONS", "generate_option_batch", "option_drafts_from_submissions", "plan_option_drafts"]
