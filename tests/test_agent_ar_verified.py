"""Original-input AR verification, independent exact-input fallback as oracle."""
from fractions import Fraction as Q

import numpy as np
import pytest
from scipy.stats import chi2

from workbench.checks import ar_confidence as ar
from workbench.checks.ar_polynomials import certify_set


@pytest.mark.parametrize('q', [1, 2, 3, 4])
def test_verified_original_input_roots_enclose_exact_oracle(q, monkeypatch):
    rng = np.random.default_rng(140+q)
    z = rng.normal(size=(90, q))
    x = z[:, :1] + rng.normal(size=(90, 1))
    y = 1.4*x[:, 0] + rng.normal(size=90)
    w = np.ones((90, 1))
    p, d = ar.robust_polynomials(y, x, z, w, chi2.ppf(.95, q))
    exact = certify_set(p, d)
    def forbidden(*args):
        pytest.fail('well-conditioned verification must not use exact row loop')
    monkeypatch.setattr(ar, 'robust_polynomials', forbidden)
    actual = ar.robust_set(y, x, z, w)
    assert actual['computation']['path'] == 'verified_numpy'
    assert actual['kind'] == exact['kind']
    cert = actual['global_certification']
    assert cert['input_topology_certified'] is True
    assert cert['cell_accepted'] == exact['global_certification']['cell_accepted']
    assert cert['distinct_real_roots'] == exact['global_certification']['distinct_real_roots']
    for fast, oracle in zip(cert['root_brackets'], exact['global_certification']['root_brackets']):
        assert Q(fast['lower_rational']) <= Q(oracle['lower_rational'])
        assert Q(fast['upper_rational']) >= Q(oracle['upper_rational'])


def test_near_boundary_covariance_falls_back_to_exact_original_input():
    x = np.array([[1.], [0.], [2.], [0.]])
    z = np.array([[1.], [-1.], [0.], [0.]])
    result = ar.robust_set(2*x[:, 0], x, z, np.empty((4, 0)))
    assert result['computation']['path'] == 'exact_fallback'
    assert result['computation']['fallback_reason']
    assert result['reason'] == 'singular_covariance_on_real_line'
    assert result['global_certification']['arithmetic'] == 'exact_binary64_input_rationals'


def test_moment_error_bounds_contain_original_binary64_exact_sums():
    from workbench.checks.ar_verified import moment_enclosure
    rng = np.random.default_rng(513)
    data = rng.normal(size=(31, 3))
    moment, pairs, _ = moment_enclosure(data)
    for i, (a, b) in enumerate(pairs):
        for j, (c, d) in enumerate(pairs):
            oracle = sum(Q(float(row[a]))*Q(float(row[b]))*
                         Q(float(row[c]))*Q(float(row[d])) for row in data)
            assert moment[i][j].lo <= oracle <= moment[i][j].hi


def test_uncertain_interval_polynomial_cannot_claim_fixed_topology():
    from workbench.checks.ar_verified import Interval, VerificationUncertain, verify_polynomials
    # x²+epsilon changes empty/singleton/two-root topology at epsilon=0.
    p = [Interval(Q(-1, 10**20), Q(1, 10**20)), Interval(0), Interval(1)]
    with pytest.raises(VerificationUncertain):
        verify_polynomials(p, [Interval(1)])


@pytest.mark.parametrize('scale', [1e-100, 1e100])
def test_arithmetic_envelope_exits_to_exact_instead_of_using_invalid_gamma(scale):
    from workbench.checks.ar_verified import VerificationUncertain, moment_enclosure
    data = np.array([[1., scale], [1., -scale]])
    with pytest.raises(VerificationUncertain, match='normal_envelope'):
        moment_enclosure(data)
