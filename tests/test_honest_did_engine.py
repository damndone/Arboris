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
