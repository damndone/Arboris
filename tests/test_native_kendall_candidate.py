"""Differential checks for the isolated candidate, not performance acceptance.

NATIVE_KENDALL_REQUIRED=1 PYTHONPATH=local/native-kendall .venv/bin/python \
    -m pytest tests/test_native_kendall_candidate.py -q
"""
from array import array
from contextlib import nullcontext
import importlib
import importlib.util
import math
import os
import struct

import numpy as np
import pytest
from scipy import stats


@pytest.fixture(scope='module')
def candidate():
    if importlib.util.find_spec('_kendall_counts') is None:
        if os.environ.get('NATIVE_KENDALL_REQUIRED') == '1':
            pytest.fail('build the required native Kendall pilot first')
        pytest.skip('independent native Kendall pilot is not built/on PYTHONPATH')
    return importlib.import_module('native.kendall_counts.candidate')


def assert_same_bits(actual, expected):
    for field in ('statistic', 'pvalue'):
        a, b = getattr(actual, field), getattr(expected, field)
        if math.isnan(b):
            assert math.isnan(a)
        else:
            assert struct.pack('!d', a) == struct.pack('!d', b), (field, a, b)


@pytest.mark.parametrize('alternative', ['less', 'greater', 'two-sided'])
@pytest.mark.parametrize('method', ['asymptotic', 'auto'])
@pytest.mark.parametrize('seed,n', [(0, 34), (1, 97), (2, 4096), (17, 10_000)])
def test_untied_candidate_matches_public_scipy_bits(candidate, alternative, method, seed, n):
    rng = np.random.default_rng(seed)
    x, y = rng.standard_normal((2, n))
    actual = candidate.evaluate(x, y, method=method, alternative=alternative)
    expected = stats.kendalltau(x, y, method=method, alternative=alternative,
                                variant='b', nan_policy='raise')
    assert_same_bits(actual, expected)
    assert actual.engine == 'native-counts'
    assert actual.reason is None


@pytest.mark.parametrize('alternative', ['less', 'greater', 'two-sided'])
def test_binary64_extremes_keep_original_order_and_inputs(candidate, alternative):
    x = np.array([-math.inf, -1.7976931348623157e308, -1., -5e-324,
                  0., 5e-324, 1., 1.7976931348623157e308, math.inf])
    y = np.array([5e-324, -math.inf, 1., math.inf, -5e-324,
                  1.7976931348623157e308, -1., 0., -1.7976931348623157e308])
    before = (x.tobytes(), y.tobytes())
    actual = candidate.evaluate(x, y, method='asymptotic', alternative=alternative)
    assert_same_bits(actual, stats.kendalltau(x, y, method='asymptotic',
                    alternative=alternative, nan_policy='raise'))
    assert (x.tobytes(), y.tobytes()) == before


@pytest.mark.parametrize('x,y,method,reason', [
    ([], [], 'auto', 'sample-too-small'),
    ([1.], [2.], 'auto', 'sample-too-small'),
    ([1., 2.], [2., 1.], 'auto', 'sample-too-small'),
    ([1., 2., 3.], [1., 3., 2.], 'auto', 'exact-method'),
    (list(range(40)), list(range(40)), 'auto', 'exact-method'),
    ([0., 0., 1., 2.], [1., 2., 3., 4.], 'asymptotic', 'ties'),
    ([-0., 0., 1., 2.], [1., 2., 3., 4.], 'auto', 'ties'),
    ([1.] * 4, [2.] * 4, 'auto', 'ties'),
])
def test_inapplicable_paths_refuse_unless_fallback_is_explicit(candidate, x, y, method, reason):
    x, y = array('d', x), array('d', y)
    with pytest.raises(candidate.CandidateNotApplicable, match=reason):
        candidate.evaluate(x, y, method=method)
    with pytest.warns() if len(x) < 2 else nullcontext():
        actual = candidate.evaluate(x, y, method=method, fallback='scipy')
        expected = stats.kendalltau(x, y, method=method, nan_policy='raise')
    assert actual.engine == 'scipy-public'
    assert actual.reason == reason
    assert_same_bits(actual, expected)


