"""Independent bootstrap, squared-error trees, and aggregation checks."""
from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from workbench import native_ridge


HEADER = 8
STRIDE = 9
FEATURE, CUT, LEFT, RIGHT, LEVEL, COUNT, MEAN, MSE, GAIN = range(STRIDE)
_MASK = (1 << 64) - 1


@pytest.fixture(scope="module")
def native():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise random forest")
    return native_ridge._loaded()[0]


def numbers(seed):
    while True:
        seed = (seed + 0x9E3779B97F4A7C15) & _MASK
        word = seed
        for shift, multiplier in [(30, 0xBF58476D1CE4E5B9), (27, 0x94D049BB133111EB)]:
            word = ((word ^ (word >> shift)) * multiplier) & _MASK
        yield word ^ (word >> 31)


def draw(words, limit):
    low_cutoff = (1 << 64) % limit
    return next(word % limit for word in words if word >= low_cutoff)


def streams(rows, trees, seed):
    stream = numbers(seed)
    for _ in range(trees):
        draws, features = numbers(next(stream)), numbers(next(stream))
        yield [draw(draws, rows) for _ in range(rows)], features


def fit(native, x, y, *, trees=5, depth=3, leaf=2, features=None, seed=731, checkpoint=None):
    design = np.asarray(x, dtype=np.float64)
    outcome = np.asarray(y, dtype=np.float64)
    m = design.shape[1] if features is None else features
    return native.fit_random_forest_regression(
        design.tobytes(), outcome.tobytes(), *design.shape, trees, depth, leaf, m, seed, checkpoint,
    )


def decode(packed):
    assert type(packed) is bytes
    values = np.frombuffer(packed, dtype=np.float64)
    header = values[:HEADER]
    trees = int(header[0])
    counts = values[HEADER:HEADER+trees].astype(int)
    nodes = values[HEADER+trees:].reshape(-1, STRIDE)
    assert counts.sum() == len(nodes)
    return header, np.split(nodes, np.cumsum(counts)[:-1])


def predict(native, x, forest, checkpoint=None):
    x = np.asarray(x, dtype=np.float64)
    packed = native.predict_random_forest_regression(x.tobytes(), *x.shape, forest, checkpoint)
    assert type(packed) is bytes and len(packed) == len(x)*8
    return np.frombuffer(packed, dtype=np.float64)


def test_hand_seeded_leaf_only_forest_uses_bootstrap_multiplicity_and_mean(native):
    x, y = np.zeros((4,1)), np.array([1.,3.,6.,8.])
    forest = fit(native, x, y, trees=3, depth=1, leaf=3, seed=1)
    header, nodes = decode(forest)
    np.testing.assert_array_equal(header, [3,4,1,3,1,1,1,4.5])
    assert list(index for index, _ in streams(4,3,1)) == [[2,2,0,1],[2,0,2,3],[0,2,1,2]]
    assert [tree[0,COUNT] for tree in nodes] == [4.,4.,4.]
    assert [tree[0,MEAN] for tree in nodes] == [4.,5.25,4.]
    assert [tree[0,FEATURE] for tree in nodes] == [-1.,-1.,-1.]
    np.testing.assert_array_equal(predict(native, [[-10.],[5.]], forest), [53./12.,53./12.])


def test_native_receipt_keeps_unresampled_training_mean_as_baseline(native):
    x, y = np.zeros((4,1)), np.array([1.,3.,6.,8.])
    forest = fit(native, x, y, trees=3, depth=1, leaf=3, seed=1)
    assert np.frombuffer(forest, dtype=np.float64)[7] == 4.5


