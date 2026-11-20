"""Exact univariate sign decomposition for AR inversion (ascending powers).

Sturm variations count *all distinct* roots, including even multiplicities.
The rational brackets, rather than rounded displayed endpoints, define roots.
This proves a computed test's topology, not its sampling assumptions/coverage.
"""
from __future__ import annotations

from fractions import Fraction as Q
from functools import reduce
from math import gcd, lcm

from .ar_cancellation import current_check


def trim(p):
    p = list(p)
    while len(p) > 1 and p[-1] == 0:
        p.pop()
    return p


def primitive(p):
    p = trim(p)
    scale = lcm(*(x.denominator if isinstance(x, Q) else 1 for x in p))
    ints = [int(x * scale) for x in p]
    divisor = reduce(gcd, ints, 0) or 1
    return [x // divisor for x in ints]


def add(p, q):
    return trim([(p[i] if i < len(p) else 0) + (q[i] if i < len(q) else 0)
                 for i in range(max(len(p), len(q)))])


def mul(p, q):
    out = [0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            out[i+j] += a*b
    return trim(out)


def evaluate(p, x):
    value = 0
    for c in reversed(p):
        value = value*x + c
    return value


def divide(p, q):
    p = [Q(x) for x in trim(p)]
    quotient = [Q(0)] * max(1, len(p)-len(q)+1)
    check = current_check()
    while p != [0] and len(p) >= len(q):
        if check is not None:
            check()
        shift = len(p)-len(q)
        c = p[-1]/q[-1]
        quotient[shift] = c
        for i, v in enumerate(q):
            p[i+shift] -= c*v
        p = trim(p)
    return trim(quotient), p


def derivative(p):
    return [i*p[i] for i in range(1, len(p))] or [0]


def polynomial_gcd(p, q):
    check = current_check()
    while q != [0]:
        if check is not None:
            check()
        p, q = q, primitive(divide(p, q)[1])
    return primitive(p)


def squarefree(p):
    return primitive(divide(p, polynomial_gcd(p, derivative(p)))[0])


def sturm(p):
    p = squarefree(p)
    sequence = [p]
    if len(p) > 1:
        sequence.append(primitive(derivative(p)))
    check = current_check()
    while len(sequence[-1]) > 1:
        if check is not None:
            check()
        remainder = divide(sequence[-2], sequence[-1])[1]
        sequence.append(primitive([-x for x in remainder]))
    return sequence


def variations(sequence, x):
    signs = [1 if v > 0 else -1 for p in sequence if (v := evaluate(p, x)) != 0]
    return sum(a != b for a, b in zip(signs, signs[1:]))


def isolate(p):
    if len(p) <= 1:
        return [], 1
    sequence = sturm(p)
    # Strict Cauchy bound; endpoints cannot be roots. It covers both tails.
    bound = 2 + max(abs(c)//abs(p[-1]) for c in p[:-1])
    todo = [(Q(-bound), Q(bound))]
    roots = []
    check = current_check()
    while todo:
        if check is not None:
            check()
        lo, hi = todo.pop()
        count = variations(sequence, lo)-variations(sequence, hi)
        if count == 0:
            continue
        if count == 1 and hi-lo <= max(Q(1), abs(lo), abs(hi))/2**44:
            roots.append((lo, hi))
            continue
        mid = (lo+hi)/2
        # Keep endpoints away from exact roots, including dyadic roots.
        while evaluate(p, mid) == 0:
            if check is not None:
                check()
            mid = (lo+mid)/2
        todo.extend([(mid, hi), (lo, mid)])
    return sorted(roots), bound


def _bracket(pair):
    lo, hi = pair
    return {'lower_rational': str(lo), 'upper_rational': str(hi)}


def certify_set(numerator, denominator):
    """Certify numerator <= 0 where the PSD covariance determinant is > 0.

    The caller supplies an exact Gram-determinant denominator (nonnegative).
    Any real singularity withholds the statistical confidence set, even if a
    continuous extension would be possible. Defined-domain pieces remain in
    evidence. No roots are removed with numeric tolerance or a pseudoinverse.
    """
    p, d = primitive(numerator), primitive(denominator)
    if d == [0]:
        return {'kind': 'unavailable', 'reason': 'singular_covariance_on_real_line',
                'global_certification': {'status': 'undefined_everywhere'}}
    product = mul(p, d) if p != [0] else d
    roots, bound = isolate(squarefree(product))
    d_sequence = sturm(d)
    singular = [variations(d_sequence, lo)-variations(d_sequence, hi) > 0 for lo, hi in roots]
    probes = [Q(-bound)] + [(a[1]+b[0])/2 for a, b in zip(roots, roots[1:])] + [Q(bound)]
    if not roots:
        probes = [Q(0)]
    accepted = [evaluate(p, b) <= 0 and evaluate(d, b) > 0 for b in probes]
    values = [float((lo+hi)/2) for lo, hi in roots]
    # Union adjacent accepted cells through nonsingular roots; retain isolated
    # accepted roots and holes. Infinity is represented by null, never JSON inf.
    pieces = []
    for i, yes in enumerate(accepted):
        if yes:
            pieces.append((i-1, i, i > 0 and not singular[i-1], i < len(roots) and not singular[i]))
    for i, undefined in enumerate(singular):
        if not undefined and not accepted[i] and not accepted[i+1]:
            pieces.append((i, i, True, True))
    pieces.sort()
    merged = []
    for a, b, ac, bc in pieces:
        if merged and merged[-1][1] == a and merged[-1][3] and ac:
            prev = merged.pop()
            merged.append((prev[0], b, prev[2], bc))
        else:
            merged.append((a, b, ac, bc))
    components = [{'lower': values[a] if a >= 0 else None,
                   'upper': values[b] if b < len(roots) else None,
                   'lower_closed': ac, 'upper_closed': bc,
                   'lower_root': a if a >= 0 else None, 'upper_root': b if b < len(roots) else None}
                  for a, b, ac, bc in merged]
    certificate = {'status': 'certified_on_defined_domain' if any(singular) else 'certified',
                   'arithmetic': 'exact_binary64_input_rationals', 'algorithm': 'sturm_sign_decomposition_v1',
                   'numerator': [str(c) for c in p], 'denominator': [str(c) for c in d],
                   'coefficient_order': 'ascending', 'cauchy_bound': str(bound),
                   'distinct_real_roots': len(roots), 'root_brackets': [_bracket(r) for r in roots],
                   'cell_accepted': accepted, 'boundary_tolerance': 'max(1,abs(root))*2^-44'}
    if any(singular):
        return {'kind': 'unavailable', 'reason': 'singular_covariance_on_real_line',
                'defined_components': components, 'undefined_points': [_bracket(r) for r, yes in zip(roots, singular) if yes],
                'global_certification': certificate}
    result = {'kind': 'disjoint', 'components': components, 'global_certification': certificate}
    if not components:
        result['kind'] = 'empty'
    elif len(components) == 1:
        c = components[0]
        if c['lower'] is None and c['upper'] is None:
            result['kind'] = 'whole_line'
        elif c['lower'] is None:
            result.update(kind='ray_below', upper=c['upper'])
        elif c['upper'] is None:
            result.update(kind='ray_above', lower=c['lower'])
        else:
            result.update(kind='singleton' if c['lower_root'] == c['upper_root'] else 'interval',
                          lower=c['lower'], upper=c['upper'])
    elif len(components) == 2 and components[0]['lower'] is None and components[1]['upper'] is None:
        result.update(kind='union_of_rays', lower=components[0]['upper'], upper=components[1]['lower'])
    return result
