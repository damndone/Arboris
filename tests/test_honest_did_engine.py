"""honest-DID (Rambachan-Roth DeltaRM) engine tests.

Task 1: oracle-shape sanity only (no Python engine yet). The R HonestDiD 0.2.8
fixtures under tests/fixtures/honest_did/ are the element-wise validation target
for the ported DeltaRM engine in later tasks (T2-T5).
"""
import json
import os

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIX = os.path.join(_HERE, "fixtures", "honest_did")

HRM = json.load(open(os.path.join(_FIX, "honest_rm.json")))


def test_oracle_present_and_widens():
    assert HRM["numPre"] == 3 and HRM["numPost"] == 4
    widths = [r["ub"] - r["lb"] for r in HRM["rm_avg"]]
    assert widths == sorted(widths)   # CI width non-decreasing in Mbar
    assert len(HRM["rm_event"]) == 4


def test_arm_constraints_cover_all_s_sign():
    ac = json.load(open(os.path.join(_FIX, "arm_constraints.json")))
    # s loops -(numPre-1):0 -> numPre values, times {TRUE,FALSE}
    assert len(ac["constraints"]) == ac["numPre"] * 2
    assert ac["s_indices"] == [-2, -1, 0]
    assert ac["primary"] == {"s": 0, "max_positive": True}
    for c in ac["constraints"]:
        assert len(c["A"]) == c["nrow"]
        assert all(len(row) == c["ncol"] for row in c["A"])


def test_conditional_test_instance_shape():
    ct = json.load(open(os.path.join(_FIX, "conditional_test.json")))
    # pure ARP conditional (simulation-free) -> no least-favorable cv field
    assert ct["hybrid_flag"] == "ARP"
    assert "lf_cv" not in ct
    assert ct["reject"] in (0, 1)
    # y_T row count matches A_RM row count; sigmaY is square of same size
    n = len(ct["A_RM"])
    assert len(ct["y_T"]) == n
    assert len(ct["sigmaY"]) == n and all(len(r) == n for r in ct["sigmaY"])


def test_arm_constraints_match_R():
    from workbench.engine.honest_did import create_arm_constraints

    ref = json.load(open(os.path.join(_FIX, "arm_constraints.json")))
    for c in ref["constraints"]:
        A = create_arm_constraints(
            num_pre=ref["numPre"],
            num_post=ref["numPost"],
            mbar=ref["Mbar"],
            s=c["s"],
            max_positive=c["max_positive"],
        )
        A_R = np.array(c["A"], dtype=float)
        assert A.shape == A_R.shape, (c["s"], c["max_positive"], A.shape, A_R.shape)
        # exact row-order match (port reproduces R's ordering)
        assert np.allclose(A, A_R, atol=1e-9), (c["s"], c["max_positive"])


CT = json.load(open(os.path.join(_FIX, "conditional_test.json")))


def test_arp_conditional_test_matches_R():
    """Option A: full reconstruction from raw betahat/sigma + intermediate checks."""
    from workbench.engine.honest_did import arp_conditional_test

    out = arp_conditional_test(
        betahat=np.array(HRM["betahat"], dtype=float),
        sigma=np.array(HRM["sigma"], dtype=float),
        num_pre=CT["numPre"],
        num_post=CT["numPost"],
        l_vec=np.array(CT["l_vec"], dtype=float),
        mbar=float(CT["Mbar"]),
        s=CT["s"],
        max_positive=CT["max_positive"],
        theta=CT["theta"],
        alpha=CT["alpha"],
    )

    # intermediate construction validated against the fixture (atol 1e-8)
    assert np.allclose(out["AGammaInv_one"], CT["AGammaInv_one"], atol=1e-8)
    assert np.allclose(out["AGammaInv_minusOne"], CT["AGammaInv_minusOne"], atol=1e-8)
    assert np.allclose(out["Y"], CT["Y"], atol=1e-8)
    assert np.allclose(out["sigmaY"], CT["sigmaY"], atol=1e-8)
    assert np.allclose(out["y_T"], CT["y_T"], atol=1e-8)
    # rowsForARP reported 1-based to match R fixture, exact
    assert out["rowsForARP_1based"] == CT["rowsForARP"]

    # deterministic output
    assert int(out["reject"]) == int(CT["reject"])
    assert abs(out["eta"] - CT["eta"]) < 1e-6