def test_each_all_feature_tree_matches_sklearn_on_independent_bootstrap(native):
    pytest.importorskip("sklearn")
    from sklearn.tree import DecisionTreeRegressor

    train = np.arange(40).reshape(-1,1)
    y = 0.03 * train[:,0]**2 + np.sin(train[:,0] / 4.)
    holdout = np.array([[-1.],[4.5],[12.5],[22.75],[33.],[40.]])
    forest = fit(native, train, y, trees=7, depth=3, leaf=4, seed=20261105)
    header, fitted = decode(forest)
    reference_predictions = []
    for (sample, _), tree in zip(streams(len(train),7,20261105), fitted, strict=True):
        reference = DecisionTreeRegressor(criterion="squared_error", max_depth=3, min_samples_leaf=4,
                                          random_state=625).fit(train[sample], y[sample])
        branch = tree[:,FEATURE] >= 0
        ref_branch = reference.tree_.children_left >= 0
        np.testing.assert_array_equal(tree[branch,CUT], reference.tree_.threshold[ref_branch])
        np.testing.assert_array_equal(tree[:,COUNT], reference.tree_.n_node_samples)
        np.testing.assert_allclose(tree[:,MEAN], reference.tree_.value[:,0,0], rtol=0, atol=2e-14)
        membership = reference.decision_path(train[sample]).tocsc()
        exact_mse = []
        for node in range(len(tree)):
            members = membership[:,node].nonzero()[0]
            values = [Fraction(float(y[sample[row]])) for row in members]
            mean = sum(values)/len(values)
            exact_mse.append(float(sum((value-mean)**2 for value in values)/len(values)))
        np.testing.assert_array_max_ulp(tree[:,MSE], exact_mse, maxulp=2)
        reference_predictions.append(reference.predict(holdout))
    assert header[4] == train.shape[1]
    np.testing.assert_allclose(predict(native, holdout, forest), np.mean(reference_predictions,axis=0), rtol=0, atol=2e-14)


def fraction_tree(x, outcome, rows, rng, *, depth, leaf, m):
    y = [Fraction(float(value)) for value in outcome]
    table = []

    def stats(sample):
        mean = sum(y[i] for i in sample)/len(sample)
        return mean, sum((y[i]-mean)**2 for i in sample)/len(sample)

    def grow(sample, level):
        mean, loss = stats(sample)
        node = len(table)
        table.append([-1.,0.,-1.,-1.,level,len(sample),float(mean),float(loss),0.])
        if level == depth or len(sample) < 2*leaf or loss == 0:
            return node
        candidates = list(range(x.shape[1]))
        if m < len(candidates):
            for i in range(m):
                j = i + draw(rng, len(candidates)-i)
                candidates[i], candidates[j] = candidates[j], candidates[i]
        best = None
        for feature in sorted(candidates[:m]):
            thresholds = sorted(set(x[i,feature] for i in sample))
            for low, high in zip(thresholds, thresholds[1:]):
                left = [i for i in sample if x[i,feature] <= low]
                right = [i for i in sample if x[i,feature] >= high]
                if min(len(left),len(right)) < leaf:
                    continue
                child_loss = (len(left)*stats(left)[1]+len(right)*stats(right)[1])/len(sample)
                improvement = loss - child_loss
                if improvement > 0 and (best is None or improvement > best[0]):
                    best = improvement, feature, (low+high)/2, left, right
        if best is not None:
            gain, feature, cut, left, right = best
            table[node][0:4] = [feature, cut, grow(left,level+1), grow(right,level+1)]
            table[node][GAIN] = float(gain)
        return node

    grow(rows, 0)
    return np.asarray(table)


def one_prediction(tree, row):
    node = tree[0]
    while node[FEATURE] >= 0:
        node = tree[int(node[LEFT if row[int(node[FEATURE])] <= node[CUT] else RIGHT])]
    return node[MEAN]


def test_per_node_feature_subsampling_matches_independent_exact_tree_search(native):
    rng = np.random.default_rng(540)
    x = rng.integers(-8, 9, size=(28,4))
    y = 3*x[:,0] - 4*x[:,1] + x[:,2]**2 - 2*x[:,3]
    held = rng.integers(-10,11,size=(12,4))
    forest = fit(native, x, y, trees=6, depth=3, leaf=3, features=2, seed=818)
    header, trees = decode(forest)
    expected = [fraction_tree(x, y, sample, feature_rng, depth=3, leaf=3, m=2)
                for sample, feature_rng in streams(len(x), 6, 818)]
    assert header[4] == 2
    for fitted, reference in zip(trees, expected, strict=True):
        np.testing.assert_array_equal(fitted[:,:MEAN], reference[:,:MEAN])
        np.testing.assert_array_max_ulp(fitted[:,MEAN:GAIN], reference[:,MEAN:GAIN], maxulp=2)
        np.testing.assert_array_max_ulp(fitted[:,GAIN], reference[:,GAIN], maxulp=4)
    np.testing.assert_allclose(predict(native, held, forest), [np.mean([one_prediction(tree,row) for tree in expected])
                                                               for row in held], rtol=0, atol=5e-14)


