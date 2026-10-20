"""HC0 AR test inversion with exact input arithmetic and global root proofs.

For R=[W,Z], H=(R'R)^-1=A/D, U=A R'y, V=A R'x, E=Dy-RU,
F=Dx-RV and K=A R', instrument covariance is M(b)/D^4 where
M(b)=sum K_i K_i' (E_i-bF_i)^2. Thus AR=D^2 (U-bV)'M^-1(U-bV).
The bordered determinant gives the numerator without polynomial division.
All input floats are represented exactly; only the scipy chi-square critical
value is rounded binary64. The certificate is conditional on that threshold.
"""
from __future__ import annotations

from fractions import Fraction as Q
from math import lcm

import numpy as np
from scipy import stats

from .ar_polynomials import add, certify_set, mul


def determinant(matrix):
    """Subset expansion, O(k^2 2^k), with integer polynomial coefficients."""
    n = len(matrix)
    states = {0: [1]}
    for i in range(n):
        following = {}
        for mask, value in states.items():
            for j in range(n):
                if mask & (1 << j):
                    continue
                sign = -1 if (mask >> (j+1)).bit_count() % 2 else 1
                term = [sign*c for c in mul(value, matrix[i][j])]
                key = mask | (1 << j)
                following[key] = add(following.get(key, [0]), term)
        states = following
    return states[(1 << n)-1]


def _inverse_integer(gram):
    n = len(gram)
    rows = [[Q(c) for c in row] + [Q(i == j) for j in range(n)] for i, row in enumerate(gram)]
    # A full-rank Gram is positive definite: no pivot exchange is required.
    for j in range(n):
        pivot = rows[j][j]
        if pivot == 0:
            raise ValueError('rank_deficient_auxiliary_design')
        rows[j] = [v/pivot for v in rows[j]]
        for i in range(n):
            if i != j:
                factor = rows[i][j]
                rows[i] = [a-factor*b for a, b in zip(rows[i], rows[j])]
    inverse = [row[n:] for row in rows]
    denominator = lcm(*(c.denominator for row in inverse for c in row))
    return [[int(c*denominator) for c in row] for row in inverse], denominator


def _integer_data(y, x, z, w):
    data = np.column_stack([y, x, w, z])
    ratios = [[float(v).as_integer_ratio() for v in row] for row in data]
    scale = max(d for row in ratios for _, d in row)
    rows = [[v*(scale//d) for v, d in row] for row in ratios]
    return [row[0] for row in rows], [row[1] for row in rows], [row[2:] for row in rows]


def _projection(y, x, r):
    p = len(r[0])
    if p == 0:
        return [], [], [], 1, y, x
    gram = [[sum(row[i]*row[j] for row in r) for j in range(p)] for i in range(p)]
    a, d = _inverse_integer(gram)
    cross_y = [sum(row[j]*v for row, v in zip(r, y)) for j in range(p)]
    cross_x = [sum(row[j]*v for row, v in zip(r, x)) for j in range(p)]
    u = [sum(v*c for v, c in zip(row, cross_y)) for row in a]
    v = [sum(t*c for t, c in zip(row, cross_x)) for row in a]
    e = [d*yy-sum(t*c for t, c in zip(row, u)) for row, yy in zip(r, y)]
    f = [d*xx-sum(t*c for t, c in zip(row, v)) for row, xx in zip(r, x)]
    return a, u, v, d, e, f


def robust_polynomials(y, x, z, w, critical):
    yy, xx, r = _integer_data(y, x, z, w)
    q = z.shape[1]
    a, u, v, d, ee, ff = _projection(yy, xx, r)
    m = [[[0, 0, 0] for _ in range(q)] for _ in range(q)]
    for row, e, f in zip(r, ee, ff):
        k = [sum(t*c for t, c in zip(aa, row)) for aa in a[-q:]]
        residual_square = [e*e, -2*e*f, f*f]
        for i in range(q):
            for j in range(q):
                for power in range(3):
                    m[i][j][power] += k[i]*k[j]*residual_square[power]
    c = [[uu, -vv] for uu, vv in zip(u[-q:], v[-q:])]
    bordered = [[*row, c[i]] for i, row in enumerate(m)] + [[*c, [0]]]
    det = determinant(m)
    border = determinant(bordered)
    critical = Q(float(critical))
    numerator = add([-critical.numerator*t for t in det],
                    [-critical.denominator*d*d*t for t in border])
    return numerator, [critical.denominator*t for t in det]


def robust_set(y, x, z, w, alpha=.05):
    q = z.shape[1]
    method = {'method': 'robust_hc0', 'reference_distribution': f'chi2({q})',
              'inference_scope': 'asymptotic_iid_observations_unweighted_single_endogenous',
              'coverage_certified': False}
    # Explicit certification envelope, not a switch to a grid/pseudoinverse.
    if x.shape[1] != 1 or q not in range(1, 5) or w.shape[1]+q > 12:
        return method | {'kind': 'unavailable', 'reason': 'outside_exact_certification_envelope'}
    critical = float(stats.chi2.ppf(1-alpha, q))
    from .ar_verified import VerificationUncertain, verified_set
    try:
        result = verified_set(y, x, z, w, critical)
        computation = {'path': 'verified_numpy', 'certification_target': 'original_binary64_observations'}
    except VerificationUncertain as uncertainty:
        computation = {'path': 'exact_fallback', 'fallback_reason': str(uncertainty),
                       'certification_target': 'original_binary64_observations'}
        try:
            numerator, denominator = robust_polynomials(y, x, z, w, critical)
        except ValueError as exc:
            return method | {'kind': 'unavailable', 'reason': str(exc), 'computation': computation}
        result = certify_set(numerator, denominator)
    return method | {'critical_value': critical, 'critical_binary64_ratio': str(Q(critical)),
                     'computation': computation} | result


def homoskedastic_set(y, x, z, w, alpha=.05):
    n, q = z.shape
    p = w.shape[1]+q
    method = {'method': 'homoskedastic', 'reference_distribution': f'F({q},{n-p})',
              'inference_scope': 'iid_homoskedastic_normal_errors_unweighted_single_endogenous',
              'coverage_certified': False}
    if x.shape[1] != 1 or q < 1 or p > 12 or n <= p:
        return method | {'kind': 'unavailable', 'reason': 'outside_exact_certification_envelope'}
    critical = float(stats.f.ppf(1-alpha, q, n-p))
    yy, xx, r = _integer_data(y, x, z, w)
    sums = []
    try:
        for design in [[row[:w.shape[1]] for row in r], r]:
            _, _, _, d, e, f = _projection(yy, xx, design)
            sums.append([Q(sum(v*v for v in e), d*d), Q(-2*sum(a*b for a, b in zip(e, f)), d*d),
                         Q(sum(v*v for v in f), d*d)])
    except ValueError as exc:
        return method | {'kind': 'unavailable', 'reason': str(exc)}
    restricted, unrestricted = sums
    numerator = [(n-p)*(a-b)-Q(critical)*q*b for a, b in zip(restricted, unrestricted)]
    denominator = [q*b for b in unrestricted]
    # Joint scaling preserves the test ratio as well as its sign.
    scale = lcm(*(c.denominator for c in numerator+denominator))
    numerator, denominator = ([int(c*scale) for c in poly] for poly in [numerator, denominator])
    return method | {'critical_value': critical, 'critical_binary64_ratio': str(Q(critical))} | certify_set(numerator, denominator)
