"""Whole-feature adversarial probes for honest-DID (v1.5.7).

Failure-path / silent-wrongness / degrade-not-fail coverage that the shipped
test suite under-covered. SMALL grids for speed (these do NOT validate against
the grid=1000 oracles; the oracle tests in test_honest_did_engine.py do).
"""
import numpy as np
import pandas as pd
import pytest

from workbench.engine.honest_did import honest_rm, arp_confidence_interval, HonestDiDError
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic


def _pd_sigma(n, seed):
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    return A @ A.T + 0.5 * np.eye(n)


# --------------------------------------------------------------------------
# Probe 1: engine degenerate dimensions run and stay finite.
# --------------------------------------------------------------------------

def test_engine_num_pre_one_runs_finite():
    # ΔRM with a single pre-period (s ranges over just s=0).
    sig = _pd_sigma(3, 0)
    beta = np.array([0.0, 0.3, 0.5])
    r = honest_rm(betahat=beta, sigma=sig, num_pre=1, num_post=2,
                  l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0, 1.0], grid_points=120)
    for rr in r["results"]:
        assert np.isfinite(rr["lb"]) and np.isfinite(rr["ub"])
        assert rr["lb"] <= rr["ub"]


def test_engine_num_post_one_runs_finite():
    # Single post-period: l_vec length 1, X_T (AGammaInv_minusOne) has 0 columns.
    sig = _pd_sigma(3, 1)
    beta = np.array([0.0, 0.1, 0.4])
    r = honest_rm(betahat=beta, sigma=sig, num_pre=2, num_post=1,
                  l_vec=np.array([1.0]), mbar_grid=[0.0, 1.0], grid_points=120)
    for rr in r["results"]:
        assert np.isfinite(rr["lb"]) and np.isfinite(rr["ub"])
        assert rr["lb"] <= rr["ub"]
    # Mbar=0 (parallel trends) must be no wider than Mbar=1.
    m0, m1 = r["results"][0], r["results"][1]
    assert (m0["ub"] - m0["lb"]) <= (m1["ub"] - m1["lb"]) + 1e-9


def test_engine_num_pre_and_post_one_runs_finite():
    sig = _pd_sigma(2, 2)
    beta = np.array([0.0, 0.4])
    r = honest_rm(betahat=beta, sigma=sig, num_pre=1, num_post=1,
                  l_vec=np.array([1.0]), mbar_grid=[0.0, 1.0], grid_points=120)
    for rr in r["results"]:
        assert np.isfinite(rr["lb"]) and np.isfinite(rr["ub"])


def test_engine_mbar_zero_is_tightest():
    sig = _pd_sigma(4, 3)
    beta = np.array([0.0, 0.05, 0.3, 0.4])
    r = honest_rm(betahat=beta, sigma=sig, num_pre=2, num_post=2,
                  l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0, 0.5, 1.0, 2.0],
                  grid_points=200)
    widths = [rr["ub"] - rr["lb"] for rr in r["results"]]
    assert all(np.isfinite(w) for w in widths)
    # widths monotonically non-decreasing in Mbar
    for a, b in zip(widths, widths[1:]):
        assert a <= b + 1e-9


def test_engine_near_singular_pd_sigma_no_nan():
    # Tiny-but-positive smallest eigenvalue must NOT slip past the guard into a
    # nan/inf-producing LP. (The guard fires only on eig <= 0.)
    Q, _ = np.linalg.qr(np.random.default_rng(5).standard_normal((3, 3)))
    for tiny in (1e-10, 1e-16):
        sig = Q @ np.diag([1.0, 1.0, tiny]) @ Q.T
        sig = 0.5 * (sig + sig.T)
        beta = np.array([0.0, 0.2, 0.5])
        r = honest_rm(betahat=beta, sigma=sig, num_pre=1, num_post=2,
                      l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0, 1.0],
                      grid_points=100)
        for rr in r["results"]:
            assert np.isfinite(rr["lb"]) and np.isfinite(rr["ub"]), (tiny, rr)


