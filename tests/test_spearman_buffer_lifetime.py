import weakref

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from workbench import native_math, statistical_tests


@pytest.fixture(autouse=True)
def native_rank_build():
    if native_math._load_native() is None:
        pytest.skip('native Spearman build required')


@pytest.mark.parametrize('dtype', [np.float64, np.int64, np.uint64])
@pytest.mark.parametrize('alternative', ['two-sided', 'less', 'greater'])
def test_cached_pair_does_not_copy_raw_columns_and_preserves_public_bits(monkeypatch, dtype, alternative):
    first = np.array([4, 2, 8, 2, 1, 3, 7, 3], dtype=dtype)[::-1]
    second = np.array([1, 9, 5, 2, 3, 6, 4, 4], dtype=np.float64)[::-1]
    cache = {}
    native_math.evaluate_spearman(first, second, rank_keys=('first', 'second'), rank_cache=cache)
    expected = stats.spearmanr(first, second, alternative=alternative)

    class NoRawStack:
        def __getattr__(self, name):
            if name == 'column_stack':
                pytest.fail('a cached pair must not duplicate its raw observation columns')
            return getattr(np, name)

    monkeypatch.setattr(native_math, 'np', NoRawStack())
    actual = native_math.evaluate_spearman(first, second, alternative=alternative,
                                          rank_keys=('first', 'second'), rank_cache=cache)
    assert actual.engine == 'native-average-rank'
    assert np.asarray((actual.statistic, actual.pvalue)).tobytes() == np.asarray(expected).tobytes()


def test_rank_buffers_are_released_before_group_statistics(monkeypatch):
    buffers = []
    rank = statistical_tests._rank_correlations
    welch = statistical_tests._welch_t_test

    def rank_and_watch(*args, **kwargs):
        rows = rank(*args, **kwargs)
        buffers.extend(weakref.ref(value) for value in kwargs['rank_cache'].values())
        return rows

    def group_without_rank_buffers(*args, **kwargs):
        assert buffers and all(value() is None for value in buffers)
        return welch(*args, **kwargs)

    monkeypatch.setattr(statistical_tests, '_rank_correlations', rank_and_watch)
    monkeypatch.setattr(statistical_tests, '_welch_t_test', group_without_rank_buffers)
    results = {key: {'results': []} for key in ('correlations', 'rank_correlations', 't_tests', 'nonparametric', 'anova', 'chi_square', 'fisher_exact')}
    statistical_tests._build_core_rows(results, pd.DataFrame({
        'x': [1., 4., 2., 5., 3., 6., 7., 8.], 'y': [3., 2., 6., 1., 8., 5., 7., 4.],
        'group': ['a', 'b', 'a', 'b', 'a', 'b', 'a', 'b'],
    }), ['x', 'y'], ['group'], ['group'], [], None, None)
    assert len(results['correlations']['results']) == 1
    assert len(results['t_tests']['results']) == 2
