"""Linear programs for honest-DID, solved by HiGHS without scipy's per-call wrapper.

``honest_rm`` solves tens of thousands of small LPs. Profiling the R-matching
event test (61 s, 86,439 LPs) put 7.9 s in HiGHS itself and the rest in
scipy's per-call wrapper, which builds an options manager for every option
of every call. This module poses the same problem to the same HiGHS release
(highspy is pinned to the version scipy bundles) the way
``scipy.optimize.linprog(method="highs")`` does:

- constraints stacked as ``A_ub`` then ``A_eq`` in column-wise form, with
  ``-inf <= A_ub x <= b_ub`` and ``b_eq <= A_eq x <= b_eq``;
- infinities replaced by HiGHS's infinity;
- the options scipy sets (presolve on, dual simplex strategy, no output);
- one solver per thread whose solution and basis are cleared before each
  problem, so nothing carries over between calls;
- success only for an optimal status whose solution passes scipy's own
  feasibility re-check (``_check_result``, tolerance ``sqrt(1e-9) * 10``).

tests/test_highs_lp.py holds it to bitwise-identical ``x``, objective and
inequality marginals against ``linprog`` and to identical ``honest_rm``
output on the R-reference fixtures. Without highspy, or with
``WORKBENCH_LP_SOLVER=scipy``, ``linprog`` itself is used.
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace
from typing import Any, Sequence

import numpy as np

try:  # pragma: no cover - availability depends on the environment
    import highspy as _highspy
except ImportError:  # pragma: no cover
    _highspy = None

_FEASIBILITY_TOL = float(np.sqrt(1e-9) * 10)


def solver() -> str:
    """Which path solves: "highspy" when available and not overridden."""

    if os.environ.get("WORKBENCH_LP_SOLVER") == "scipy" or _highspy is None:
        return "scipy"
    return "highspy"


def _bounds_arrays(bounds: Any, n: int) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(bounds, tuple) and len(bounds) == 2 and not isinstance(bounds[0], (tuple, list)):
        pairs: Sequence[Any] = [bounds] * n
    else:
        pairs = list(bounds)
    lower = np.array([-np.inf if low is None else float(low) for low, _ in pairs], dtype=float)
    upper = np.array([np.inf if high is None else float(high) for _, high in pairs], dtype=float)
    return lower, upper


def _scipy(c, A_ub, b_ub, A_eq, b_eq, bounds) -> Any:
    from scipy.optimize import linprog

    return linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")


_LOCAL = threading.local()


def _solver() -> Any:
    """One HiGHS instance per thread, set up with the options scipy sets."""

    highs = getattr(_LOCAL, "highs", None)
    if highs is None:
        highs = _highspy.Highs()
        for name, value in (
            ("output_flag", False),
            ("log_to_console", False),
            ("presolve", "on"),
            ("highs_debug_level", 0),
            ("simplex_strategy", 1),  # kSimplexStrategyDual, as scipy sets it
        ):
            highs.setOptionValue(name, value)
        _LOCAL.highs = highs
    return highs


def _replace_inf(values: np.ndarray) -> np.ndarray:
    values = values.copy()
    infinite = np.isinf(values)
    values[infinite] = np.sign(values[infinite]) * _highspy.kHighsInf
    return values


def linprog_highs(
    c: Any,
    *,
    A_ub: Any = None,
    b_ub: Any = None,
    A_eq: Any = None,
    b_eq: Any = None,
    bounds: Any = (0, None),
) -> Any:
    """``linprog(method="highs")`` for the fields honest-DID reads:
    ``success``, ``x``, ``fun`` and ``ineqlin.marginals``."""

    if solver() == "scipy":
        return _scipy(c, A_ub, b_ub, A_eq, b_eq, bounds)

    cost = np.asarray(c, dtype=float).reshape(-1)
    n = cost.size
    a_ub = np.zeros((0, n)) if A_ub is None else np.atleast_2d(np.asarray(A_ub, dtype=float))
    a_eq = np.zeros((0, n)) if A_eq is None else np.atleast_2d(np.asarray(A_eq, dtype=float))
    rhs_ub = np.zeros(0) if b_ub is None else np.asarray(b_ub, dtype=float).reshape(-1)
    rhs_eq = np.zeros(0) if b_eq is None else np.asarray(b_eq, dtype=float).reshape(-1)
    m_ub = rhs_ub.size
    lower, upper = _bounds_arrays(bounds, n)

    matrix = np.vstack([a_ub, a_eq])
    lhs = np.concatenate([np.full(m_ub, -np.inf), rhs_eq])
    rhs = np.concatenate([rhs_ub, rhs_eq])
    # Column-wise (CSC) storage of the dense matrix, zeros dropped as
    # scipy.sparse.csc_array does: column by column, rows ascending.
    nonzero = matrix.T != 0
    _columns, row_index = np.nonzero(nonzero)
    starts = np.concatenate([[0], np.cumsum(nonzero.sum(axis=1))])
    indices = row_index
    values = matrix.T[nonzero]

    lp = _highspy.HighsLp()
    lp.num_col_ = n
    lp.num_row_ = int(matrix.shape[0])
    lp.col_cost_ = cost
    lp.col_lower_ = _replace_inf(lower)
    lp.col_upper_ = _replace_inf(upper)
    lp.row_lower_ = _replace_inf(lhs)
    lp.row_upper_ = _replace_inf(rhs)
    lp.a_matrix_.format_ = _highspy.MatrixFormat.kColwise
    lp.a_matrix_.num_col_ = n
    lp.a_matrix_.num_row_ = int(matrix.shape[0])
    lp.a_matrix_.start_ = np.asarray(starts, dtype=np.int32)
    lp.a_matrix_.index_ = np.asarray(indices, dtype=np.int32)
    lp.a_matrix_.value_ = np.asarray(values, dtype=float)

    highs = _solver()
    # No warm start: the previous problem's solution and basis are dropped,
    # so each problem is solved as by a new solver (as scipy does).
    highs.clearSolver()
    highs.passModel(lp)
    highs.run()
    status = highs.getModelStatus()
    if status != _highspy.HighsModelStatus.kOptimal:
        return SimpleNamespace(success=False, x=None, fun=None, ineqlin=SimpleNamespace(marginals=None))

    solution = highs.getSolution()
    x = np.array(solution.col_value)
    row_value = np.array(solution.row_value)
    row_dual = np.array(solution.row_dual)
    fun = highs.getInfo().objective_function_value
    slack = _replace_inf(rhs) - row_value
    feasible = not (
        np.isnan(x).any()
        or np.isnan(fun)
        or np.isnan(slack).any()
        or not np.all((x >= lower - _FEASIBILITY_TOL) & (x <= upper + _FEASIBILITY_TOL))
        or (slack[:m_ub] < -_FEASIBILITY_TOL).any()
        or (np.abs(slack[m_ub:]) > _FEASIBILITY_TOL).any()
    )
    return SimpleNamespace(
        success=feasible,
        x=x,
        fun=fun,
        ineqlin=SimpleNamespace(marginals=row_dual[:m_ub]),
    )
