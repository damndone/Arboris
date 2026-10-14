"""The honest-DID LP fast path solves exactly as scipy's linprog(method="highs")."""
from __future__ import annotations

import numpy as np
import pytest

from workbench.engine import highs_lp
from workbench.engine.highs_lp import linprog_highs

pytest.importorskip("highspy")


def _scipy(*args, **kwargs):
    return highs_lp._scipy(*args, **kwargs)


def _same(fast, slow):
    assert bool(fast.success) == bool(slow.success)
    if not slow.success:
        return
    assert np.array_equal(fast.x, slow.x)
    assert fast.fun == slow.fun
    expected = slow.ineqlin.marginals
    got = fast.ineqlin.marginals
    assert (expected is None and (got is None or len(got) == 0)) or np.array_equal(got, expected)


def test_every_lp_of_a_real_honest_rm_run_solves_identically(monkeypatch):
    """Record the LPs one R-reference honest_rm run poses, then solve each
    both ways: x, objective and marginals must be bit-for-bit equal."""
    import test_honest_did_engine as reference
    from workbench.engine import honest_did

    recorded = []

    def record(c, **kwargs):
        recorded.append((np.array(c, dtype=float), {k: (np.array(v) if v is not None and k != "bounds" else v) for k, v in kwargs.items()}))
        return linprog_highs(c, **kwargs)

    monkeypatch.setattr(honest_did, "linprog_highs", record)
    hrm = reference.HRM
    event = hrm["rm_event"][0]
    l_vec = np.zeros(hrm["numPost"])
    l_vec[event["event_index"]] = 1.0
    honest_did.honest_rm(betahat=np.array(hrm["betahat"]), sigma=np.array(hrm["sigma"]),
                         num_pre=hrm["numPre"], num_post=hrm["numPost"], l_vec=l_vec, mbar_grid=[1.0], alpha=0.05)
    assert len(recorded) > 1000
    shapes = {("A_ub" in kwargs and kwargs["A_ub"] is not None, "A_eq" in kwargs and kwargs["A_eq"] is not None) for _, kwargs in recorded}
    assert shapes == {(True, False), (False, True)}  # both LP forms honest-DID uses
    for c, kwargs in recorded[:: max(len(recorded) // 1500, 1)]:
        _same(linprog_highs(c, **kwargs), _scipy(c, kwargs.get("A_ub"), kwargs.get("b_ub"), kwargs.get("A_eq"), kwargs.get("b_eq"), kwargs["bounds"]))


@pytest.mark.parametrize("problem", [
    # infeasible: x >= 1 and x <= 0
    dict(c=[1.0], A_ub=[[-1.0], [1.0]], b_ub=[-1.0, 0.0], bounds=[(None, None)]),
    # unbounded below
    dict(c=[-1.0], A_ub=[[-1.0]], b_ub=[0.0], bounds=[(None, None)]),
    # equality with non-negative variables
    dict(c=[1.0, 2.0, 0.5], A_eq=[[1.0, 1.0, 1.0], [0.0, 1.0, -1.0]], b_eq=[1.0, 0.0], bounds=(0, None)),
])
def test_edge_cases_match(problem):
    c = problem.pop("c")
    _same(linprog_highs(c, **problem),
          _scipy(c, problem.get("A_ub"), problem.get("b_ub"), problem.get("A_eq"), problem.get("b_eq"), problem["bounds"]))


def test_scipy_can_be_forced(monkeypatch):
    monkeypatch.setenv("WORKBENCH_LP_SOLVER", "scipy")
    assert highs_lp.solver() == "scipy"
    result = linprog_highs([1.0], A_ub=[[-1.0]], b_ub=[-2.0], bounds=[(None, None)])
    assert result.success and result.x[0] == 2.0 and hasattr(result, "message")
