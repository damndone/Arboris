"""Deterministic squared-error CART checks against hand and sklearn oracles."""
from __future__ import annotations

import numpy as np
import pytest

from workbench import native_ridge


STRIDE = 9
FEATURE, THRESHOLD, LEFT, RIGHT, DEPTH, COUNT, MEAN, MSE, GAIN = range(STRIDE)


@pytest.fixture(scope="module")
def native():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise CART regression")
    return native_ridge._loaded()[0]


def fit(native, x, y, *, depth=2, min_leaf=2, checkpoint=None):
    design, target = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    packed = native.fit_cart_regression(design.tobytes(), target.tobytes(), *design.shape, depth, min_leaf, checkpoint)
    assert type(packed) is bytes
    return packed, np.frombuffer(packed, dtype=np.float64).reshape(-1, STRIDE)


def predict(native, x, tree, checkpoint=None):
    design = np.asarray(x, dtype=np.float64)
    packed = native.predict_cart_regression(design.tobytes(), *design.shape, tree, checkpoint)
    assert type(packed) is bytes and len(packed) == 8 * len(design)
    return np.frombuffer(packed, dtype=np.float64)


def tied_fixture():
    column = np.repeat(np.arange(4), 2)
    return np.column_stack([column, column]), np.array([0, 0, 4, 4, 4, 4, 0, 0])


def test_hand_mse_tree_counts_equal_gain_and_duplicate_rows(native):
    x, y = tied_fixture()
    packed, nodes = fit(native, x, y)
    expected = [
        [0, .5, 1, 2, 0, 8, 2, 4, 4 / 3],
        [-1, 0, -1, -1, 1, 2, 0, 0, 0],
        [0, 2.5, 3, 4, 1, 6, 8 / 3, 32 / 9, 32 / 9],
        [-1, 0, -1, -1, 2, 4, 4, 0, 0],
        [-1, 0, -1, -1, 2, 2, 0, 0, 0],
    ]
    np.testing.assert_allclose(nodes, expected, rtol=0, atol=2e-15)
    np.testing.assert_array_equal(predict(native, [[.5, 100], [2.5, -100], [3, 0]], packed), [0., 4., 0.])
    order = [7, 1, 5, 2, 4, 3, 0, 6]
    assert fit(native, x[order], y[order])[0] == packed


def test_squared_error_tree_matches_independent_sklearn(native):
    pytest.importorskip("sklearn")
    from sklearn.metrics import mean_squared_error
    from sklearn.tree import DecisionTreeRegressor

    rng = np.random.default_rng(1973)
    first = np.arange(60)
    train_x = np.column_stack([first, rng.permutation(first), (first + 1) % 5])
    train_y = np.select([first < 14, first < 39, first < 48], [-4, 8, -1], default=5) + rng.normal(0, .125, len(first))
    held_x = np.column_stack([rng.integers(-5, 65, 22) + .5, rng.integers(0, 60, 22), rng.integers(0, 5, 22)])
    held_y = rng.normal(0, 1, len(held_x))
    reference = DecisionTreeRegressor(criterion="squared_error", splitter="best", max_depth=3, min_samples_leaf=3,
                                      random_state=577).fit(train_x, train_y)
    packed, nodes = fit(native, train_x, train_y, depth=3, min_leaf=3)
    branch, ref_branch = nodes[:, FEATURE] >= 0, reference.tree_.children_left >= 0
    np.testing.assert_array_equal(nodes[:, COUNT], reference.tree_.n_node_samples)
    np.testing.assert_array_equal(nodes[branch, FEATURE], reference.tree_.feature[ref_branch])
    np.testing.assert_array_equal(nodes[branch, THRESHOLD], reference.tree_.threshold[ref_branch])
    np.testing.assert_allclose(nodes[:, MEAN], reference.tree_.value[:, 0, 0], atol=4e-15)
    np.testing.assert_allclose(nodes[:, MSE], reference.tree_.impurity, atol=3e-13)
    native_y = predict(native, held_x, packed)
    np.testing.assert_allclose(native_y, reference.predict(held_x), atol=4e-15)
    assert np.mean((held_y - native_y)**2) == pytest.approx(mean_squared_error(held_y, reference.predict(held_x)), abs=1e-13)


