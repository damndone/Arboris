"""The Rust kernels against the NumPy code they replace, bit for bit."""
import ctypes

import numpy as np
import pandas as pd
import pytest

from workbench import native_kernels
from workbench.engine.packs.multivariate.clustering import _kmeans, fit_clustering
from workbench.engine.packs.multivariate.common import MultivariatePackError
from workbench.engine.packs.resampling import run_bootstrap, run_permutation
from workbench.engine.packs.survival_analysis.ph_diagnostics import ph_score_test

pytestmark = pytest.mark.skipif(native_kernels._library() is None,
                                reason='native/kernels/build.py has not been run')


def bits(values):
    return np.asarray(values, dtype=float).tobytes()


SEEDS = [0, 1, 7, 2**31 - 1, 2**31, 2**32 - 1, 2**32, 2**32 + 1, 2**62 + 12345, 2**63 - 1]


@pytest.mark.parametrize('size', [2, 3, 7, 8, 9, 15, 16, 17, 127, 128, 129, 130, 256, 1000, 1001, 4099, 100_000])
@pytest.mark.parametrize('statistic,reduce', [('mean', np.mean), ('median', np.median)])
def test_bootstrap_draws_and_statistics(size, statistic, reduce):
    values = np.random.default_rng(size).normal(size=size) * 10.0 ** np.random.default_rng(size + 1).integers(-8, 8, size)
    expected = [reduce(values[np.random.default_rng(seed).integers(0, size, size=size)]) for seed in SEEDS]
    assert bits(native_kernels.bootstrap_statistics(values, SEEDS, statistic)) == bits(expected)


@pytest.mark.parametrize('size,left', [(2, 1), (9, 4), (17, 8), (130, 1), (130, 129), (1001, 500), (4099, 17), (100_000, 50_000)])
@pytest.mark.parametrize('statistic,reduce', [('difference_in_means', np.mean), ('difference_in_medians', np.median)])
def test_permutation_draws_and_statistics(size, left, statistic, reduce):
    pooled = np.random.default_rng(size).standard_t(3, size=size)
    shuffled = [np.random.default_rng(seed).permutation(pooled) for seed in SEEDS]
    expected = [reduce(item[:left]) - reduce(item[left:]) for item in shuffled]
    assert bits(native_kernels.permutation_statistics(pooled, left, SEEDS, statistic)) == bits(expected)


def test_tied_values_and_thread_counts_do_not_change_results():
    values = np.round(np.random.default_rng(1).normal(size=50_000), 1) + 0.0
    seeds = list(range(100))  # 5M draws: this runs on several threads.
    expected = [np.median(values[np.random.default_rng(s).integers(0, 50_000, size=50_000)]) for s in seeds]
    assert bits(native_kernels.bootstrap_statistics(values, seeds, 'median')) == bits(expected)


def test_negative_zero_selects_the_python_path():
    values = np.array([-0.0, 0.0, 1.0])
    assert native_kernels.bootstrap_statistics(values, [1], 'median') is None
    assert native_kernels.permutation_statistics(values, 1, [1], 'difference_in_medians') is None
    assert native_kernels.bootstrap_statistics(values, [1], 'mean') is not None


def _reference_kmeans(values, n_clusters, random_state, max_iter, tol):
    original = (native_kernels.lloyd_step, native_kernels.min_distances)
    native_kernels.lloyd_step = native_kernels.min_distances = lambda *_: None
    try:
        return _kmeans(values, n_clusters, random_state=random_state, max_iter=max_iter, tol=tol)
    finally:
        native_kernels.lloyd_step, native_kernels.min_distances = original


@pytest.mark.parametrize('rows,width,k', [(40, 1, 2), (500, 2, 3), (2000, 3, 5), (3000, 8, 8), (1500, 9, 4),
                                          (1200, 17, 6), (800, 40, 3), (60_000, 8, 8)])
def test_kmeans_matches_with_and_without_the_kernel(rows, width, k):
    values = np.random.default_rng(rows + width).normal(size=(rows, width))
    native = _kmeans(values, k, random_state=3, max_iter=300, tol=1e-4)
    reference = _reference_kmeans(values, k, 3, 300, 1e-4)
    assert np.array_equal(native[0], reference[0])
    assert bits(native[1]) == bits(reference[1])
    assert native[2:] == reference[2:]


