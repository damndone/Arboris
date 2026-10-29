"""Product-call differential/selection contract for native Kendall integration."""
from array import array
import importlib.util
import logging
import math
import os
import struct

import numpy as np
import pandas as pd
import pytest
from scipy import stats


@pytest.fixture(scope='module')
def kernel():
    from workbench import native_kendall
    return native_kendall


def same_bits(actual, expected):
    for key in ('statistic', 'pvalue'):
        left, right = getattr(actual, key), getattr(expected, key)
        assert (math.isnan(left) and math.isnan(right)) or (
            struct.pack('!d', left) == struct.pack('!d', right))


@pytest.fixture(scope='module')
def built_native():
    if importlib.util.find_spec('_kendall_counts') is None:
        if os.environ.get('NATIVE_KENDALL_REQUIRED') == '1':
            pytest.fail('native Kendall is required for these checks')
        pytest.skip('native Kendall extension not built/on PYTHONPATH')


@pytest.mark.parametrize('seed,n,tied', [(0, 34, False), (1, 97, True),
                                       (2, 4096, True), (3, 10_000, False)])
@pytest.mark.parametrize('alternative', ['less', 'greater', 'two-sided'])
def test_native_asymptotic_matches_public_scipy_bits(kernel, built_native, seed, n, tied, alternative):
    rng = np.random.default_rng(seed)
    x, y = rng.normal(size=(2, n))
    if tied:
        x, y = np.round(x), np.round(y)
    result = kernel.evaluate(x, y, method='asymptotic', alternative=alternative, engine='native')
    assert result.engine == 'native-counts'
    same_bits(result, stats.kendalltau(x, y, method='asymptotic', alternative=alternative))


@pytest.mark.parametrize('n', [3, 33, 34, 1_000_000])
def test_auto_exact_and_small_boundaries_remain_original(kernel, built_native, n):
    x = np.arange(n, dtype=np.float64)
    y = x[::-1].copy()
    result = kernel.evaluate(x, y)
    assert result.engine == 'scipy-public'
    assert result.reason == 'exact-method'
    same_bits(result, stats.kendalltau(x, y))


@pytest.mark.parametrize('n', [250_000, 1_000_000])
def test_large_ties_reproduce_scipy_float_intermediates(kernel, built_native, n):
    x = np.zeros(n, dtype=np.float64)
    x[-1] = 1.
    y = np.arange(n, dtype=np.float64)
    result = kernel.evaluate(x, y, method='asymptotic', engine='native')
    assert result.engine == 'native-counts'
    same_bits(result, stats.kendalltau(x, y, method='asymptotic'))


def test_multiple_large_tie_groups_preserve_scipy_sum_order(kernel, built_native):
    sizes = [300_000, 299_999, 17, 17, 199_999, 199_968]
    x = np.repeat(np.arange(len(sizes), dtype=np.float64), sizes)
    indices = (np.arange(x.size, dtype=np.int64) * 7919) % x.size
    y = x[indices]
    result = kernel.evaluate(x, y, method='asymptotic', engine='native')
    assert result.engine == 'native-counts'
    same_bits(result, stats.kendalltau(x, y, method='asymptotic'))


def test_original_path_is_explicitly_selectable_and_logged(kernel, caplog):
    x, y = np.arange(40.), np.arange(40.)[::-1].copy()
    with caplog.at_level(logging.INFO, logger='workbench.native_kendall'):
        result = kernel.evaluate(x, y, engine='scipy')
    assert result.engine == 'scipy-public' and result.reason == 'requested-reference'
    same_bits(result, stats.kendalltau(x, y))
    assert any(getattr(record, 'kendall_engine', '') == 'scipy-public' for record in caplog.records)


def test_native_errors_are_not_swallowed(kernel, built_native, monkeypatch):
    native = kernel._load_native()
    def fail(*args, **kwargs):
        raise RuntimeError('injected kernel error')
    monkeypatch.setattr(native, 'count_with_ties', fail)
    with pytest.raises(RuntimeError, match='injected kernel error'):
        kernel.evaluate(np.arange(40.), (np.arange(40.) * 7) % 40)


@pytest.mark.parametrize('x,y', [
    (np.array([0., math.nan, 2.]), np.array([2., 1., 0.])),
    (np.array([1, 2, 3], dtype=np.int32), np.array([3, 2, 1], dtype=np.int32)),
    (np.arange(12.)[::2], np.arange(6.)),
])
def test_non_native_inputs_keep_reference_behavior(kernel, x, y):
    result = kernel.evaluate(x, y)
    assert result.engine == 'scipy-public'
    same_bits(result, stats.kendalltau(x, y))


@pytest.mark.parametrize('masked', [False, True])
def test_array_subclasses_keep_public_reference_semantics(kernel, masked):
    class ArraySubclass(np.ndarray):
        pass
    x = np.arange(40., dtype=np.float64)
    x = np.ma.array(x, mask=(x % 5 == 0)) if masked else x.view(ArraySubclass)
    y = (np.arange(40., dtype=np.float64) * 7) % 40
    original = stats.kendalltau(x, y, method='asymptotic')
    result = kernel.evaluate(x, y, method='asymptotic')
    assert result.engine == 'scipy-public'
    assert result.reason == 'array-subclass'
    same_bits(result, original)


def test_pairwise_row_contract_and_actual_native_call(kernel, built_native, monkeypatch):
    from workbench import statistical_test_pairs
    x = np.arange(100, dtype=np.float64)
    frame = pd.DataFrame({'x': x, 'y': (x * 7) % 100})
    original = stats.kendalltau(frame.x, frame.y)
    def forbidden_reference(*args, **kwargs):
        pytest.fail('eligible product Kendall path called the reference implementation')
    monkeypatch.setattr(kernel.stats, 'kendalltau', forbidden_reference)
    row = statistical_test_pairs._rank_correlations(frame, 'x', 'y')[1]
    assert row == {'test_id': 'kendall_correlation:x:y', 'test_type': 'kendall_correlation',
        'variables': ['x', 'y'], 'nobs': 100, 'statistic': float(original.statistic),
        'p_value': float(original.pvalue), 'effect': {'tau': float(original.statistic)},
        'warnings': [], 'source_id': 'statistical_tests.rank_correlations.kendall.x.y',
        'computation': {'engine': 'native-counts', 'reason': None}}


def test_pairwise_precision_reference_receipt_is_durable_without_changing_values(kernel, built_native):
    from workbench import statistical_test_pairs
    x = np.array([2**53, 2**53 + 1, 2**53 + 2, 2**53 + 3], dtype=np.int64)
    y = np.array([1, 3, 2, 4], dtype=np.int64)
    expected = stats.kendalltau(x, y)
    spearman, row = statistical_test_pairs._rank_correlations(pd.DataFrame({'x': x, 'y': y}), 'x', 'y')
    assert row['statistic'] == expected.statistic
    assert row['p_value'] == expected.pvalue
    assert row['warnings'] == ['KENDALL_PUBLIC_INTEGER_PROMOTION']
    assert spearman['warnings'] == []
    assert row['computation'] == {'engine': 'scipy-public', 'reason': 'public-integer-promotion'}
