from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm


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
    """First period where cohort `g` is treated, shifted earlier by `anticipation`."""
    return g - anticipation


def reference_period(*, g: float, anticipation: int) -> float:
    """The last clean pre-period for cohort `g` (one period before effective start)."""
    return g - 1 - anticipation


def base_period_for(*, g: float, t: float, base_period: str, anticipation: int) -> float:
    """Base period to difference cell (g,t) against. Post periods (t ≥ effective start)
    always use the reference period; pre periods use t−1 under "varying" or the fixed
    reference period under "universal"."""
    ref = reference_period(g=g, anticipation=anticipation)
    if t >= effective_treatment_start(g=g, anticipation=anticipation):
        return ref
    if base_period == "universal":
        return ref
    if base_period == "varying":
        return t - 1
    raise CSSpecError(f"CS_BAD_BASE_PERIOD: '{base_period}'")


def cell_influence_function(cell: dict, *, est_method: str) -> np.ndarray:
    """Observation-level influence function for one (g,t) cell, row-aligned on
    `cell["_units"]`. Faithful port of DRDID 1.3.0 panel estimators:
      dr  → DRDID:::drdid_panel        (PS-correction + WLS/OR-correction)
      ipw → DRDID:::std_ipw_did_panel  (PS-correction only)
      reg → DRDID:::reg_did_panel      (OLS/OR-correction only)
    DRDID normalizes i.weights by their mean (here all 1 → no-op) and applies
    trimming `trim.ps`: control units kept iff ps < 0.995. Returns att.inf.func
    (the same array DRDID would, with se = sqrt(mean(inf^2)/n))."""
    if not cell.get("valid", False):
        raise CSSpecError("CS_INVALID_CELL_NO_IF: cannot compute influence function for an invalid cell")
    D = np.asarray(cell["_D"], dtype=float)
    dY = np.asarray(cell["_dY"], dtype=float)
    X = np.asarray(cell["_X"], dtype=float)
    ps = np.asarray(cell["_ps"], dtype=float)
    out_delta = np.asarray(cell["_mhat"], dtype=float)
    n = D.shape[0]
    iw = np.ones(n)  # i.weights, already mean-normalized to 1

    # DRDID trimming: ps.fit < 1.01 for treated (always True); controls ps < 0.995.
    trim_ps = ps < 1.01
    trim_ps = np.where(D == 0, ps < 0.995, trim_ps).astype(float)

    if est_method == "reg":
        # reg_did_panel: no trimming, w.treat = w.cont = i.weights * D
        w_treat = iw * D
        w_cont = iw * D
        reg_att_treat = w_treat * dY
        reg_att_cont = w_cont * out_delta
        eta_treat = np.mean(reg_att_treat) / np.mean(w_treat)
        eta_cont = np.mean(reg_att_cont) / np.mean(w_cont)

        weights_ols = iw * (1.0 - D)
        wols_x = (weights_ols[:, None]) * X
        wols_eX = (weights_ols * (dY - out_delta))[:, None] * X
        XpX = wols_x.T @ X / n
        XpX_inv = np.linalg.solve(XpX, np.eye(XpX.shape[0]))
        asy_lin_rep_ols = wols_eX @ XpX_inv

        inf_treat = (reg_att_treat - w_treat * eta_treat) / np.mean(w_treat)
        inf_cont_1 = reg_att_cont - w_cont * eta_cont
        M1 = (w_cont[None, :] @ X).ravel() / n
        inf_cont_2 = asy_lin_rep_ols @ M1
        inf_control = (inf_cont_1 + inf_cont_2) / np.mean(w_cont)
        return inf_treat - inf_control

    # Shared PS-correction machinery for ipw and dr.
    W = ps * (1.0 - ps) * iw
    w_treat = trim_ps * iw * D
    w_cont = trim_ps * iw * ps * (1.0 - D) / (1.0 - ps)
    mw_treat = np.mean(w_treat)
    mw_cont = np.mean(w_cont)

    score_ps = (iw * (D - ps))[:, None] * X
    XtWX_ps = X.T @ (W[:, None] * X)
    Hessian_ps = np.linalg.solve(XtWX_ps, np.eye(XtWX_ps.shape[0])) * n
    asy_lin_rep_ps = score_ps @ Hessian_ps

    if est_method == "ipw":
        att_treat = w_treat * dY
        att_cont = w_cont * dY
        eta_treat = np.mean(att_treat) / mw_treat
        eta_cont = np.mean(att_cont) / mw_cont

        inf_treat = (att_treat - w_treat * eta_treat) / mw_treat
        inf_cont_1 = att_cont - w_cont * eta_cont
        M2 = ((w_cont * (dY - eta_cont))[None, :] @ X).ravel() / n
        inf_cont_2 = asy_lin_rep_ps @ M2
        inf_control = (inf_cont_1 + inf_cont_2) / mw_cont
        return inf_treat - inf_control

    if est_method == "dr":
        dr_att_treat = w_treat * (dY - out_delta)
        dr_att_cont = w_cont * (dY - out_delta)
        eta_treat = np.mean(dr_att_treat) / mw_treat
        eta_cont = np.mean(dr_att_cont) / mw_cont

        weights_ols = iw * (1.0 - D)
        wols_x = (weights_ols[:, None]) * X
        wols_eX = (weights_ols * (dY - out_delta))[:, None] * X
        XpX = wols_x.T @ X / n
        XpX_inv = np.linalg.solve(XpX, np.eye(XpX.shape[0]))
        asy_lin_rep_wols = wols_eX @ XpX_inv

        inf_treat_1 = dr_att_treat - w_treat * eta_treat
        M1 = (w_treat[None, :] @ X).ravel() / n
        inf_treat_2 = asy_lin_rep_wols @ M1
        inf_cont_1 = dr_att_cont - w_cont * eta_cont
        M2 = ((w_cont * (dY - out_delta - eta_cont))[None, :] @ X).ravel() / n
        inf_cont_2 = asy_lin_rep_ps @ M2
        M3 = (w_cont[None, :] @ X).ravel() / n
        inf_cont_3 = asy_lin_rep_wols @ M3

        inf_treat = (inf_treat_1 - inf_treat_2) / mw_treat
        inf_control = (inf_cont_1 + inf_cont_2 - inf_cont_3) / mw_cont
        return inf_treat - inf_control

    raise CSSpecError(f"CS_BAD_EST_METHOD: '{est_method}'")


