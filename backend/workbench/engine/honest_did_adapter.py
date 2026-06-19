"""Thin Callaway-Sant'Anna -> honest-DID adapter (Task 6, v1.5.7.1).

Extracts ``(betahat, sigma)`` from a CS *dynamic* aggregation ONCE (a single
frozen statistics snapshot) and runs BOTH honest-DID tracks against it:

  * ``rm`` — Rambachan-Roth ΔRM relative-magnitudes sensitivity (ARP grid).
  * ``sd`` — ΔSD smoothness sensitivity via Fixed-Length CIs (FLCI).

Per spec §3.1 there is NO recompute between tracks: the cluster-robust Σ, the
kept indices, and the event times are computed once and read by both. The
cluster-robust covariance reuses the v1.5.6.1 single-row convention:
Σ_full = (1/N²) Σ_c S_c S_cᵀ with N = n_total (entity count).

Return shape (NESTED)::

    { "rm": {status, reason, num_pre, num_post, mbar_grid, post_average,
             per_event_time},
      "sd": {status, reason, method:"FLCI", num_pre, num_post, m_grid, scale,
             post_average, per_event_time},
      "_debug_keep_idx": [...], "_debug_event_times": [...],
      "_debug_sigma": [[...]] }

``status`` is ``"ok"`` (reason None) on success or ``"not_available"`` (with a
reason) on any ``HonestDiDError``. The runner adds ``"degraded"`` for unexpected
errors and strips the top-level ``_debug_*`` snapshot from the shipped artifact.

The ``_debug_*`` keys stay at TOP LEVEL — they are the single frozen snapshot
BOTH tracks read. The adapter NEVER throws: a shape mismatch returns
``{"rm": not_available, "sd": not_available}``.
"""
from __future__ import annotations

import numpy as np

from .honest_did import honest_rm, honest_sd, HonestDiDError

# Multipliers on the smoothness scale used to build the ΔSD M-grid.
HONEST_SD_M_MULT = [0.0, 0.5, 1.0, 1.5, 2.0]
# Floor for the smoothness scale so a (near-)degenerate Σ still yields a usable
# M-grid rather than an all-zero one.
HONEST_SD_SCALE_FLOOR = 1e-8


def _na(reason: str) -> dict:
    return {"status": "not_available", "reason": reason}


def _run_track(fn, *, betahat, sigma, num_pre, num_post, et, extra, **kw) -> dict:
    """Run one honest-DID track for the post-average and each post event-time.

    Returns ``{status:"ok", ...}`` on success, ``{status:"not_available", ...}``
    on ``HonestDiDError``. Both ``num_pre``/``num_post`` are always echoed.
    """
    try:
        # Let the engine raise its clean HONEST_NO_PRE/POST_PERIODS guard BEFORE we
        # build the averaging weights (1/num_post would ZeroDivisionError on an
        # empty-post snapshot, escaping the narrow `except HonestDiDError`).
        if num_post < 1 or num_pre < 1:
            fn(betahat=betahat, sigma=sigma, num_pre=num_pre,
               num_post=num_post, l_vec=np.zeros(max(num_post, 0)), **kw)
        l_avg = np.full(num_post, 1.0 / num_post)
        avg = fn(betahat=betahat, sigma=sigma, num_pre=num_pre,
                 num_post=num_post, l_vec=l_avg, **kw)
        per_event = []
        for j in range(num_post):
            lv = np.zeros(num_post)
            lv[j] = 1.0
            r = fn(betahat=betahat, sigma=sigma, num_pre=num_pre,
                   num_post=num_post, l_vec=lv, **kw)
            per_event.append({"event_time": et[num_pre + j], **r})
        return {"status": "ok", "reason": None,
                "num_pre": num_pre, "num_post": num_post,
                **extra, "post_average": avg, "per_event_time": per_event}
    except HonestDiDError as exc:
        # Echo the snapshot-derived ``extra`` (e.g. sd's ``scale``/``m_grid``/
        # ``method``) on the degenerate path too — these are computed BEFORE the
        # track runs and remain meaningful for diagnostics/rendering.
        return {"status": "not_available", "reason": str(exc),
                "num_pre": num_pre, "num_post": num_post, **extra}


def honest_did_from_cs_dynamic(agg_dynamic, *, row_cluster, n_total, mbar_grid,
                               alpha=0.05, grid_points=1000, m_mult=None,
                               scale_floor=HONEST_SD_SCALE_FLOOR) -> dict:
    """Run BOTH honest-DID tracks from one CS dynamic aggregation snapshot.

    Returns a JSON-safe NESTED block ``{"rm": ..., "sd": ..., "_debug_*": ...}``.
    Never throws: a row_cluster/component_if shape mismatch returns both tracks
    as ``not_available``.
    """
    m_mult = HONEST_SD_M_MULT if m_mult is None else m_mult
    labels = [float(x) for x in agg_dynamic["label"]]
    beta = np.asarray(agg_dynamic["estimate"], dtype=float)
    CIF = np.asarray(agg_dynamic["component_if"], dtype=float)  # (N, n_labels)
    N = int(n_total)
    rc = np.asarray(row_cluster)

    # Honor the "NEVER throws" contract: a row_cluster/component_if mismatch (or
    # empty IF) would otherwise raise from np.add.at below.
    if CIF.ndim != 2 or rc.shape[0] != CIF.shape[0] or CIF.shape[1] == 0:
        reason = "HONEST_BAD_INPUT: row_cluster/component_if shape mismatch."
        return {"rm": _na(reason), "sd": _na(reason)}

    # --- frozen snapshot (computed ONCE, read by both tracks) ---------------
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

    # --- ΔRM track ----------------------------------------------------------
    rm = _run_track(
        honest_rm, betahat=betahat, sigma=sigma, num_pre=num_pre,
        num_post=num_post, et=et,
        extra={"mbar_grid": list(map(float, mbar_grid))},
        mbar_grid=mbar_grid, alpha=alpha, grid_points=grid_points,
    )

    # --- ΔSD track (FLCI) ---------------------------------------------------
    # Smoothness scale = max pre/post SE (sqrt diag of Σ), floored.
    diag = np.sqrt(np.clip(np.diag(sigma), 0.0, None)) if sigma.size else np.array([0.0])
    scale = float(diag.max()) if diag.size else 0.0
    if scale < scale_floor:
        scale = scale_floor
    m_grid = [float(mult) * scale for mult in m_mult]
    sd = _run_track(
        honest_sd, betahat=betahat, sigma=sigma, num_pre=num_pre,
        num_post=num_post, et=et,
        extra={"method": "FLCI", "m_grid": m_grid, "scale": scale},
        m_grid=m_grid, alpha=alpha,
    )

    return {"rm": rm, "sd": sd, **debug}
