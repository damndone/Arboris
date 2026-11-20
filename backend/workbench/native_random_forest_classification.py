from __future__ import annotations

import math

import numpy as np
import pandas as pd
from pandas.api import types as dtypes

from .checks.ar_cancellation import current_check
from .native_cart import _INT_FIELDS, _NODE_FIELDS
from .native_random_forest import _MAX_NODES, validate_random_forest_size
from .native_ridge import (
    _classification_metrics, _columns, _holdout, _loaded, _native_vector, _sample_values, _split,
    nominal_training_rows,
)


_TAG = 4001
_HEADER_WIDTH = 9


def _decode(packed: bytes, expected: tuple[int, ...]):
    error = 'FOREST_CLASSIFICATION_BUILD_INVALID: native forest returned an invalid receipt'
    n_trees, train_rows, max_depth = expected[1:4]
    entries = len(packed) // 8 if type(packed) is bytes else 0
    width = len(_NODE_FIELDS)
    start = _HEADER_WIDTH + 2 * n_trees
    if not start + n_trees * width <= entries <= start + _MAX_NODES * width:
        raise RuntimeError(error)
    values = _native_vector(packed, entries, prefix='FOREST_CLASSIFICATION')
    if not np.array_equal(values[:_HEADER_WIDTH], expected):
        raise RuntimeError(error)
    counts, distinct = values[_HEADER_WIDTH:start].reshape(n_trees, 2).T
    if not (((1 <= counts) & (counts <= (1 << (max_depth + 1)) - 1) & (counts == np.floor(counts))).all()
            and ((1 <= distinct) & (distinct <= train_rows) & (distinct == np.floor(distinct))).all()):
        raise RuntimeError(error)
    count = int(counts.sum())
    if entries != start + count * width:
        raise RuntimeError(error)
    return counts.astype(np.intp), distinct.astype(np.intp), values[start:].reshape(count, width)


def run_random_forest_classification(
    frame: pd.DataFrame, *, outcome: str, predictors: list[str], holdout_fraction: float, n_trees: int = 16,
    max_depth: int = 4, min_samples_leaf: int = 2, max_features: int = 0, seed: int = 0, time_col: str | None = None,
) -> dict:
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    if time_col in names:
        raise ValueError('FOREST_CLASSIFICATION_INVALID_COLUMNS: time used to split the sample cannot also be a predictor')
    fraction = _holdout(holdout_fraction)
    rows, columns = len(frame), len(names)
    features = validate_random_forest_size(
        rows, columns, training_rows=nominal_training_rows(rows, fraction), n_trees=n_trees, max_depth=max_depth,
        min_samples_leaf=min_samples_leaf, max_features=max_features, seed=seed,
    )
    positions, split = _split(frame, time_col, fraction)
    train_rows = split['train_rows']
    if min_samples_leaf > train_rows:
        raise ValueError('FOREST_CLASSIFICATION_INVALID_OPTIONS: equal times leave fewer rows than min_samples_leaf')
    labels = frame[outcome]
    if (not dtypes.is_numeric_dtype(labels.dtype) or dtypes.is_bool_dtype(labels.dtype)
            or dtypes.is_complex_dtype(labels.dtype) or not (labels.eq(0) | labels.eq(1)).fillna(False).all()):
        raise ValueError('FOREST_CLASSIFICATION_INVALID_LABELS: outcome must contain only numeric 0 and 1')
    values = _sample_values(frame, names, outcome, positions, checkpoint)
    training, actual = values[:train_rows, -1], values[train_rows:, -1]
    train_positive, test_positive = int(np.count_nonzero(training)), int(np.count_nonzero(actual))
    if not 0 < train_positive < train_rows:
        raise ValueError('FOREST_CLASSIFICATION_TRAIN_SINGLE_CLASS: training must contain both 0 and 1')
    native, receipt = _loaded()
    fit = getattr(native, 'fit_random_forest_classification', None)
    predict = getattr(native, 'predict_random_forest_classification', None)
    if not callable(fit) or not callable(predict):
        raise RuntimeError('FOREST_CLASSIFICATION_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench')
    forest = fit(values[:train_rows, :-1].tobytes(), training.tobytes(), train_rows, columns, n_trees, max_depth,
                 min_samples_leaf, features, seed, checkpoint)
    expected = (_TAG, n_trees, train_rows, max_depth, min_samples_leaf, features, seed, columns, train_positive)
    sizes, distinct, nodes = _decode(forest, expected)
    probabilities = _native_vector(
        predict(values[train_rows:, :-1].tobytes(), actual.size, columns, forest, checkpoint),
        actual.size, prefix='FOREST_CLASSIFICATION',
    )
    if not ((0 < probabilities) & (probabilities < 1)).all():
        raise RuntimeError('FOREST_CLASSIFICATION_BUILD_INVALID: probabilities must be strictly between 0 and 1')
    scores = np.log(probabilities) - np.log1p(-probabilities)
    baseline = math.log(train_positive) - math.log(train_rows - train_positive)
    metrics = _classification_metrics(actual, scores, test_positive)
    baseline_metrics = _classification_metrics(actual, baseline, test_positive)

    start = 0
    pure = 0
    trees = []
    for tree_id, (size, unique_rows) in enumerate(zip(sizes, distinct, strict=True)):
        if checkpoint is not None:
            checkpoint()
        end = start + int(size)
        pure += int(nodes[start, 6] in (0, train_rows))
        trees.append({'tree_id': tree_id, 'bootstrap_unique_rows': int(unique_rows), 'nodes': [
            {'node_id': node_id, **{name: int(value) if name in _INT_FIELDS else float(value)
                                    for name, value in zip(_NODE_FIELDS, node, strict=True)}}
            for node_id, node in enumerate(nodes[start:end])
        ]})
        start = end
    distinct_total = int(distinct.sum())
    draws = train_rows * n_trees
    if checkpoint is not None:
        checkpoint()
    return {
        'schema_version': 1, 'model_type': 'native_random_forest_classification',
        'engine': 'cpp17_random_forest_classification', 'outcome': outcome, 'predictors': names, 'nobs': rows,
        'split': split, 'native_build': dict(receipt), 'classification_threshold': .5, 'metrics': metrics,
        'prevalence_baseline': {'probability': train_positive / train_rows, **baseline_metrics},
        'roc_auc_reason': 'single_class_test_outcome' if metrics['roc_auc'] is None else None,
        'class_counts': {'train': {'0': train_rows-train_positive, '1': train_positive},
                         'test': {'0': actual.size-test_positive, '1': test_positive}},
        'model_structure': {'tree_count': n_trees, 'node_count': len(nodes),
                            'leaf_count': int(np.count_nonzero(nodes[:, 0] == -1)), 'depth': int(nodes[:, 4].max())},
        'sampling': {'draws_per_tree': train_rows, 'repeat_fraction': (draws-distinct_total)/draws,
                     'mean_distinct_training_rows': distinct_total/n_trees, 'single_class_trees': pure},
        'options': {'n_trees': n_trees, 'max_depth': max_depth, 'min_samples_leaf': min_samples_leaf,
                    'max_features': features, 'max_features_requested': max_features, 'seed': seed,
                    'bootstrap': 'training_rows_with_replacement', 'feature_sampling': 'without_replacement_each_eligible_node',
                    'rng': 'splitmix64_independent_per_tree_streams', 'criterion': 'gini',
                    'leaf_probability': 'laplace_smoothed', 'aggregation': 'equal_weight_leaf_probability'},
        'prediction_basis': {'kind': 'random_forest_classification', 'predictor_order': names, 'trees': trees},
    }