@pytest.mark.parametrize('alternative', ['less', 'greater', 'two-sided'])
def test_explicit_exact_uses_public_oracle_only_when_requested(candidate, alternative):
    x, y = array('d', [1, 2, 3, 4]), array('d', [1, 4, 2, 3])
    with pytest.raises(candidate.CandidateNotApplicable, match='exact-method'):
        candidate.evaluate(x, y, method='exact', alternative=alternative)
    actual = candidate.evaluate(x, y, method='exact', alternative=alternative, fallback='scipy')
    assert actual.engine == 'scipy-public'
    assert_same_bits(actual, stats.kendalltau(x, y, method='exact', alternative=alternative))


def test_large_tie_group_cannot_enter_native_inference(candidate):
    # Large integer tie sums need not equal SciPy's float-intermediate sums.
    x = np.zeros(250_000, dtype=np.float64)
    x[-1] = 1.
    y = np.arange(x.size, dtype=np.float64)
    with pytest.raises(candidate.CandidateNotApplicable, match='ties'):
        candidate.evaluate(x, y, method='asymptotic')
    result = candidate.evaluate(x, y, method='asymptotic', fallback='scipy')
    assert_same_bits(result, stats.kendalltau(x, y, method='asymptotic'))


def test_one_million_untied_values_match_public_scipy_bits(candidate):
    # Fixed, non-extreme permutation. This checks the support boundary, not time.
    x = np.arange(1_000_000, dtype=np.float64)
    y = (x * 7919) % x.size
    actual = candidate.evaluate(x, y)
    assert actual.engine == 'native-counts'
    assert_same_bits(actual, stats.kendalltau(x, y, nan_policy='raise'))


def test_native_branch_never_invokes_public_scipy(candidate, monkeypatch):
    x = np.arange(40, dtype=np.float64)
    y = (x * 7) % x.size
    expected = stats.kendalltau(x, y, method='asymptotic')

    def unexpected_scipy(*args, **kwargs):
        pytest.fail('supported native branch unexpectedly invoked public SciPy')

    monkeypatch.setattr(candidate.stats, 'kendalltau', unexpected_scipy)
    actual = candidate.evaluate(x, y, method='asymptotic')
    assert_same_bits(actual, expected)


def test_exact_with_ties_retains_original_scipy_refusal(candidate):
    x, y = array('d', [1, 1, 2, 3]), array('d', [3, 1, 2, 4])
    with pytest.raises(ValueError, match='Ties found'):
        candidate.evaluate(x, y, method='exact', fallback='scipy')


@pytest.mark.parametrize('option,value', [('method', 'invalid'), ('alternative', 'invalid'),
                                         ('fallback', 'automatic')])
def test_unknown_options_are_rejected(candidate, option, value):
    with pytest.raises(ValueError, match=option):
        candidate.evaluate(array('d', [1, 2, 3]), array('d', [3, 2, 1]), **{option: value})


@pytest.mark.parametrize('fallback', ['raise', 'scipy'])
def test_invalid_native_buffers_never_trigger_scipy_fallback(candidate, fallback):
    with pytest.raises(ValueError, match='NaN'):
        candidate.evaluate(array('d', [math.nan]), array('d', [1]), fallback=fallback)
    with pytest.raises(ValueError, match='contiguous'):
        candidate.evaluate(np.arange(8.)[::2], np.arange(4.), fallback=fallback)
    with pytest.raises(TypeError):
        candidate.evaluate(np.arange(4, dtype=np.int64), np.arange(4.), fallback=fallback)


def test_unreviewed_scipy_version_fails_closed(candidate, monkeypatch):
    monkeypatch.setattr(candidate.scipy, '__version__', '1.19.0')
    with pytest.raises(RuntimeError, match='1.18.0'):
        candidate.evaluate(array('d', [1, 2, 3]), array('d', [3, 2, 1]), fallback='scipy')
