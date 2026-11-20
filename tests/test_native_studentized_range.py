"""Tukey p-values in C++ and one critical value per (k, df, alpha), with SciPy's exact bits."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import _stats, studentized_range
from statsmodels.sandbox.stats import multicomp
from statsmodels.stats.multicomp import pairwise_tukeyhsd

from workbench import native_studentized_range
from workbench.statistical_test_kernels import statsmodels_pairwise_tukey


def _sample(seed: int, groups: int = 3, per_group: int = 40):
    rng = np.random.default_rng(seed)
    values = rng.normal(size=groups * per_group) + np.repeat(np.arange(groups) * 0.3, per_group)
    labels = np.repeat(np.asarray([f"g{i}" for i in range(groups)]), per_group)
    return values, labels


def test_columns_with_the_same_shape_share_one_critical_value():
    statsmodels_pairwise_tukey(*_sample(1))
    before = multicomp.get_tukeyQcrit2.cache_info()
    statsmodels_pairwise_tukey(*_sample(2))
    after = multicomp.get_tukeyQcrit2.cache_info()
    assert after.misses == before.misses
    assert after.hits == before.hits + 1


def test_memoized_critical_value_is_the_exact_scipy_value():
    statsmodels_pairwise_tukey(*_sample(3, groups=4, per_group=25))
    for k, df in ((4, 96.0), (3, 117.0), (7, 40.0)):
        assert multicomp.get_tukeyQcrit2(k, df, alpha=0.05) == studentized_range.ppf(0.95, k, df)


def test_memo_leaves_every_tukey_result_bit_identical():
    statsmodels_pairwise_tukey(*_sample(4))
    memoized = multicomp.get_tukeyQcrit2
    for seed, groups in ((5, 3), (6, 4), (5, 3), (7, 6)):
        values, labels = _sample(seed, groups=groups, per_group=30)
        with_memo = pairwise_tukeyhsd(values, labels)
        multicomp.get_tukeyQcrit2 = memoized.__wrapped__
        try:
            without_memo = pairwise_tukeyhsd(values, labels)
        finally:
            multicomp.get_tukeyQcrit2 = memoized
        assert with_memo.q_crit == without_memo.q_crit
        for name in ("meandiffs", "pvalues", "confint", "std_pairs"):
            assert np.asarray(getattr(with_memo, name)).tobytes() == np.asarray(getattr(without_memo, name)).tobytes()
        assert with_memo.reject.tolist() == without_memo.reject.tolist()


def _built():
    module = native_studentized_range._native()
    if module is None:
        pytest.skip("native studentized range is not built")
    return module


@pytest.mark.parametrize(("k", "df"), [(3, 100.0), (4, 737.0), (10, 737.0), (2, 30.0), (6, 12.0), (5, 3.0), (20, 2000.0)])
def test_native_p_values_equal_scipy_bit_for_bit(k, df):
    _built()
    q = np.r_[np.random.default_rng(int(k * df)).uniform(.01, 8, 24), 12.0, 40.0, 1e-3]
    native = native_studentized_range.tukey_pvalue(k, df, q)
    assert native.tobytes() == studentized_range.sf(q, k, df).tobytes()


@pytest.mark.parametrize("q", [np.array([0.0, 1.0]), np.array([np.nan, 1.0]), np.array([np.inf, 1.0]), 1.5])
def test_values_the_native_path_does_not_take_use_the_reference(q):
    expected = studentized_range.sf(q, 3, 50.0)
    assert np.array_equal(native_studentized_range.tukey_pvalue(3, 50.0, q), expected, equal_nan=True)


def test_a_zero_range_is_exactly_scipys_value():
    _built()
    q = np.array([0.0, 1.0, 0.0, 2.5])
    assert native_studentized_range.tukey_pvalue(3, 50.0, q).tobytes() == studentized_range.sf(q, 3, 50.0).tobytes()
    q = np.zeros(2)
    assert native_studentized_range.tukey_pvalue(3, 50.0, q).tobytes() == studentized_range.sf(q, 3, 50.0).tobytes()


def test_large_df_uses_the_reference_asymptotic_form():
    q = np.array([1.0, 3.0])
    assert native_studentized_range.tukey_pvalue(3, 200000.0, q).tobytes() == studentized_range.sf(q, 3, 200000.0).tobytes()


def test_thread_count_does_not_change_the_result():
    module = _built()
    q = np.random.default_rng(9).uniform(.1, 7, 40)
    logconst = _stats._studentized_range_cdf_logconst(5.0, 60.0)
    capsule = _stats.__pyx_capi__["_studentized_range_cdf"]
    assert module.cdf_many(capsule, q.tobytes(), 5.0, 60.0, logconst, 1) == module.cdf_many(capsule, q.tobytes(), 5.0, 60.0, logconst, 8)


def test_absent_extension_selects_the_reference(monkeypatch):
    monkeypatch.setattr(native_studentized_range, "_native", lambda: None)
    q = np.array([1.0, 3.0])
    assert native_studentized_range.tukey_pvalue(3, 50.0, q).tobytes() == studentized_range.sf(q, 3, 50.0).tobytes()


def test_extension_that_disagrees_stands_aside():
    class Wrong:
        ABI_VERSION = 1

        @staticmethod
        def cdf_many(_capsule, q, *_rest):
            return bytes(len(q))

    assert native_studentized_range._agrees_with_reference(Wrong) is False
