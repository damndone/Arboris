"""Opt-in integer Kendall counts; public SciPy checks, never private API calls.

Build: .venv/bin/python native/kendall_counts/build.py
Test: NATIVE_KENDALL_REQUIRED=1 PYTHONPATH=local/native-kendall \\
      .venv/bin/python -m pytest tests/test_native_kendall_counts.py -q
These are functional checks, including the 1M support boundary, not benchmarks.
The public tau statistic reconstructs SciPy's discordance count; small inputs
also have an independent, exact O(n squared) pair-enumeration oracle.
"""
from array import array
from collections import Counter
import importlib
import importlib.util
from itertools import product
import math
import os

import numpy as np
import pytest
from scipy import stats


def test_required_native_kendall_pilot_exists():
    if os.environ.get('NATIVE_KENDALL_REQUIRED') == '1':
        assert importlib.util.find_spec('_kendall_counts') is not None, 'build the native Kendall pilot first'


@pytest.fixture(scope='module')
def native():
    if importlib.util.find_spec('_kendall_counts') is None:
        if os.environ.get('NATIVE_KENDALL_REQUIRED') != '1':
            pytest.skip('independent native Kendall pilot not built/on PYTHONPATH')
        pytest.fail('required native Kendall pilot is missing')
    return importlib.import_module('_kendall_counts')


def tie_stats(values):
    sizes = Counter(values).values()
    return (sum(t * (t - 1) // 2 for t in sizes),
            sum(t * (t - 1) * (t - 2) for t in sizes),
            sum(t * (t - 1) * (2 * t + 5) for t in sizes))


def enumerated(x, y):
    discordant = joint = 0
    for i in range(len(x)):
        for j in range(i):
            if x[i] == x[j] and y[i] == y[j]:
                joint += 1
            elif x[i] != x[j] and y[i] != y[j] and (x[i] < x[j]) != (y[i] < y[j]):
                discordant += 1
    xt, x0, x1 = tie_stats(x)
    yt, y0, y1 = tie_stats(y)
    return {'n': len(x), 'discordant': discordant, 'joint_tie_pairs': joint,
            'x_tie_pairs': xt, 'y_tie_pairs': yt, 'x_tie_triples': x0, 'y_tie_triples': y0,
            'x_tie_weighted': x1, 'y_tie_weighted': y1}


CASES = [
    ([], []), ([1], [2]), ([1, 2], [2, 1]),
    ([1, 2, 3, 4], [1, 2, 3, 4]), ([1, 2, 3, 4], [4, 3, 2, 1]),
    ([0] * 8, [0] * 8), ([0] * 8, list(range(8))),
    ([1, 1, 2, 2, 3, 3], [1, 2, 1, 2, 1, 2]),
    ([12, 2, 1, 12, 2], [1, 4, 7, 1, 0]),
    ([-math.inf, -0.0, 0.0, math.inf, math.inf], [math.inf, 0.0, -0.0, -math.inf, math.inf]),
    ([5e-324, 0.0, -5e-324, 1.7976931348623157e308], [1, 2, 2, 3]),
]


@pytest.mark.parametrize('x,y', CASES)
def test_constructed_counts_match_independent_pair_oracle(native, x, y):
    assert native.count(array('d', x), array('d', y)) == enumerated(x, y)


def test_all_binary_rank_sequences_of_length_four(native):
    for pattern in product((0.0, 1.0), repeat=8):
        x, y = pattern[:4], pattern[4:]
        assert native.count(array('d', x), array('d', y)) == enumerated(x, y)


@pytest.mark.parametrize('seed,n', tuple(product(range(12), (3, 7, 31, 79))))
def test_fixed_random_counts_match_independent_pair_oracle(native, seed, n):
    rng = np.random.default_rng(seed)
    x = rng.integers(-4, 5, n).astype(np.float64)
    y = rng.integers(-5, 6, n).astype(np.float64)
    assert native.count(x, y) == enumerated(x, y)


@pytest.mark.parametrize('n,tied', tuple(product((3, 20, 500, 10_000), (True, False))))
def test_public_scipy_tie_counts_discordance_and_tau_agree(native, n, tied):
    rng = np.random.default_rng(20261027 + n)
    x, y = rng.standard_normal((2, n))
    if tied:
        x, y = np.round(x), np.round(y)
    # Public SciPy ranking determines its tie equivalence classes.
    expected_x = tie_stats(stats.rankdata(x, method='dense'))
    expected_y = tie_stats(stats.rankdata(y, method='dense'))
    actual = native.count(x, y)
    assert (actual['x_tie_pairs'], actual['x_tie_triples'], actual['x_tie_weighted']) == expected_x
    assert (actual['y_tie_pairs'], actual['y_tie_triples'], actual['y_tie_weighted']) == expected_y
    expected_joint = sum(int(t) * (int(t) - 1) // 2 for t in np.unique(
        np.column_stack((x, y)), axis=0, return_counts=True)[1])
    assert actual['joint_tie_pairs'] == expected_joint
    total = n * (n - 1) // 2
    denominator_x, denominator_y = total - actual['x_tie_pairs'], total - actual['y_tie_pairs']
    result = stats.kendalltau(x, y, variant='b', method='asymptotic', nan_policy='raise')
    if not denominator_x or not denominator_y:
        assert math.isnan(result.statistic)
        return
    score = total - actual['x_tie_pairs'] - actual['y_tie_pairs'] + actual['joint_tie_pairs'] - 2 * actual['discordant']
    reconstructed_tau = np.clip(score / np.sqrt(denominator_x) / np.sqrt(denominator_y), -1.0, 1.0)
    assert reconstructed_tau == result.statistic
    scipy_score = round(float(result.statistic) * math.sqrt(denominator_x) * math.sqrt(denominator_y))
    scipy_discordant = (total - expected_x[0] - expected_y[0] + expected_joint - scipy_score) // 2
    assert actual['discordant'] == scipy_discordant


