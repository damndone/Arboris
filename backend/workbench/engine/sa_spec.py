from __future__ import annotations

import numpy as np


class SASpecError(ValueError):
    """SA_* failure (bad SA spec) → structured MODEL_FIT_FAILED (mirrors CSSpecError)."""


def select_reference_cohort(cohort):
    """Reference cohort for SA. None when a never-treated group exists (the natural
    comparison); otherwise the LAST-treated cohort as the normalization baseline.
    never-treated = non-finite cohort (NaN or inf)."""
    cohort = np.asarray(cohort, dtype=float)
    finite = cohort[np.isfinite(cohort)]
    has_never = bool(np.any(~np.isfinite(cohort)))
    if has_never:
        return None, True
    if finite.size == 0:
        raise SASpecError("SA_NO_TREATED_COHORT: no treated cohort and no never-treated group.")
    return float(np.max(finite)), False


def validate_sa_input(*, cohort, times):
    cohort = np.asarray(cohort, dtype=float)
    if np.unique(np.asarray(times)).size < 2:
        raise SASpecError("SA_TOO_FEW_PERIODS: need >=2 time periods.")
    if cohort[np.isfinite(cohort)].size == 0:
        raise SASpecError("SA_NO_TREATED_COHORT: no treated cohort present.")
    return True
