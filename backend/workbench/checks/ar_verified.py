"""Verified AR reduction of the original binary64 observations (on demand).

Higham's deterministic gamma bound encloses raw degree-four moments. All
subsequent inverse/contraction/determinant operations use rational outward
intervals. Sturm isolates the midpoint roots, but DOES NOT certify the input:
uniform Bernstein signs on the complement, monotonicity/existence in each
root box, and uniform Cauchy tails supply that separate proof. Uncertainty
raises VerificationUncertain; callers must use the original exact row path.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
from itertools import combinations_with_replacement
from math import comb

import numpy as np

from .ar_polynomials import certify_set


class VerificationUncertain(Exception):
    pass


_SCALE = 2**192


@dataclass(frozen=True, eq=False)
class Interval:
    lo: Q
    hi: Q

    def __init__(self, lo, hi=None):
        lo, hi = Q(lo), Q(lo if hi is None else hi)
        if lo > hi:
            raise ValueError('reversed_interval')
        object.__setattr__(self, 'lo', Q((lo*_SCALE).__floor__(), _SCALE))
        object.__setattr__(self, 'hi', Q((hi*_SCALE).__ceil__(), _SCALE))

    def __add__(self, other):
        other = as_interval(other)
        return Interval(self.lo+other.lo, self.hi+other.hi)

    __radd__ = __add__

    def __neg__(self):
        return Interval(-self.hi, -self.lo)

    def __sub__(self, other):
        return self+-as_interval(other)

    def __rsub__(self, other):
        return as_interval(other)+-self

    def __mul__(self, other):
        other = as_interval(other)
        values = [a*b for a in (self.lo, self.hi) for b in (other.lo, other.hi)]
        return Interval(min(values), max(values))

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = as_interval(other)
        if other.lo <= 0 <= other.hi:
            raise VerificationUncertain('interval_pivot_contains_zero')
        return self*Interval(1/other.hi, 1/other.lo)

    def __eq__(self, other):
        other = as_interval(other)
        return self.lo == other.lo and self.hi == other.hi

    def record(self):
        return [str(self.lo), str(self.hi)]


def as_interval(value):
    return value if isinstance(value, Interval) else Interval(value)


def sign(value):
    return 1 if value.lo > 0 else -1 if value.hi < 0 else 0


def moment_enclosure(data):
    """Enclose sum d_a*d_b*d_c*d_d without observation-wise Python work.

    At most two feature multiplications, one dot product and block aggregation
    affect a term. gamma_(4n+16) dominates their binary64 error paths for any
    reduction order. The ABS dot is rounded too: divide its enclosure by
    1-gamma, rather than treating a rounded absolute sum as an upper bound.
    A 4n*eta additive allowance covers gradual-underflow in sums. Products
    outside the normal arithmetic envelope are sent to exact fallback.
    """
    import hashlib
    n, m = data.shape
    steps = 4*n+16
    if steps >= 2**53:
        raise VerificationUncertain('gamma_envelope_exhausted')
    gamma = Q(steps, 2**53-steps)
    eta = Q(1, 2**1074)
    pairs = list(combinations_with_replacement(range(m), 2))
    left, right = np.array(pairs).T
    size = len(pairs)
    sums, absolute = np.zeros((size, size)), np.zeros((size, size))
    digest = hashlib.sha256(f'ar_raw_binary64_moments_v1:{n}:{m}:<f8'.encode())
    finfo = np.finfo(np.float64)
    safe_low, safe_high = np.sqrt(finfo.tiny), np.sqrt(finfo.max/(4*n+16))
    for start in range(0, n, 16384):
        block = np.asarray(data[start:start+16384], dtype='<f8', order='C')
        if not np.isfinite(block).all():
            raise VerificationUncertain('nonfinite_input')
        digest.update(memoryview(block).cast('B'))
        with np.errstate(over='ignore', under='ignore', invalid='ignore'):
            features = block[:, left]*block[:, right]
        nonzero_operands = (block[:, left] != 0) & (block[:, right] != 0)
        magnitudes = np.abs(features)
        if (not np.isfinite(features).all() or
                np.any(nonzero_operands & (magnitudes < safe_low)) or
                np.any(magnitudes > safe_high)):
            raise VerificationUncertain('moment_product_outside_normal_envelope')
        sums += features.T@features
        absolute += magnitudes.T@magnitudes
    if not np.isfinite(sums).all() or not np.isfinite(absolute).all():
        raise VerificationUncertain('moment_accumulation_overflow')
    underflow = steps*eta
    moment = []
    for i in range(size):
        row = []
        for j in range(size):
            absolute_upper = (Q(float(absolute[i, j]))+underflow)/(1-gamma)
            radius = gamma*absolute_upper+underflow
            value = Q(float(sums[i, j]))
            row.append(Interval(value-radius, value+radius))
        moment.append(row)
    return moment, pairs, {'input_sha256': digest.hexdigest(), 'rows': n,
                           'gamma_steps': steps, 'gamma': str(gamma),
                           'underflow_allowance': str(underflow),
                           'moment_bounds': [[v.record() for v in row] for row in moment]}


def inverse_enclosure(gram):
    n = len(gram)
    rows = [list(row)+[Interval(i == j) for j in range(n)] for i, row in enumerate(gram)]
    for j in range(n):
        pivot = rows[j][j]
        if pivot.lo <= 0:
            raise VerificationUncertain('gram_positive_pivot_not_verified')
        rows[j] = [v/pivot for v in rows[j]]
        rows[j][j] = Interval(1)
        for i in range(n):
            if i != j:
                factor = rows[i][j]
                rows[i] = [a-factor*b for a, b in zip(rows[i], rows[j])]
                rows[i][j] = Interval(0)  # algebraically zero, not independent
    return [row[n:] for row in rows]


def _quadratic_product(a, b, pairs):
    return [a[i]*b[j] + (a[j]*b[i] if i != j else 0) for i, j in pairs]


def _bilinear(a, moment, b):
    # Exact structural zeros greatly reduce small-matrix interval arithmetic.
    return sum(a[i]*sum(moment[i][j]*b[j] for j in range(len(b)) if b[j] != 0)
               for i in range(len(a)) if a[i] != 0)


def polynomial_enclosures(y, x, z, w, critical):
    from .ar_confidence import determinant
    from .ar_polynomials import add
    # Constant, response, endogenous, nuisance, excluded instruments.
    data = np.column_stack([np.ones(len(y)), y, x, w, z])
    moment, pairs, evidence = moment_enclosure(data)
    index = {pair: i for i, pair in enumerate(pairs)}
    def second(i, j):
        return moment[index[(0, min(i, j))]][index[(0, max(i, j))]]
    p, q = w.shape[1]+z.shape[1], z.shape[1]
    inverse = inverse_enclosure([[second(i+3, j+3) for j in range(p)] for i in range(p)])
    u = [sum(row[j]*second(j+3, 1) for j in range(p)) for row in inverse]
    v = [sum(row[j]*second(j+3, 2) for j in range(p)) for row in inverse]
    e, f = [Interval(0), Interval(1), Interval(0)]+[-t for t in u], [Interval(0), Interval(0), Interval(1)]+[-t for t in v]
    k = [[Interval(0)]*3+row for row in inverse[-q:]]
    ke, kf = [_quadratic_product(row, e, pairs) for row in k], [_quadratic_product(row, f, pairs) for row in k]
    covariance = [[[_bilinear(ke[i], moment, ke[j]),
                    -_bilinear(ke[i], moment, kf[j])-_bilinear(kf[i], moment, ke[j]),
                    _bilinear(kf[i], moment, kf[j])] for j in range(q)] for i in range(q)]
    c = [[a, -b] for a, b in zip(u[-q:], v[-q:])]
    bordered = [[*row, c[i]] for i, row in enumerate(covariance)] + [[*c, [Interval(0)]]]
    denominator, border = determinant(covariance), determinant(bordered)
    numerator = add([-Q(float(critical))*a for a in denominator], [-b for b in border])
    evidence.update(inverse_bounds=[[v.record() for v in row] for row in inverse],
                    response_projection_bounds=[v.record() for v in u],
                    endogenous_projection_bounds=[value.record() for value in v])
    return numerator, denominator, evidence


def _evaluate(poly, x):
    value = Interval(0)
    for c in reversed(poly):
        value = value*x+c
    return value


def _bernstein(poly, lo, hi):
    n = len(poly)-1
    powers = [sum(poly[i]*comb(i, j)*lo**(i-j)*(hi-lo)**j for i in range(j, n+1))
              for j in range(n+1)]
    return [sum(powers[j]*Q(comb(k, j), comb(n, j)) for j in range(k+1)) for k in range(n+1)]


def _uniform_sign(poly, lo, hi, wanted):
    todo, proof = [(lo, hi, 0)], []
    while todo:
        a, b, depth = todo.pop()
        bounds = _bernstein(poly, a, b)
        if all(sign(c) == wanted for c in bounds):
            proof.append({'interval': [str(a), str(b)], 'sign': wanted,
                          'bernstein': [v.record() for v in bounds]})
            continue
        if depth >= 32 or len(proof)+len(todo) >= 512:
            raise VerificationUncertain('uniform_complement_sign_not_verified')
        mid = (a+b)/2
        todo.extend([(a, mid, depth+1), (mid, b, depth+1)])
    return proof


def _bound(poly):
    leading = poly[-1]
    if sign(leading) == 0:
        raise VerificationUncertain('polynomial_degree_not_verified')
    minimum = min(abs(leading.lo), abs(leading.hi))
    return Q(2+max((max(abs(v.lo), abs(v.hi))/minimum).__ceil__() for v in poly[:-1])) if len(poly)>1 else Q(1)


def verify_polynomials(numerator, denominator):
    """Uniform topology proof for EVERY coefficient vector in the box.

    Root endpoints remain rational isolating boxes of the ORIGINAL-input
    polynomial, not exact equalities between the roots of different polynomials.
    Displayed midpoints are approximations; the boxes are authoritative.
    """
    middle = lambda poly: [(v.lo+v.hi)/2 for v in poly]
    centre = certify_set(middle(numerator), middle(denominator))
    if centre['kind'] == 'unavailable':
        raise VerificationUncertain('midpoint_has_covariance_singularity')
    pbound, dbound = _bound(numerator), _bound(denominator)
    if len(denominator)%2 == 0 or sign(denominator[-1]) != 1:
        raise VerificationUncertain('covariance_tail_not_positive')
    denominator_proof = _uniform_sign(denominator, -dbound, dbound, 1)
    roots = centre['global_certification']['root_brackets']
    boxes, root_proofs = [], []
    derivative = [i*numerator[i] for i in range(1, len(numerator))] or [Interval(0)]
    for root in roots:
        a, b = Q(root['lower_rational']), Q(root['upper_rational'])
        midpoint = (a+b)/2
        radius = max(Q(1), abs(midpoint))/2**44
        for _ in range(40):
            lo, hi = midpoint-radius, midpoint+radius
            left, right = _evaluate(numerator, lo), _evaluate(numerator, hi)
            slope = _evaluate(derivative, Interval(lo, hi))
            if sign(left)*sign(right) == -1 and sign(slope) != 0:
                break
            radius *= 4
        else:
            raise VerificationUncertain('root_existence_uniqueness_not_verified')
        if (boxes and boxes[-1][1] >= lo) or lo <= -pbound or hi >= pbound:
            raise VerificationUncertain('root_boxes_not_disjoint')
        boxes.append((lo, hi))
        root_proofs.append({'left': left.record(), 'right': right.record(), 'derivative': slope.record()})
    gaps = list(zip([-pbound]+[b for a, b in boxes], [a for a, b in boxes]+[pbound]))
    complement = []
    for a, b in gaps:
        wanted = sign(_evaluate(numerator, (a+b)/2))
        if not wanted:
            raise VerificationUncertain('cell_sign_not_verified')
        complement.extend(_uniform_sign(numerator, a, b, wanted))
    certificate = centre['global_certification']
    certificate.pop('numerator')
    certificate.pop('denominator')
    certificate.update(arithmetic='exact_binary64_input_rationals',
                       algorithm='gamma_moments_rational_intervals_sturm_bernstein_v1',
                       input_topology_certified=True,
                       numerator_coefficient_bounds=[v.record() for v in numerator],
                       denominator_coefficient_bounds=[v.record() for v in denominator],
                       cauchy_bound=str(pbound), denominator_cauchy_bound=str(dbound),
                       root_brackets=[{'lower_rational': str(a), 'upper_rational': str(b)} for a, b in boxes],
                       root_proofs=root_proofs, complement_proof=complement, denominator_proof=denominator_proof,
                       boundary_tolerance='individual_verified_rational_boxes; displayed_endpoints_are_approximations')
    return centre


def verified_set(y, x, z, w, critical):
    numerator, denominator, evidence = polynomial_enclosures(y, x, z, w, critical)
    result = verify_polynomials(numerator, denominator)
    result['global_certification']['reduction'] = evidence
    return result
