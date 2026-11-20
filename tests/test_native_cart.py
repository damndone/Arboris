"""Native classification tree checks against exact counts and scikit-learn."""

from __future__ import annotations

import numpy as np
import pytest

from workbench import native_ridge


STRIDE = 9
FEATURE, THRESHOLD, LEFT, RIGHT, DEPTH, SAMPLES, POSITIVES, PROBABILITY, GAIN = range(STRIDE)


@pytest.fixture(scope="module")
def native():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise native CART")
    return native_ridge._loaded()[0]


def _fit(native, x, y, *, depth=2, min_leaf=2, checkpoint=None):
    design = np.asarray(x, dtype=np.float64)
    labels = np.asarray(y, dtype=np.float64)
    packed = native.fit_cart(design.tobytes(), labels.tobytes(), *design.shape, depth, min_leaf, checkpoint)
    return packed, np.frombuffer(packed, dtype=np.float64).reshape(-1, STRIDE)


def _predict(native, x, tree, checkpoint=None):
    design = np.asarray(x, dtype=np.float64)
    packed = native.predict_cart(design.tobytes(), *design.shape, tree, checkpoint)
    assert len(packed) == len(design) * 8
    return np.frombuffer(packed, dtype=np.float64)


def _probability(positives, rows):
    return (positives + 1) / (rows + 2)


def _tied_fixture():
    column = np.repeat(np.arange(4), 2)
    return np.column_stack([column, column]), np.array([0, 0, 1, 1, 1, 1, 0, 0])


def test_hand_tree_keeps_duplicates_and_breaks_exact_ties_by_feature_then_cut(native):
    x, y = _tied_fixture()
    packed, nodes = _fit(native, x, y)
    expected = [
        [0, .5, 1, 2, 0, 8, 4, _probability(4, 8), 1 / 6],
        [-1, 0, -1, -1, 1, 2, 0, _probability(0, 2), 0],
        [0, 2.5, 3, 4, 1, 6, 4, _probability(4, 6), 4 / 9],
        [-1, 0, -1, -1, 2, 4, 4, _probability(4, 4), 0],
        [-1, 0, -1, -1, 2, 2, 0, _probability(0, 2), 0],
    ]
    np.testing.assert_allclose(nodes, expected, rtol=0, atol=2e-16)
    np.testing.assert_array_equal(_predict(native, [[.5, 100], [2.5, -100], [3, 0]], packed),
                                  [_probability(0, 2), _probability(4, 4), _probability(0, 2)])
    order = [7, 1, 5, 2, 4, 3, 0, 6]
    assert _fit(native, x[order], y[order])[0] == packed


def test_same_gini_partitions_and_leaf_probabilities_as_independent_sklearn(native):
    pytest.importorskip("sklearn")
    from sklearn.tree import DecisionTreeClassifier

    feature = np.arange(16)
    x = np.column_stack([feature, feature % 2])
    y = np.repeat([0, 1, 0], [5, 8, 3])
    holdout = np.array([[3.75, 0], [4.5, 1], [4.75, 0], [12.5, 0], [13, 1], [50, 0]])
    oracle = DecisionTreeClassifier(criterion="gini", splitter="best", max_depth=2, min_samples_leaf=2,
                                    random_state=121).fit(x, y)
    packed, nodes = _fit(native, x, y)
    split = nodes[:, FEATURE] >= 0
    ref_split = oracle.tree_.children_left >= 0
    np.testing.assert_array_equal(nodes[split, FEATURE], oracle.tree_.feature[ref_split])
    np.testing.assert_array_equal(nodes[split, THRESHOLD], oracle.tree_.threshold[ref_split])
    np.testing.assert_array_equal(nodes[:, SAMPLES], oracle.tree_.n_node_samples)
    fitted_leaves = oracle.apply(x)
    expected = [_probability(y[fitted_leaves == leaf].sum(), np.count_nonzero(fitted_leaves == leaf))
                for leaf in oracle.apply(holdout)]
    np.testing.assert_array_equal(_predict(native, holdout, packed), expected)

    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

    actual = np.array([0., 0., 0., 1., 1., 0.])
    probability = _predict(native, holdout, packed)
    logit = np.log(probability) - np.log1p(-probability)
    observed = native_ridge._classification_metrics(actual, logit, int(actual.sum()))
    assert observed == pytest.approx({
        "accuracy": accuracy_score(actual, probability >= .5), "brier_score": brier_score_loss(actual, probability),
        "log_loss": log_loss(actual, probability), "roc_auc": roc_auc_score(actual, probability),
    }, abs=2e-15)