def test_lp_conditional_test_low_level_matches_R():
    """Option B: low-level test directly on fixture y_T / X_T / sigmaY / rows."""
    from workbench.engine.honest_did import _lp_conditional_test

    y_T = np.array(CT["y_T"], dtype=float)
    X_T = np.array(CT["AGammaInv_minusOne"], dtype=float)
    sigma_Y = np.array(CT["sigmaY"], dtype=float)
    rows0 = [r - 1 for r in CT["rowsForARP"]]  # 1-based R -> 0-based

    out = _lp_conditional_test(
        y_T=y_T, X_T=X_T, sigma=sigma_Y, alpha=CT["alpha"], rows_for_arp=rows0
    )
    assert int(out["reject"]) == int(CT["reject"])
    assert abs(out["eta"] - CT["eta"]) < 1e-6


# ---------------------------------------------------------------------------
# Task 4: test-inversion CI for one Mbar (grid + union) + degenerate dual path.
# ---------------------------------------------------------------------------


def test_ci_for_one_mbar_matches_R():
    from workbench.engine.honest_did import arp_confidence_interval

    ref = next(r for r in HRM["rm_avg"] if abs(r["Mbar"] - 1.0) < 1e-9)
    lb, ub = arp_confidence_interval(
        betahat=np.array(HRM["betahat"]),
        sigma=np.array(HRM["sigma"]),
        num_pre=HRM["numPre"],
        num_post=HRM["numPost"],
        l_vec=np.array(HRM["l_avg"]),
        mbar=1.0,
        alpha=0.05,
    )
    assert abs(lb - ref["lb"]) < 1e-3 and abs(ub - ref["ub"]) < 1e-3


def test_grid_accept_elementwise_matches_R():
    from workbench.engine.honest_did import _arp_accept_grid

    GA = json.load(open(os.path.join(_FIX, "grid_accept.json")))
    acc = _arp_accept_grid(
        betahat=np.array(HRM["betahat"]),
        sigma=np.array(HRM["sigma"]),
        num_pre=HRM["numPre"],
        num_post=HRM["numPost"],
        l_vec=np.array(HRM["l_avg"]),
        mbar=1.0,
        alpha=0.05,
        grid=np.array(GA["grid"]),
    )
    mism = int(np.sum(np.asarray(acc, int) != np.asarray(GA["accept"], int)))
    assert mism <= 3, f"{mism} accept mismatches (dual-path port likely wrong if clustered)"


# ---------------------------------------------------------------------------
# Task 5: honest_rm top-level entry (Mbar grid + breakdown + guards + determinism).
# ---------------------------------------------------------------------------


def test_honest_rm_avg_matches_R():
    from workbench.engine.honest_did import honest_rm

    out = honest_rm(
        betahat=np.array(HRM["betahat"]),
        sigma=np.array(HRM["sigma"]),
        num_pre=HRM["numPre"],
        num_post=HRM["numPost"],
        l_vec=np.array(HRM["l_avg"]),
        mbar_grid=HRM["mbar_grid"],
        alpha=0.05,
    )
    assert len(out["results"]) == len(HRM["rm_avg"])
    for r_ours, r_ref in zip(out["results"], HRM["rm_avg"]):
        assert abs(r_ours["Mbar"] - r_ref["Mbar"]) < 1e-12
        assert abs(r_ours["lb"] - r_ref["lb"]) < 1e-3
        assert abs(r_ours["ub"] - r_ref["ub"]) < 1e-3


def test_honest_rm_event_matches_R():
    from workbench.engine.honest_did import honest_rm

    numPost = HRM["numPost"]
    for ev in HRM["rm_event"]:
        j = ev["event_index"]
        lv = np.zeros(numPost)
        lv[j] = 1.0
        out = honest_rm(
            betahat=np.array(HRM["betahat"]),
            sigma=np.array(HRM["sigma"]),
            num_pre=HRM["numPre"],
            num_post=numPost,
            l_vec=lv,
            mbar_grid=[1.0],
            alpha=0.05,
        )
        r = out["results"][0]
        assert abs(r["lb"] - ev["lb"]) < 1e-3 and abs(r["ub"] - ev["ub"]) < 1e-3


