"""Exact counts plus ordered binary tie groups for SciPy-compatible inference."""
from array import array
from collections import Counter
import importlib
import importlib.util
import math
import os

import numpy as np
import pytest


@pytest.fixture(scope='module')
def native():
    if importlib.util.find_spec('_kendall_counts') is None:
        if os.environ.get('NATIVE_KENDALL_REQUIRED') == '1':
            pytest.fail('build the required native Kendall module')
        pytest.skip('native Kendall not built/on PYTHONPATH')
    return importlib.import_module('_kendall_counts')


@pytest.mark.parametrize('x,y', [
    ([], []), ([1.], [1.]),
    ([2, 2, 2, 1, 1, 4, 3, 3], [5, 5, 1, 1, 1, 1, 2, 2]),
    ([-math.inf, -0., 0., math.inf, math.inf], [1, 3, 3, 1, 1]),
])
def test_tie_sizes_are_uint32_bytes_in_sorted_rank_order(native, x, y):
    result = native.count_with_ties(array('d', x), array('d', y))
    original = native.count(array('d', x), array('d', y))
    assert native.API_VERSION == 4
    assert {key: result[key] for key in original} == original
    for name, values in [('x', x), ('y', y)]:
        expected = [count for _, count in sorted(Counter(values).items()) if count > 1]
        raw = result[name + '_tie_sizes']
        assert type(raw) is bytes
        assert np.frombuffer(raw, dtype=np.uint32).tolist() == expected


def test_many_tie_groups_and_grouped_fenwick_have_exact_counts(native):
    n = 100_000
    x = np.repeat(np.arange(n // 2, dtype=np.float64), 2)
    y = x[::-1].copy()
    result = native.count_with_ties(x, y)
    assert result['discordant'] == n * (n - 1) // 2 - n // 2
    assert result['joint_tie_pairs'] == n // 2
    for name in ('x', 'y'):
        sizes = np.frombuffer(result[name + '_tie_sizes'], dtype=np.uint32)
        assert sizes.size == n // 2
        assert np.all(sizes == 2)
        assert result[name + '_tie_pairs'] == n // 2


@pytest.mark.parametrize('n', [0, 3, 100_000])
def test_workspace_counts_owned_rows_and_tree_without_tie_vectors(native, n):
    x = np.arange(n, dtype=np.float64)
    result = native.count_with_ties(x, x)
    assert result['workspace_bytes'] == 16 * n + 4 * (n + 1)
    assert native.workspace_bytes() >= result['workspace_bytes']


def test_workspace_counts_both_tie_vectors_with_live_tree(native):
    n = 100_000
    values = np.zeros(n, dtype=np.float64)
    result = native.count_with_ties(values, values)
    assert result['workspace_bytes'] == 16 * n + 8 + 4 + 4
