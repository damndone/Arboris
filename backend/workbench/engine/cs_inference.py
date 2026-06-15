from __future__ import annotations

import numpy as np
from scipy import stats


def multiplier_bootstrap(if_matrix, *, B=1000, alpha=0.05, seed=20260615,
                         estimates=None):
    """Callaway-Sant'Anna multiplier (wild) bootstrap on a cluster-row influence
    matrix Psi of shape (G, K). Returns analytical SE, pointwise CIs, and a
    simultaneous (sup-t) uniform band. Seed-deterministic (golden 0-drift).

    if_matrix : (G, K) ndarray, mean-zero columns (cluster-row IF).
    estimates : optional (K,) point estimates; CIs are centered on them
        (default zeros).
    """
    Psi = np.asarray(if_matrix, dtype=float)
    G, K = Psi.shape
    if estimates is None:
        estimates = np.zeros(K)
    estimates = np.asarray(estimates, dtype=float)
    # analytical SE (R getSE convention on cluster-row IF)
    se = np.sqrt((Psi ** 2).sum(axis=0)) / G
    # Mammen two-point multipliers (mean 0, var 1), one per sampling unit (row)
    rng = np.random.default_rng(seed)
    k1 = (1 - np.sqrt(5)) / 2
    k2 = (1 + np.sqrt(5)) / 2
    p = (np.sqrt(5) + 1) / (2 * np.sqrt(5))
    V = np.where(rng.random((B, G)) < p, k1, k2)        # (B, G)
    # bootstrap draws of the estimator perturbation: R_b = (1/G) sum_c V_bc Psi_ck
    R = (V @ Psi) / G                                    # (B, K)
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