def test_engine_negative_eigenvalue_guard_fires():
    Q, _ = np.linalg.qr(np.random.default_rng(6).standard_normal((3, 3)))
    sig = Q @ np.diag([1.0, 1.0, -1e-8]) @ Q.T
    sig = 0.5 * (sig + sig.T)
    with pytest.raises(HonestDiDError, match="HONEST_DEGENERATE_SIGMA"):
        honest_rm(betahat=np.array([0.0, 0.2, 0.5]), sigma=sig, num_pre=1,
                  num_post=2, l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0],
                  grid_points=50)


# --------------------------------------------------------------------------
# Probe 6: breakdown != None correctness (both lb>0 and ub<0 directions).
# --------------------------------------------------------------------------

def test_breakdown_is_largest_mbar_excluding_zero_negative_effect():
    sig = 0.05 * np.eye(4)
    beta = np.array([0.0, 0.0, -1.0, -1.0])  # excludes 0 via ub<0 at small Mbar
    r = honest_rm(betahat=beta, sigma=sig, num_pre=2, num_post=2,
                  l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0, 0.5, 1.0, 1.5, 2.0],
                  grid_points=600)
    excl = [rr["Mbar"] for rr in r["results"]
            if np.isfinite(rr["lb"]) and (rr["lb"] > 0 or rr["ub"] < 0)]
    assert r["breakdown"] == (max(excl) if excl else None)
    assert r["breakdown"] is not None       # this design DOES break down somewhere


def test_breakdown_none_when_all_include_zero():
    # Wide Sigma, zero effect: every CI brackets 0 -> breakdown None.
    sig = _pd_sigma(4, 9)
    beta = np.zeros(4)
    r = honest_rm(betahat=beta, sigma=sig, num_pre=2, num_post=2,
                  l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0, 1.0], grid_points=120)
    assert r["breakdown"] is None


# --------------------------------------------------------------------------
# Probe 3: determinism across 3 runs (byte-identical results).
# --------------------------------------------------------------------------

def test_engine_deterministic_three_runs():
    sig = _pd_sigma(4, 4)
    beta = np.array([0.0, 0.05, 0.3, 0.4])
    kw = dict(betahat=beta, sigma=sig, num_pre=2, num_post=2,
              l_vec=np.array([0.5, 0.5]), mbar_grid=[0.0, 1.0], grid_points=150)
    r1 = honest_rm(**kw)
    r2 = honest_rm(**kw)
    r3 = honest_rm(**kw)
    assert r1 == r2 == r3


# --------------------------------------------------------------------------
# Probe 1/2: adapter skipped paths + degrade-not-fail (no throw).
# --------------------------------------------------------------------------

def _agg(labels, est, N=40, seed=3):
    rng = np.random.default_rng(seed)
    return {"label": labels, "estimate": est,
            "component_if": (rng.standard_normal((N, len(labels))) * 0.1).tolist()}


def test_adapter_all_pre_skips():
    out = honest_did_from_cs_dynamic(_agg([-3.0, -2.0, -1.0], [0.1, 0.2, 0.0]),
                                     row_cluster=np.arange(40), n_total=40,
                                     mbar_grid=[0.0], grid_points=30)
    assert out["rm"]["status"] == "not_available"
    assert "HONEST_NO_POST_PERIODS" in out["rm"]["reason"]
    assert out["sd"]["status"] == "not_available"
    assert "HONEST_NO_POST_PERIODS" in out["sd"]["reason"]


def test_adapter_all_post_skips():
    out = honest_did_from_cs_dynamic(_agg([-1.0, 0.0, 1.0, 2.0], [0.0, 0.3, 0.4, 0.5]),
                                     row_cluster=np.arange(40), n_total=40,
                                     mbar_grid=[0.0], grid_points=30)
    assert out["rm"]["status"] == "not_available"
    assert "HONEST_NO_PRE_PERIODS" in out["rm"]["reason"]
    assert out["sd"]["status"] == "not_available"
    assert "HONEST_NO_PRE_PERIODS" in out["sd"]["reason"]


