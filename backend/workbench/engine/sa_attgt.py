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
            break
    return M


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

    # --- Build interaction columns (sparse-friendly: indicator columns). ---
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
