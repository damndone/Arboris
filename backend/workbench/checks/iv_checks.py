"""Instrument checks: first-stage strength with the Anderson-Rubin set, and the
exclusion restriction.

The first stage uses instruments and endogenous regressors but not the outcome,
so its strength is a design-level check. Below the Lee, McCrary, Moreira &
Porter (2022) threshold the usual t-test over-rejects; the Anderson-Rubin set
stays valid however weak the instrument, and is attached automatically.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

from .context import CheckContext
from .contracts import CheckOutcome, CheckSpec, Threshold

_GRID_POINTS = 4001


def _arrays(fitted: Any) -> dict[str, Any] | None:
    model = getattr(fitted, "model", None)
    try:
        y = np.asarray(model.dependent.ndarray, dtype=float).reshape(-1)
        x = np.asarray(model.endog.ndarray, dtype=float)
        z = np.asarray(model.instruments.ndarray, dtype=float)
        w = np.asarray(model.exog.ndarray, dtype=float)
    except AttributeError:
        return None
    return {"y": y, "x": x, "z": z, "w": w, "cov_type": str(getattr(fitted, "cov_type", "") or "")}


def _residualize(matrix: np.ndarray, on: np.ndarray) -> np.ndarray:
    if on.size == 0:
        return matrix
    coef, *_ = np.linalg.lstsq(on, matrix, rcond=None)
    return matrix - on @ coef


def anderson_rubin_homoskedastic(y, x, z, w, alpha: float = 0.05) -> dict[str, Any]:
    """Closed form: AR(b) <= F(q, n - kw - q) is a quadratic inequality in b."""
    n, q = z.shape
    kw = w.shape[1]
    yt, xt, zt = (_residualize(a, w) for a in (y[:, None], x, z))
    yt, xt = yt[:, 0], xt[:, 0]
    critical = float(stats.f.ppf(1 - alpha, q, n - kw - q))
    weight = (n - kw - q) / q
    # e'Pe and e'e for e = y - b x, through q-dimensional products only, so the
    # n x n projection is never formed.
    gram = np.linalg.inv(zt.T @ zt)
    zy, zx = zt.T @ yt, zt.T @ xt

    def form(pu, pv, tuv):
        projected = float(pu @ gram @ pv)
        return weight * projected - critical * (tuv - projected)

    a = form(zx, zx, float(xt @ xt))
    b = -2 * form(zx, zy, float(xt @ yt))
    c = form(zy, zy, float(yt @ yt))
    return _quadratic_set(a, b, c) | {"method": "homoskedastic", "critical_value": critical}


def _quadratic_set(a: float, b: float, c: float) -> dict[str, Any]:
    discriminant = b * b - 4 * a * c
    if abs(a) < 1e-14:
        if abs(b) < 1e-14:
            return {"kind": "whole_line" if c <= 0 else "empty"}
        root = -c / b
        return {"kind": "ray_below", "upper": root} if b > 0 else {"kind": "ray_above", "lower": root}
    if discriminant < 0:
        return {"kind": "empty"} if a > 0 else {"kind": "whole_line"}
    roots = sorted(((-b - math.sqrt(discriminant)) / (2 * a), (-b + math.sqrt(discriminant)) / (2 * a)))
    if a > 0:
        return {"kind": "interval", "lower": roots[0], "upper": roots[1]}
    return {"kind": "union_of_rays", "lower": roots[0], "upper": roots[1]}


def _robust_statistic(e: np.ndarray, regressors: np.ndarray, columns: slice) -> float:
    """Wald statistic of the instrument coefficients with HC0 covariance."""
    xtx_inv = np.linalg.inv(regressors.T @ regressors)
    coef = xtx_inv @ regressors.T @ e
    residual = e - regressors @ coef
    meat = (regressors * residual[:, None] ** 2).T @ regressors
    vcov = xtx_inv @ meat @ xtx_inv
    block = coef[columns]
    return float(block @ np.linalg.solve(vcov[columns, columns], block))


def anderson_rubin_robust(y, x, z, w, centre: float, scale: float, alpha: float = 0.05) -> dict[str, Any]:
    """Heteroskedasticity-robust AR set by test inversion on a grid.

    AR(b) is the HC0 Wald test that the instruments' coefficients are zero in
    the regression of y - b x on the exogenous regressors and the instruments,
    against chi2(q) -- the covariance and reference distribution the model's
    own robust inference uses. Boundaries are refined by bisection; a set that
    reaches the edge of the grid is reported as unbounded on that side.
    """
    q = z.shape[1]
    regressors = np.column_stack([w, z])
    columns = slice(w.shape[1], w.shape[1] + q)
    critical = float(stats.chi2.ppf(1 - alpha, q))

    def accepted(b: float) -> bool:
        return _robust_statistic(y - b * x[:, 0], regressors, columns) <= critical

    half_width = 100 * scale if scale > 0 else 100.0
    grid = np.linspace(centre - half_width, centre + half_width, _GRID_POINTS)
    inside = np.array([accepted(b) for b in grid])

    def boundary(lo: float, hi: float) -> float:
        # lo and hi straddle the boundary; return its position.
        inside_lo = accepted(lo)
        for _ in range(60):
            mid = (lo + hi) / 2
            if accepted(mid) == inside_lo:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    if not inside.any():
        return {"kind": "empty", "method": "robust_hc0", "critical_value": critical}
    if inside.all():
        return {"kind": "whole_line", "method": "robust_hc0", "critical_value": critical}
    changes = np.flatnonzero(np.diff(inside.astype(int)))
    edges = [boundary(grid[i], grid[i + 1]) for i in changes]
    method = {"method": "robust_hc0", "critical_value": critical}
    if inside[0] and inside[-1] and len(edges) == 2:
        return {"kind": "union_of_rays", "lower": edges[0], "upper": edges[1]} | method
    if not inside[0] and not inside[-1] and len(edges) == 2:
        return {"kind": "interval", "lower": edges[0], "upper": edges[1]} | method
    if inside[0] and not inside[-1] and len(edges) == 1:
        return {"kind": "ray_below", "upper": edges[0]} | method
    if inside[-1] and not inside[0] and len(edges) == 1:
        return {"kind": "ray_above", "lower": edges[0]} | method
    return {"kind": "disjoint", "boundaries": edges} | method


def _describe(region: dict[str, Any]) -> str:
    kind = region["kind"]
    if kind == "interval":
        return f"[{region['lower']:.4g}, {region['upper']:.4g}]"
    if kind == "union_of_rays":
        return f"(-inf, {region['lower']:.4g}] and [{region['upper']:.4g}, +inf)"
    if kind == "ray_below":
        return f"(-inf, {region['upper']:.4g}]"
    if kind == "ray_above":
        return f"[{region['lower']:.4g}, +inf)"
    if kind == "whole_line":
        return "the whole real line (the data are uninformative about the effect)"
    if kind == "empty":
        return "empty (the instrument restrictions are rejected at every value)"
    return "a union of disjoint pieces"


def first_stage_strength(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    fitted = context.fitted
    try:
        diagnostics = fitted.first_stage.diagnostics
        f_statistic = float(diagnostics["f.stat"].min())
    except (AttributeError, KeyError, TypeError, ValueError):
        return CheckOutcome("not_checked", "The fit does not expose its first-stage statistics.")
    evidence: dict[str, Any] = {"first_stage_f": f_statistic, "covariance": str(getattr(fitted, "cov_type", ""))}
    if f_statistic >= spec.threshold("caution_below"):
        return CheckOutcome("holds", f"First-stage F = {f_statistic:.1f}; the instruments are strong.", evidence)
    arrays = _arrays(fitted)
    region = None
    if arrays is not None and arrays["x"].shape[1] == 1:
        params = getattr(fitted, "params", None)
        name = list(getattr(fitted.model.endog, "cols", [None]))[0]
        centre = float(params[name]) if params is not None and name in params else 0.0
        scale = float(fitted.std_errors[name]) if name in getattr(fitted, "std_errors", {}) else 1.0
        if arrays["cov_type"] == "unadjusted":
            region = anderson_rubin_homoskedastic(arrays["y"], arrays["x"], arrays["z"], arrays["w"])
        else:
            region = anderson_rubin_robust(arrays["y"], arrays["x"], arrays["z"], arrays["w"], centre, scale)
        evidence["anderson_rubin_95"] = region
        evidence["endogenous_regressor"] = name
    weak = f_statistic < spec.threshold("fails_below")
    region_text = (
        f" The Anderson-Rubin 95% confidence set for {evidence['endogenous_regressor']}, valid however weak "
        f"the instrument, is {_describe(region)}."
        if region is not None else
        " With more than one endogenous regressor no Anderson-Rubin set is attached."
    )
    if weak:
        return CheckOutcome(
            "fails",
            f"First-stage F = {f_statistic:.1f}, below 10: the instruments are weak, the 2SLS estimate is "
            "biased toward OLS and its standard error is unreliable." + region_text,
            evidence,
            "Report the Anderson-Rubin set instead of the 2SLS interval, or find stronger instruments.",
        )
    return CheckOutcome(
        "caution",
        f"First-stage F = {f_statistic:.1f}, below 104.7: the usual 2SLS t-test over-rejects at this "
        "strength." + region_text,
        evidence,
        "Rely on the Anderson-Rubin set for inference on the endogenous regressor.",
    )


def exclusion_restriction(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    fitted = context.fitted
    arrays = _arrays(fitted)
    if arrays is None:
        return CheckOutcome("not_checked", "The fit does not expose its instruments.")
    overidentifying = arrays["z"].shape[1] - arrays["x"].shape[1]
    if overidentifying <= 0:
        return CheckOutcome(
            "needs_reason",
            "The model is exactly identified, so the exclusion restriction (the instrument affects the "
            "outcome only through the endogenous regressor) cannot be tested from the data. It rests on "
            "your argument.",
            {"overidentifying_restrictions": 0},
            "State why the instrument has no other path to the outcome.",
        )
    try:
        test = fitted.sargan
        statistic, p_value = float(test.stat), float(test.pval)
    except (AttributeError, TypeError, ValueError):
        return CheckOutcome("not_checked", "The fit does not expose an over-identification test.")
    evidence = {"overidentifying_restrictions": overidentifying, "sargan": statistic, "p_value": p_value}
    if p_value < spec.threshold("alpha"):
        return CheckOutcome(
            "caution",
            f"The over-identification test rejects (Sargan p = {p_value:.3g}): at least one instrument "
            "appears to affect the outcome other than through the endogenous regressor.",
            evidence,
            "Reconsider which instruments are valid.",
        )
    return CheckOutcome(
        "holds",
        f"The over-identification test does not reject (Sargan p = {p_value:.3g}). Not rejecting does not "
        "show the instruments are valid; it tests only their mutual consistency.",
        evidence,
    )


FIRST_STAGE_STRENGTH = CheckSpec(
    check_id="iv.first_stage_strength",
    title="Instrument strength",
    requires=frozenset({"design.instruments"}),
    blinding="design",
    thresholds=(
        Threshold("fails_below", 10.0, "first-stage F below 10", "Staiger & Stock (1997), Econometrica 65(3)"),
        Threshold("caution_below", 104.7, "first-stage F below 104.7; the Anderson-Rubin set is attached",
                  "Lee, McCrary, Moreira & Porter (2022), AER 112(10); Anderson & Rubin (1949)"),
    ),
    run=first_stage_strength,
)

EXCLUSION_RESTRICTION = CheckSpec(
    check_id="iv.exclusion_restriction",
    title="Exclusion restriction",
    requires=frozenset({"design.instruments"}),
    blinding="post_fit",
    thresholds=(Threshold("alpha", 0.05, "over-identification test p below 0.05", "Sargan (1958), Econometrica 26(3)"),),
    run=exclusion_restriction,
)