def test_kmeans_with_duplicate_rows_and_an_empty_cluster_matches():
    values = np.vstack([np.zeros((50, 2)), np.ones((50, 2))])
    native = _kmeans(values, 2, random_state=1, max_iter=50, tol=1e-4)
    reference = _reference_kmeans(values, 2, 1, 50, 1e-4)
    assert np.array_equal(native[0], reference[0]) and bits(native[1]) == bits(reference[1])
    centers = np.array([[0.0, 0.0], [5.0, 5.0], [9.0, 9.0]])
    labels, updated = native_kernels.lloyd_step(values, centers)
    distances = np.square(values[:, None, :] - centers[None, :, :]).sum(axis=2)
    assert np.array_equal(labels, np.argmin(distances, axis=1))
    assert bits(updated[2]) == bits(values[int(np.argmax(np.min(distances, axis=1)))])


@pytest.mark.parametrize('method', ['percentile', 'bca'])
def test_the_public_bootstrap_result_is_identical_without_the_kernel(method, monkeypatch):
    values = np.random.default_rng(5).normal(size=300)
    native = run_bootstrap(values, n_resamples=200, seed=9, interval_method=method)
    monkeypatch.setattr(native_kernels, 'bootstrap_statistics', lambda *_: None)
    assert native == run_bootstrap(values, n_resamples=200, seed=9, interval_method=method)


def test_the_public_permutation_result_is_identical_without_the_kernel(monkeypatch):
    rng = np.random.default_rng(6)
    left, right = rng.normal(size=120), rng.normal(.3, size=90)
    native = run_permutation(left, right, n_resamples=200, seed=2)
    monkeypatch.setattr(native_kernels, 'permutation_statistics', lambda *_: None)
    assert native == run_permutation(left, right, n_resamples=200, seed=2)


@pytest.mark.parametrize('rows,width,tied', [(50, 1, False), (800, 2, False), (5000, 3, False), (3000, 7, False),
                                             (2000, 3, True)])
@pytest.mark.parametrize('ties', ['breslow', 'efron'])
def test_ph_score_test_is_identical_without_the_kernel(rows, width, tied, ties, monkeypatch):
    rng = np.random.default_rng(rows + width)
    x = rng.normal(size=(rows, width))
    time = rng.exponential(np.exp(-x[:, 0] * .3)) + .01
    time = np.round(time, 1) + .01 if tied else time
    event = rng.random(rows) < .75
    names = [f'x{j}' for j in range(width)]
    beta = np.full(width, .2)
    native = ph_score_test(time, event, x, beta, names, ties=ties)
    monkeypatch.setattr(native_kernels, 'ph_sweep', lambda *_: None)
    assert native == ph_score_test(time, event, x, beta, names, ties=ties)
    assert native['status'] == 'computed'


def test_a_nonzero_kernel_status_is_an_error():
    with pytest.raises(RuntimeError, match='native kernel failed'):
        native_kernels._checked(1)
    assert ctypes.sizeof(ctypes.c_size_t) == 8


def test_kmeans_above_the_silhouette_bound_is_served_without_a_silhouette():
    frame = pd.DataFrame(np.random.default_rng(1).normal(size=(2500, 3)), columns=list('abc'))
    result = fit_clustering(frame, list('abc'), algorithm='kmeans', standardization='none',
                            selection='fixed', n_clusters=3, random_state=1)
    assert result['result']['silhouette'] is None
    assert result['result']['candidate_metrics'][0]['inertia'] > 0


@pytest.mark.parametrize('options', [dict(algorithm='hierarchical', selection='fixed', n_clusters=3),
                                     dict(algorithm='kmeans', selection='silhouette_candidates',
                                          candidate_ks=[2, 3], random_state=1)])
def test_all_pairs_methods_refuse_above_the_bound_before_allocating(options):
    frame = pd.DataFrame(np.zeros((2001, 2)), columns=list('ab'))
    with pytest.raises(MultivariatePackError, match='bounded at 2000'):
        fit_clustering(frame, list('ab'), standardization='none', **options)
