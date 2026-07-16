from __future__ import annotations

import numpy as np


class SASpecError(ValueError):
    """SA_* failure (bad SA spec) → structured MODEL_FIT_FAILED (mirrors CSSpecError)."""


def select_reference_cohort(cohort):
    """Reference cohort for SA. None when a never-treated group exists (the natural
    comparison); otherwise the LAST-treated cohort as the normalization baseline.
    never-treated = non-finite cohort (NaN or inf).

    NOTE (v1.5.8 hardening): the `has_never is False` branch returns the last-treated
    cohort, but the no-never-treated identification it implies is NOT validated against
    the fixest::sunab oracle and diverges from it structurally (fixest does NOT exclude
    the last cohort; it keeps all cohorts and relies on collinearity removal). The
    estimator therefore BLOCKS no-never-treated panels in `validate_sa_input`
    (SA_NO_NEVER_TREATED), so this branch is currently dormant scaffolding kept for a
    future, properly-validated no-never implementation. See docs/architecture/v1.5.8-IMPL-NOTES.md."""
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
    # Block no-never-treated panels. The no-never (last-cohort-reference) path was
    # specified (spec §3) but never validated against fixest::sunab — all v1.5.8
    # fixtures have a never-treated group. It is structurally non-conforming: the
    # engine excludes the last cohort wholesale while fixest keeps it, and the
    # estimator then emits UNIDENTIFIED high-event-time coefficients (the Gram-Schmidt
    # collinearity drop does not fire on that construction) — i.e. silently-wrong
    # CATTs, the worst failure mode for an econometrics tool. Until a properly-
    # validated no-never implementation lands, fail loud. See docs/architecture/v1.5.8-IMPL-NOTES.md.
    if not np.any(~np.isfinite(cohort)):
        raise SASpecError(
            "SA_NO_NEVER_TREATED: Sun-Abraham in this version requires a never-treated "
            "comparison group, but every entity in this panel is eventually treated. The "
            "no-never-treated (last-cohort-reference) identification is not yet validated "
            "and is disabled to avoid returning unidentified coefficients. For a fully-"
            "staggered panel with no never-treated units, use cs_did with "
            "control_group='not_yet' (Callaway-Sant'Anna handles not-yet-treated controls)."
        )
    return True