@pytest.mark.parametrize("offset", [2.0**52, -(2.0**52)])
def test_large_common_outcome_offset_does_not_distort_split_or_mse(native, offset):
    x, y = tied_fixture()
    packed, nodes = fit(native, x, offset+y)
    _, centered = fit(native, x, y)
    np.testing.assert_array_equal(nodes[:, :MEAN], centered[:, :MEAN])
    np.testing.assert_allclose(nodes[:, MSE:], centered[:, MSE:], rtol=0, atol=2e-15)
    np.testing.assert_array_equal(predict(native, x, packed), offset+y)


def test_mixed_magnitudes_keep_small_descendant_variation(native):
    x = np.arange(8).reshape(-1, 1)
    y = np.array([1e150, 0., 0., 0., 1., 1., 1., 1.])
    packed, nodes = fit(native, x, y, min_leaf=1)
    assert nodes[0, THRESHOLD] == .5
    assert nodes[2, THRESHOLD] == 3.5
    np.testing.assert_array_equal(predict(native, x, packed), y)


def test_distinct_adjacent_outcomes_preserve_a_resolvable_positive_gain(native):
    adjacent = np.nextafter(1., 2.)
    x = [[0.], [0.], [1.], [1.]]
    tree, nodes = fit(native, x, [1., 1., adjacent, adjacent])
    assert nodes[0, MEAN] == 1.
    assert nodes[0, MSE] == nodes[0, GAIN] == 2.0**-106
    np.testing.assert_array_equal(predict(native, x, tree), [1., 1., adjacent, adjacent])


def test_nonconstant_outcome_with_no_improving_split_is_a_leaf(native):
    x = np.repeat(np.arange(3), 2).reshape(-1, 1)
    tree, nodes = fit(native, x, [-1., 1., -5., 5., -2., 2.])
    assert nodes.shape == (1, STRIDE)
    assert nodes[0, MEAN] == 0. and nodes[0, MSE] == 10. and nodes[0, GAIN] == 0.
    np.testing.assert_array_equal(predict(native, x, tree), np.zeros(len(x)))


def test_rescaling_a_near_cancelled_mean_preserves_a_representable_raw_value(native):
    large, small = 2.0**500, 2.0**-573
    x = [[0.], [0.], [0.]]
    tree, nodes = fit(native, x, [large, small, -large], min_leaf=1)
    assert nodes[0, MEAN] == small/3.
    np.testing.assert_array_equal(predict(native, x, tree), np.full(3, small/3.))


@pytest.mark.parametrize("kind", ["constant_response", "constant_predictors", "minimum_leaf"])
def test_valid_unsplit_tree_reports_the_training_mean(native, kind):
    x, y = tied_fixture()
    if kind == "constant_response":
        y = np.full_like(y, np.finfo(np.float64).max, dtype=np.float64)
    if kind == "constant_predictors":
        x = np.ones_like(x)
    packed, nodes = fit(native, x, y, min_leaf=5 if kind == "minimum_leaf" else 2)
    expected = float(y[0]) if kind == "constant_response" else 2.
    assert nodes.shape == (1, STRIDE)
    assert nodes[0, FEATURE] == -1
    assert nodes[0, MEAN] == expected and nodes[0, GAIN] == 0.
    assert nodes[0, MSE] == (0. if kind == "constant_response" else 4.)
    np.testing.assert_array_equal(predict(native, x, packed), np.full(len(x), expected))


def test_raw_threshold_handles_extremes_and_adjacent_values(native):
    largest = np.finfo(np.float64).max
    for low, high, threshold in [(-largest, largest, 0.), (1., np.nextafter(1., 2.), 1.)]:
        x = [[low], [low], [high], [high]]
        tree, nodes = fit(native, x, [0., 0., 4., 4.])
        assert nodes[0, THRESHOLD] == threshold
        np.testing.assert_array_equal(predict(native, x, tree), [0., 0., 4., 4.])


