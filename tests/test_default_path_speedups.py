"""The 2026-11-03 default-path speedups against the code they replace, bit for bit.

Each speedup has a reference mode that restores the previous computation: Python's builtin
sum instead of the Rust kernel, every Spearman pair ranked on its own, Kendall computed inline,
Welch groups boxed into lists, percentiles from a fresh Python sort. Results are compared as
the bytes of every float, on at least 100,000 random rows.
"""
from __future__ import annotations

from concurrent.futures import Future
import math
import threading

import numpy as np
import pandas as pd
import pytest

from workbench import native_kendall, native_kernels, native_math, statistical_exploration_compute as exploration
from workbench import statistical_test_kernels, statistical_test_pairs, statistical_tests
from workbench.statistical_exploration import ExplorationSpec, execute_exploration

needs_kernels = pytest.mark.skipif(native_kernels._library() is None,
                                   reason='native/kernels/build.py has not been run')
needs_spearman = pytest.mark.skipif(native_math._load_native() is None,
                                    reason='native/spearman_ranks/build.py has not been run')


def bits(value):
    """Every float as its exact bytes, recursively; other values as they are."""
    if isinstance(value, (float, np.floating)):
        return ('float', np.float64(value).tobytes())
    if isinstance(value, dict):
        return {key: bits(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [bits(item) for item in value]
    if isinstance(value, np.ndarray):
        return ('array', value.dtype.str, value.tobytes())
    return value


def _float_columns(rng, n):
    """Distributions that stress rounding: wide exponents, cancellation, ties, signed zeros."""
    return {
        'normal': rng.normal(size=n),
        'wide': rng.normal(size=n) * 10.0 ** rng.integers(-300, 300, n),
        'cancelling': np.concatenate([rng.normal(size=n // 2) * 1e16, -rng.normal(size=n - n // 2) * 1e16]),
        'rounded': np.round(rng.normal(40, 6, n), 1),
        'zeros': rng.choice([-0.0, 0.0, 1.0, -1.0, 2.5], n),
        'cauchy': rng.standard_cauchy(n),
        'integers': rng.integers(-2**53, 2**53, n).astype(float),
    }


@needs_kernels
@pytest.mark.parametrize('size', [1, 2, 3, 8, 129, 1001, 100_000, 250_000])
def test_python_sum_kernel_equals_builtin_sum(size):
    rng = np.random.default_rng(size)
    for name, values in _float_columns(rng, size).items():
        assert bits(native_kernels.python_sum(values)) == bits(sum(map(float, values))), name


@needs_kernels
def test_python_sum_kernel_keeps_special_values():
    for values in ([-0.0], [-0.0, -0.0], [0.0, -0.0], [1e308, 1e308, -1e308], [np.inf, -np.inf],
                   [np.nan, 1.0], [5e-324, -5e-324, 5e-324], [1.0, 1e100, 1.0, -1e100]):
        array = np.array(values)
        assert bits(native_kernels.python_sum(array)) == bits(sum(map(float, array))), values


def test_python_sum_refuses_what_it_does_not_reproduce():
    assert native_kernels.python_sum(np.array([], dtype=float)) is None
    assert native_kernels.python_sum(np.array([1, 2, 3])) is None
    assert native_kernels.python_sum(np.array([1.0, 2.0]).astype('>f8')) is None
    assert native_kernels.python_sum([1.0, 2.0]) is None


@needs_kernels
def test_group_summary_total_is_the_same_with_and_without_the_kernel(monkeypatch):
    rng = np.random.default_rng(3)
    arrays = list(_float_columns(rng, 120_000).values())
    native = [statistical_test_kernels._GroupSummary(array).total for array in arrays]
    monkeypatch.setattr(native_kernels, 'python_sum', lambda values: None)
    assert bits(native) == bits([statistical_test_kernels._GroupSummary(array).total for array in arrays])


def _reference_percentile(series, percentile):
    """_stata_percentile before 2026-11-03: a Python sort per call."""
    values = sorted(float(value) for value in series.dropna().tolist())
    if not values:
        return None
    if percentile <= 0:
        return values[0]
    if percentile >= 100:
        return values[-1]
    position = len(values) * float(percentile) / 100.0
    if math.isclose(position, round(position), rel_tol=0.0, abs_tol=1e-12):
        index = int(round(position))
        return (values[index - 1] + values[index]) / 2.0
    return values[math.ceil(position) - 1]


PERCENTILES = (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100, 12.5, 33.3)


def _percentile_series(rng, n):
    columns = {name: pd.Series(values) for name, values in _float_columns(rng, n).items()}
    columns['with_nan'] = pd.Series(np.where(rng.random(n) < .1, np.nan, rng.normal(size=n)))
    columns['int64'] = pd.Series(rng.integers(-2**62, 2**62, n))
    columns['uint64'] = pd.Series(rng.integers(0, 2**63, n, dtype=np.uint64) * np.uint64(2))
    columns['bool'] = pd.Series(rng.random(n) < .3)
    columns['nullable_int'] = pd.Series(rng.integers(0, 50, n), dtype='Int64').mask(rng.random(n) < .05)
    columns['nullable_float'] = pd.Series(rng.normal(size=n), dtype='Float64').mask(rng.random(n) < .05)
    columns['float32'] = pd.Series(rng.normal(size=n).astype(np.float32))
    return columns


@pytest.mark.parametrize('size', [1, 2, 3, 4, 7, 100, 100_000])
def test_percentiles_equal_a_fresh_python_sort(size):
    rng = np.random.default_rng(size + 11)
    for name, series in _percentile_series(rng, size).items():
        ordered = exploration._sorted_floats(series)
        for percentile in PERCENTILES:
            expected = _reference_percentile(series, percentile)
            assert bits(exploration._stata_percentile(series, percentile)) == bits(expected), (name, percentile)
            assert bits(exploration._percentile_of_sorted(ordered, percentile)) == bits(expected), (name, percentile)


def test_negative_and_positive_zero_keep_their_input_order():
    for values in ([0.0, -0.0, -0.0, 0.0], [-0.0, 0.0], [0.0, -0.0], [1.0, -0.0, 0.0, -1.0]):
        series = pd.Series(values)
        assert bits(list(exploration._sorted_floats(series))) == bits(sorted(values))
        for percentile in PERCENTILES:
            assert bits(exploration._stata_percentile(series, percentile)) == bits(_reference_percentile(series, percentile))


def test_summarize_detail_is_identical_to_the_per_percentile_sort(monkeypatch):
    rng = np.random.default_rng(5)
    frame = pd.DataFrame({name: series for name, series in _percentile_series(rng, 100_000).items()
                          if name not in {'bool'}})
    spec = ExplorationSpec('summarize_detail', tuple(frame.columns))
    fast = execute_exploration(frame, spec)
    monkeypatch.setattr(exploration, '_sorted_floats',
                        lambda series: sorted(float(value) for value in series.dropna().tolist()))
    monkeypatch.setattr(exploration, '_percentile_of_sorted',
                        lambda values, percentile: _reference_percentile(pd.Series(values, dtype=float), percentile))
    assert bits(fast) == bits(execute_exploration(frame, spec))


def test_summarize_detail_sorts_each_column_once(monkeypatch):
    """Regression: 9 percentiles of 3 columns were 27 full Python sorts of the column."""
    calls = []
    original = exploration._sorted_floats
    monkeypatch.setattr(exploration, '_sorted_floats', lambda series: calls.append(series.name) or original(series))
    frame = pd.DataFrame({'a': np.arange(50.), 'b': np.arange(50) % 7, 'c': np.linspace(0, 1, 50)})
    execute_exploration(frame, ExplorationSpec('summarize_detail', ('a', 'b', 'c')))
    assert sorted(calls) == ['a', 'b', 'c']


class _InlineExecutor:
    """The reference: each Kendall count computed where it is submitted, in order."""

    def __init__(self, *args, **kwargs):
        pass

    def submit(self, function, *args):
        future = Future()
        future.set_result(function(*args))
        return future

    def shutdown(self, **kwargs):
        pass


def _reference_mode(monkeypatch):
    monkeypatch.setattr(native_kernels, 'python_sum', lambda values: None)
    monkeypatch.setattr(native_math, '_pair_ranks',
                        lambda a, b, keys, cache, check_cancel: native_math.average_ranks(
                            np.column_stack((a, b)), check_cancel=check_cancel))
    monkeypatch.setattr(statistical_tests, 'ThreadPoolExecutor', _InlineExecutor)
    monkeypatch.setattr(statistical_test_pairs, '_welch_input', lambda values: values.tolist())


def _statistics_frame(n, seed):
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        'wage': np.round(np.exp(1.2 + rng.normal(0, .35, n)), 2),
        'hours': np.round(rng.normal(40, 6, n), 1),
        'spread': rng.normal(size=n) * 10.0 ** rng.integers(-8, 8, n),
        'education': rng.integers(9, 21, n),
        'big': rng.integers(-2**60, 2**60, n),
        'female': rng.binomial(1, .5, n),
        'region': rng.choice(['north', 'south', 'east', 'west'], n),
        'grade': rng.integers(1, 6, n),
    })
    frame['gappy'] = np.where(rng.random(n) < .05, np.nan, rng.normal(size=n))
    frame.loc[rng.random(n) < .02, 'hours'] = -0.0
    return frame


@needs_kernels
@needs_spearman
@pytest.mark.parametrize('rows', [2_000, 120_000])
def test_statistics_stage_is_identical_to_the_reference(rows, monkeypatch):
    """Above 100,000 rows this is the two-lane path, below it the serial one."""
    frame = _statistics_frame(rows, rows)
    columns = list(frame.columns)
    fast = statistical_tests.run_statistical_tests(frame, analysis_columns=columns, dataset_sha256='0' * 64,
                                                   lineage_parent='test')
    _reference_mode(monkeypatch)
    reference = statistical_tests.run_statistical_tests(frame, analysis_columns=columns, dataset_sha256='0' * 64,
                                                        lineage_parent='test')
    assert bits(fast) == bits(reference)
    assert fast['rank_correlations']['results'], 'the frame must exercise rank correlations'


@needs_kernels
def test_welch_on_arrays_equals_welch_on_lists(monkeypatch):
    rng = np.random.default_rng(8)
    n = 150_000
    frame = pd.DataFrame({'float': rng.normal(size=n) * 10.0 ** rng.integers(-5, 5, n),
                          'int': rng.integers(-2**62, 2**62, n), 'small': rng.integers(0, 9, n),
                          'group': rng.binomial(1, .4, n)})
    fast = [statistical_test_pairs._welch_t_test(frame, column, 'group') for column in ('float', 'int', 'small')]
    _reference_mode(monkeypatch)
    assert bits(fast) == bits([statistical_test_pairs._welch_t_test(frame, column, 'group')
                               for column in ('float', 'int', 'small')])


@needs_spearman
def test_each_whole_column_is_ranked_once(monkeypatch):
    """Regression: every pair re-ranked both of its columns, so a column was ranked k - 1 times."""
    widths = []
    original = native_math.average_ranks
    monkeypatch.setattr(native_math, 'average_ranks',
                        lambda matrix, *, check_cancel=None: widths.append(matrix.shape[1]) or original(matrix, check_cancel=check_cancel))
    frame = _statistics_frame(500, 1)[['wage', 'hours', 'spread', 'education', 'gappy']]
    statistical_tests._build_core_results(frame, list(frame.columns), [], [], [])
    # Four whole columns are ranked once each; the pairs with the gappy column drop rows.
    assert sum(widths) == 4 + 2 * 4


def test_kendall_runs_off_the_core_thread(monkeypatch):
    """Regression: the GIL-free Kendall counts ran one after another on the core thread."""
    monkeypatch.setattr(statistical_tests, '_STATISTICS_PARALLEL_MIN_ROWS', 0)
    threads = []
    original = native_kendall.evaluate
    monkeypatch.setattr(native_kendall, 'evaluate',
                        lambda x, y: threads.append(threading.current_thread().name) or original(x, y))
    frame = _statistics_frame(300, 2)[['wage', 'hours', 'education']]
    results = statistical_tests._build_core_results(frame, list(frame.columns), [], [], [])
    assert len(threads) == 3 and all(name.startswith('workbench-statistics-kendall') for name in threads)
    assert all(isinstance(row, dict) for row in results['rank_correlations']['results'])


def test_small_frames_keep_kendall_inline(monkeypatch):
    """Regression: on a 750-row table the thread handoffs made the stage 4.5% slower."""
    threads = []
    original = native_kendall.evaluate
    monkeypatch.setattr(native_kendall, 'evaluate',
                        lambda x, y: threads.append(threading.current_thread()) or original(x, y))
    frame = _statistics_frame(300, 2)[['wage', 'hours', 'education']]
    statistical_tests._build_core_results(frame, list(frame.columns), [], [], [])
    assert threads == [threading.current_thread()] * 3


@pytest.mark.parametrize('threshold', [0, 10**9])
def test_a_kendall_failure_still_reaches_the_caller(threshold, monkeypatch):
    monkeypatch.setattr(statistical_tests, '_STATISTICS_PARALLEL_MIN_ROWS', threshold)

    def broken(x, y):
        raise RuntimeError('native Kendall failed')
    monkeypatch.setattr(native_kendall, 'evaluate', broken)
    frame = _statistics_frame(300, 3)[['wage', 'hours']]
    with pytest.raises(RuntimeError, match='native Kendall failed'):
        statistical_tests._build_core_results(frame, list(frame.columns), [], [], [])


def test_cancellation_while_waiting_for_kendall_propagates(monkeypatch):
    monkeypatch.setattr(statistical_tests, '_STATISTICS_PARALLEL_MIN_ROWS', 0)
    release = threading.Event()
    original = native_kendall.evaluate

    def slow(x, y):
        release.wait(5)
        return original(x, y)

    class Cancelled(Exception):
        pass

    def cancel():
        if threading.current_thread() is threading.main_thread() and slow_started.is_set():
            release.set()
            raise Cancelled
    slow_started = threading.Event()
    monkeypatch.setattr(native_kendall, 'evaluate', lambda x, y: slow_started.set() or slow(x, y))
    frame = _statistics_frame(300, 4)[['wage', 'hours']]
    with pytest.raises(Cancelled):
        statistical_tests._build_core_results(frame, list(frame.columns), [], [], [], check_cancel=cancel)
