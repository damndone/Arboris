"""Sun & Abraham (2021) interaction-weighted estimator — saturated within-OLS stage.

This module implements the linchpin CATT(g,e) coefficient estimator validated
element-wise against a committed `fixest::sunab` oracle (≤1e-8). The construction
mirrors `feols(y ~ sunab(cohort, year) | id + year)` == the saturated
`feols(y ~ i(rel, cohort, ref=-1) | id + year)` fit on TREATED-ONLY rows.

Recipe (see docs/v1.5.8-IMPL-NOTES.md — derived & validated to ≤5e-14):
  1. Design rows = finite-cohort (treated) rows; never-treated excluded.
     Interaction columns = cohorts in (finite cohorts EXCEPT ref_cohort).
  2. Two-way FE absorption (alternating id/year demean to convergence) of y and
     every interaction column. Both FEs absorbed — required to reproduce fixest's
     exact collinearity detection.
  3. Interaction columns in fixest natural order = period-primary: iterate e
     ascending (excluding e=-1), then g ascending; include only if >=1 obs.
  4. Sequential collinearity removal (modified Gram-Schmidt, NATURAL order, no
     pivoting): drop column j iff (||v_orth|| / ||v_0||)^2 <= 1e-10.
  5. Solve lstsq(Dkept_absorbed, y_absorbed) -> CATT(g,e).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .cs_attgt import EffectEstimateBundle
from .sa_spec import SASpecError, select_reference_cohort, validate_sa_input

# fixest collin.tol default — relative squared shrinkage below which a column is
# declared exactly collinear with the already-kept basis.
_COLLIN_TOL = 1e-10
# two-way absorption convergence threshold (max abs change of the demeaned vector).
_ABSORB_TOL = 1e-13
_ABSORB_MAX_ITER = 100000


def _absorb_two_way(M, id_codes, yr_codes, n_id, n_yr):
    """Alternating id/year demeaning to convergence. M is (n, k) float64.

    Returns a demeaned copy. Both fixed effects are projected out, which is what
    fixest does internally (and what its collinearity detection assumes)."""
    M = np.array(M, dtype=np.float64, copy=True)
    if M.ndim == 1:
        M = M.reshape(-1, 1)
    for _ in range(_ABSORB_MAX_ITER):
        prev = M
        # id-demean
        id_sum = np.zeros((n_id, M.shape[1]))
        np.add.at(id_sum, id_codes, M)
        id_cnt = np.bincount(id_codes, minlength=n_id).astype(np.float64)
        M = M - (id_sum / id_cnt[:, None])[id_codes]
        # year-demean
        yr_sum = np.zeros((n_yr, M.shape[1]))
        np.add.at(yr_sum, yr_codes, M)
        yr_cnt = np.bincount(yr_codes, minlength=n_yr).astype(np.float64)
        M = M - (yr_sum / yr_cnt[:, None])[yr_codes]
        if np.max(np.abs(M - prev)) < _ABSORB_TOL:
            return M
    raise SASpecError(
        f"SA_ABSORB_NO_CONVERGE: two-way FE absorption failed to converge in "
        f"{_ABSORB_MAX_ITER} iterations."
    )


def estimate_sa_saturated(
    df,
    *,
    entity,
    time,
    y,
    cohort,
    _return_internals=False,
):
    """Saturated within-OLS CATT(g,e) coefficients (fixest::sunab equivalent).

    Returns a dict with parallel lists "g"/"e"/"beta" (kept cells, sorted by (g,e)),
    plus "collinear_cells", "dropped_cells", "ref_cohort", "has_never".
    """
    ent_all = df[entity].to_numpy()
    time_all = df[time].to_numpy()
    y_all = df[y].to_numpy(dtype=np.float64)
    coh_all = df[cohort].to_numpy(dtype=np.float64)

    # Spec validation (bad inputs -> SASpecError).
    validate_sa_input(cohort=coh_all, times=time_all)
    ref_cohort, has_never = select_reference_cohort(coh_all)

    all_entity_ids = np.unique(ent_all)
    N_all = int(all_entity_ids.size)

    # --- 1. Treated-only design rows (finite cohort). ---
    treated = np.isfinite(coh_all)
    ent_t = ent_all[treated]
    time_t = time_all[treated]
    y_t = y_all[treated]
    coh_t = coh_all[treated]
    rel_t = time_t - coh_t  # relative period e = time - cohort

    if ent_t.size == 0:
        raise SASpecError("SA_NO_TREATED_COHORT: no treated rows in design.")

    # Entity / year integer codes over the TREATED design rows.
    treated_entity_ids, ent_codes = np.unique(ent_t, return_inverse=True)
    year_vals, yr_codes = np.unique(time_t, return_inverse=True)
    n_id = treated_entity_ids.size
    n_yr = year_vals.size

    # --- Candidate cells: cohorts getting interaction columns. ---
    finite_cohorts = np.unique(coh_t)
    if ref_cohort is None:
        interact_cohorts = finite_cohorts
    else:
        interact_cohorts = finite_cohorts[finite_cohorts != ref_cohort]

    # Relative periods present (excluding e = -1, the reference period).
    rel_present = np.unique(rel_t)
    rel_present = rel_present[rel_present != -1]

    # --- 3. Natural order = period-primary: e ascending, then g ascending. ---
    # Build candidate (g,e) list and their column masks; a column enters the design
    # only if it has >=1 observation. Zero-support candidates -> dropped_cells.
    candidate_keys = []
    col_masks = []
    dropped_cells = []
    for e in np.sort(rel_present):
        for g in np.sort(interact_cohorts):
            mask = (coh_t == g) & (rel_t == e)
            if mask.any():
                candidate_keys.append((float(g), float(e)))
                col_masks.append(mask)
            else:
                dropped_cells.append({"g": float(g), "e": float(e)})

    n_cols = len(candidate_keys)

    # dense indicator columns (one per candidate (g,e); sparse deferred per spec §2.2)
    D = np.zeros((ent_t.size, n_cols), dtype=np.float64)
    for j, mask in enumerate(col_masks):
        D[mask, j] = 1.0

    # --- 2. Two-way FE absorption of y and all interaction columns. ---
    y_abs = _absorb_two_way(y_t, ent_codes, yr_codes, n_id, n_yr).ravel()
    D_abs = _absorb_two_way(D, ent_codes, yr_codes, n_id, n_yr)

    # --- 4. Sequential collinearity removal (modified Gram-Schmidt, natural order). ---
    Q = np.zeros((ent_t.size, 0))  # orthonormal basis of kept columns
    kept_idx = []
    collinear_cells = []
    for j in range(n_cols):
        v = D_abs[:, j].copy()
        n0 = np.linalg.norm(v)
        if n0 == 0.0:
            # absorbed to exactly zero -> degenerate; treat as collinear drop.
            collinear_cells.append({"g": candidate_keys[j][0], "e": candidate_keys[j][1]})
            continue
        if Q.shape[1] > 0:
            v = v - Q @ (Q.T @ v)
        nv = np.linalg.norm(v)
        if (nv / n0) ** 2 <= _COLLIN_TOL:
            collinear_cells.append({"g": candidate_keys[j][0], "e": candidate_keys[j][1]})
        else:
            Q = np.column_stack([Q, v / nv])
            kept_idx.append(j)

    kept_keys = [candidate_keys[j] for j in kept_idx]
    # solve on the original (non-orthonormalized) kept columns so betas are in the
    # cell basis, not the GS basis
    Dk = D_abs[:, kept_idx] if kept_idx else np.zeros((ent_t.size, 0))

    # --- 5. Solve on kept columns. ---
    if Dk.shape[1] > 0:
        beta_kept, *_ = np.linalg.lstsq(Dk, y_abs, rcond=None)
    else:
        beta_kept = np.zeros(0)

    # --- Return cells sorted by (g, e). ---
    order = sorted(range(len(kept_keys)), key=lambda i: (kept_keys[i][0], kept_keys[i][1]))
    g_out = [kept_keys[i][0] for i in order]
    e_out = [kept_keys[i][1] for i in order]
    beta_out = [float(beta_kept[i]) for i in order]

    res = {
        "g": g_out,
        "e": e_out,
        "beta": beta_out,
        "collinear_cells": collinear_cells,
        "dropped_cells": dropped_cells,
        "ref_cohort": ref_cohort,
        "has_never": has_never,
    }

    if _return_internals:
        res["_internals"] = {
            "Dk": Dk,
            "y_abs": y_abs,
            "beta_kept": np.asarray(beta_kept, dtype=np.float64),
            "kept_keys": list(kept_keys),
            "ent_codes": ent_codes,
            "treated_entity_ids": treated_entity_ids,
            "all_entity_ids": all_entity_ids,
            "N_all": N_all,
        }

    return res


def sa_influence(res) -> np.ndarray:
    """N_all-scaled analytic entity influence function for the SA CATT(g,e).

    Returns an (N_all, K) matrix aligned to res["g"]/res["e"] (sorted-(g,e) order),
    one row per entity in np.unique(all entities) order, never-treated rows = 0.

    This is the v1.5.8 linchpin: the N_all scale factor makes
    cs_aggregate._se(IF[:, k], row_cluster, N_all) reproduce fixest's BARE
    (ssc adj=FALSE,cluster.adj=FALSE) cluster vcov, and (IF_k·IF_l)/N_all^2 the
    full vcov off-diagonals — so the shared cs_aggregate SE path and the
    honest-DID adapter work for SA for free.

    Recipe (validated to <=5e-13 vs the committed fixest oracle):
        phi_i = N_all * (Dk'Dk)^+ @ (sum_t Dk_it * eps_it),  eps = within residuals
    accumulated over each treated entity's rows; never-treated entities (zero
    score) stay zero. Columns are reordered from kept_keys (solve order) to the
    sorted res["g"]/res["e"] return order.
    """
    I = res["_internals"]
    Dk = I["Dk"]
    beta = np.asarray(I["beta_kept"], dtype=np.float64)
    ent_codes = I["ent_codes"]
    N_all = int(I["N_all"])

    resid = I["y_abs"] - Dk @ beta                  # within residuals eps_hat
    XtX_inv = np.linalg.pinv(Dk.T @ Dk)             # identified-subspace bread (K x K)
    scored = Dk * resid[:, None]                    # (n_treated_rows, K) per-obs score

    n_tre = len(I["treated_entity_ids"])
    K = Dk.shape[1]
    ent_sum = np.zeros((n_tre, K))
    np.add.at(ent_sum, ent_codes, scored)           # sum_t per treated entity
    phi_treated = N_all * (ent_sum @ XtX_inv.T)     # (n_treated, K), N_all-scaled

    # scatter into (N_all, K): never-treated rows stay 0
    pos = {eid: i for i, eid in enumerate(I["all_entity_ids"])}
    phi_full = np.zeros((N_all, K))
    for r, eid in enumerate(I["treated_entity_ids"]):
        phi_full[pos[eid], :] = phi_treated[r, :]

    # reorder columns from kept_keys (solve order) to sorted res["g"]/res["e"]
    key_to_col = {k: c for c, k in enumerate(I["kept_keys"])}
    out_cols = [key_to_col[(float(g), float(e))] for g, e in zip(res["g"], res["e"])]
    return phi_full[:, out_cols]


def estimate_sa(norm, *, cluster_var=None) -> EffectEstimateBundle:
    """Wrap the SA CATT(g,e) estimator + influence function into the shared
    EffectEstimateBundle contract (the estimator-agnostic seam that Callaway-
    Sant'Anna also emits), so cs_aggregate / honest-DID consume SA for free.

    Mirrors `estimate_att_gt` (cs_attgt.py) row construction exactly: entity rows
    in `units_all = np.sort(unique entity ids)` order (== the order sa_influence
    places IF rows in), per-entity cluster ids (entity-default), an entity-aligned
    cohort vector (0 = never-treated), cohort sizes, valid-only self-describing
    cell_metadata, and the applied sample_spec. Only identified (g,e) cells enter;
    the estimator has already valid-filtered (zero-support -> dropped, collinear
    -> removed), so every emitted cell is `valid: True`.
    """
    frame, entity, time, y = norm.frame, norm.entity, norm.time, norm.y
    res = estimate_sa_saturated(frame, entity=entity, time=time, y=y,
                                cohort="_did_cohort", _return_internals=True)
    IF = sa_influence(res)                                   # (N_all, K), aligned to res g/e
    estimates = np.asarray(res["beta"], dtype=float)

    cohort = frame.groupby(entity)["_did_cohort"].first()
    units_all = np.sort(cohort.index.to_numpy())            # IF row order (== np.unique)
    N = res["_internals"]["N_all"]

    # Per-entity cluster id (entity-default when cluster_var is falsy/== entity).
    # Single row convention: clustering lives ONLY here (aux["row_cluster"]); the
    # IF stays entity-level everywhere downstream.
    clustered = bool(cluster_var and cluster_var != entity)
    if clustered:
        if cluster_var not in frame.columns:
            raise SASpecError(f"SA_CLUSTER_COL_MISSING: '{cluster_var}' is not a column.")
        cl_by_unit = frame.drop_duplicates(entity).set_index(entity)[cluster_var]
        row_cluster = np.asarray(cl_by_unit.loc[units_all])
    else:
        row_cluster = np.asarray(units_all)

    # Entity-aligned cohort vector (0 = never-treated) for the aggregation `wif`.
    row_cohort = np.array([float(cohort.loc[u]) if np.isfinite(cohort.loc[u]) else 0.0
                           for u in units_all], dtype=float)

    # Cohort entity counts (treated cohorts only).
    finite_cohorts = sorted({float(g) for g in cohort.to_numpy() if np.isfinite(g)})
    n_by_g = {g: int((cohort == g).sum()) for g in finite_cohorts}
    total_treated = sum(n_by_g.values())
    weights = {"n_g": n_by_g,
               "p_g": {g: n_by_g[g] / total_treated for g in finite_cohorts} if total_treated else {}}

    # cell_metadata — only identified cells enter (estimator already valid-filtered).
    meta = [{"g": float(g), "t": float(g + e), "event_time": float(e), "valid": True,
             "n_treated": n_by_g.get(float(g), 0), "n_control": None, "warning": None}
            for g, e in zip(res["g"], res["e"])]

    # Balanced flag (every entity observed at every observed period) — used by Task 8.
    obs_per_entity = frame.groupby(entity)[time].nunique()
    n_periods = frame[time].nunique()
    balanced = bool((obs_per_entity == n_periods).all())

    diagnostics = {"dropped_cells": res["dropped_cells"],
                   "collinear_cells": res["collinear_cells"],
                   "support_zero_cells": res["dropped_cells"],
                   "balanced": balanced,
                   "sample_spec": {"estimator": "sun_abraham", "cluster_var": cluster_var,
                                   "ref_cohort": res["ref_cohort"], "has_never": res["has_never"]}}
    vcov_config = {"cluster_var": cluster_var if clustered else entity,
                   "cluster_level": cluster_var if clustered else "entity",
                   "confidence_level": 0.95, "band_type": None}
    aux = {"n_total": int(N), "row_cohort": row_cohort, "row_cluster": row_cluster}
    return EffectEstimateBundle(estimates=estimates, influence_func=IF, aux=aux,
        cluster_ids=np.unique(row_cluster), cell_metadata=meta, weights=weights,
        vcov_config=vcov_config, diagnostics=diagnostics)
