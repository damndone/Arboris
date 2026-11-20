"""Exact Gini, bootstrap multiplicity, and independent probability checks."""
from __future__ import annotations

from fractions import Fraction
import math

import numpy as np
import pytest

from tests.test_native_random_forest import draw, streams
from workbench import native_ridge


TAG = 4001.
HEADER = 9
STRIDE = 9
FEATURE, CUT, LEFT, RIGHT, LEVEL, COUNT, POSITIVE, PROBABILITY, GAIN = range(STRIDE)


@pytest.fixture(scope="module")
def native():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise the classification forest")
    return native_ridge._loaded()[0]


def fit(native, x, y, *, trees=5, depth=3, leaf=2, features=None, seed=731, checkpoint=None):
    design, labels = np.asarray(x,dtype=np.float64), np.asarray(y,dtype=np.float64)
    selected = design.shape[1] if features is None else features
    return native.fit_random_forest_classification(
        design.tobytes(),labels.tobytes(),*design.shape,trees,depth,leaf,selected,seed,checkpoint,
    )


def predict(native, x, forest, checkpoint=None):
    design = np.asarray(x,dtype=np.float64)
    packed = native.predict_random_forest_classification(design.tobytes(),*design.shape,forest,checkpoint)
    assert type(packed) is bytes and len(packed) == len(design)*8
    return np.frombuffer(packed,dtype=np.float64)


def decode(forest):
    assert type(forest) is bytes
    packed = np.frombuffer(forest,dtype=np.float64)
    header = packed[:HEADER]
    count = int(header[1])
    meta = packed[HEADER:HEADER+2*count].reshape(count,2).astype(int)
    nodes = packed[HEADER+2*count:].reshape(-1,STRIDE)
    assert len(nodes) == meta[:,0].sum()
    return header, meta[:,1], np.split(nodes,np.cumsum(meta[:,0])[:-1])


def fraction_gini(labels, x, sample, feature_rng, *, depth, leaf, features):
    tables = []

    def impurity(rows):
        positive = sum(int(labels[i]) for i in rows)
        return Fraction(2*positive*(len(rows)-positive),len(rows)**2)

    def add(rows, level):
        n, positive = len(rows), sum(int(labels[i]) for i in rows)
        node = len(tables)
        before = impurity(rows)
        tables.append([-1.,0.,-1.,-1.,level,n,positive,(positive+1)/(n+2),0.])
        if level == depth or n < 2*leaf or before == 0:
            return node
        candidates = list(range(x.shape[1]))
        if features < len(candidates):
            for i in range(features):
                j = i + draw(feature_rng,len(candidates)-i)
                candidates[i],candidates[j] = candidates[j],candidates[i]
        best = None
        for feature in sorted(candidates[:features]):
            values = sorted(set(x[i,feature] for i in rows))
            for low, high in zip(values,values[1:]):
                left = [i for i in rows if x[i,feature] <= low]
                right = [i for i in rows if x[i,feature] >= high]
                if min(len(left),len(right)) < leaf:
                    continue
                gain = before - (len(left)*impurity(left)+len(right)*impurity(right))/n
                if gain > 0 and (best is None or gain > best[0]):
                    best = gain,feature,(low+high)/2,left,right
        if best is not None:
            gain,feature,cut,left,right = best
            tables[node][:4] = [feature,cut,add(left,level+1),add(right,level+1)]
            tables[node][GAIN] = float(gain)
        return node

    add(sample,0)
    return np.asarray(tables)


def tree_probability(tree, point):
    node = tree[0]
    while node[FEATURE] >= 0:
        node = tree[int(node[LEFT if point[int(node[FEATURE])] <= node[CUT] else RIGHT])]
    return float(node[PROBABILITY])


def test_pure_bootstrap_trees_are_kept_and_smoothed_with_observed_duplicate_rate(native):
    x, y = np.zeros((3,1)), np.array([0.,0.,1.])
    forest = fit(native,x,y,trees=5,depth=1,leaf=2,seed=0)
    header, unique, trees = decode(forest)
    np.testing.assert_array_equal(header,[TAG,5,3,1,2,1,0,1,1])
    np.testing.assert_array_equal(unique,[2,2,1,3,1])
    assert (15-int(unique.sum()))/15 == 2/5
    assert [tree[0,POSITIVE] for tree in trees] == [2.,1.,0.,1.,3.]
    assert [tree[0,PROBABILITY] for tree in trees] == [.6,.4,.2,.4,.8]
    np.testing.assert_array_equal(predict(native,[[-9.],[9.]],forest),[12/25,12/25])
    with pytest.raises(ValueError,match="CART_TRAIN_SINGLE_CLASS"):
        native.fit_cart(x.tobytes(),np.zeros(3).tobytes(),3,1,1,1)


