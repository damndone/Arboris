import numpy as np
from workbench.engine.cs_inference import multiplier_bootstrap


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
