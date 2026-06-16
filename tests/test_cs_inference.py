import numpy as np
import pytest
from workbench.engine.cs_inference import multiplier_bootstrap


def test_bootstrap_B_below_one_raises():
    # B=0 used to reach an empty-quantile IndexError; guard it structurally.
    with pytest.raises(ValueError, match="CS_BAD_BOOTSTRAP_B"):
        multiplier_bootstrap(_if(), B=0, alpha=0.05, seed=1)


def _if():
    rng = np.random.default_rng(0)
    return rng.normal(size=(80, 5))


def test_determinism_same_seed():
    a = multiplier_bootstrap(_if(), B=1000, alpha=0.05, seed=12345)
    b = multiplier_bootstrap(_if(), B=1000, alpha=0.05, seed=12345)
    assert np.array_equal(a["uniform_crit"], b["uniform_crit"])
    assert np.allclose(a["se"], b["se"])


def test_different_seed_changes_crit_but_not_se_much():
    a = multiplier_bootstrap(_if(), B=2000, alpha=0.05, seed=1)
    b = multiplier_bootstrap(_if(), B=2000, alpha=0.05, seed=2)
    # analytical SE is seed-independent; bootstrap crit varies but stays sane
    assert np.allclose(a["se"], b["se"])
    assert a["uniform_crit"] > 0 and b["uniform_crit"] > 0


def test_uniform_band_at_least_pointwise():
    r = multiplier_bootstrap(_if(), B=4000, alpha=0.05, seed=7)
    assert r["uniform_crit"] >= 1.959   # sup-t critical value >= z_{0.975}


def test_se_matches_analytical():
    # se_k = sqrt( G^-2 * sum_c Psi_ck^2 )   (cluster-row IF, R getSE convention)
    psi = _if()
    r = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=3)
    G = psi.shape[0]
    expected = np.sqrt((psi**2).sum(axis=0)) / G
    assert np.allclose(r["se"], expected, rtol=1e-12)


def test_pointwise_and_uniform_band_shapes():
    psi = _if()
    est = np.arange(psi.shape[1], dtype=float)
    r = multiplier_bootstrap(psi, B=1000, alpha=0.05, seed=9, estimates=est)
    assert r["pointwise_ci"].shape == (psi.shape[1], 2)
    assert r["uniform_band"].shape == (psi.shape[1], 2)
    # uniform band is wider than (or equal to) pointwise
    assert np.all(r["uniform_band"][:, 1] - r["uniform_band"][:, 0] >=
                  r["pointwise_ci"][:, 1] - r["pointwise_ci"][:, 0] - 1e-9)


def test_degenerate_zero_column_does_not_nan_the_band():
    psi = _if().copy()
    psi[:, 2] = 0.0                      # one fully-degenerate column
    est = np.arange(psi.shape[1], dtype=float)
    r = multiplier_bootstrap(psi, B=1000, alpha=0.05, seed=11, estimates=est)
    assert np.isfinite(r["uniform_crit"])                 # not NaN
    assert np.all(np.isfinite(r["uniform_band"]))         # whole band finite
    # the degenerate column has zero-width band; others are non-degenerate
    assert r["uniform_band"][2, 1] - r["uniform_band"][2, 0] == 0.0
    assert np.all(r["uniform_band"][[0, 1, 3, 4], 1] -
                  r["uniform_band"][[0, 1, 3, 4], 0] > 0)


def test_clusters_none_is_unchanged():
    psi = _if()
    a = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=3)
    b = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=3, clusters=None)
    assert np.array_equal(a["se"], b["se"])
    assert a["uniform_crit"] == b["uniform_crit"]


def test_distinct_clusters_equal_entity_identity():
    # each row its own cluster => identical to unclustered (rowsum is identity)
    psi = _if()                                   # (80, 5)
    distinct = np.arange(psi.shape[0])
    a = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=9)
    b = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=9, clusters=distinct)
    assert np.allclose(a["se"], b["se"])
    assert np.allclose(a["uniform_band"], b["uniform_band"])


def test_clustered_se_matches_rowsum_crve():
    # se under clustering = sqrt(sum_c S_c^2)/N  (N = #rows, not #clusters)
    psi = _if()                                   # (80, 5)
    clusters = np.arange(psi.shape[0]) % 16       # 16 clusters of 5
    r = multiplier_bootstrap(psi, B=200, alpha=0.05, seed=4, clusters=clusters)
    import pandas as pd
    S = pd.DataFrame(psi).groupby(clusters).sum().to_numpy()   # (16, 5)
    expected = np.sqrt((S ** 2).sum(axis=0)) / psi.shape[0]
    assert np.allclose(r["se"], expected, atol=1e-12)