def cluster_influence(obs_if: np.ndarray, cluster_of_obs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sum observation-level IF within clusters. Returns (cluster_ids_sorted, summed_if).
    Default cluster = entity → each obs is its own cluster → identity."""
    ids = np.unique(cluster_of_obs)
    summed = np.array([obs_if[cluster_of_obs == c].sum() for c in ids])
    return ids, summed


def att_gt_cell(*, frame, entity, time, y, g, t, base_t, control_group,
                anticipation, covariates, est_method):
    """Sant'Anna-Zhao panel ATT for one (g,t) cell on sub-sample S(g,t).
    frame must carry the canonical `_did_cohort` column (float, NaN/inf = never-treated).
    Returns att + cell counts + the intermediates the influence-function task needs.

    Intermediate contract (present only on the success return; see that return):
      - All six arrays (`_units`, `_D`, `_dY`, `_X`, `_ps`, `_mhat`) are ROW-ALIGNED
        on `_units` order — index i refers to the same unit across every array.
      - `_units` (n,): entity ids of the cell complete-case sub-sample S(g,t).
      - `_D` (n,): cohort-g treatment indicator, float 1.0 (treated) / 0.0 (comparison).
      - `_dY` (n,): the long difference Y_t − Y_base_t.
      - `_X` (n, 1+len(covariates)): design matrix WITH a leading intercept column
        (shape (n, 1) when covariates is empty).
      - `_ps` (n,): propensity score, ALREADY clipped to [1e-6, 1-1e-6].
      - `_mhat` (n,): fitted outcome-regression prediction of `_dY`.
      - Callers MUST check `valid` is True before touching any `_*` intermediate: the
        empty-cell early return sets valid=False and OMITS all six arrays.
    """
    cohort = frame.groupby(entity)["_did_cohort"].first()
    treated = set(cohort.index[cohort == g])
    comp = set(cohort.index[comparison_mask(cohort, g=g, t=t, base_t=base_t,
                                            control_group=control_group, anticipation=anticipation)])
    keep = treated | comp
    sub = frame[frame[entity].isin(keep) & frame[time].isin([t, base_t])]
    wide = sub.pivot_table(index=entity, columns=time, values=y)
    ok = wide[[t, base_t]].notna().all(axis=1)        # cell-level complete-case
    units = wide.index[ok].to_numpy()
    dY = (wide.loc[units, t] - wide.loc[units, base_t]).to_numpy()
    D = np.array([u in treated for u in units], dtype=float)
    if D.sum() == 0 or (1.0 - D).sum() == 0:
        return {"att": float("nan"), "n_treated": int(D.sum()),
                "n_control": int((1 - D).sum()), "valid": False, "warning": "CS_EMPTY_CELL"}
    # covariates at the base period (pre-treatment, time-invariant in this design)
    X = np.ones((len(units), 1))
    if covariates:
        base_rows = (frame[frame[time] == base_t].drop_duplicates(entity)
                     .set_index(entity).loc[units, covariates].to_numpy(float))
        X = np.column_stack([np.ones(len(units)), base_rows])
    # propensity score: constant => p = treated share (=> weights collapse to 2x2)
    if X.shape[1] == 1:
        ps = np.full(len(units), D.mean())
    else:
        ps = sm.Logit(D, X).fit(disp=0).predict(X)
    ps = np.clip(ps, 1e-6, 1 - 1e-6)
    # outcome regression on the comparison units (constant if no covariates)
    if X.shape[1] == 1:
        mhat = np.full(len(units), dY[D == 0].mean())
    else:
        ols = sm.OLS(dY[D == 0], X[D == 0]).fit()
        mhat = X @ ols.params
    w1 = D / D.mean()
    raw0 = ps * (1 - D) / (1 - ps)
    w0 = raw0 / raw0.mean()
    if est_method == "dr":
        att = float(np.mean((w1 - w0) * (dY - mhat)))
    elif est_method == "ipw":
        att = float(np.mean((w1 - w0) * dY))
    elif est_method == "reg":
        att = float(np.mean(w1 * (dY - mhat)))
    else:
        raise CSSpecError(f"CS_BAD_EST_METHOD: '{est_method}'")
    # Success return: the `_*` arrays are row-aligned on `_units` (see docstring
    # contract). `_X` carries the leading intercept; `_ps` is already clipped.
    return {"att": att, "n_treated": int(D.sum()), "n_control": int((1 - D).sum()),
            "valid": True, "warning": None, "_units": units, "_D": D, "_dY": dY,
            "_X": X, "_ps": ps, "_mhat": mhat}
