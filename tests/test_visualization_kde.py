"""The large-sample KDE curve equals scipy's evaluation of the same estimator."""

import numpy as np
from scipy import stats

from workbench.visualization import KDE_DIRECT_LIMIT, _kde_values


def test_distinct_value_evaluation_matches_scipy():
    rng = np.random.default_rng(3)
    for data in (rng.integers(0, 40, 200_000).astype(float), np.round(rng.normal(40, 6, 200_000), 1)):
        kde = stats.gaussian_kde(data)
        xs = np.linspace(data.min(), data.max(), 200)
        np.testing.assert_allclose(_kde_values(kde, data, xs), kde(xs), rtol=1e-10, atol=0)


def test_small_or_mostly_distinct_samples_use_scipy_itself():
    rng = np.random.default_rng(4)
    for data in (rng.normal(size=KDE_DIRECT_LIMIT), rng.normal(size=100_000)):
        kde = stats.gaussian_kde(data)
        xs = np.linspace(data.min(), data.max(), 50)
        assert np.array_equal(_kde_values(kde, data, xs), kde(xs))