def test_all_feature_bootstrap_trees_match_sklearn_and_independent_laplace_counts(native):
    pytest.importorskip("sklearn")
    from sklearn.tree import DecisionTreeClassifier

    x = np.arange(40).reshape(-1,1)
    y = np.repeat([0,1,0,1],[7,13,12,8])
    held = np.array([[2.25],[6.75],[9.],[17.],[22.],[27.],[33.5],[37.]])
    actual = np.array([0.,1.,1.,1.,0.,0.,1.,1.])
    forest = fit(native,x,y,trees=7,depth=3,leaf=3,seed=8166)
    _, unique, fitted = decode(forest)
    probabilities = []
    for ((sample,_), used, tree) in zip(streams(40,7,8166),unique,fitted,strict=True):
        oracle = DecisionTreeClassifier(criterion="gini",max_depth=3,min_samples_leaf=3,random_state=117).fit(x[sample],y[sample])
        branch = tree[:,FEATURE] >= 0
        ref_branch = oracle.tree_.children_left >= 0
        assert used == len(set(sample))
        np.testing.assert_array_equal(tree[branch,CUT],oracle.tree_.threshold[ref_branch])
        np.testing.assert_array_equal(tree[:,COUNT],oracle.tree_.n_node_samples)
        training_leaves = oracle.apply(x[sample])
        probabilities.append([(y[sample][training_leaves == leaf].sum()+1)/(np.count_nonzero(training_leaves == leaf)+2)
                              for leaf in oracle.apply(held)])
    reference = np.array([math.fsum(column)/len(fitted) for column in np.asarray(probabilities).T])
    scores = predict(native,held,forest)
    np.testing.assert_array_equal(scores,reference)

    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
    logit = np.log(scores)-np.log1p(-scores)
    metrics = native_ridge._classification_metrics(actual,logit,int(actual.sum()))
    assert metrics == pytest.approx({"log_loss":log_loss(actual,reference),"brier_score":brier_score_loss(actual,reference),
                                     "accuracy":accuracy_score(actual,reference>=.5),"roc_auc":roc_auc_score(actual,reference)})


def test_feature_subset_gini_search_and_probabilities_match_exact_independent_oracle(native):
    rng = np.random.default_rng(541)
    x = rng.integers(-8,9,size=(30,4))
    y = (3*x[:,0]-4*x[:,1]+x[:,2]**2-2*x[:,3] > 14).astype(int)
    holdout = rng.integers(-10,11,size=(12,4))
    forest = fit(native,x,y,trees=6,depth=3,leaf=3,features=2,seed=813)
    _, unique, actual = decode(forest)
    expected = []
    for (sample, feature_rng), used, fitted in zip(streams(30,6,813),unique,actual,strict=True):
        assert used == len(set(sample))
        oracle = fraction_gini(y,x,sample,feature_rng,depth=3,leaf=3,features=2)
        expected.append(oracle)
        np.testing.assert_array_equal(fitted[:,:GAIN],oracle[:,:GAIN])
        np.testing.assert_array_max_ulp(fitted[:,GAIN],oracle[:,GAIN],maxulp=2)
    reference = [math.fsum(tree_probability(tree,row) for tree in expected)/len(expected) for row in holdout]
    np.testing.assert_array_equal(predict(native,holdout,forest),reference)


def test_seed_and_tree_prefix_are_fixed_and_scoring_does_not_change_the_fit(native):
    rng = np.random.default_rng(433)
    x, y = rng.normal(size=(36,3)), np.arange(36)%2
    fit_one = fit(native,x,y,features=2,seed=2**32-1)
    assert fit(native,x,y,features=2,seed=2**32-1) == fit_one
    _, a_unique, a = decode(fit_one)
    _, b_unique, b = decode(fit(native,x,y,features=2,seed=2**32-1,trees=6))
    np.testing.assert_array_equal(a_unique,b_unique[:5])
    assert all(first.tobytes() == second.tobytes() for first,second in zip(a,b[:5],strict=True))
    assert fit(native,x,y,features=2,seed=2**32-2) != fit_one
    predict(native,x*1e6,fit_one)
    assert fit(native,x,y,features=2,seed=2**32-1) == fit_one
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_DATA"):
        native.fit_random_forest_classification(np.r_[x,x[:1]].tobytes(),y.astype(float).tobytes(),36,3,5,3,2,2,0)


@pytest.mark.parametrize("label",[-1.,.5,2.,np.nan,np.inf])
def test_full_training_labels_are_checked_before_any_bootstrap(native,label):
    x, y = np.arange(8).reshape(-1,1), np.array([0.,1.]*4)
    y[-1] = label
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_LABELS"):
        fit(native,x,y)