def test_prediction_does_not_change_fit_and_depth_is_fixed(native):
    x, y = tied_fixture()
    tree, nodes = fit(native, x, y, depth=1)
    assert nodes[:, DEPTH].max() == 1
    assert nodes[0, COUNT] == 8
    np.testing.assert_array_equal(predict(native, [[0., 3.], [2., 0.]], tree), [0., 8./3.])
    np.testing.assert_array_equal(predict(native, [[0., 1e12], [20., 7.]], tree), [0., 8./3.])
    assert fit(native, x, y, depth=1)[0] == tree


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_training_and_scoring_inputs_fail_closed(native, bad):
    x, y = tied_fixture()
    bad_x, bad_y = x.astype(float), y.astype(float)
    bad_x[0, 1], bad_y[-1] = bad, bad
    with pytest.raises(ValueError, match="CART_REGRESSION_INVALID_DATA"):
        fit(native, bad_x, y)
    with pytest.raises(ValueError, match="CART_REGRESSION_INVALID_DATA"):
        fit(native, x, bad_y)
    packed, _ = fit(native, x, y)
    with pytest.raises(ValueError, match="CART_REGRESSION_INVALID_DATA"):
        predict(native, bad_x, packed)


@pytest.mark.parametrize("magnitude", [1e-200, 1e200])
def test_unrepresentable_positive_raw_mse_is_rejected(native, magnitude):
    with pytest.raises(ValueError, match="CART_REGRESSION_NUMERICAL_RANGE"):
        fit(native, [[0.], [0.], [1.], [1.]], [0., 0., magnitude, magnitude])


def test_representable_subnormal_mse_is_retained(native):
    tiny = 2.0**(-535)
    x = [[0.], [0.], [1.], [1.]]
    tree, nodes = fit(native, x, [0., 0., tiny, tiny])
    assert nodes[0, MSE] == nodes[0, GAIN] == 2.0**(-1072)
    np.testing.assert_array_equal(predict(native, x, tree), [0., 0., tiny, tiny])


def test_invalid_shapes_and_work_budgets_reject_before_allocating(native):
    fit_method = native.fit_cart_regression
    with pytest.raises(ValueError, match="CART_REGRESSION_INVALID_DATA"):
        fit_method(b"", b"", 4, 1, 2, 1)
    for rows, cols, depth, leaf in [(14_000, 64, 10, 1), (4, 65, 1, 2), (4, 2, 11, 2), (100_001, 1, 1, 1)]:
        with pytest.raises(ValueError, match="CART_REGRESSION_WORK_LIMIT"):
            fit_method(b"", b"", rows, cols, depth, leaf)
    with pytest.raises(ValueError, match="CART_REGRESSION_INVALID_DATA"):
        fit_method(b"", b"", 4, 2, 1, 5)


@pytest.mark.parametrize("column,value", [
    (LEFT, 0), (RIGHT, 3), (COUNT, 7), (DEPTH, 1), (MEAN, 2.5), (MSE, -1), (GAIN, .1), (THRESHOLD, np.nan),
])
def test_forged_or_inconsistent_tree_cannot_be_traversed(native, column, value):
    x, y = tied_fixture()
    _, table = fit(native, x, y)
    corrupt = table.copy()
    corrupt[0, column] = value
    with pytest.raises(ValueError, match="CART_REGRESSION_INVALID_TREE"):
        predict(native, x, corrupt.tobytes())


def test_cancellation_exception_survives_training_and_scoring(native):
    class Stop(Exception):
        pass

    x, y = tied_fixture()
    tree, _ = fit(native, x, y)
    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise Stop("cart regression cancelled")

    with pytest.raises(Stop, match="cart regression cancelled"):
        fit(native, x, y, checkpoint=stop)
    calls = 0
    with pytest.raises(Stop, match="cart regression cancelled"):
        predict(native, x, tree, checkpoint=stop)