# --------------------------------------------------------------------------
# Probe 4/7: cluster-robust Sigma follows the run's clustering.
# --------------------------------------------------------------------------

def test_adapter_entity_sigma_equals_outer_if():
    rng = np.random.default_rng(11)
    N = 40
    CIF = rng.standard_normal((N, 4)) * 0.1
    agg = {"label": [-2.0, -1.0, 0.0, 1.0], "estimate": [0.05, 0.0, 0.3, 0.4],
           "component_if": CIF.tolist()}
    out = honest_did_from_cs_dynamic(agg, row_cluster=np.arange(N), n_total=N,
                                     mbar_grid=[0.0], grid_points=30)
    keep = [0, 2, 3]  # e=-1 (idx 1) dropped
    expected = (CIF.T @ CIF / N ** 2)[np.ix_(keep, keep)]
    assert np.allclose(np.array(out["_debug_sigma"]), expected)


def test_adapter_clustered_sigma_differs_and_matches_cluster_sums():
    rng = np.random.default_rng(11)
    N = 40
    CIF = rng.standard_normal((N, 4)) * 0.1
    agg = {"label": [-2.0, -1.0, 0.0, 1.0], "estimate": [0.05, 0.0, 0.3, 0.4],
           "component_if": CIF.tolist()}
    sig_ent = np.array(honest_did_from_cs_dynamic(
        agg, row_cluster=np.arange(N), n_total=N, mbar_grid=[0.0],
        grid_points=30)["_debug_sigma"])
    clusters = np.repeat(np.arange(4), 10)
    sig_cl = np.array(honest_did_from_cs_dynamic(
        agg, row_cluster=clusters, n_total=N, mbar_grid=[0.0],
        grid_points=30)["_debug_sigma"])
    assert not np.allclose(sig_cl, sig_ent)
    uniq, inv = np.unique(clusters, return_inverse=True)
    Sc = np.zeros((len(uniq), 4))
    np.add.at(Sc, inv, CIF)
    keep = [0, 2, 3]
    expected = (Sc.T @ Sc / N ** 2)[np.ix_(keep, keep)]
    assert np.allclose(sig_cl, expected)


# --------------------------------------------------------------------------
# Probe 2 (CRITICAL escape): a GENERIC (non-HonestDiDError) blowup inside the
# adapter must NOT fail run_cs_did -- the runner's `except Exception` contains it.
# --------------------------------------------------------------------------

def _staggered_csv(tmp_path):
    rng = np.random.default_rng(3)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0), ("G", 2019), ("H", 2021),
                        ("I", 0), ("J", 2019)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / "csdid.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_generic_exception_in_honest_degrades_not_fails(tmp_path, monkeypatch):
    import workbench.econometrics.runner as runner
    from workbench.orchestrator import run_workflow as _rw
    from workbench.projects import create_project
    from workbench.artifacts import read_json

    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 80)

    # Force a generic (non-HonestDiDError) blowup deep inside honest_rm -- this is
    # NOT caught by the adapter's narrow `except HonestDiDError`; only the runner's
    # `except Exception` can contain it.
    import workbench.engine.honest_did_adapter as ad

    def boom(**kw):
        raise RuntimeError("simulated internal blowup")

    monkeypatch.setattr(ad, "honest_rm", boom)

    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat", honest_did=True)
    run_root = project.root / "runs" / result["run_id"]
    # run STILL completes despite the generic blowup
    assert read_json(run_root / "run_manifest.json")["status"] == "completed"
    art = read_json(run_root / "cs_did.json")
    hd = art["honest_did"]
    # the runner's `except Exception` degrades BOTH tracks with the same reason
    assert hd["rm"]["status"] == "degraded"
    assert "HONEST_INTERNAL_ERROR" in hd["rm"]["reason"]
    assert hd["sd"]["status"] == "degraded"
    assert "HONEST_INTERNAL_ERROR" in hd["sd"]["reason"]
    assert not any(k.startswith("_debug_") for k in hd)
