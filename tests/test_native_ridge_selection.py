"""Ridge validation losses against independent QR/SVD and hand cases."""
from __future__ import annotations

import math

import numpy as np
import pytest

from workbench import native_ridge


@pytest.fixture(scope="module")
def native():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise Ridge selection")
    return native_ridge._loaded()[0]


def selection(native, training_x, training_y, validation_x, validation_y, grid, *, magnitude=1., checkpoint=None):
    x = np.asarray(training_x, dtype=np.float64)
    vx = np.asarray(validation_x, dtype=np.float64)
    y, vy = np.asarray(training_y, dtype=np.float64), np.asarray(validation_y, dtype=np.float64)
    alphas = np.asarray(grid, dtype=np.float64)
    packed = native.select_ridge(x.tobytes(), y.tobytes(), vx.tobytes(), vy.tobytes(), len(x), len(vx), x.shape[1],
                                  alphas.tobytes(), magnitude, checkpoint)
    assert type(packed) is bytes and len(packed) == (1+len(alphas))*8
    receipt = np.frombuffer(packed, dtype=np.float64)
    assert np.isfinite(receipt).all()
    assert receipt[0].is_integer() and 0 <= receipt[0] < len(alphas)
    return int(receipt[0]), receipt[1:]


def test_native_chronological_validation_uses_original_response_units(native):
    x = np.tile([-1., 1.], 3).reshape(-1, 1)
    grid = [24., 6., .1, 1.]
    selected, errors = selection(native, x, x[:, 0], x[:2], [-1., 1.], grid, magnitude=2.)
    assert selected == 1
    np.testing.assert_allclose(errors, np.abs(12 / (6 + np.asarray(grid)) - 1), rtol=1e-14, atol=1e-15)


def test_candidate_rmse_matches_independent_sklearn_and_normal_equations(native):
    sklearn = pytest.importorskip("sklearn.linear_model")
    rng = np.random.default_rng(717)
    x = rng.normal(size=(35, 4))
    x[:, 2] = 2 * x[:, 0]
    x[:, 3] = 0
    y = .4 + x @ np.array([.7, -.3, .1, 0]) + rng.normal(scale=.25, size=len(x))
    validation = rng.normal(size=(9, 4))
    validation[:, 2] = 2 * validation[:, 0]
    validation[:, 3] = 0
    actual = validation @ np.array([1., -.1, .05, 0]) + .3
    grid = [.0001, 1., 10., 100.]
    scale = 19.
    winner, errors = selection(native, x, y / scale, validation, actual, grid, magnitude=scale)
    exact_errors = []
    for alpha, actual_error in zip(grid, errors, strict=True):
        reference = sklearn.Ridge(alpha=alpha, fit_intercept=True, solver="svd").fit(x, y)
        centered = x - x.mean(axis=0)
        y_centered = y - y.mean()
        coefficients = np.linalg.solve(centered.T @ centered + alpha * np.eye(x.shape[1]), centered.T @ y_centered)
        prediction = (validation - x.mean(axis=0)) @ coefficients + y.mean()
        np.testing.assert_allclose(reference.predict(validation), prediction, rtol=2e-11, atol=2e-11)
        expected = math.sqrt(float(np.mean((actual - reference.predict(validation)) ** 2)))
        assert actual_error == pytest.approx(expected, rel=1e-12)
        exact_errors.append(expected)
    assert winner == min(range(len(grid)), key=lambda i: exact_errors[i])


def test_equal_losses_choose_largest_alpha_independent_of_grid_order(native):
    x = np.arange(7, dtype=np.float64).reshape(-1, 1)
    for grid in ([1., 20., 3.], [20., 3., 1.]):
        winner, errors = selection(native, x[:4], np.zeros(4), x[4:], [2., 2., 2.], grid)
        assert grid[winner] == 20.
        np.testing.assert_array_equal(errors, [2., 2., 2.])


@pytest.mark.parametrize("grid", [[], [1.], [1., 1.], [1., 0.], [1., -2.], [1., np.inf], [1., np.nan],
                                  list(range(1, 18))])
def test_native_rejects_unbounded_or_invalid_alpha_grid(native, grid):
    x = np.array([[-1.], [1.]])
    with pytest.raises(ValueError, match="RIDGE_SELECTION_INVALID_GRID"):
        selection(native, x, x[:, 0], x, x[:, 0], grid)


def test_native_fails_closed_on_shapes_nonfinite_buffers_and_work(native):
    x = np.array([[-1.], [1.]])
    alphas = np.array([1., 2.]).tobytes()
    with pytest.raises(ValueError, match="RIDGE_SELECTION_WORK_LIMIT"):
        native.select_ridge(b"", b"", b"", b"", 15_000, 2, 80, alphas, 1.)
    with pytest.raises(ValueError, match="RIDGE_SELECTION_INVALID_DATA"):
        native.select_ridge(b"", b"", b"", b"", 2, 2, 1, alphas, 1.)
    with pytest.raises(ValueError, match="RIDGE_SELECTION_INVALID_DATA"):
        selection(native, x, x[:, 0], x, [0., np.nan], [1., 2.])
    with pytest.raises(ValueError, match="RIDGE_SELECTION_INVALID_DATA"):
        selection(native, x, x[:, 0], x * np.inf, [0., 1.], [1., 2.])
    with pytest.raises(ValueError, match="RIDGE_SELECTION_INVALID_DATA"):
        selection(native, x, x[:, 0], x, [0., 1.], [1., 2.], magnitude=0.)


def test_native_rmse_preserves_large_finite_loss_and_rejects_unrepresentable_loss(native):
    x = np.array([[-1.], [1.]])
    large = np.finfo(float).max
    _, errors = selection(native, x, [0., 0.], x, [large, large], [1., 2.])
    np.testing.assert_array_equal(errors, [large, large])
    subnormal = np.nextafter(0., 1.)
    with pytest.raises(ValueError, match="RIDGE_SELECTION_NUMERICAL_RANGE"):
        selection(native, x, [0., 0.], np.zeros((6, 1)), [subnormal, 0., 0., 0., 0., 0.], [1., 2.])
    with pytest.raises(ValueError, match="RIDGE_SELECTION_NUMERICAL_RANGE"):
        selection(native, x, [-1., 1.], [[3.]], [0.], [1., 2.], magnitude=large)


def test_native_checkpoint_exception_escapes_candidate_loop(native):
    class Stop(Exception):
        pass

    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls >= 6:
            raise Stop("stop Ridge validation")

    x = np.arange(32, dtype=np.float64).reshape(-1, 1)
    with pytest.raises(Stop, match="stop Ridge validation"):
        selection(native, x[:24], x[:24, 0], x[24:], x[24:, 0], [1., 2., 3.], checkpoint=cancel)
