"""honest-DID (Rambachan-Roth) ΔRM sensitivity engine.

Faithful Python port of R ``HonestDiD 0.2.8``. The committed R oracles under
``tests/fixtures/honest_did/`` are the element-wise source of truth.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq, linprog, minimize
from scipy.stats import norm, truncnorm


class HonestDiDError(ValueError):
    """HONEST_*-prefixed failure; degrades the honest_did block, never fails the run."""


def _create_a_sd(*, num_pre: int, num_post: int) -> np.ndarray:
    """Build the ΔSD (smoothness) second-difference constraint operator.

    Faithful port of R ``HonestDiD:::.create_A_SD(numPrePeriods, numPostPeriods)``
    (HonestDiD 0.2.8), validated element-wise against the committed oracle
    ``tests/fixtures/honest_did/a_sd.json`` (12×7 for num_pre=3, num_post=4).

    Construction:
      1. Place the second-difference stencil ``[1, -2, 1]`` at columns r:(r+2)
         in row r of ``Atilde`` over the AUGMENTED grid of length
         ``num_pre + num_post + 1`` (which includes the reference period).
         ``Atilde`` has shape ``(num_pre + num_post - 1) × (num_pre + num_post + 1)``.
      2. Drop the reference-period column (0-based index ``num_pre``); a stencil
         straddling it loses that entry. Shape → ``(...) × (num_pre + num_post)``.
      3. Return ``A = vstack([Atilde, -Atilde])`` — the two-sided form encoding
         ``|second diff| ≤ M``, i.e. ``Δ^SD(M) = {δ : A δ ≤ M·1}``.

    The only guard here: there must be at least one constructible second-difference
    row (augmented grid length ≥ 3), i.e. ``num_pre + num_post >= 2``. The
    ``num_pre >= 2`` identifiability guard belongs to the later ``honest_sd`` entry.
    """
    if num_pre + num_post < 2:
        raise HonestDiDError(
            "HONEST_SD_INSUFFICIENT_PERIODS: need num_pre + num_post >= 2 to "
            f"construct any ΔSD second-difference row (got num_pre={num_pre}, "
            f"num_post={num_post})."
        )
    n_rows = num_pre + num_post - 1
    n_aug = num_pre + num_post + 1
    atilde = np.zeros((n_rows, n_aug), dtype=float)
    for r in range(n_rows):
        atilde[r, r : r + 3] = [1.0, -2.0, 1.0]
    atilde = np.delete(atilde, num_pre, axis=1)  # drop reference-period column
    return np.vstack([atilde, -atilde])


def _folded_normal_quantile(t: float, *, alpha: float = 0.05) -> float:
    """(1-alpha) quantile of the folded normal |N(t,1)|.

    Root of g(c) = Φ(c-t) - Φ(-c-t) - (1-alpha), strictly increasing in c.
    Deterministic (Brent root-find; no Monte Carlo). Used by FLCI: the
    half-length is sqrt(var) * c_alpha(bias/sqrt(var)).
    """
    t = abs(float(t))
    target = 1.0 - alpha

    def g(c):
        return (norm.cdf(c - t) - norm.cdf(-c - t)) - target

    lo = norm.ppf(1.0 - alpha / 2.0)   # value at t=0; lower bound for any t>=0
    hi = lo + t + 10.0                 # generous upper bracket; g(hi) > 0
    return float(brentq(g, lo, hi, xtol=1e-12, rtol=1e-14))


def _folded_normal_quantile_monotone(ts, *, alpha: float = 0.05) -> np.ndarray:
    """c_alpha over a sequence of t values, forced non-decreasing to remove
    sub-ULP solver noise that could perturb a downstream argmin. c_alpha(t) is
    theoretically strictly increasing in t; this only corrects numerical noise."""
    out = np.array([_folded_normal_quantile(t, alpha=alpha) for t in ts], dtype=float)
    return np.maximum.accumulate(out)


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


_EPS = np.finfo(float).eps  # .Machine$double.eps
_ROUNDEPS_TOL = _EPS ** (3.0 / 4.0)  # ~1.8e-12


def _roundeps(x: float) -> float:
    """Port of R ``HonestDiD:::.roundeps``: snap near-zero magnitudes to 0."""
    return 0.0 if abs(x) < _ROUNDEPS_TOL else x


def _max_program(*, s_T, gamma_tilde, sigma, W_T, c):
    """Port of R ``HonestDiD:::.max_program``.

    f = s_T + (gamma' sigma gamma)^{-1} (sigma gamma) c.
    maximize f' x s.t. (W_T') x == [1, 0, ...], x >= 0.
    R solves min(-f' x) via Rglpk; scipy linprog(c=-f) minimizes -f' x too, so
    ``optimum = res.fun = min(-f' x) = -max(f' x)``, matching R's ``$optimum``.
    Returns dict(solution, optimum, success).
    """
    gsg = float(gamma_tilde @ sigma @ gamma_tilde)
    f = s_T + (1.0 / gsg) * (sigma @ gamma_tilde) * c
    f = np.asarray(f, dtype=float).reshape(-1)
    Aeq = W_T.T  # rows = ncol(W_T), cols = len(x)
    beq = np.zeros(Aeq.shape[0])
    beq[0] = 1.0
    res = linprog(
        c=-f, A_eq=Aeq, b_eq=beq, bounds=(0, None), method="highs"
    )
    if not res.success or res.x is None:
        return {"solution": None, "optimum": np.inf, "success": False}
    return {"solution": np.asarray(res.x, dtype=float), "optimum": float(res.fun), "success": True}


def _check_solution(*, c, tol, s_T, gamma_tilde, sigma, W_T):
    """Port of R ``HonestDiD:::.check_if_solution_helper``.

    honestsolution = (|c - (-optimum)| <= tol). Returns the LP dict augmented
    with ``honestsolution`` (NA -> None when the LP failed).
    """
    lp = _max_program(s_T=s_T, gamma_tilde=gamma_tilde, sigma=sigma, W_T=W_T, c=c)
    if not lp["success"]:
        lp["honestsolution"] = None
        return lp
    lp["honestsolution"] = bool(abs(c - (-lp["optimum"])) <= tol)
    return lp


def _vlo_vup_dual(*, eta, s_T, gamma_tilde, sigma, W_T):
    """Port of R ``HonestDiD:::.vlo_vup_dual_fn`` (bisection root-finder).

    Resolves the conditioning event [vlo, vup] for the degenerate dual path.
    The ``solution``/``b`` used in the secant-like ``mid`` update come from the
    MOST RECENT ``_check_solution`` call, mirroring R's reassignment of
    ``linprog`` inside the while condition.
    """
    tol_c = 1e-6
    tol_equality = 1e-6
    gsg = float(gamma_tilde @ sigma @ gamma_tilde)
    sigma_B = np.sqrt(gsg)
    low_initial = min(-100.0, eta - 20.0 * sigma_B)
    high_initial = max(100.0, eta + 20.0 * sigma_B)
    maxiters = 10000
    switchiters = 10
    b = (1.0 / gsg) * (sigma @ gamma_tilde)
    b = np.asarray(b, dtype=float).reshape(-1)
    s_T = np.asarray(s_T, dtype=float).reshape(-1)

    def check(cval):
        return _check_solution(
            c=cval, tol=tol_equality, s_T=s_T, gamma_tilde=gamma_tilde,
            sigma=sigma, W_T=W_T,
        )

    checksol = check(eta)["honestsolution"]
    if checksol is None or not checksol:
        return {"vlo": eta, "vup": np.inf}

    # ---- vup ----
    linprog_hi = check(high_initial)
    if linprog_hi["honestsolution"]:
        vup = np.inf
    else:
        dif = 0.0
        iters = 1
        linprog = linprog_hi  # most-recent check result feeding the mid update
        sol = linprog["solution"]
        mid = _roundeps(float(sol @ s_T)) / (1.0 - float(sol @ b))
        linprog = check(mid)
        while (not linprog["honestsolution"]) and iters < maxiters:
            iters += 1
            if iters >= switchiters:
                dif = tol_c + 1.0
                break
            sol = linprog["solution"]
            mid = _roundeps(float(sol @ s_T)) / (1.0 - float(sol @ b))
            linprog = check(mid)
        low = eta
        high = mid
        while dif > tol_c and iters < maxiters:
            iters += 1
            mid = (high + low) / 2.0
            if check(mid)["honestsolution"]:
                low = mid
            else:
                high = mid
            dif = high - low
        vup = mid

    # ---- vlo (mirrored) ----
    linprog_lo = check(low_initial)
    if linprog_lo["honestsolution"]:
        vlo = -np.inf
    else:
        dif = 0.0
        iters = 1
        linprog = linprog_lo
        sol = linprog["solution"]
        mid = _roundeps(float(sol @ s_T)) / (1.0 - float(sol @ b))
        linprog = check(mid)
        while (not linprog["honestsolution"]) and iters < maxiters:
            iters += 1
            if iters >= switchiters:
                dif = tol_c + 1.0
                break
            sol = linprog["solution"]
            mid = _roundeps(float(sol @ s_T)) / (1.0 - float(sol @ b))
            linprog = check(mid)
        low = mid
        high = eta
        while dif > tol_c and iters < maxiters:
            mid = (low + high) / 2.0
            iters += 1
            if check(mid)["honestsolution"]:
                high = mid
            else:
                low = mid
            dif = high - low
        vlo = mid

    return {"vlo": vlo, "vup": vup}


def _lp_dual(*, y_T, X_T, eta, gamma_tilde, sigma):
    """Port of R ``HonestDiD:::.lp_dual_fn``."""
    y_T = np.asarray(y_T, dtype=float).reshape(-1)
    X_T = np.atleast_2d(np.asarray(X_T, dtype=float))
    sd_vec = np.sqrt(np.diag(sigma))
    W_T = np.hstack([sd_vec.reshape(-1, 1), X_T])
    gsg = float(gamma_tilde @ sigma @ gamma_tilde)
    n = y_T.shape[0]
    s_T = (np.eye(n) - (1.0 / gsg) * (sigma @ np.outer(gamma_tilde, gamma_tilde))) @ y_T
    v = _vlo_vup_dual(eta=eta, s_T=s_T, gamma_tilde=gamma_tilde, sigma=sigma, W_T=W_T)
    return {"vlo": v["vlo"], "vup": v["vup"], "eta": eta, "gamma_tilde": gamma_tilde}


def _lp_conditional_test_dual(*, y, X, sig, eta, lam, mod_size, soln) -> dict:
    """Degenerate / non-full-rank ARP path. Port of the dual branch of R
    ``.lp_conditional_test_fn`` (uses ``.lp_dual_fn`` -> ``.vlo_vup_dual_fn``)."""
    lp_dual = _lp_dual(y_T=y, X_T=X, eta=eta, gamma_tilde=lam, sigma=sig)
    sigma_B_dual2 = float(lam @ sig @ lam)
    if abs(sigma_B_dual2) < _EPS:
        return {"reject": int(eta > 0), "eta": eta, "delta": soln["delta_star"]}
    if sigma_B_dual2 < 0:
        raise HonestDiDError(
            "HONEST_DUAL_NEG_VAR: .vlo_vup_dual_fn returned a negative variance."
        )
    sigma_B_dual = np.sqrt(sigma_B_dual2)
    maxstat = lp_dual["eta"] / sigma_B_dual
    zlo_dual = lp_dual["vlo"] / sigma_B_dual
    zup_dual = lp_dual["vup"] / sigma_B_dual
    if not (zlo_dual <= maxstat <= zup_dual):
        return {"reject": 0, "eta": eta, "delta": soln["delta_star"]}
    cval = max(0.0, _norminvp_generalized(1.0 - mod_size, zlo_dual, zup_dual))
    reject = int(maxstat > cval)
    return {"reject": reject, "eta": eta, "delta": soln["delta_star"]}


def _build_polyhedron(
    *, betahat, sigma, num_pre, num_post, l_vec, mbar, s, max_positive
) -> dict:
    """Build the per-``(s, sign)`` ARP constants ONCE (cached across the theta grid).

    Port of the construction inside R ``.ARP_computeCI`` (everything outside the
    ``testTheta`` closure). Returns the pieces the per-theta LP reuses.
    """
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
    A_post = A[:, num_pre:num_pre + num_post]
    AGammaInv = A_post @ Gamma_inv
    AGammaInv_one = AGammaInv[:, 0]
    AGammaInv_minusOne = AGammaInv[:, 1:]
    Y = A @ betahat - d
    sigmaY = A @ sigma @ A.T
    post_cols = np.arange(num_pre, A.shape[1])
    rows0 = np.nonzero(np.any(A[:, post_cols] != 0, axis=1))[0]
    return {
        "A": A,
        "AGammaInv_one": AGammaInv_one,
        "AGammaInv_minusOne": AGammaInv_minusOne,
        "Y": Y,
        "sigmaY": sigmaY,
        "rows0": list(rows0),
    }


def _arp_accept_grid(
    *,
    betahat: np.ndarray,
    sigma: np.ndarray,
    num_pre: int,
    num_post: int,
    l_vec: np.ndarray,
    mbar: float,
    alpha: float,
    grid: np.ndarray,
) -> np.ndarray:
    """Union accept vector over (s, max_positive) for each theta in ``grid``.

    Port of R ``computeConditionalCS_DeltaRM``'s ``pmax`` over s in
    ``-(num_pre-1)..0`` and ``max_positive in {True, False}``, with each
    fixed-S CI from the ARP branch of ``.ARP_computeCI``. The per-(s,sign)
    constants are cached once and reused across the grid (the R ``testTheta``
    closure pattern).
    """
    betahat = np.asarray(betahat, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float)
    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)
    grid = np.asarray(grid, dtype=float).reshape(-1)

    s_indices = range(-(num_pre - 1), 1)
    accept_union = np.zeros(grid.shape[0], dtype=int)

    for s in s_indices:
        for max_positive in (True, False):
            poly = _build_polyhedron(
                betahat=betahat, sigma=sigma, num_pre=num_pre,
                num_post=num_post, l_vec=l_vec, mbar=mbar, s=s,
                max_positive=max_positive,
            )
            Y = poly["Y"]
            AGI_one = poly["AGammaInv_one"]
            AGI_minus = poly["AGammaInv_minusOne"]
            sigmaY = poly["sigmaY"]
            rows0 = poly["rows0"]
            for i, theta in enumerate(grid):
                if accept_union[i] == 1:
                    continue  # already in the union; max over (s,sign) stays 1
                y_T = Y - AGI_one * theta
                out = _lp_conditional_test(
                    y_T=y_T, X_T=AGI_minus, sigma=sigmaY,
                    alpha=alpha, rows_for_arp=rows0,
                )
                if out["reject"] == 0:
                    accept_union[i] = 1
    return accept_union


def arp_confidence_interval(
    *,
    betahat: np.ndarray,
    sigma: np.ndarray,
    num_pre: int,
    num_post: int,
    l_vec: np.ndarray,
    mbar: float,
    alpha: float = 0.05,
    grid_points: int = 1000,
    grid_lb: float | None = None,
    grid_hi: float | None = None,
) -> tuple[float, float]:
    """Test-inversion CI for ΔRM(mbar): theta NOT rejected, union over (s, sign).

    Faithful port of R ``computeConditionalCS_DeltaRM`` + endpoint extraction
    (``lb = min(grid[accept==1])``, ``ub = max(...)``). ``grid = seq(grid_lb,
    grid_hi, length.out=grid_points)`` with default ``±20*sdTheta`` where
    ``sdTheta = sqrt(l' Sigma_post l)``.
    """
    betahat = np.asarray(betahat, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float)
    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)

    sigma_post = sigma[num_pre:num_pre + num_post, num_pre:num_pre + num_post]
    sd_theta = float(np.sqrt(l_vec @ sigma_post @ l_vec))
    if grid_hi is None:
        grid_hi = 20.0 * sd_theta
    if grid_lb is None:
        grid_lb = -20.0 * sd_theta
    grid = np.linspace(grid_lb, grid_hi, grid_points)

    accept = _arp_accept_grid(
        betahat=betahat, sigma=sigma, num_pre=num_pre, num_post=num_post,
        l_vec=l_vec, mbar=mbar, alpha=alpha, grid=grid,
    )
    accepted = grid[accept == 1]
    if accepted.size == 0:
        return (np.nan, np.nan)
    return (float(accepted.min()), float(accepted.max()))


def honest_rm(
    *,
    betahat: np.ndarray,
    sigma: np.ndarray,
    num_pre: int,
    num_post: int,
    l_vec: np.ndarray,
    mbar_grid,
    alpha: float = 0.05,
    grid_points: int = 1000,
) -> dict:
    """Robust ΔRM confidence sets across the Mbar grid + the breakdown Mbar.

    Pure, deterministic (golden 0-drift). Loops ``arp_confidence_interval`` over
    ``mbar_grid``.

    Raises ``HonestDiDError`` on degenerate inputs (these DEGRADE the honest_did
    block, never fail the run — caught upstream by the adapter/runner):

      HONEST_NO_PRE_PERIODS   if num_pre  < 1  (ΔRM needs a pre-period to bound against)
      HONEST_NO_POST_PERIODS  if num_post < 1  (no post-period to test)
      HONEST_DEGENERATE_SIGMA if sigma is not positive-definite.

    Returns ``{"results": [{"Mbar", "lb", "ub"}...], "breakdown": float|None}``
    where ``breakdown`` is the LARGEST Mbar whose CI still EXCLUDES 0
    (``lb > 0`` or ``ub < 0``); ``None`` if no Mbar excludes 0.
    """
    if num_pre < 1:
        raise HonestDiDError(
            "HONEST_NO_PRE_PERIODS: ΔRM requires at least one pre-period."
        )
    if num_post < 1:
        raise HonestDiDError(
            "HONEST_NO_POST_PERIODS: ΔRM requires at least one post-period."
        )

    betahat = np.asarray(betahat, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float)
    if not (np.isfinite(sigma).all() and np.isfinite(betahat).all()):
        # eigvalsh on a non-finite sigma raises LinAlgError/ValueError (a generic
        # HONEST_INTERNAL_ERROR upstream); report the degeneracy cleanly instead.
        raise HonestDiDError(
            "HONEST_DEGENERATE_SIGMA: non-finite values in sigma or betahat."
        )
    sigma_sym = 0.5 * (sigma + sigma.T)
    if float(np.linalg.eigvalsh(sigma_sym).min()) <= 0.0:
        raise HonestDiDError(
            "HONEST_DEGENERATE_SIGMA: sigma is not positive-definite."
        )

    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)

    results = []
    for M in mbar_grid:
        lb, ub = arp_confidence_interval(
            betahat=betahat,
            sigma=sigma,
            num_pre=num_pre,
            num_post=num_post,
            l_vec=l_vec,
            mbar=float(M),
            alpha=alpha,
            grid_points=grid_points,
        )
        results.append({"Mbar": float(M), "lb": float(lb), "ub": float(ub)})

    excludes0 = [
        r["Mbar"]
        for r in results
        if (r["lb"] == r["lb"] and r["ub"] == r["ub"])  # not NaN
        and (r["lb"] > 0.0 or r["ub"] < 0.0)
    ]
    breakdown = max(excludes0) if excludes0 else None

    return {"results": results, "breakdown": breakdown}


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

    poly = _build_polyhedron(
        betahat=betahat, sigma=sigma, num_pre=num_pre, num_post=num_post,
        l_vec=l_vec, mbar=mbar, s=s, max_positive=max_positive,
    )
    AGammaInv_one = poly["AGammaInv_one"]
    AGammaInv_minusOne = poly["AGammaInv_minusOne"]
    Y = poly["Y"]
    sigmaY = poly["sigmaY"]
    rows0 = poly["rows0"]

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


# ===========================================================================
# Task 4: ΔSD Fixed-Length Confidence Interval (FLCI).
# Faithful port of R HonestDiD 0.2.8 findOptimalFLCI / .findOptimalFLCI_helper.
# Deterministic: convex sub-problems via SLSQP + analytic folded-normal CV.
# Oracle: tests/fixtures/honest_did/flci_sd.json (regenerated with an analytic
# .qfoldednormal so the whole path is deterministic) + flci_intermediates.json.
# ===========================================================================


def _flci_wtol_premat(num_pre: int) -> np.ndarray:
    """``WtoLPreMat`` (p×p): identity with the sub-diagonal set to −1, so
    ``(WtoLPreMat @ W)_1 = W_1`` and ``(·)_i = W_i − W_{i-1}``. For p==1: [[1]]."""
    mat = np.eye(num_pre)
    for col in range(num_pre - 1):
        mat[col + 1, col] = -1.0
    return mat


def _flci_var_pieces(*, sigma, num_pre, num_post, l_vec) -> dict:
    """Constants for ``var(W)`` and ``bias(W)`` (R ``.createMatricesForVarianceFromW``
    + ``.createObjectiveObjectForBias`` constant). ``W`` and ``l_vec`` live in R^p, R^q.

    var(W) = L @ SigmaPre @ L + 2 * L @ (SigmaPrePost @ l_vec) + SigmaPostScalar,
    where L = WtoLPreMat @ W.
    bias(W) per unit M = bias_const + sum_i |cumsum(W)_i|.
    """
    sigma = np.asarray(sigma, dtype=float)
    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)
    p, q = num_pre, num_post
    sigma_pre = sigma[:p, :p]
    sigma_pre_post = sigma[:p, p:]
    sigma_post_scalar = float(l_vec @ sigma[p:, p:] @ l_vec)
    wtol = _flci_wtol_premat(p)
    lin = sigma_pre_post @ l_vec  # (p,)
    c_sum = float(np.arange(1, q + 1) @ l_vec)  # sum_{s} s * l_vec[s-1]
    # bias_const = sum_{s=1..q} | (1..s) . last-s-of-l_vec | - C_sum
    bias_const = 0.0
    for s in range(1, q + 1):
        seg = l_vec[q - s:]  # last s entries
        bias_const += abs(float(np.arange(1, s + 1) @ seg))
    bias_const -= c_sum
    return {
        "sigma_pre": sigma_pre,
        "lin": lin,
        "sigma_post_scalar": sigma_post_scalar,
        "wtol": wtol,
        "c_sum": c_sum,
        "bias_const": bias_const,
    }


def _flci_var_of_w(W, pieces) -> float:
    L = pieces["wtol"] @ W
    return float(L @ pieces["sigma_pre"] @ L + 2.0 * (L @ pieces["lin"]) + pieces["sigma_post_scalar"])


def _flci_min_sd(*, sigma, num_pre, num_post, l_vec) -> float:
    """``hMin = sqrt( min_W var(W) s.t. sum(W) = C_sum )``  (R ``.findLowestH``).

    Equality-constrained convex QP — closed form via Lagrange/KKT on the dense
    quadratic in W.  var(W) = W'Q W + 2 g'W + const with Q = WtoL' SigmaPre WtoL,
    g = WtoL' lin.  Minimize s.t. a'W = C_sum, a = ones(p).
    """
    pieces = _flci_var_pieces(sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec)
    wtol = pieces["wtol"]
    Q = wtol.T @ pieces["sigma_pre"] @ wtol
    g = wtol.T @ pieces["lin"]
    p = num_pre
    a = np.ones(p)
    c_sum = pieces["c_sum"]
    # KKT: [2Q  a; a' 0] [W; lam] = [-2g; C_sum]
    KKT = np.zeros((p + 1, p + 1))
    KKT[:p, :p] = 2.0 * Q
    KKT[:p, p] = a
    KKT[p, :p] = a
    rhs = np.concatenate([-2.0 * g, [c_sum]])
    sol = np.linalg.solve(KKT, rhs)
    W = sol[:p]
    return float(np.sqrt(_flci_var_of_w(W, pieces)))


def _flci_h_for_min_bias(*, sigma, num_pre, num_post, l_vec) -> float:
    """``h0`` (R ``.findHForMinimumBias``): w0 = [0,...,0, C_sum]; h0 = sqrt(var(w0))."""
    pieces = _flci_var_pieces(sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec)
    w0 = np.zeros(num_pre)
    w0[-1] = pieces["c_sum"]
    return float(np.sqrt(_flci_var_of_w(w0, pieces)))


def _flci_worst_case_bias_given_h(*, h, sigma, num_pre, num_post, l_vec) -> dict:
    """``min_W bias(W) s.t. var(W) <= h**2 and sum(W) = C_sum``  (R
    ``.findWorstCaseBiasGivenH``, per unit M).

    Smoothed via auxiliaries U∈R^p with U_i >= cumsum(W)_i, U_i >= -cumsum(W)_i;
    minimize bias_const + sum(U). Variables x = [U (p), W (p)] (dim 2p).
    Returns {"value": bias_per_unit_M, "L_opt": WtoLPreMat@W, "status"}.
    """
    pieces = _flci_var_pieces(sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec)
    p = num_pre
    wtol = pieces["wtol"]
    Q = wtol.T @ pieces["sigma_pre"] @ wtol
    g = wtol.T @ pieces["lin"]
    const_var = pieces["sigma_post_scalar"]
    c_sum = pieces["c_sum"]
    bias_const = pieces["bias_const"]
    # cumsum operator (lower-triangular ones)
    cum = np.tril(np.ones((p, p)))

    def split(x):
        return x[:p], x[p:]

    def obj(x):
        U, _W = split(x)
        return bias_const + float(U.sum())

    def obj_grad(x):
        gr = np.zeros(2 * p)
        gr[:p] = 1.0
        return gr

    # Equality: sum(W) = C_sum
    def eq(x):
        _U, W = split(x)
        return float(W.sum() - c_sum)

    def eq_jac(x):
        j = np.zeros(2 * p)
        j[p:] = 1.0
        return j

    # Inequalities (>= 0 in scipy): U - cumsum(W) >= 0 ; U + cumsum(W) >= 0 ;
    # h**2 - var(W) >= 0.
    def ineq(x):
        U, W = split(x)
        cw = cum @ W
        var = float(W @ Q @ W + 2.0 * (g @ W) + const_var)
        return np.concatenate([U - cw, U + cw, [h * h - var]])

    def ineq_jac(x):
        _U, W = split(x)
        rows = []
        for i in range(p):  # U_i - cumsum(W)_i
            r = np.zeros(2 * p)
            r[i] = 1.0
            r[p:] = -cum[i]
            rows.append(r)
        for i in range(p):  # U_i + cumsum(W)_i
            r = np.zeros(2 * p)
            r[i] = 1.0
            r[p:] = cum[i]
            rows.append(r)
        rv = np.zeros(2 * p)  # h^2 - var(W): d/dW = -(2 Q W + 2 g)
        rv[p:] = -(2.0 * (Q @ W) + 2.0 * g)
        rows.append(rv)
        return np.array(rows)

    # Feasible warm start: W with sum=C_sum at min-SD; U = |cumsum(W)|.
    a = np.ones(p)
    KKT = np.zeros((p + 1, p + 1))
    KKT[:p, :p] = 2.0 * Q
    KKT[:p, p] = a
    KKT[p, :p] = a
    rhs = np.concatenate([-2.0 * g, [c_sum]])
    W0 = np.linalg.solve(KKT, rhs)[:p]
    U0 = np.abs(cum @ W0)
    x0 = np.concatenate([U0, W0])

    res = minimize(
        obj, x0, jac=obj_grad, method="SLSQP",
        constraints=[
            {"type": "eq", "fun": eq, "jac": eq_jac},
            {"type": "ineq", "fun": ineq, "jac": ineq_jac},
        ],
        options={"ftol": 1e-12, "maxiter": 1000},
    )
    _U, W = split(res.x)
    status = "optimal" if res.success else "failed"
    return {
        "value": float(obj(res.x)),
        "L_opt": wtol @ W,
        "status": status,
    }


def _flci_ci_halflength(*, h, m, sigma, num_pre, num_post, l_vec, alpha, wc=None) -> float:
    """``CI_halflength(h, M) = c_alpha(M*bias(h)/h) * h`` (analytic folded-normal
    CV). Returns NaN if the worst-case bias is non-finite. ``wc`` may be a
    precomputed ``_flci_worst_case_bias_given_h`` result for ``h``."""
    if wc is None:
        wc = _flci_worst_case_bias_given_h(
            h=h, sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec
        )
    bias = wc["value"]
    if not np.isfinite(bias):
        return float("nan")
    max_bias = m * bias
    return float(_folded_normal_quantile(max_bias / h, alpha=alpha) * h)


def _flci_derivative_bisection(*, h_min, h0, m, sigma, num_pre, num_post, l_vec, alpha, num_points):
    """Port of R ``.findOptimalCIDerivativeBisection``: bisect on the finite-
    difference derivative of ``CI_halflength`` over ``[h_min, h0]``. Returns the
    optimal ``h`` or NaN (caller falls back to a grid search)."""
    a, b = h_min, h0

    def f(h):
        return _flci_ci_halflength(
            h=h, m=m, sigma=sigma, num_pre=num_pre, num_post=num_post,
            l_vec=l_vec, alpha=alpha,
        )

    eps = _EPS
    dif = min((b - a) / num_points, abs(b) * eps ** (1.0 / 3.0))
    # Degenerate search interval (h_min >= h0, e.g. num_pre == 1 leaves no
    # bias/variance slope to optimize): the finite-difference step collapses to 0.
    # Bail to NaN so the caller's grid fallback handles the single-point case.
    if not (dif > 0.0):
        return float("nan")
    failtol = eps ** 0.5
    fa = f(a)
    fb = f(b)
    fpa = (f(a + dif) - fa) / dif
    fpb = (f(b - dif) - fb) / (-dif)
    iters = 1
    maxiter = 10 * int(np.ceil(np.log(abs(b - a) / dif) / np.log(2.0)))
    failed = False
    hstar = float("nan")

    if (fpa > fpb) or np.isnan(fa) or np.isnan(fb):
        failed = True
    elif fpb < 0:
        hstar = b
    elif fpa > 0:
        hstar = a
    else:
        while (not failed) and abs(b - a) > dif:
            iters += 1
            x = (a + b) / 2.0
            fpx = (f(x + dif) - f(x - dif)) / (2.0 * dif)
            failed = (fpx > fpb + failtol) or (fpx + failtol < fpa) or iters > maxiter
            if fpx > 0:
                b = x
            else:
                a = x
        hstar = (a + b) / 2.0

    return float("nan") if failed else hstar


def flci(
    *,
    betahat,
    sigma,
    num_pre: int,
    num_post: int,
    l_vec,
    m: float,
    alpha: float = 0.05,
    num_points: int = 100,
) -> dict:
    """ΔSD Fixed-Length Confidence Interval. Faithful port of R
    ``HonestDiD::findOptimalFLCI`` (0.2.8) with an ANALYTIC folded-normal CV, so
    the whole path is deterministic. Validated element-wise vs ``flci_sd.json``.

    Returns ``{"half_length", "lb", "ub"}``.
    """
    betahat = np.asarray(betahat, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float)
    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)
    m = float(m)

    h0 = _flci_h_for_min_bias(sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec)
    h_min = _flci_min_sd(sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec)

    hstar = _flci_derivative_bisection(
        h_min=h_min, h0=h0, m=m, sigma=sigma, num_pre=num_pre,
        num_post=num_post, l_vec=l_vec, alpha=alpha, num_points=num_points,
    )

    if np.isnan(hstar):
        # Fallback grid: keep only solver-optimal points, take argmin half-length.
        h_grid = np.linspace(h_min, h0, num_points)
        best = None
        for h in h_grid:
            wc = _flci_worst_case_bias_given_h(
                h=h, sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec
            )
            if wc["status"] not in ("optimal", "optimal_inaccurate"):
                continue
            if not np.isfinite(wc["value"]):
                continue
            hl = _flci_ci_halflength(
                h=h, m=m, sigma=sigma, num_pre=num_pre, num_post=num_post,
                l_vec=l_vec, alpha=alpha, wc=wc,
            )
            if best is None or hl < best[0]:
                best = (hl, h, wc)
        if best is None:
            return {"half_length": float("nan"), "lb": float("nan"), "ub": float("nan")}
        half_length, h_used, wc = best
    else:
        h_used = hstar
        wc = _flci_worst_case_bias_given_h(
            h=h_used, sigma=sigma, num_pre=num_pre, num_post=num_post, l_vec=l_vec
        )
        half_length = _flci_ci_halflength(
            h=h_used, m=m, sigma=sigma, num_pre=num_pre, num_post=num_post,
            l_vec=l_vec, alpha=alpha, wc=wc,
        )

    optimal_vec = np.concatenate([wc["L_opt"], l_vec])
    center = float(optimal_vec @ betahat)
    return {
        "half_length": float(half_length),
        "lb": center - half_length,
        "ub": center + half_length,
    }


def honest_sd(
    *,
    betahat: np.ndarray,
    sigma: np.ndarray,
    num_pre: int,
    num_post: int,
    l_vec: np.ndarray,
    m_grid,
    alpha: float = 0.05,
    num_points: int = 100,
) -> dict:
    """Robust ΔSD confidence sets across the M grid + the breakdown M.

    Mirrors :func:`honest_rm` in shape and guard style, but uses the validated
    ΔSD Fixed-Length CI :func:`flci` (second-difference / smoothness restriction)
    instead of the ΔRM ARP test, and reports the smoothness bound under the
    ``"M"`` key. Pure, deterministic (golden 0-drift); loops ``flci`` over
    ``m_grid``.

    Raises ``HonestDiDError`` on degenerate inputs (these DEGRADE the honest_did
    block, never fail the run — caught upstream by the adapter/runner):

      HONEST_NO_PRE_PERIODS   if num_pre  < 1  (R's findOptimalFLCI imposes one
                                                sum-weights equality; needs >=1 pre)
      HONEST_NO_POST_PERIODS  if num_post < 1  (no post-period to test)
      HONEST_DEGENERATE_SIGMA if sigma is not positive-definite.

    Returns ``{"results": [{"M", "lb", "ub"}...], "breakdown": float|None}``
    where ``breakdown`` is the LARGEST M whose CI still EXCLUDES 0
    (``lb > 0`` or ``ub < 0``); ``None`` if no M excludes 0.
    """
    if num_pre < 1:
        raise HonestDiDError(
            "HONEST_NO_PRE_PERIODS: ΔSD requires at least one pre-period."
        )
    if num_post < 1:
        raise HonestDiDError(
            "HONEST_NO_POST_PERIODS: ΔSD requires at least one post-period."
        )

    betahat = np.asarray(betahat, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float)
    if not (np.isfinite(sigma).all() and np.isfinite(betahat).all()):
        raise HonestDiDError(
            "HONEST_DEGENERATE_SIGMA: non-finite values in sigma or betahat."
        )
    sigma_sym = 0.5 * (sigma + sigma.T)
    if float(np.linalg.eigvalsh(sigma_sym).min()) <= 0.0:
        raise HonestDiDError(
            "HONEST_DEGENERATE_SIGMA: sigma is not positive-definite."
        )

    l_vec = np.asarray(l_vec, dtype=float).reshape(-1)

    results = []
    for M in m_grid:
        r = flci(
            betahat=betahat,
            sigma=sigma,
            num_pre=num_pre,
            num_post=num_post,
            l_vec=l_vec,
            m=float(M),
            alpha=alpha,
            num_points=num_points,
        )
        results.append({"M": float(M), "lb": float(r["lb"]), "ub": float(r["ub"])})

    excludes0 = [
        r["M"]
        for r in results
        if (r["lb"] == r["lb"] and r["ub"] == r["ub"])  # not NaN
        and (r["lb"] > 0.0 or r["ub"] < 0.0)
    ]
    breakdown = max(excludes0) if excludes0 else None

    return {"results": results, "breakdown": breakdown}
