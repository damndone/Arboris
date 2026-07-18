"""Locked identifiers for the initial repeated-measures recipe."""

from __future__ import annotations


LMM_RECIPE_ID = "repeated_measures.linear_mixed_effects.v1"
LMM_RECOVERY_ACTION_ID = "lmm.simplify_random_effects_v1"
LMM_RECOVERY_OPERATION_ID = "model.rerun"
LMM_RECOVERY_PATCH = {"model_options": {"random_slope": False}}
LMM_BLOCKING_CODES = frozenset(
    {
        "LMM_SUBJECT_ID_MISSING",
        "LMM_TIME_NOT_NUMERIC",
        "LMM_GROUP_NOT_BINARY",
        "LMM_GROUP_VARIES_WITHIN_SUBJECT",
        "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
        "LMM_CONVERGENCE_FAILED",
    }
)