def test_readonly_unaligned_and_native_buffers_do_not_change_inputs(native):
    raw = b'x' + np.array([3., 1., 2., 2.], dtype=np.float64).tobytes()
    x = np.frombuffer(raw, dtype=np.float64, offset=1)
    y = np.array([1., 3., 2., 2.])
    before = y.tobytes()
    assert not x.flags.aligned
    assert native.count(memoryview(x).toreadonly(), memoryview(y)) == enumerated(x, y)
    assert y.tobytes() == before


@pytest.mark.parametrize('bad', [math.nan, -math.nan])
def test_nan_is_rejected_before_sorting(native, bad):
    with pytest.raises(ValueError, match='NaN'):
        native.count(array('d', [1, bad]), array('d', [1, 2]))


@pytest.mark.parametrize('bad', [
    [1., 2.], np.array([1, 2], dtype=np.int64), np.array([1, 2], dtype=np.float32),
    np.array([1, 2], dtype='>f8'),
])
def test_non_float64_or_non_native_format_is_rejected(native, bad):
    with pytest.raises(TypeError):
        native.count(bad, array('d', [1, 2]))


@pytest.mark.parametrize('bad', [np.ones((2, 2)), np.arange(8.)[::2], np.arange(4.)[::-1]])
def test_non_1d_or_non_contiguous_buffers_are_rejected(native, bad):
    with pytest.raises(ValueError):
        native.count(bad, array('d', [1, 2, 3, 4]))


def test_unequal_lengths_are_rejected(native):
    with pytest.raises(ValueError, match='same length'):
        native.count(array('d', [1, 2]), array('d', [1]))


def test_one_million_ties_use_exact_integers_at_supported_boundary(native):
    n = 1_000_000
    values = np.zeros(n, dtype=np.float64)
    result = native.count(values, values)
    pairs, triples, weighted = n * (n - 1) // 2, n * (n - 1) * (n - 2), n * (n - 1) * (2 * n + 5)
    assert native.MAX_INPUT_SIZE == n
    assert weighted < 2**63
    assert result == {'n': n, 'discordant': 0, 'joint_tie_pairs': pairs,
        'x_tie_pairs': pairs, 'y_tie_pairs': pairs, 'x_tie_triples': triples,
        'y_tie_triples': triples, 'x_tie_weighted': weighted, 'y_tie_weighted': weighted}


def test_one_million_reverse_order_counts_beyond_32_bit_range(native):
    n = 1_000_000
    x = np.arange(n, dtype=np.float64)
    y = x[::-1].copy()
    result = native.count(x, y)
    assert result['discordant'] == n * (n - 1) // 2 > 2**32
    assert not any(value for key, value in result.items() if key not in {'n', 'discordant'})


def test_above_supported_length_fails_before_native_allocation(native):
    values = np.zeros(1_000_001, dtype=np.float64)
    with pytest.raises(OverflowError, match='1000000'):
        native.count(values, values)