def test_honest_rm_deterministic():
    from workbench.engine.honest_did import honest_rm

    kw = dict(
        betahat=np.array(HRM["betahat"]),
        sigma=np.array(HRM["sigma"]),
        num_pre=HRM["numPre"],
        num_post=HRM["numPost"],
        l_vec=np.array(HRM["l_avg"]),
        mbar_grid=HRM["mbar_grid"],
        alpha=0.05,
    )
    a, b = honest_rm(**kw), honest_rm(**kw)
    assert [r["lb"] for r in a["results"]] == [r["lb"] for r in b["results"]]
    assert [r["ub"] for r in a["results"]] == [r["ub"] for r in b["results"]]
    assert a["breakdown"] == b["breakdown"]


def test_honest_rm_guards():
    import pytest

    from workbench.engine.honest_did import honest_rm, HonestDiDError

    sig = np.eye(4)
    with pytest.raises(HonestDiDError, match="HONEST_NO_PRE_PERIODS"):
        honest_rm(betahat=np.zeros(4), sigma=sig, num_pre=0, num_post=4,
                  l_vec=np.ones(4) / 4, mbar_grid=[1.0])
    with pytest.raises(HonestDiDError, match="HONEST_NO_POST_PERIODS"):
        honest_rm(betahat=np.zeros(4), sigma=sig, num_pre=4, num_post=0,
                  l_vec=np.array([]), mbar_grid=[1.0])
    bad = np.ones((4, 4))
    with pytest.raises(HonestDiDError, match="HONEST_DEGENERATE_SIGMA"):
        honest_rm(betahat=np.zeros(4), sigma=bad, num_pre=2, num_post=2,
                  l_vec=np.ones(2) / 2, mbar_grid=[1.0])


# --- Task 2: ΔSD second-difference operator (R .create_A_SD port) ---

def test_create_a_sd_matches_r_oracle():
    import json as _json
    from pathlib import Path
    from workbench.engine.honest_did import _create_a_sd
    o = _json.loads((Path(_FIX) / "a_sd.json").read_text())
    A = _create_a_sd(num_pre=o["numPre"], num_post=o["numPost"])
    expected = np.asarray(o["A_sd"], dtype=float)
    assert A.shape == expected.shape          # 12x7 for the fixture
    assert np.allclose(A, expected, atol=1e-9)


def test_create_a_sd_two_sided_structure():
    from workbench.engine.honest_did import _create_a_sd
    A = _create_a_sd(num_pre=3, num_post=4)
    k = A.shape[0] // 2
    assert np.allclose(A[k:], -A[:k])          # rbind(Atilde, -Atilde)


def test_create_a_sd_insufficient_periods_raises():
    import pytest
    from workbench.engine.honest_did import _create_a_sd, HonestDiDError
    with pytest.raises(HonestDiDError, match="HONEST_SD_INSUFFICIENT_PERIODS"):
        _create_a_sd(num_pre=0, num_post=1)    # total 1 -> no second-diff row


def test_folded_normal_quantile_t0_is_standard_normal():
    from workbench.engine.honest_did import _folded_normal_quantile
    from scipy.stats import norm
    # |N(0,1)| (1-alpha) quantile == two-sided z_{1-alpha/2}
    assert abs(_folded_normal_quantile(0.0, alpha=0.05) - norm.ppf(0.975)) < 1e-8


def test_folded_normal_quantile_strictly_increasing_in_t():
    from workbench.engine.honest_did import _folded_normal_quantile
    ts = [0.0, 0.5, 1.0, 2.0, 5.0]
    vals = [_folded_normal_quantile(t, alpha=0.05) for t in ts]
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_folded_normal_quantile_satisfies_cdf_equation():
    from workbench.engine.honest_did import _folded_normal_quantile
    from scipy.stats import norm
    t = 1.3
    c = _folded_normal_quantile(t, alpha=0.05)
    assert abs((norm.cdf(c - t) - norm.cdf(-c - t)) - 0.95) < 1e-8


def test_folded_normal_quantile_monotone_is_nondecreasing():
    from workbench.engine.honest_did import _folded_normal_quantile_monotone
    # even if input t is non-monotone, output is forced nondecreasing
    ts = [0.0, 1.0, 0.9, 2.0]
    out = _folded_normal_quantile_monotone(ts, alpha=0.05)
    assert np.all(np.diff(out) >= 0)
    # the first three "true" values are increasing then the 0.9 would dip; clamp holds it
    assert out[2] >= out[1]


