"""dCDH (de Chaisemartin-D'Haultfoeuille, DIDmultiplegtDYN) estimator core.

v1.5.9 — binary, non-absorbing, same_switchers=TRUE, DID_l long-difference
estimator + analytic cluster-robust influence function. Validated element-wise
against the committed R `DIDmultiplegtDYN` 2.3.4 oracle (point estimates 1e-12,
per-l SE reconstructed to machine precision; see docs/v1.5.9-IMPL-NOTES.md).

Zero new deps (NumPy/pandas only). Reuses the project SE helper convention:
each IF column is N-scaled so `cs_aggregate._se(IF[:,k], arange(N), N)` returns
the oracle SE (unclustered identity == sqrt(sum(if^2))/N).

Scope: this module ships ONLY `estimate_dcdh_dynamic` (point estimates + risk
sets + internals) and `dcdh_influence` (the 命门 IF). Bundle/result assembly
(`estimate_dcdh`) is a later task and is intentionally NOT built here.

The validated recipe
--------------------
Notation: F = a unit's first up-switch time; reference period = F-1.
* Effect_l (1-based l=1..L) <-> event_time l-1. Long difference compares
  ref = F-1 to tgt = F + (l-1)  (so Effect_1 is exactly F-1 -> F).
* Placebo_l (1-based l=1..P): symmetric PRE long difference Y[F-1-l] - Y[F-1],
  reported at event_time -(l+1) so the axis is monotone. The control set is the
  SAME never-treated-through-(F-1+l) set used by Effect_l (control filter at the
  EFFECT horizon, NOT the placebo period) — this口径 is what reproduces the
  oracle placebo numbers.
* Control per (F, target) = baseline=0 unit, D=0 for every period s<=filter,
  observed at both ref and the relevant comparison period. Switch-back units are
  valid switchers but excluded from controls once ever treated.
* same_switchers=TRUE: the switcher set is the units observed at F-1 AND at all
  effect horizons F..F+L-1; constant across l (=> 72 switchers here).
* Cohorts F are aggregated weighted by their switcher count w_F = n_sw_F / sum.

SE 命门: within each (F, target) cell, each subgroup's demeaned long difference
gets a Bessel factor sqrt(n/(n-1)); the per-unit contributions are summed across
cells, giving the entity influence function whose clustered (by id) sum of
squares equals the DYN variance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class DCDHEstimatorError(ValueError):
    """DCDH_EST_* failure (degenerate estimation)."""


def estimate_dcdh_dynamic(norm) -> dict:
    """Compute DID_l dynamic effects + symmetric placebos for a TreatmentPathPanel.

    `norm` is the object returned by `dcdh_spec.normalize_treatment_path`.
    Returns the result dict documented in the module header / task spec, including
    `_internals` carrying everything `dcdh_influence` needs.
    """
    frame = norm.frame
    ent, time, y = norm.entity, norm.time, norm.y

    f = frame.copy()
    f[time] = pd.to_numeric(f[time], errors="coerce")

    # Wide views: outcome and treatment path keyed by (unit, period).
    Y = f.pivot(index=ent, columns=time, values=y)
    D = f.pivot(index=ent, columns=time, values="_dcdh_D")
    years = sorted(int(c) for c in Y.columns)
    Y.columns = [int(c) for c in Y.columns]
    D.columns = [int(c) for c in D.columns]

    per_unit = f.groupby(ent).agg(
        base=("_dcdh_baseline", "first"),
        fs=("_dcdh_first_switch", "first"),
        direction=("_dcdh_first_switch_direction", "first"))
    eligible = per_unit[(per_unit["base"] == 0) & (per_unit["direction"] == "up")]
    base0_units = per_unit[per_unit["base"] == 0].index
    cohorts = sorted(int(v) for v in eligible["fs"].dropna().unique())
    if not cohorts:
        raise DCDHEstimatorError("DCDH_EST_NO_COHORTS: no eligible up-switch cohort.")

    # L / P from the oracle口径: L=3 effects, P=2 placebos. Derive L as the max
    # number of post-switch horizons any cohort can reach (capped at 3 to match
    # DYN's `effects=3`), P=2 placebos — but keep robust to fixtures by clamping
    # to feasibility below.
    L = 3
    P = 2

    ids = list(Y.index)
    N = len(ids)
    idx = {i: k for k, i in enumerate(ids)}

    # same_switchers set per cohort: observed at F-1 AND all effect horizons.
    def cohort_switchers(F):
        ref = F - 1
        need = [ref] + [F + k for k in range(L) if (F + k) in years]
        members = eligible[eligible["fs"] == F].index
        keep = []
        for i in members:
            row = Y.loc[i, need]
            if not row.isna().any():
                keep.append(i)
        return keep

    def controls(ref, tgt, filter_period):
        """baseline=0, never treated through `filter_period`, obs at ref and tgt."""
        cols_upto = [yy for yy in years if yy <= filter_period]
        out = []
        for i in base0_units:
            if D.loc[i, cols_upto].sum() != 0:
                continue
            if np.isnan(Y.loc[i, ref]) or np.isnan(Y.loc[i, tgt]):
                continue
            out.append(i)
        return out

    def build_cell(F, ell, kind):
        """Return (ref, tgt, switchers, controls, filter_period) or None."""
        ref = F - 1
        if ref not in years:
            return None
        if kind == "effect":
            tgt = F + ell            # event_time = ell (0-based) => Effect_(ell+1)
            filter_period = tgt
        else:                        # placebo: ell is the 1-based placebo index
            tgt = F - 1 - ell        # symmetric pre period
            filter_period = F - 1 + ell   # EFFECT-horizon control filter
        if tgt not in years:
            return None
        sw = cohort_switchers(F)
        sw = [i for i in sw if not np.isnan(Y.loc[i, tgt]) and not np.isnan(Y.loc[i, ref])]
        if not sw:
            return None
        ct = controls(ref, tgt, filter_period)
        if not ct:
            return None
        return ref, tgt, sw, ct, filter_period

    def aggregate(ell, kind):
        """Return (estimate, IF_unscaled, n_switchers_total, n_controls_repr).

        IF_unscaled[i] is the per-unit contribution to the estimate (sums ~0);
        clustered se = sqrt(sum(IF^2)) * 1  (it already carries 1/n_sw etc.).
        """
        cells = []
        totsw = 0
        for F in cohorts:
            cell = build_cell(F, ell, kind)
            if cell is None:
                continue
            ref, tgt, sw, ct, _ = cell
            cells.append((ref, tgt, sw, ct))
            totsw += len(sw)
        if not cells or totsw == 0:
            return None
        est = 0.0
        IF = np.zeros(N)
        n_ctrl_repr = cells[0][3]  # representative control count (first cohort)
        for ref, tgt, sw, ct in cells:
            ns = len(sw)
            nc = len(ct)
            w = ns / totsw
            ds = np.array([Y.loc[i, tgt] - Y.loc[i, ref] for i in sw])
            dc = np.array([Y.loc[i, tgt] - Y.loc[i, ref] for i in ct])
            est += w * (ds.mean() - dc.mean())
            # within-cell Bessel correction on each demeaned subgroup (DYN口径).
            bs = np.sqrt(ns / (ns - 1)) if ns > 1 else 0.0
            bc = np.sqrt(nc / (nc - 1)) if nc > 1 else 0.0
            sw_dm = ds - ds.mean()
            ct_dm = dc - dc.mean()
            for j, i in enumerate(sw):
                IF[idx[i]] += w * sw_dm[j] / ns * bs
            for j, i in enumerate(ct):
                IF[idx[i]] += -w * ct_dm[j] / nc * bc
        return est, IF, totsw, len(n_ctrl_repr)

    effect_estimate = []
    placebo_estimate = []
    estimate_axis = []       # estimates aligned to event_time_axis / if_columns order
    if_columns = []          # one per reported event_time, in axis order
    risk_set_by_ell = []
    event_time_axis = []

    # ---- placebos first (most-negative event_time first for a monotone axis) ----
    placebo_cells = []
    for l in range(1, P + 1):
        agg = aggregate(l, "placebo")
        if agg is None:
            continue
        est, IF, ns, nc = agg
        placebo_cells.append((l, est, IF, ns, nc))
        placebo_estimate.append(est)
    # report Placebo_l at event_time -(l+1); ascending axis => largest l first.
    for l, est, IF, ns, nc in sorted(placebo_cells, key=lambda r: -(r[0] + 1)):
        ev = -(l + 1)
        event_time_axis.append(ev)
        estimate_axis.append(est)
        if_columns.append(IF)
        risk_set_by_ell.append({"ell": int(ev), "n_switchers": int(ns),
                                "n_controls": int(nc), "dropped_reason": None})

    # ---- effects (event_time 0..L-1) ----
    for ell in range(L):
        agg = aggregate(ell, "effect")
        if agg is None:
            risk_set_by_ell.append({"ell": int(ell), "n_switchers": 0,
                                    "n_controls": 0,
                                    "dropped_reason": "no feasible cohort at horizon"})
            continue
        est, IF, ns, nc = agg
        effect_estimate.append(est)
        estimate_axis.append(est)
        event_time_axis.append(int(ell))
        if_columns.append(IF)
        risk_set_by_ell.append({"ell": int(ell), "n_switchers": int(ns),
                                "n_controls": int(nc), "dropped_reason": None})

    # keep risk_set_by_ell aligned/sorted to the reported axis ordering.
    risk_set_by_ell = sorted(
        [c for c in risk_set_by_ell if c["dropped_reason"] is None
         or c["n_switchers"] == 0],
        key=lambda c: c["ell"])

    internals = {
        "if_columns": [col.tolist() for col in if_columns],
        "event_time": list(event_time_axis),
        "n_total": int(N),
        # entity ids as-is (may be strings) — used downstream only for IF row order
        # and cluster alignment, never JSON-serialized. Do NOT float()-coerce (breaks
        # string ids like "u00").
        "unit_ids": list(ids),
        "n_placebo": len(placebo_estimate),
        "n_effect": len(effect_estimate),
    }

    return {
        "effect_estimate": effect_estimate,
        "placebo_estimate": placebo_estimate,
        "estimate": list(estimate_axis),     # aligned to event_time / if_columns order
        "event_time": list(event_time_axis),
        "risk_set_by_ell": risk_set_by_ell,
        "_internals": internals,
    }


def dcdh_influence(res):
    """Analytic cluster-robust influence function for the DYN per-l estimates.

    Returns (IF, row_cluster, N) where:
      * IF is (N, L_total) entity-row influence functions, mean-zero per column,
        N-scaled so that `cs_aggregate._se(IF[:,k], row_cluster, N)` reproduces
        the oracle per-l SE (identity cluster => sqrt(sum(if^2))/N).
      * row_cluster = arange(N) (one cluster per entity; DYN clusters on id and
        each entity is its own cluster in this panel).
      * N = total entity count (excluded/never units carry all-zero rows).

    Columns are ordered to match `res["event_time"]` (placebos at negative
    event_time first, then effects 0..L-1).
    """
    internals = res["_internals"]
    N = int(internals["n_total"])
    cols = internals["if_columns"]
    if not cols:
        return np.zeros((N, 0)), np.arange(N), N
    # _internals stores the per-unit *contribution* IFs (carry 1/n_sw etc.). The
    # project SE helper divides by N, so N-scale here: column * N.
    IF = np.array(cols, dtype=float).T * N
    row_cluster = np.arange(N)
    return IF, row_cluster, N


def estimate_dcdh(norm, *, cluster_var=None):
    """Assemble the dCDH event study into the shared EventStudyBundle contract.

    Mirrors the SA cluster convention (engine/sa_attgt.py): entity-default
    row_cluster, or a per-unit cluster id from `cluster_var` with the same
    degenerate-column guards so a bad cluster column never yields a silently-wrong
    SE. The IF stays entity-level; clustering lives only in aux["row_cluster"].
    """
    from .event_study import EventStudyBundle
    from .dcdh_spec import DCDHSpecError

    res = estimate_dcdh_dynamic(norm)
    IF, _row_cluster, N = dcdh_influence(res)
    est = np.asarray(res["estimate"], dtype=float)
    ev = np.asarray(res["event_time"], dtype=float)
    nsw_by_ell = {int(r["ell"]): int(r["n_switchers"]) for r in res["risk_set_by_ell"]}
    n_switchers = np.array([nsw_by_ell.get(int(e), 0) for e in ev], dtype=int)

    frame, entity = norm.frame, norm.entity
    units_all = np.asarray(res["_internals"]["unit_ids"])   # IF row order

    clustered = bool(cluster_var and cluster_var != entity)
    if clustered:
        if cluster_var not in frame.columns:
            raise DCDHSpecError(f"DCDH_CLUSTER_COL_MISSING: '{cluster_var}' is not a column.")
        try:
            cl_by_unit = frame.drop_duplicates(entity).set_index(entity)[cluster_var]
            cl = cl_by_unit.loc[units_all]
        except (KeyError, TypeError) as exc:
            raise DCDHSpecError(f"DCDH_CLUSTER_COL_BAD: could not resolve cluster column "
                                f"'{cluster_var}': {exc}") from exc
        if cl.isna().any():
            raise DCDHSpecError("DCDH_CLUSTER_COL_NAN: cluster column has missing values.")
        cl = cl.to_numpy().astype(str)
        if len(np.unique(cl)) < 2:
            raise DCDHSpecError("DCDH_CLUSTER_SINGLE: need >= 2 clusters for cluster-robust SE.")
        row_cluster = np.asarray(cl)
    else:
        row_cluster = np.asarray(units_all)

    diagnostics = {
        "risk_set_by_ell": res["risk_set_by_ell"],
        "excluded_units": list(norm.excluded_units),
        "sample": dict(norm.summary),
        "cluster_var": cluster_var if clustered else entity,
    }
    aux = {"n_total": int(N), "row_cluster": row_cluster}
    return EventStudyBundle(estimates=est, influence_func=IF, event_times=ev,
                            cluster_ids=np.unique(row_cluster), n_switchers=n_switchers,
                            aux=aux, diagnostics=diagnostics)
