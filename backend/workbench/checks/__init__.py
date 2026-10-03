"""The check library (v1.8.10 design §4): assumption checks declared by the
traits they need, their blinding level and their sourced thresholds."""

from .context import CheckContext, Design, build_context, design_from_fitted
from .contracts import BLINDING_LEVELS, STATUSES, CheckOutcome, CheckSpec, Threshold
from .registry import CHECKS, applicable_checks, run_checks

__all__ = [
    "BLINDING_LEVELS", "CHECKS", "STATUSES", "CheckContext", "CheckOutcome", "CheckSpec", "Design",
    "Threshold", "applicable_checks", "build_context", "design_from_fitted", "run_checks",
]