# ---------------------------------------------------------------------------
# Task 4: FLCI (DeltaSD) convex sub-problems + public flci(). Oracle =
# flci_sd.json (regenerated with an analytic qfoldednormal) + intermediates.
# ---------------------------------------------------------------------------

FLCI_INT = json.load(open(os.path.join(_FIX, "flci_intermediates.json")))
FLCI_SD = json.load(open(os.path.join(_FIX, "flci_sd.json")))


def _flci_inputs():
    beta = np.array(HRM["betahat"], dtype=float)
    sigma = np.array(HRM["sigma"], dtype=float)
    return beta, sigma, HRM["numPre"], HRM["numPost"], np.array(FLCI_SD["l_vec"], dtype=float)


def test_flci_hmin_matches_r():
    from workbench.engine.honest_did import _flci_min_sd
    _beta, sigma, npre, npost, l = _flci_inputs()
    hMin = _flci_min_sd(sigma=sigma, num_pre=npre, num_post=npost, l_vec=l)
    assert abs(hMin - FLCI_INT["hMin"]) < 1e-6


def test_flci_h0_matches_r():
    from workbench.engine.honest_did import _flci_h_for_min_bias
    _beta, sigma, npre, npost, l = _flci_inputs()
    h0 = _flci_h_for_min_bias(sigma=sigma, num_pre=npre, num_post=npost, l_vec=l)
    assert abs(h0 - FLCI_INT["h0"]) < 1e-6


def test_flci_worst_case_bias_finite_and_lopt_matches_r():
    # At h = hMin the worst-case bias optimizer's L_opt should match R's
    # optimalPrePeriodVec for the M=0 anchor (whose chosen h is hMin).
    from workbench.engine.honest_did import (
        _flci_min_sd,
        _flci_worst_case_bias_given_h,
    )
    _beta, sigma, npre, npost, l = _flci_inputs()
    hMin = _flci_min_sd(sigma=sigma, num_pre=npre, num_post=npost, l_vec=l)
    wb = _flci_worst_case_bias_given_h(
        h=hMin, sigma=sigma, num_pre=npre, num_post=npost, l_vec=l
    )
    assert wb["status"] == "optimal"
    assert np.isfinite(wb["value"])
    L_r = np.array(FLCI_INT["perM"][0]["optimalPrePeriodVec"], dtype=float)
    assert np.max(np.abs(wb["L_opt"] - L_r)) < 1e-4


def test_flci_matches_r_oracle_over_m_grid():
    from workbench.engine.honest_did import flci
    beta, sigma, npre, npost, l = _flci_inputs()
    alpha = FLCI_SD["alpha"]
    for row in FLCI_SD["results"]:
        r = flci(
            betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
            l_vec=l, m=row["M"], alpha=alpha,
        )
        # half-length (the FLCI width) is the load-bearing quantity: 1e-6.
        assert abs(r["half_length"] - row["optimalHalfLength"]) < 1e-6, row["M"]
        if row["M"] == 0:
            # M=0 center sits on a FLAT bias manifold: R's CVXR/ECOS leaves
            # ~2e-10 slack in hMin which the degenerate worst-case-bias direction
            # amplifies ~1e4x into the L_opt -> center. The CI WIDTH is exact
            # (above); only the center wobbles at solver-noise scale. The M=0
            # anchor below pins the half-length analytically.
            assert abs(r["lb"] - row["lb"]) < 5e-6, row["M"]
            assert abs(r["ub"] - row["ub"]) < 5e-6, row["M"]
        else:
            assert abs(r["lb"] - row["lb"]) < 1e-6, row["M"]
            assert abs(r["ub"] - row["ub"]) < 1e-6, row["M"]


def test_flci_m_zero_is_min_sd_ci():
    from scipy.stats import norm
    from workbench.engine.honest_did import _flci_min_sd, flci
    beta, sigma, npre, npost, l = _flci_inputs()
    hMin = _flci_min_sd(sigma=sigma, num_pre=npre, num_post=npost, l_vec=l)
    r = flci(
        betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
        l_vec=l, m=0.0, alpha=0.05,
    )
    assert abs(r["half_length"] - norm.ppf(0.975) * hMin) < 1e-8
