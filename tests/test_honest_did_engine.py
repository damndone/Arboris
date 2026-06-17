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