def test_only_training_rows_are_needed_to_fit_and_predictions_do_not_mutate_tree(native):
    x, y = _tied_fixture()
    packed, nodes = _fit(native, x, y)
    held_out = np.array([[0, 9], [1, -9]])
    first = _predict(native, held_out, packed)
    second = _predict(native, -held_out, packed)
    assert np.any(first != second)
    assert _fit(native, x, y)[0] == packed
    assert nodes[0, SAMPLES] == len(x)


@pytest.mark.parametrize("depth,min_leaf", [(1, 2), (10, 5)])
def test_depth_minimum_leaf_and_no_gain_terminate_growth(native, depth, min_leaf):
    x, y = _tied_fixture()
    _, nodes = _fit(native, x, y, depth=depth, min_leaf=min_leaf)
    leaves = nodes[:, FEATURE] == -1
    assert nodes[:, DEPTH].max() <= depth
    assert np.all(nodes[leaves, SAMPLES] >= min_leaf)
    assert len(nodes) == (3 if depth == 1 else 1)
    _, constant = _fit(native, np.ones_like(x), y, depth=10)
    assert constant.shape == (1, STRIDE)
    assert constant[0, FEATURE] == -1
    assert constant[0, PROBABILITY] == .5


def test_split_thresholds_keep_raw_binary64_extremes_and_adjacent_values(native):
    largest = np.finfo(np.float64).max
    for low, high, expected_threshold in [(-largest, largest, 0.0), (1.0, np.nextafter(1., 2.), 1.0)]:
        x = [[low], [low], [high], [high]]
        packed, nodes = _fit(native, x, [0, 0, 1, 1])
        assert nodes[0, THRESHOLD] == expected_threshold
        np.testing.assert_array_equal(_predict(native, x, packed), [.25, .25, .75, .75])


@pytest.mark.parametrize("bad_label", [.5, np.nan, np.inf, 2.0])
def test_native_rejects_invalid_binary_targets(native, bad_label):
    x, y = _tied_fixture()
    bad = y.astype(np.float64)
    bad[-1] = bad_label
    with pytest.raises(ValueError, match="CART_INVALID_LABELS"):
        _fit(native, x, bad)


def test_native_input_and_budget_refusals(native):
    x, y = _tied_fixture()
    with pytest.raises(ValueError, match="CART_TRAIN_SINGLE_CLASS"):
        _fit(native, x, np.zeros_like(y))
    bad = x.astype(np.float64)
    bad[0, 0] = np.inf
    with pytest.raises(ValueError, match="CART_INVALID_DATA"):
        _fit(native, bad, y)
    with pytest.raises(ValueError, match="CART_INVALID_DATA"):
        native.fit_cart(b"", np.asarray(y, dtype=np.float64).tobytes(), 8, 2, 2, 2)
    for rows, cols, depth, leaf in [(14_000, 64, 10, 1), (4, 65, 1, 2), (4, 2, 11, 2)]:
        with pytest.raises(ValueError, match="CART_WORK_LIMIT"):
            native.fit_cart(b"", b"", rows, cols, depth, leaf)
    with pytest.raises(ValueError, match="CART_INVALID_DATA"):
        native.fit_cart(b"", b"", 4, 2, 1, 5)


@pytest.mark.parametrize("column,value", [(LEFT, 0), (RIGHT, 4), (DEPTH, 1), (POSITIVES, 3), (GAIN, 0.0),
                                         (PROBABILITY, .75), (THRESHOLD, np.nan)])
def test_predict_refuses_malformed_or_inconsistent_tree_before_traversing(native, column, value):
    x, y = _tied_fixture()
    _, tree = _fit(native, x, y)
    bad = tree.copy()
    bad[0, column] = value
    with pytest.raises(ValueError, match="CART_INVALID_TREE"):
        _predict(native, x, bad.tobytes())


def test_native_scoring_rejects_nonfinite_unused_columns_and_bad_tree_size(native):
    x, y = _tied_fixture()
    packed, _ = _fit(native, x, y)
    with pytest.raises(ValueError, match="CART_INVALID_DATA"):
        _predict(native, [[0.0, np.inf]], packed)
    with pytest.raises(ValueError, match="CART_INVALID_TREE"):
        _predict(native, [[0.0, 0.0]], packed[:-8])


def test_native_cancel_retains_the_original_exception(native):
    class Stop(Exception):
        pass

    def stop():
        raise Stop("cart cancelled")

    x, y = _tied_fixture()
    packed, _ = _fit(native, x, y)
    with pytest.raises(Stop, match="cart cancelled"):
        _fit(native, x, y, checkpoint=stop)
    with pytest.raises(Stop, match="cart cancelled"):
        _predict(native, x, packed, checkpoint=stop)
