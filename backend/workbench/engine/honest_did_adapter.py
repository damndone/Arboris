"""Thin Callaway-Sant'Anna -> honest-DID adapter (Task 6, v1.5.7).

Extracts ``(betahat, sigma)`` from a CS *dynamic* aggregation and runs the
Rambachan-Roth ΔRM honest-DID sensitivity for the post-average and each post
event-time. The cluster-robust covariance reuses the v1.5.6.1 single-row
convention: Σ_full = (1/N²) Σ_c S_c S_cᵀ with N = n_total (entity count).

The ``_debug_*`` keys are intentional testability hooks; the runner (Task 7)
strips them from the shipped artifact. On any degenerate extraction the adapter
returns ``{"skipped": True, "reason": ...}`` and NEVER throws.
"""
from __future__ import annotations

import numpy as np

from .honest_did import honest_rm, HonestDiDError


def honest_did_from_cs_dynamic(agg_dynamic, *, row_cluster, n_total,
                               mbar_grid, alpha=0.05, grid_points=1000) -> dict:
    """Run ΔRM honest-DID from a CS dynamic aggregation.

    Returns a JSON-safe block; on any ``HonestDiDError`` returns
    ``{"skipped": True, "reason": ...}``.
    """
    labels = [float(x) for x in agg_dynamic["label"]]
    beta = np.asarray(agg_dynamic["estimate"], dtype=float)
    CIF = np.asarray(agg_dynamic["component_if"], dtype=float)  # (N, n_labels)
    N = int(n_total)
    rc = np.asarray(row_cluster)

    # Honor the "NEVER throws" contract: a row_cluster/component_if mismatch (or
    # empty IF) would otherwise raise from np.add.at BEFORE the try below.
    if CIF.ndim != 2 or rc.shape[0] != CIF.shape[0] or CIF.shape[1] == 0:
        return {"skipped": True,
                "reason": "HONEST_BAD_INPUT: row_cluster/component_if shape mismatch.",
                "num_pre": 0, "num_post": 0}

    # Cluster-robust Σ_full (v1.5.6.1 single-row convention, N = entity count).
    uniq, inv = np.unique(rc, return_inverse=True)
    S = np.zeros((len(uniq), CIF.shape[1]))
    np.add.at(S, inv, CIF)
    Sigma_full = S.T @ S / (N ** 2)

    # Keep all event times EXCEPT the reference period e == -1 (structural zero);
    # order pre (<0, ascending) then post (>=0, ascending).
    keep = [i for i, e in enumerate(labels) if abs(e + 1.0) > 1e-9]
    keep.sort(key=lambda i: (labels[i] >= 0, labels[i]))
    et = [labels[i] for i in keep]
    num_pre = sum(1 for e in et if e < 0)
    num_post = sum(1 for e in et if e >= 0)

    betahat = beta[keep]
    sigma = Sigma_full[np.ix_(keep, keep)]
    debug = {
        "_debug_keep_idx": keep,
        "_debug_event_times": et,
        "_debug_sigma": sigma.tolist(),
    }

    try:
        if num_pre < 1:
            raise HonestDiDError("HONEST_NO_PRE_PERIODS: ΔRM needs >=1 pre-period.")
        if num_post < 1:
            raise HonestDiDError("HONEST_NO_POST_PERIODS: no post-period to test.")
        l_avg = np.full(num_post, 1.0 / num_post)
        avg = honest_rm(betahat=betahat, sigma=sigma, num_pre=num_pre,
                        num_post=num_post, l_vec=l_avg, mbar_grid=mbar_grid,
                        alpha=alpha, grid_points=grid_points)
        per_event = []
        for j in range(num_post):
            lv = np.zeros(num_post)
            lv[j] = 1.0
            r = honest_rm(betahat=betahat, sigma=sigma, num_pre=num_pre,
                          num_post=num_post, l_vec=lv, mbar_grid=mbar_grid,
                          alpha=alpha, grid_points=grid_points)
            per_event.append({"event_time": et[num_pre + j], **r})
        return {
            "skipped": False,
            "num_pre": num_pre,
            "num_post": num_post,
            "mbar_grid": list(map(float, mbar_grid)),
            "post_average": avg,
            "per_event_time": per_event,
            **debug,
        }
    except HonestDiDError as exc:
        return {
            "skipped": True,
            "reason": str(exc),
            "num_pre": num_pre,
            "num_post": num_post,
            **debug,
        }
