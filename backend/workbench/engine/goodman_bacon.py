"""Goodman-Bacon decomposition of the two-way fixed-effects DiD estimate.

The component weights implement the variance-weighted 2x2 decomposition of
Goodman-Bacon (2021), "Difference-in-Differences with Variation in Treatment
Timing" (Journal of Econometrics 225(2)), for the balanced-panel case. The
weighted average of all 2x2 component estimates equals the plain TWFE DiD
coefficient (the correctness anchor, exercised by the identity tests).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _two_by_two_did(panel: pd.DataFrame, y, time, treat_group, ctrl_group,
                    pre_periods, post_periods) -> float:
    """Standard 2x2 DiD: (treat_post - treat_pre) - (ctrl_post - ctrl_pre)."""
    def cell(group, periods):
        sub = panel[(panel["_grp"] == group) & (panel[time].isin(periods))]
        return sub[y].mean()
    return ((cell(treat_group, post_periods) - cell(treat_group, pre_periods))
            - (cell(ctrl_group, post_periods) - cell(ctrl_group, pre_periods)))


def goodman_bacon_decompose(frame: pd.DataFrame, *, y: str, entity: str, time: str,
                            cohort: str) -> dict:
    """Decompose the TWFE DiD estimate into weighted 2x2 comparisons
    (Goodman-Bacon 2021).

    Pure, deterministic. Requires a balanced panel keyed by (entity, time). The
    weighted average of component estimates equals the TWFE DiD coefficient.

    Never-treated units are encoded either as NaN or as a non-positive cohort
    value (0 / <=0 sentinel) and form the never-treated control group U.
    """
    df = frame.copy()
    df[time] = pd.to_numeric(df[time], errors="coerce")
    df["_cohort_val"] = pd.to_numeric(df[cohort], errors="coerce")
    # Goodman-Bacon is defined for balanced panels. Enforce it loudly rather than
    # returning a silently-wrong decomposition on ragged data.
    counts = df.groupby(entity)[time].nunique()
    period_set_sizes = df.groupby(entity)[time].apply(lambda s: tuple(sorted(s.unique())))
    if counts.nunique() != 1 or period_set_sizes.nunique() != 1:
        raise ValueError(
            "DID_UNBALANCED_PANEL: Goodman-Bacon decomposition requires a balanced "
            "panel (every unit observed in the same set of periods)."
        )
    # Never-treated cohort: NaN or non-positive sentinel (e.g. 0) -> +inf group.
    never_mask = df["_cohort_val"].isna() | (df["_cohort_val"] <= 0)
    df["_grp"] = df["_cohort_val"].where(~never_mask, np.inf)

    times = sorted(df[time].unique())
    n_periods = len(times)
    groups = sorted(g for g in df["_grp"].unique())
    treated_groups = [g for g in groups if np.isfinite(g)]
    never = np.inf in groups

    n_total = df[entity].nunique()
    # Group sample shares n_k (fraction of units in timing group k).
    share = {g: df[df["_grp"] == g][entity].nunique() / n_total for g in groups}
    # Fraction of time each treated group spends treated, Dbar_k, on the common
    # balanced time grid.
    Dbar = {}
    for k in treated_groups:
        post = sum(1 for t in times if t >= k)
        Dbar[k] = post / n_periods

    components: list[dict] = []
    weights_raw: list[tuple[str, float, float]] = []  # (type, weight_raw, estimate)

    # (1) timing group k vs never-treated U.
    #     Bacon (2021) weight: (n_k + n_U)^2 * n_kU (1 - n_kU) * Dbar_k (1 - Dbar_k)
    if never:
        n_U = share[np.inf]
        for k in treated_groups:
            pre = [t for t in times if t < k]
            post = [t for t in times if t >= k]
            if not pre or not post:
                continue
            est = _two_by_two_did(df, y, time, k, np.inf, pre, post)
            if np.isnan(est):
                raise ValueError(
                    "DID_BACON_EMPTY_CELL: a 2x2 comparison had an empty cell; "
                    "cannot decompose."
                )
            n_k = share[k]
            denom = n_k + n_U
            n_kU = n_k / denom
            w = (denom ** 2) * n_kU * (1 - n_kU) * Dbar[k] * (1 - Dbar[k])
            weights_raw.append(("treated_vs_untreated", w, est))

    # (2) pairs of timing groups (k earlier, l later).
    for i, k in enumerate(treated_groups):
        for l in treated_groups[i + 1:]:
            n_k, n_l = share[k], share[l]
            n_kl = n_k / (n_k + n_l)
            Dk, Dl = Dbar[k], Dbar[l]

            # 2a. earlier-vs-later ("good"): k treated, l as not-yet-treated control,
            #     window = periods before l's treatment.
            pre_k = [t for t in times if t < k]
            mid = [t for t in times if k <= t < l]
            if pre_k and mid and Dl < 1.0:
                est = _two_by_two_did(df, y, time, k, l, pre_k, mid)
                if np.isnan(est):
                    raise ValueError(
                        "DID_BACON_EMPTY_CELL: a 2x2 comparison had an empty cell; "
                        "cannot decompose."
                    )
                # Bacon weight:
                #   ((n_k + n_l)(1 - Dbar_l))^2 * n_kl(1-n_kl)
                #     * ((Dbar_k - Dbar_l)/(1 - Dbar_l)) * ((1 - Dbar_k)/(1 - Dbar_l))
                w = (((n_k + n_l) * (1 - Dl)) ** 2) * n_kl * (1 - n_kl) \
                    * ((Dk - Dl) / (1 - Dl)) * ((1 - Dk) / (1 - Dl))
                weights_raw.append(("earlier_vs_later", max(w, 0.0), est))

            # 2b. later-vs-earlier ("forbidden"): l treated, k as already-treated
            #     control, window = periods from k's treatment onward.
            mid2 = [t for t in times if k <= t < l]
            post_l = [t for t in times if t >= l]
            if mid2 and post_l and Dk > 0.0:
                est = _two_by_two_did(df, y, time, l, k, mid2, post_l)
                if np.isnan(est):
                    raise ValueError(
                        "DID_BACON_EMPTY_CELL: a 2x2 comparison had an empty cell; "
                        "cannot decompose."
                    )
                # Bacon weight:
                #   ((n_k + n_l) Dbar_k)^2 * n_kl(1-n_kl)
                #     * (Dbar_l/Dbar_k) * ((Dbar_k - Dbar_l)/Dbar_k)
                w = (((n_k + n_l) * Dk) ** 2) * n_kl * (1 - n_kl) \
                    * (Dl / Dk) * ((Dk - Dl) / Dk)
                weights_raw.append(("later_vs_earlier", max(w, 0.0), est))

    total = sum(w for _, w, _ in weights_raw)
    if total <= 0:
        return {"components": [], "weighted_avg": 0.0, "forbidden_weight": 0.0,
                "message": "No valid 2x2 comparisons (degenerate timing)."}

    for typ, w, est in weights_raw:
        components.append({"type": typ, "weight": float(w / total),
                           "estimate": float(est)})
    weighted_avg = float(sum(c["weight"] * c["estimate"] for c in components))
    forbidden_weight = float(sum(c["weight"] for c in components
                                 if c["type"] == "later_vs_earlier"))
    return {
        "components": components,
        "weighted_avg": weighted_avg,
        "forbidden_weight": forbidden_weight,
        "message": (
            f"{forbidden_weight:.0%} of the TWFE estimate comes from 'forbidden' "
            f"later-vs-earlier comparisons (already-treated units as controls); "
            f"under staggered adoption the TWFE estimate may be biased."
            if forbidden_weight > 0 else
            "No forbidden comparisons; TWFE reduces to clean 2x2 DiD."
        ),
    }
