from __future__ import annotations

import numpy as np
from scipy import stats


def multiplier_bootstrap(if_matrix, *, B=1000, alpha=0.05, seed=20260615,
                         estimates=None, clusters=None):
    """Callaway-Sant'Anna multiplier (wild) bootstrap.

    if_matrix : (N, K) ENTITY-row IF, mean-zero columns.
    clusters  : optional (N,) cluster id per entity row. When given, the IF is
        summed within clusters (R's rowsum) before drawing one Mammen multiplier
        per CLUSTER; the analytical/robust scale divisor stays N (entities), so
        the unclustered case (each entity its own cluster) is the exact identity.
    estimates : optional (K,) point estimates; CIs are centered on them.
    """
    if B < 1:
        raise ValueError("CS_BAD_BOOTSTRAP_B: B must be >= 1")
    Psi_entity = np.asarray(if_matrix, dtype=float)
    N, K = Psi_entity.shape
    if clusters is None:
        Psi = Psi_entity
    else:
        clusters = np.asarray(clusters)
        if clusters.shape[0] != N:
            raise ValueError("CS_CLUSTER_LEN_MISMATCH: clusters length != IF rows")
        uniq, inv = np.unique(clusters, return_inverse=True)
        Psi = np.zeros((len(uniq), K))
        np.add.at(Psi, inv, Psi_entity)            # rowsum within cluster
    G = Psi.shape[0]                               # rows to draw multipliers over
    if estimates is None:
        estimates = np.zeros(K)
    estimates = np.asarray(estimates, dtype=float)
    # analytical/robust SE uses the ENTITY count N (cluster-robust CRVE convention)
    se = np.sqrt((Psi ** 2).sum(axis=0)) / N
    rng = np.random.default_rng(seed)
    k1 = (1 - np.sqrt(5)) / 2
    k2 = (1 + np.sqrt(5)) / 2
    p = (np.sqrt(5) + 1) / (2 * np.sqrt(5))
    V = np.where(rng.random((B, G)) < p, k1, k2)        # (B, G) one per cluster
    R = (V @ Psi) / N                                   # (B, K)  divisor N
    # robust scale (CS IQR estimator), fall back to analytical se if degenerate
    q75, q25 = np.quantile(R, 0.75, axis=0), np.quantile(R, 0.25, axis=0)
    sigma = (q75 - q25) / (stats.norm.ppf(0.75) - stats.norm.ppf(0.25))
    sigma = np.where(sigma > 0, sigma, se)
    # pointwise z critical value
    z = stats.norm.ppf(1 - alpha / 2)
    pointwise_ci = np.column_stack([estimates - z * se, estimates + z * se])
    # simultaneous sup-t critical value. Exclude degenerate (sigma==0, i.e.
    # all-zero IF) columns from the max so one dead column can't NaN-out the
    # whole simultaneous band; divide only over good columns (no RuntimeWarning).
    good = sigma > 0
    if good.any():
        tstat = np.max(np.abs(R[:, good]) / sigma[good], axis=1)   # (B,)
        uniform_crit = float(np.quantile(tstat, 1 - alpha))
    else:
        uniform_crit = float(z)
    uniform_band = np.column_stack([estimates - uniform_crit * se,
                                    estimates + uniform_crit * se])
    return {"se": se, "pointwise_ci": pointwise_ci, "uniform_band": uniform_band,
            "uniform_crit": uniform_crit, "band_type": "simultaneous", "B": B,
            "alpha": alpha, "seed": seed}
