"""Read-time freshness and the fail-closed execution gate (spec §4.2).

One comparison function, two call sites. The read-time evaluator and `confirm()`
must never be able to disagree, so `evaluate_option_freshness` and
`assert_executable` both delegate to `_compare` — there is no second opinion to
drift.

The whole point of the separation is *when* it is evaluated, not *what*:
read-time says "as of a moment ago this still held", which is a UI hint and
never a permission. The upstream can change between the render and the click,
which is why `confirm()` recomputes.
"""

from __future__ import annotations

from typing import Any

from ...contracts.agent.notebook_option import NotebookOptionRevision
from ..context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
)
from .errors import OptionRevisionStale

FRESH = "fresh"
STALE = "stale"
REVALIDATING = "revalidating"


def _compare(
    revision: NotebookOptionRevision, context: NotebookPlanningContextV1
) -> tuple[bool, str]:
    observed = freshness_dependency_fingerprint(context)
    return observed == revision.freshness_dependency_fingerprint, observed


def evaluate_option_freshness(
    revision: NotebookOptionRevision, context: NotebookPlanningContextV1
) -> str:
    """Pure read. Writes nothing, decides nothing, grants nothing."""

    matches, _ = _compare(revision, context)
    return FRESH if matches else STALE


def assert_executable(
    revision: NotebookOptionRevision, context: NotebookPlanningContextV1
) -> None:
    """The gate. Recomputes at confirm time, refuses on any divergence.

    Note what is *not* consulted: `generation_context_hash`. It changes whenever
    a sibling option is written, and gating on it would make every batch stale
    itself (spec §4.0).
    """

    matches, observed = _compare(revision, context)
    if matches:
        return
    raise OptionRevisionStale(
        f"option {revision.option_id} revision {revision.option_revision} was pinned to "
        f"freshness fingerprint {revision.freshness_dependency_fingerprint}, but the "
        f"current context fingerprints as {observed}; it must be revalidated before it "
        "can be executed",
        option_id=revision.option_id,
        requested_revision=revision.option_revision,
        current_revision=revision.option_revision,
        reason="freshness_dependency_changed",
        pinned_freshness_dependency_fingerprint=revision.freshness_dependency_fingerprint,
        observed_freshness_dependency_fingerprint=observed,
    )


def freshness_details(
    revision: NotebookOptionRevision, context: NotebookPlanningContextV1
) -> dict[str, Any]:
    matches, observed = _compare(revision, context)
    return {
        "freshness_status": FRESH if matches else STALE,
        "pinned_freshness_dependency_fingerprint": (
            revision.freshness_dependency_fingerprint
        ),
        "observed_freshness_dependency_fingerprint": observed,
        "evaluated_at_read_time": True,
        "grants_execution_permission": False,
    }


__all__ = [
    "FRESH",
    "REVALIDATING",
    "STALE",
    "assert_executable",
    "evaluate_option_freshness",
    "freshness_details",
]