def test_single_class_full_training_fails_closed_and_nonfinite_scoring_is_refused(native):
    x, y = np.arange(8).reshape(-1,1), np.array([0.,1.]*4)
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_TRAIN_SINGLE_CLASS"):
        fit(native,x,np.zeros(8))
    forest = fit(native,x,y)
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_DATA"):
        predict(native,[[np.inf]],forest)


@pytest.mark.parametrize("index,replacement",[(0,1.),(1,0.),(7,2.),(8,0.),(HEADER,99.),(HEADER+1,0.),(HEADER+1,9.),
                                               (HEADER+10+PROBABILITY,.1)])
def test_forest_metadata_and_probability_receipt_are_validated(native,index,replacement):
    x, y = np.arange(8).reshape(-1,1), np.array([0.,1.]*4)
    forest = fit(native,x,y)
    table = np.frombuffer(forest,dtype=np.float64).copy()
    table[index] = replacement
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_TREE"):
        predict(native,x,table.tobytes())


def test_forest_types_cannot_be_used_interchangeably(native):
    x, y = np.arange(8,dtype=np.float64).reshape(-1,1), np.array([0.,1.]*4)
    regression = native.fit_random_forest_regression(x.tobytes(),y.tobytes(),8,1,3,2,1,1,1)
    classifier = fit(native,x,y,trees=3,leaf=1)
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_TREE"):
        predict(native,x,regression)
    with pytest.raises(ValueError,match="RANDOM_FOREST_INVALID_TREE"):
        native.predict_random_forest_regression(x.tobytes(),8,1,classifier)


def test_distinct_rows_must_be_possible_given_full_and_bootstrap_class_counts(native):
    x, y = np.zeros((3,1)), np.array([0.,0.,1.])
    forest = fit(native,x,y,trees=5,depth=1,leaf=2,seed=0)
    for tree, impossible in [(0,1.),(4,2.)]:
        packed = np.frombuffer(forest,dtype=np.float64).copy()
        packed[HEADER+2*tree+1] = impossible
        with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_TREE"):
            predict(native,x,packed.tobytes())


def test_actual_ensemble_node_budget_is_checked_after_preflight(native):
    rng = np.random.default_rng(371)
    x, y = rng.normal(size=(4096,8)), rng.integers(0,2,4096)
    with pytest.raises(ValueError,match="fitted forest exceeds its total node budget"):
        fit(native,x,y,trees=32,depth=10,leaf=1,features=4,seed=917)


def test_work_and_predictor_width_bounds_and_cooperative_cancellation(native):
    class Stop(Exception):
        pass

    x, y = np.arange(16,dtype=float).reshape(-1,1), np.array([0.,1.]*8)
    forest = fit(native,x,y)
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_WORK_LIMIT"):
        native.fit_random_forest_classification(b"",b"",15_000,64,32,8,1,10,0)
    with pytest.raises(ValueError,match="FOREST_CLASSIFICATION_INVALID_TREE"):
        predict(native,np.c_[x,x],forest)

    def cancel_on(target):
        calls = 0
        def checkpoint():
            nonlocal calls
            calls += 1
            if calls >= target:
                raise Stop("stop classification forest")
        return checkpoint

    with pytest.raises(Stop,match="stop classification forest"):
        fit(native,x,y,checkpoint=cancel_on(8))
    with pytest.raises(Stop,match="stop classification forest"):
        predict(native,x,forest,checkpoint=cancel_on(4))


def test_classification_forest_keeps_existing_native_tree_and_forest_receipts_repeatable(native):
    x = np.arange(12, dtype=np.float64).reshape(-1, 1)
    labels = np.repeat([0., 1., 0.], 4)
    target = np.linspace(-3., 4., 12)
    design = x.tobytes()
    cart_options = design, labels.tobytes(), 12, 1, 3, 2
    forest_options = design, target.tobytes(), 12, 1, 4, 3, 2, 1, 731
    tree = native.fit_cart(*cart_options)
    regressor = native.fit_random_forest_regression(*forest_options)
    cart_scores = native.predict_cart(design, 12, 1, tree)
    regression_scores = native.predict_random_forest_regression(design, 12, 1, regressor)

    classifier = fit(native, x, labels, seed=814)
    assert len(predict(native, x, classifier)) == 12

    assert native.fit_cart(*cart_options) == tree
    assert native.fit_random_forest_regression(*forest_options) == regressor
    assert native.predict_cart(design, 12, 1, tree) == cart_scores
    assert native.predict_random_forest_regression(design, 12, 1, regressor) == regression_scores
