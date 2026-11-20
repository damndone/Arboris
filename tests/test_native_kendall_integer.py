"""Exact native signed/unsigned order and mixed-column tau/p differentials."""
from collections import Counter
import importlib
import importlib.util
from itertools import product
import math
import os
import struct

import numpy as np
import pytest
from scipy import stats


@pytest.fixture(scope='module')
def native():
    if importlib.util.find_spec('_kendall_counts') is None:
        if os.environ.get('NATIVE_KENDALL_REQUIRED') == '1':
            pytest.fail('native Kendall required')
        pytest.skip('native Kendall is not built/on PYTHONPATH')
    return importlib.import_module('_kendall_counts')


VALUES = {
    'i8': [-2**63, -2**63 + 1, -2**53 - 1, -2**53, -1, 0, 1,
           2**53, 2**53 + 1, 2**63 - 2, 2**63 - 1],
    'u8': [0, 1, 2, 2**53 - 1, 2**53, 2**53 + 1, 2**63 - 1,
           2**63, 2**64 - 2, 2**64 - 1],
    'f8': [-math.inf, -1.7976931348623157e308, -1., -5e-324, -0.,
           0., 5e-324, 1., 1.7976931348623157e308, math.inf],
}


def exact_pair_oracle(x, y):
    x, y = x.tolist(), y.tolist()  # small independent oracle only; never product processing
    result = {'n': len(x), 'discordant': 0, 'joint_tie_pairs': 0}
    for i in range(len(x)):
        for j in range(i):
            result['joint_tie_pairs'] += x[i] == x[j] and y[i] == y[j]
            result['discordant'] += (x[i] != x[j] and y[i] != y[j]
                                    and (x[i] < x[j]) != (y[i] < y[j]))
    for name, values in [('x', x), ('y', y)]:
        sizes = Counter(values).values()
        result[name + '_tie_pairs'] = sum(t * (t - 1) // 2 for t in sizes)
        result[name + '_tie_triples'] = sum(t * (t - 1) * (t - 2) for t in sizes)
        result[name + '_tie_weighted'] = sum(t * (t - 1) * (2 * t + 5) for t in sizes)
    return result


def pair(dtype_x, dtype_y):
    rng = np.random.default_rng(20261029)
    choices_x = np.array(VALUES[dtype_x], dtype=dtype_x)
    choices_y = np.array(VALUES[dtype_y], dtype=dtype_y)
    return (choices_x[rng.integers(0, len(choices_x), 73)],
            choices_y[rng.integers(0, len(choices_y), 73)])


@pytest.mark.parametrize('dtype_x,dtype_y', list(product(VALUES, repeat=2)))
def test_all_native_type_pairs_keep_exact_counts(native, dtype_x, dtype_y):
    x, y = pair(dtype_x, dtype_y)
    expected = exact_pair_oracle(x, y)
    before = x.tobytes(), y.tobytes()
    result = native.count_with_ties(x, y)
    assert {key: result[key] for key in expected} == expected
    assert result['public_float_compatible'] is (dtype_x == dtype_y == 'f8')
    assert (x.tobytes(), y.tobytes()) == before


@pytest.mark.parametrize('dtype_x,dtype_y', list(product(VALUES, repeat=2)))
@pytest.mark.parametrize('alternative', ['less', 'greater', 'two-sided'])
def test_far_integer_precision_boundary_preserves_public_scipy_bits(native, dtype_x, dtype_y, alternative):
    from workbench import native_kendall
    x, y = pair(dtype_x, dtype_y)
    if dtype_x == dtype_y == 'f8':
        result = native_kendall.evaluate(x, y, method='asymptotic',
                                        alternative=alternative, engine='native')
        assert result.engine == 'native-counts'
    else:
        with pytest.raises(native_kendall.CandidateNotApplicable, match='public-integer-promotion'):
            native_kendall.evaluate(x, y, method='asymptotic', alternative=alternative, engine='native')
        result = native_kendall.evaluate(x, y, method='asymptotic', alternative=alternative)
        assert result.engine == 'scipy-public'
        assert result.reason == 'public-integer-promotion'
        assert result.workspace_bytes > 0
    expected = stats.kendalltau(x, y, method='asymptotic', alternative=alternative)
    for name in ('statistic', 'pvalue'):
        assert struct.pack('!d', getattr(result, name)) == struct.pack('!d', getattr(expected, name))


@pytest.mark.parametrize('dtype', ['i8', 'u8'])
def test_unaligned_readonly_integer_snapshot_retains_endpoint_order(native, dtype):
    values = np.array(VALUES[dtype], dtype=dtype)
    raw = b'x' + values.tobytes()
    x = np.frombuffer(raw, dtype=dtype, offset=1)
    y = np.arange(x.size, dtype=np.float64)[::-1].copy()
    expected = exact_pair_oracle(x, y)
    result = native.count_with_ties(memoryview(x).toreadonly(), y)
    assert {key: result[key] for key in expected} == expected


@pytest.mark.parametrize('dtype,values', [
    ('i8', [-2**53, -2**53 + 1, -1, 0, 1, 2**53 - 1, 2**53]),
    ('u8', [0, 1, 2**53 - 1, 2**53]),
])
def test_safe_integer_precision_endpoints_remain_native(native, dtype, values):
    from workbench import native_kendall
    x = np.array(values, dtype=dtype)
    y = np.arange(x.size, dtype=np.float64)
    result = native_kendall.evaluate(x, y, method='asymptotic', engine='native')
    expected = stats.kendalltau(x, y, method='asymptotic')
    assert result.engine == 'native-counts'
    for name in ('statistic', 'pvalue'):
        assert struct.pack('!d', getattr(result, name)) == struct.pack('!d', getattr(expected, name))