def test_seed_and_tree_prefix_are_deterministic_and_holdout_is_not_a_fit_input(native):
    rng = np.random.default_rng(120)
    x, y = rng.normal(size=(30,3)), rng.normal(size=30)
    forest = fit(native, x, y, seed=4294967295, features=2)
    assert forest == fit(native, x, y, seed=4294967295, features=2)
    _, trees = decode(forest)
    _, longer = decode(fit(native, x, y, seed=4294967295, trees=6, features=2))
    assert all(a.tobytes() == b.tobytes() for a,b in zip(trees,longer[:5],strict=True))
    _, changed = decode(fit(native, x, y, seed=4294967294, features=2))
    assert any(a.tobytes() != b.tobytes() for a,b in zip(trees,changed,strict=True))
    predict(native, x*1e8, forest)
    assert forest == fit(native, x, y, seed=4294967295, features=2)
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_DATA"):
        native.fit_random_forest_regression(np.r_[x,x[:1]].tobytes(), y.tobytes(), 30,3,5,3,2,2,0)


@pytest.mark.parametrize("level", [np.finfo(float).max, np.nextafter(0.,1.), -np.finfo(float).max])
def test_constant_extreme_leaf_means_are_aggregated_without_overflow_or_underflow(native, level):
    x = np.arange(8).reshape(-1,1)
    forest = fit(native, x, np.full(8,level), trees=7)
    np.testing.assert_array_equal(predict(native,x,forest),np.full(8,level))


@pytest.mark.parametrize("options", [{"seed":-1},{"seed":2**32},{"seed":True},{"features":0},{"features":2},
                                     {"trees":0},{"leaf":9}])
def test_invalid_forest_options_fail_closed(native, options):
    x = np.arange(8).reshape(-1,1)
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_OPTIONS"):
        fit(native,x,x[:,0],**options)


def test_caps_for_trees_depth_work_and_actual_total_nodes(native):
    f = native.fit_random_forest_regression
    for rows, columns, trees, depth, max_features in [(16,3,33,2,2),(16,3,3,11,2),(15_000,64,32,8,10)]:
        with pytest.raises(ValueError, match="RANDOM_FOREST_WORK_LIMIT"):
            f(b"",b"",rows,columns,trees,depth,1,max_features,0)
    x = np.arange(512).reshape(-1,1)
    with pytest.raises(ValueError, match="RANDOM_FOREST_WORK_LIMIT"):
        fit(native,x,x[:,0],trees=32,depth=10,leaf=1,seed=777)


def test_forest_refuses_a_different_predictor_width_even_if_all_trees_are_leaves(native):
    x = np.zeros((8,2))
    forest = fit(native, x, np.ones(8), features=1)
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_TREE"):
        predict(native, np.zeros((8,1)), forest)


@pytest.mark.parametrize("index,replacement", [(0,0.),(1,2.),(2,1.5),(4,2.),(5,2**32),(6,2.),(7,np.nan),
                                             (HEADER,99.),(HEADER+5+COUNT,1.)])
def test_malformed_forest_headers_and_tree_counts_are_refused(native, index, replacement):
    x = np.arange(12).reshape(-1,1)
    forest = fit(native,x,x[:,0])
    values = np.frombuffer(forest,dtype=np.float64).copy()
    values[index] = replacement
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_TREE"):
        predict(native,x,values.tobytes())


def test_nonfinite_data_and_cancellation_do_not_return_partial_forest_or_prediction(native):
    class Stop(Exception):
        pass

    x = np.arange(20,dtype=float).reshape(-1,1)
    y = x[:,0].copy()
    forest = fit(native,x,y)
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_DATA"):
        fit(native,np.where(x > 18,np.nan,x),y)
    y[-1] = np.inf
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_DATA"):
        fit(native,x,y)
    with pytest.raises(ValueError, match="RANDOM_FOREST_INVALID_DATA"):
        predict(native,[[float("inf")]],forest)

    def cancellation(after):
        calls = 0

        def poll():
            nonlocal calls
            calls += 1
            if calls >= after:
                raise Stop("stop forest")
        return poll

    with pytest.raises(Stop,match="stop forest"):
        fit(native,x,x[:,0],checkpoint=cancellation(8))
    with pytest.raises(Stop,match="stop forest"):
        predict(native,x,forest,checkpoint=cancellation(4))
