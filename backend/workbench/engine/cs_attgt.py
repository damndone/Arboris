from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class CSSpecError(ValueError):
    """CS_*-prefixed failure → structured MODEL_FIT_FAILED (v1.5.5.1 convention)."""


@dataclass
class EffectEstimateBundle:
    estimates: np.ndarray                 # (K,)
    influence_func: np.ndarray            # (G, K) cluster rows, mean-zero columns
    cluster_ids: np.ndarray               # (G,)
    cell_metadata: list[dict]             # K records
    weights: dict                         # cohort sizes n_g, shares p̂_g
    vcov_config: dict
    diagnostics: dict = field(default_factory=dict)


def comparison_mask(cohort: pd.Series, *, g: float, t: float, base_t: float,
                    control_group: str, anticipation: int) -> pd.Series:
    """Boolean mask over the entity-indexed cohort series selecting clean controls
    for cell (g,t). never-treated always qualify; already-treated always excluded.

    `g` (the treated cohort) is reserved in the signature for later tasks; the
    current clean-control rule keys off `t`/`base_t` only."""
    safe_until = max(t, base_t)
    # Never-treated sentinel = non-finite cohort. `did_spec.normalize_did_input`
    # encodes never-treated as float NaN, while the tests build it via
    # `.replace(0, np.inf)`. `~np.isfinite(...)` catches BOTH NaN and inf, so the
    # mask is robust to either convention — do not "fix" this to an == check.
    never = ~np.isfinite(cohort)
    if control_group == "never":
        return never
    if control_group == "not_yet":
        return never | (cohort > safe_until + anticipation)
    raise CSSpecError(f"CS_BAD_CONTROL_GROUP: '{control_group}'")


def effective_treatment_start(*, g: float, anticipation: int) -> float:
    return g - anticipation


def reference_period(*, g: float, anticipation: int) -> float:
    return g - 1 - anticipation


def base_period_for(*, g: float, t: float, base_period: str, anticipation: int) -> float:
    ref = reference_period(g=g, anticipation=anticipation)
    if t >= effective_treatment_start(g=g, anticipation=anticipation):
        return ref
    if base_period == "universal":
        return ref
    if base_period == "varying":
        return t - 1
    raise CSSpecError(f"CS_BAD_BASE_PERIOD: '{base_period}'")
