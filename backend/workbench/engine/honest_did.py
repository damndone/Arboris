"""honest-DID (Rambachan-Roth) ΔRM sensitivity engine.

Faithful Python port of R ``HonestDiD 0.2.8``. The committed R oracles under
``tests/fixtures/honest_did/`` are the element-wise source of truth.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog
from scipy.stats import truncnorm


class HonestDiDError(ValueError):
    """HONEST_*-prefixed failure; degrades the honest_did block, never fails the run."""


def create_arm_constraints(
    *,
    num_pre: int,
    num_post: int,
    mbar: float,
    s: int,
    max_positive: bool = True,
    drop_zero: bool = True,
) -> np.ndarray:
    """ΔRM(Mbar) per-``(s, sign)`` constraint matrix ``A``.

    Faithful port of R ``HonestDiD:::.create_A_RM``. ``arm_constraints.json`` is
    the oracle. The full ΔRM set is the UNION over ``s in -(num_pre-1)..0`` and
    ``max_positive in {True, False}``; this builds ONE polyhedron of that union.

    Index conversion (R 1-based -> Python 0-based):
      * ``Atilde``: n x (n+1), n = num_pre + num_post. Row ``i`` (0..n-1) gets
        ``[-1, 1]`` at columns ``[i, i+1]``.
      * ``v_max_dif``: R writes columns ``(num_pre+s):(num_pre+1+s)`` (1-based).
        0-based those two columns are ``num_pre + s - 1`` and ``num_pre + s``.
      * ``drop_zero``: delete 1-based column ``num_pre+1`` = 0-based column
        ``num_pre`` (the normalized event-time -1 reference period).
    """
    n = num_pre + num_post

    # Atilde: first differences, row i has [-1, 1] at cols [i, i+1].
    Atilde = np.zeros((n, n + 1))
    for i in range(n):
        Atilde[i, i] = -1.0
        Atilde[i, i + 1] = 1.0

    # v_max_dif: [-1, 1] at 0-based columns (num_pre + s - 1) and (num_pre + s).
    v_max_dif = np.zeros((1, n + 1))
    c0 = num_pre + s - 1
    v_max_dif[0, c0] = -1.0
    v_max_dif[0, c0 + 1] = 1.0
    if not max_positive:
        v_max_dif = -v_max_dif

    # repmat v over pre periods, Mbar*v over post periods, stacked vertically.
    A_UB = np.vstack(
        [np.tile(v_max_dif, (num_pre, 1)), np.tile(mbar * v_max_dif, (num_post, 1))]
    )

    A = np.vstack([Atilde - A_UB, -Atilde - A_UB])

    # Drop all-zero rows (squared L2 norm <= 1e-10), preserving R's row order.
    zerorows = np.einsum("ij,ij->i", A, A) <= 1e-10
    A = A[~zerorows, :]

    if drop_zero:
        A = np.delete(A, num_pre, axis=1)

    return A


# ---------------------------------------------------------------------------
# Task 3: ARP conditional single-(theta, s, sign) test. Port of R HonestDiD's
# .construct_Gamma / .test_delta_lp_fn / .lp_conditional_test_fn (ARP branch).
# ---------------------------------------------------------------------------

_TOL_LAMBDA = 1e-6


def _rref(mat: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """Reduced row echelon form (Gauss-Jordan), mirroring ``pracma::rref``."""
    A = mat.astype(float).copy()
    rows, cols = A.shape
    r = 0
    for c in range(cols):
        if r >= rows:
            break
        # partial pivot: largest magnitude in column c at/below row r
        piv = np.argmax(np.abs(A[r:, c])) + r
        if abs(A[piv, c]) <= tol:
            A[r:, c] = 0.0
            continue
        A[[r, piv]] = A[[piv, r]]
        A[r] = A[r] / A[r, c]
        for i in range(rows):
            if i != r and abs(A[i, c]) > tol:
                A[i] = A[i] - A[i, c] * A[r]
        r += 1
    return A


def _construct_gamma(l_vec: np.ndarray) -> np.ndarray:
    """Port of R ``HonestDiD:::.construct_Gamma``.

    Builds an invertible basis ``Gamma`` whose first row is ``l_vec``. Columns of
    ``B = [l | I]`` are selected by the leading-1 positions of ``rref(B)``.
    """
    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)
    bar_t = l_vec.shape[0]
    B = np.hstack([l_vec.reshape(-1, 1), np.eye(bar_t)])
    rref_b = _rref(B)
    leading_ones = []
    for row in range(rref_b.shape[0]):
        # first column with a (leading) nonzero in this rref row; R uses == 0
        nz = np.nonzero(np.abs(rref_b[row]) > 1e-9)[0]
        if nz.size == 0:
            continue
        leading_ones.append(nz[0])
    Gamma = B[:, leading_ones].T
    if abs(np.linalg.det(Gamma)) < 1e-12:
        raise HonestDiDError("HONEST_GAMMA_SINGULAR: rref basis is singular.")
    return Gamma


def _test_delta_lp(y_T: np.ndarray, X_T: np.ndarray, sigma: np.ndarray) -> dict:
    """Port of R ``HonestDiD:::.test_delta_lp_fn`` (the eta LP).

    minimize eta s.t.  -[sdVec | X_T] @ x <= -y_T, all variables free.
    Returns eta_star (objective), delta_star (x[1:]), lambda (inequality duals,
    R sign so that ``lambda > tol`` marks BINDING constraints), error_flag.
    """
    X_T = np.atleast_2d(X_T)
    if X_T.shape[0] != y_T.shape[0]:
        X_T = X_T.reshape(y_T.shape[0], -1)
    dim_delta = X_T.shape[1]
    sd_vec = np.sqrt(np.diag(sigma))
    f = np.concatenate([[1.0], np.zeros(dim_delta)])
    C = -np.hstack([sd_vec.reshape(-1, 1), X_T])  # C x <= b
    b = -y_T
    res = linprog(
        f, A_ub=C, b_ub=b, bounds=[(None, None)] * (dim_delta + 1), method="highs"
    )
    if not res.success or res.x is None:
        return {"eta_star": np.inf, "delta_star": None, "lambda": None, "error_flag": 1}
    eta = float(res.fun)
    delta = np.asarray(res.x[1:], dtype=float)
    # R: lambda = -duals. scipy highs ineqlin.marginals are <=0 for active rows;
    # negating yields R's convention where lambda > tol selects binding rows.
    lam = -np.asarray(res.ineqlin.marginals, dtype=float)
    return {"eta_star": eta, "delta_star": delta, "lambda": lam, "error_flag": 0}


def _norminvp_generalized(p: float, l: float, u: float) -> float:
    """Truncated standard-normal inverse CDF on [l, u]. Port of R helper."""
    return float(truncnorm.ppf(p, a=l, b=u))


def _lp_conditional_test(
    *,
    y_T: np.ndarray,
    X_T: np.ndarray,
    sigma: np.ndarray,
    alpha: float,
    rows_for_arp,
) -> dict:
    """Port of R ``HonestDiD:::.lp_conditional_test_fn`` for ``hybrid_flag="ARP"``.

    Deterministic: an LP for the test statistic + a truncated-normal conditional
    critical value. ``rows_for_arp`` are 0-based row indices.
    """
    y_T = np.asarray(y_T, dtype=float)
    X_T = np.atleast_2d(np.asarray(X_T, dtype=float))
    sigma = np.asarray(sigma, dtype=float)
    rows = list(rows_for_arp)

    y = y_T[rows]
    X = X_T[rows, :]
    sig = sigma[np.ix_(rows, rows)]
    M = sig.shape[0]
    k = X.shape[1]

    soln = _test_delta_lp(y, X, sig)
    eta = soln["eta_star"]
    if soln["error_flag"] > 0:
        # LP failed -> do not reject
        return {"reject": 0, "eta": eta, "delta": soln["delta_star"]}

    mod_size = alpha  # ARP: no least-favorable first stage
    lam = soln["lambda"]
    B_index = lam > _TOL_LAMBDA
    Bc_index = ~B_index
    size_B = int(B_index.sum())
    degenerate_flag = size_B != (k + 1)

    sd_vec = np.sqrt(np.diag(sig))
    X_TB = X[B_index, :]
    # full-rank check on X_TB (R: rankMatrix(X_TB) == min(dim))
    if X_TB.size == 0 or min(X_TB.shape) == 0:
        full_rank_flag = False
    else:
        full_rank_flag = np.linalg.matrix_rank(X_TB) == min(X_TB.shape)

    if (not full_rank_flag) or degenerate_flag:
        # Degenerate / non-full-rank path: dual-based vlo/vup.
        return _lp_conditional_test_dual(
            y=y, X=X, sig=sig, eta=eta, lam=lam, mod_size=mod_size, soln=soln
        )

    # --- Non-degenerate path (priority for the fixture) ---
    sd_B = sd_vec[B_index]
    sd_Bc = sd_vec[Bc_index]
    X_TBc = X[Bc_index, :]
    I = np.eye(M)
    S_B = I[B_index, :]
    S_Bc = I[Bc_index, :]
    cB = np.hstack([sd_B.reshape(-1, 1), X_TB])
    cBc = np.hstack([sd_Bc.reshape(-1, 1), X_TBc])

    Gamma_B = cBc @ np.linalg.solve(cB, S_B) - S_Bc
    e1 = np.zeros(size_B)
    e1[0] = 1.0
    v_B = np.linalg.solve(cB, S_B).T @ e1  # (M,) vector
    sigma2_B = float(v_B @ sig @ v_B)
    sigma_B = np.sqrt(sigma2_B)
    rho = (Gamma_B @ sig @ v_B) / sigma2_B
    maximand = (-(Gamma_B @ y) / rho) + float(v_B @ y)

    vlo = maximand[rho > 0].max() if np.any(rho > 0) else -np.inf
    vup = maximand[rho < 0].min() if np.any(rho < 0) else np.inf

    zlo = vlo / sigma_B
    zup = vup / sigma_B
    maxstat = eta / sigma_B

    if not (zlo <= maxstat <= zup):
        return {"reject": 0, "eta": eta, "delta": soln["delta_star"]}
    cval = max(0.0, _norminvp_generalized(1.0 - mod_size, zlo, zup))
    reject = int(maxstat > cval)
    return {"reject": reject, "eta": eta, "delta": soln["delta_star"]}


def _lp_conditional_test_dual(*, y, X, sig, eta, lam, mod_size, soln) -> dict:
    """Degenerate / non-full-rank ARP path (R ``.lp_dual_fn`` + ``.vlo_vup_dual_fn``).

    DEFERRED to Task 4. R's dual path resolves the conditioning event ``[vlo, vup]``
    via a bisection root-finder (``.check_if_solution_helper``), a scheme that is
    materially different from the closed-form non-degenerate path and is NOT
    exercised by the Task-3 fixture (whose binding set has exactly ``k+1`` rows ->
    non-degenerate). Rather than ship an unvalidated approximation that could
    silently return a wrong reject, this raises so callers cannot mistake an
    unported branch for a correct answer. Task 4 will port ``.vlo_vup_dual_fn``
    faithfully and validate it against the full-grid oracle.
    """
    raise HonestDiDError(
        "HONEST_DUAL_PATH_UNPORTED: degenerate/non-full-rank ARP branch is "
        "deferred to Task 4 (R .vlo_vup_dual_fn bisection not yet ported)."
    )


def arp_conditional_test(
    *,
    betahat: np.ndarray,
    sigma: np.ndarray,
    num_pre: int,
    num_post: int,
    l_vec: np.ndarray,
    mbar: float,
    s: int,
    max_positive: bool,
    theta: float,
    alpha: float,
) -> dict:
    """Single-(theta, s, sign) ARP conditional test for ΔRM(Mbar).

    Faithful port of the ARP branch of R ``HonestDiD:::.ARP_computeCI`` /
    ``.lp_conditional_test_fn``. Reconstructs the moment system from raw
    ``betahat``/``sigma`` (the full path Task 4 loops over a theta-grid) and runs
    the deterministic conditional test. Returns ``reject`` (0/1), ``eta``, plus
    intermediate construction arrays for validation.
    """
    betahat = np.asarray(betahat, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float)
    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)

    A = create_arm_constraints(
        num_pre=num_pre,
        num_post=num_post,
        mbar=mbar,
        s=s,
        max_positive=max_positive,
        drop_zero=True,
    )
    d = np.zeros(A.shape[0])  # ΔRM: d is zeros

    Gamma = _construct_gamma(l_vec)
    Gamma_inv = np.linalg.inv(Gamma)
    # A restricted to POST columns: 0-based cols num_pre .. num_pre+num_post-1
    A_post = A[:, num_pre:num_pre + num_post]
    AGammaInv = A_post @ Gamma_inv
    AGammaInv_one = AGammaInv[:, 0]
    AGammaInv_minusOne = AGammaInv[:, 1:]

    Y = A @ betahat - d
    sigmaY = A @ sigma @ A.T

    # rowsForARP: post-period-moment rows (numPost>1). 0-based.
    post_cols = np.arange(num_pre, A.shape[1])
    rows0 = np.nonzero(np.any(A[:, post_cols] != 0, axis=1))[0]

    y_T = Y - AGammaInv_one * theta

    out = _lp_conditional_test(
        y_T=y_T,
        X_T=AGammaInv_minusOne,
        sigma=sigmaY,
        alpha=alpha,
        rows_for_arp=list(rows0),
    )
    out["AGammaInv_one"] = AGammaInv_one
    out["AGammaInv_minusOne"] = AGammaInv_minusOne
    out["Y"] = Y
    out["sigmaY"] = sigmaY
    out["y_T"] = y_T
    out["rowsForARP_1based"] = [int(r) + 1 for r in rows0]
    return out
