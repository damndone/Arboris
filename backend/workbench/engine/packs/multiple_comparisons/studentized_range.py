"""Bounded Studentized-range tail evaluation for Games--Howell inference.

The public statsmodels ``libqsturng`` helper clamps upper-tail p-values at
0.001.  That is unsuitable for an evidence-producing pack because a very
strong comparison would be reported as exactly 0.001.  This module evaluates
the finite-d.f. range integral directly with fixed Gauss--Legendre nodes and
uses SciPy's direct distribution for the small-d.f. region where the R-style
finite-d.f. reference is undefined.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats
from scipy.special import erf, gammaln, ndtr


_MAX_FINITE_DF = 25_000.0
_FINITE_DF_CUTOFF = 2.0
_LOG_TERM_CUTOFF = -30.0
_LOG_RANGE_CUTOFF = -50.0
_RANGE_INTEGRATION_LIMIT = 8.0
_RANGE_SPLIT = 3.0
_NORMALIZATION = math.sqrt(2.0 * math.pi)
_RANGE_NODES, _RANGE_WEIGHTS = np.polynomial.legendre.leggauss(12)
_DF_NODES, _DF_WEIGHTS = np.polynomial.legendre.leggauss(16)


def _range_probability(range_value: float, group_count: int) -> float:
    """Return the infinite-d.f. range CDF for one range."""

    half_range = range_value * 0.5
    if half_range >= _RANGE_INTEGRATION_LIMIT:
        return 1.0

    first_term = erf(half_range / math.sqrt(2.0))
    if first_term >= math.exp(_LOG_RANGE_CUTOFF / group_count):
        first_term = first_term**group_count
    else:
        first_term = 0.0

    interval_count = 2 if range_value > _RANGE_SPLIT else 3
    interval_width = (_RANGE_INTEGRATION_LIMIT - half_range) / interval_count
    second_term = 0.0
    exponent = group_count - 1
    cutoff = math.exp(_LOG_TERM_CUTOFF / exponent)
    for interval in range(interval_count):
        lower = half_range + interval * interval_width
        upper = lower + interval_width
        midpoint = 0.5 * (upper + lower)
        half_width = 0.5 * (upper - lower)
        normal_points = midpoint + half_width * _RANGE_NODES
        normal_range_mass = ndtr(normal_points) - ndtr(normal_points - range_value)
        keep = normal_range_mass >= cutoff
        if not np.any(keep):
            continue
        contribution = np.sum(
            _RANGE_WEIGHTS[keep]
            * np.exp(-0.5 * normal_points[keep] ** 2)
            * normal_range_mass[keep] ** exponent
        )
        second_term += (
            (2.0 * half_width * group_count) / _NORMALIZATION * float(contribution)
        )

    probability = first_term + second_term
    return min(1.0, max(0.0, probability))


def _finite_df_cdf(q: float, group_count: int, degrees_of_freedom: float) -> float:
    """Evaluate a finite-d.f. Studentized-range CDF by quadrature."""

    half_df = degrees_of_freedom * 0.5
    df_minus_one = half_df - 1.0
    df_quarter = degrees_of_freedom * 0.25
    unit_length = 1.0
    if degrees_of_freedom > 100.0:
        unit_length = 0.5
    if degrees_of_freedom > 800.0:
        unit_length = 0.25
    if degrees_of_freedom > 5_000.0:
        unit_length = 0.125

    log_normalization = (
        half_df * math.log(degrees_of_freedom)
        - degrees_of_freedom * math.log(2.0)
        - gammaln(half_df)
        + math.log(unit_length)
    )
    total = 0.0
    for interval in range(1, 51):
        midpoint = (2 * interval - 1) * unit_length
        chi_square_points = midpoint + unit_length * _DF_NODES
        log_terms = (
            log_normalization
            + df_minus_one * np.log(chi_square_points)
            - df_quarter * chi_square_points
        )
        keep = log_terms >= _LOG_TERM_CUTOFF
        if not np.any(keep):
            interval_total = 0.0
        else:
            range_points = q * np.sqrt(0.5 * chi_square_points[keep])
            range_probabilities = np.array(
                [
                    _range_probability(float(value), group_count)
                    for value in range_points
                ]
            )
            interval_total = float(
                np.sum(
                    _DF_WEIGHTS[keep]
                    * np.exp(log_terms[keep])
                    * range_probabilities
                )
            )
        if interval * unit_length >= 1.0 and interval_total <= 1.0e-14:
            break
        total += interval_total
    return min(1.0, max(0.0, total))


def studentized_range_upper_tail(
    q: float, group_count: int, degrees_of_freedom: float
) -> tuple[float, str]:
    """Return ``P(Q >= q)`` and the numerical backend used.

    R's finite-d.f. studentized-range reference requires d.f. at least two.
    Games--Howell can produce a smaller Welch d.f.; SciPy's direct distribution
    remains defined there, so the fallback is explicit rather than silently
    returning an invalid or clipped p-value.
    """

    if not math.isfinite(q) or q < 0.0:
        raise ValueError("q must be a finite non-negative value")
    if group_count < 2 or not math.isfinite(degrees_of_freedom) or degrees_of_freedom <= 0.0:
        raise ValueError("studentized-range shape parameters are invalid")
    if degrees_of_freedom < _FINITE_DF_CUTOFF:
        probability = float(stats.studentized_range.sf(q, group_count, degrees_of_freedom))
        return min(1.0, max(0.0, probability)), "scipy_studentized_range_df_lt_2"
    if degrees_of_freedom > _MAX_FINITE_DF:
        probability = 1.0 - _range_probability(q, group_count)
        return min(1.0, max(0.0, probability)), "direct_range_gauss_legendre_infinite_df"
    cdf = _finite_df_cdf(q, group_count, degrees_of_freedom)
    return min(1.0, max(0.0, 1.0 - cdf)), "direct_range_gauss_legendre_finite_df"


__all__ = ["studentized_range_upper_tail"]
