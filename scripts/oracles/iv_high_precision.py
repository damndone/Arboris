#!/usr/bin/env python3
"""Independent high-precision IV moments and diagnostic arithmetic.

The input doubles convert exactly to Decimal; subsequent arithmetic is rounded, not exact.
The estimator solves the IV moment equations using Decimal normal equations, independently
of both the production Householder QR algorithm and linearmodels' pseudoinverse code.
Repeat at a higher precision to check stability; this is not an exact-arithmetic certificate.
Tail probabilities are checked separately against R, not computed at high precision here.

    PYTHONPATH=backend .venv/bin/python scripts/oracles/iv_high_precision.py
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import sys


D = Decimal


def column(values):
    return [D(float(value)) for value in values]


def dot(a, b):
    return sum((x * y for x, y in zip(a, b)), D(0))


def solve(matrix, rhs):
    size = len(rhs)
    a = [row[:] + [rhs[index]] for index, row in enumerate(matrix)]
    for pivot in range(size):
        best = max(range(pivot, size), key=lambda row: abs(a[row][pivot]))
        a[pivot], a[best] = a[best], a[pivot]
        if not a[pivot][pivot]:
            raise ValueError("singular oracle moment matrix")
        for row in range(pivot + 1, size):
            factor = a[row][pivot] / a[pivot][pivot]
            a[row] = [x - factor * y for x, y in zip(a[row], a[pivot])]
    out = [D(0)] * size
    for row in reversed(range(size)):
        out[row] = (a[row][size] - sum(a[row][j] * out[j] for j in range(row + 1, size))) / a[row][row]
    return out


def transpose(matrix):
    return [list(row) for row in zip(*matrix)]


def multiply(a, b):
    return [[dot(row, col) for col in transpose(b)] for row in a]


def inverse(matrix):
    n = len(matrix)
    return transpose([solve(matrix, [D(i == j) for i in range(n)]) for j in range(n)])


def cross(columns):
    return [[dot(a, b) for b in columns] for a in columns]


def prediction(columns, beta):
    return [dot(row, beta) for row in zip(*columns)]


def residual(target, predicted):
    return [a - b for a, b in zip(target, predicted)]


def ols(columns, target):
    bread = inverse(cross(columns))
    beta = [dot(row, [dot(c, target) for c in columns]) for row in bread]
    return beta, residual(target, prediction(columns, beta)), bread


def projection(columns, target):
    return prediction(columns, ols(columns, target)[0])


def covariance(columns, errors, bread, kind):
    if kind == "unadjusted":
        variance = dot(errors, errors) / D(len(errors))
        return [[variance * value for value in row] for row in bread]
    scores = [[value * error for value, error in zip(col, errors)] for col in columns]
    return multiply(multiply(bread, cross(scores)), bread)


def wald(beta, cov, count):
    tail = beta[-count:]
    block = [row[-count:] for row in cov[-count:]]
    return dot(tail, solve(block, tail))


def high_precision(data, endog, instruments, covariance_type="unadjusted", *, exog=("w",), precision=80):
    """Flat numerical fields for an intercept model with iid/n or HC0 covariance.

    The standard Wu T2 is the augmented-regression F used by R fixest. The
    excluded-only linearmodels 7.0 expression is retained separately as an
    arithmetic record of its projection defect, not an interchangeable test.
    """
    if covariance_type not in {"unadjusted", "robust"}:
        raise ValueError("oracle only implements unadjusted and HC0")
    names = ["Intercept", *exog, *endog]
    selected = data[["y", *exog, *endog, *instruments]].dropna()
    if any(not math.isfinite(float(value)) for row in selected.itertuples(index=False, name=None) for value in row):
        raise ValueError("non-finite oracle input")
    with localcontext() as ctx:
        ctx.prec = precision
        n, k, m = len(selected), len(names), len(endog)
        if n <= k + m:
            raise ValueError("positive augmented-regression residual df required")
        one, y = [D(1)] * n, column(selected["y"])
        included = [one, *[column(selected[name]) for name in exog]]
        endogenous = [column(selected[name]) for name in endog]
        excluded = [column(selected[name]) for name in instruments]
        x, z = [*included, *endogenous], [*included, *excluded]
        zz_inverse = inverse(cross(z))
        zx = [[dot(a, b) for b in x] for a in z]
        moment_map = multiply(zz_inverse, zx)
        information = multiply(transpose(zx), moment_map)
        bread = inverse(information)
        z_y = [[dot(col, y)] for col in z]
        rhs = multiply(transpose(moment_map), z_y)
        beta = solve(information, [row[0] for row in rhs])
        e = residual(y, prediction(x, beta))
        if covariance_type == "unadjusted":
            variance = dot(e, e) / D(n)
            cov = [[variance * value for value in row] for row in bread]
        else:
            z_scores = [[value * error for value, error in zip(col, e)] for col in z]
            meat = multiply(multiply(transpose(moment_map), cross(z_scores)), moment_map)
            cov = multiply(multiply(bread, meat), bread)
        ssr = dot(e, e)
        mean = sum(y) / D(n)
        centered = [value - mean for value in y]
        tss = dot(centered, centered)
        out = {f"params.{name}": value for name, value in zip(names, beta)}
        out.update({f"cov.{a}.{b}": cov[i][j] for i, a in enumerate(names) for j, b in enumerate(names)})
        for i, name in enumerate(names):
            out[f"std_errors.{name}"] = cov[i][i].sqrt()
            out[f"tstats.{name}"] = beta[i] / cov[i][i].sqrt()
        out.update(nobs=n, df_model=k, df_resid=n-k, ssr=ssr, centered_tss=tss,
                   rsquared=1-ssr/tss, rsquared_adj=1-(ssr/tss)*D(n-1)/D(n-k))
        first_residuals = []
        for name, col in zip(endog, endogenous):
            first_beta, first_e, first_bread = ols(z, col)
            first_cov = covariance(z, first_e, first_bread, covariance_type)
            stat = wald(first_beta, first_cov, len(excluded))
            out[f"first_stage.{name}"] = stat / D(len(excluded)) if covariance_type == "unadjusted" else stat
            out[f"first_stage.{name}.df"] = len(excluded)
            if covariance_type == "unadjusted":
                out[f"first_stage.{name}.df_denom"] = n-len(z)
            first_residuals.append(first_e)
        augmented = [*x, *first_residuals]
        control_beta, control_e, control_bread = ols(augmented, y)
        control_cov = covariance(augmented, control_e, control_bread, covariance_type)
        out["wooldridge_regression"] = wald(control_beta, control_cov, m)
        out["wooldridge_regression.df"] = m
        q = len(excluded)-m
        if q:
            fitted_endogenous = [residual(col, first_e) for col, first_e in zip(endogenous, first_residuals)]
            basis = [*included, *fitted_endogenous]
            scores = [[a*b for a, b in zip(residual(col, projection(basis, col)), e)] for col in excluded[:q]]
            score_sum = [sum(col) for col in scores]
            out["wooldridge_overid"] = dot(score_sum, solve(cross(scores), score_sum))
            out["wooldridge_overid.df"] = q
        if covariance_type == "unadjusted":
            if q:
                ze = [dot(col, e) for col in z]
                out["sargan"] = D(n) * dot(ze, solve(cross(z), ze)) / ssr
                out["sargan.df"] = q
            _, ordinary_e, _ = ols(x, y)
            z1e = [dot(col, ordinary_e) for col in [*z, *endogenous]]
            ze = [dot(col, e) for col in excluded]
            delta = dot(z1e, solve(cross([*z, *endogenous]), z1e)) - dot(ze, solve(cross(excluded), ze))
            df = n-k-m
            out["wu_hausman_excluded_projection"] = delta / D(m) / ((dot(ordinary_e, ordinary_e)-delta)/D(df))
            # Independent nested-SSR F, rather than copying the projection implementation.
            out["wu_hausman_control_function"] = ((dot(ordinary_e, ordinary_e)-dot(control_e, control_e))/D(m)
                                                    / (dot(control_e, control_e)/D(df)))
            for label in ["wu_hausman_excluded_projection", "wu_hausman_control_function"]:
                out[f"{label}.df"], out[f"{label}.df_denom"] = m, df
        return {name: float(value) for name, value in out.items()}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from test_fast_engine_iv_independent import design, fast, numerical_fields

    for shape in ("plain", "weak", "near_collinear", "near_collinear_endog", "scaled", "small", "missing"):
        data = design()
        if shape == "weak":
            data["d1"] -= .595 * data.z1 + .395 * data.z2
        elif shape == "near_collinear":
            data["z2"] = data.z1 + 1e-5 * data.z2
        elif shape == "near_collinear_endog":
            data["d2"] = data.d1 + 1e-5 * data.d2
        elif shape == "scaled":
            for name, scale in {"y": 1e6, "w": 1e3, "d1": 1e-3, "z2": 1e-3}.items():
                data[name] *= scale
        elif shape == "small":
            data = data.iloc[:8]
        elif shape == "missing":
            for row, name in enumerate(["y", "w", "d1", "z1"]):
                data.loc[row, name] = float("nan")
        for kind in ("unadjusted", "robust"):
            expected = high_precision(data, ["d1", "d2"], ["z1", "z2", "z3"], kind)
            higher = high_precision(data, ["d1", "d2"], ["z1", "z2", "z3"], kind, precision=110)
            observed = numerical_fields(fast(data, kind))
            differences = [{"field": key, "absolute_error": abs(value-expected[key]),
                            "relative_error": abs(value-expected[key])/max(abs(expected[key]), 1e-300)}
                           for key, value in observed.items() if key in expected]
            print(json.dumps({"shape": shape, "covariance": kind, "precision_stable_as_float": expected == higher,
                              "worst": sorted(differences, key=lambda row: row["relative_error"], reverse=True)[:5]}))


if __name__ == "__main__":
    main()
