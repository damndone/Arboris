"""The check library: which checks apply to a fit, and running them.

Applicability has one rule: the traits a check requires are a subset of the
traits the fit has. A check that applies but cannot run within its budget, or
fails to compute, reports "not checked" with the reason -- never silence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .context import CheckContext
from .contracts import CheckOutcome, CheckSpec
from .design_checks import COLLINEARITY, ROWS_PER_PARAMETER
from .iv_checks import EXCLUSION_RESTRICTION, FIRST_STAGE_STRENGTH
from .fit_checks import (
    CLUSTER_COUNT,
    EVENTS_PER_VARIABLE,
    HETEROSKEDASTICITY,
    OVERDISPERSION,
    PERFECT_FIT,
    SEPARATION,
)

CHECKS: tuple[CheckSpec, ...] = (
    ROWS_PER_PARAMETER,
    COLLINEARITY,
    CLUSTER_COUNT,
    FIRST_STAGE_STRENGTH,
    EVENTS_PER_VARIABLE,
    PERFECT_FIT,
    SEPARATION,
    HETEROSKEDASTICITY,
    OVERDISPERSION,
    EXCLUSION_RESTRICTION,
)


def applicable_checks(traits: frozenset[str], checks: Sequence[CheckSpec] = CHECKS) -> list[CheckSpec]:
    return [spec for spec in checks if spec.requires <= traits]


def run_checks(context: CheckContext, checks: Sequence[CheckSpec] = CHECKS) -> list[dict[str, Any]]:
    results = []
    cells = context.design.matrix.size if context.design is not None else 0
    degenerate: str | None = None
    for spec in applicable_checks(context.traits, checks):
        if degenerate is not None and spec.blinding == "post_fit":
            # A fit that cannot support inference (perfect fit, separation)
            # makes later checks of the fitted relationship meaningless.
            outcome = CheckOutcome("not_applicable", f"Not meaningful: {degenerate}.")
        elif spec.max_cells is not None and cells > spec.max_cells:
            outcome = CheckOutcome(
                "not_checked",
                f"The design has {cells:,} cells, above this check's budget of {spec.max_cells:,}.",
            )
        else:
            try:
                outcome = spec.run(context, spec)
            except Exception as exc:  # noqa: BLE001 - a check never fails the run
                outcome = CheckOutcome("not_checked", f"The check could not be computed: {type(exc).__name__}: {exc}")
        result = spec.result(outcome)
        if result["suppresses_inference"]:
            degenerate = spec.title.lower()
        results.append(result)
    return results
