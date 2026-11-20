from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .checks.ar_cancellation import current_check
from .native_cart_regression import _holdout_errors, _INT_FIELDS, _NODE_FIELDS
from .native_ridge import _columns, _holdout, _loaded, _native_vector, _sample_values, _split, nominal_training_rows


_MAX_TREES = 32
_MAX_NODES = 8191
_MAX_SEED = 2**32 - 1
_HEADER_WIDTH = 8


def validate_random_forest_size(
    rows: int, columns: int, *, training_rows: int, n_trees: int, max_depth: int, min_samples_leaf: int,
    max_features: int, seed: int,
) -> int:
    if not 1 <= columns <= 64 or not 3 <= rows <= 100_000 or rows * (columns + 1) > 1_000_000:
        raise ValueError('RANDOM_FOREST_WORK_LIMIT: at most 100000 rows, 64 predictors, and 1000000 input cells')
    for value, low, high, name in (
        (n_trees, 1, _MAX_TREES, 'n_trees'), (max_depth, 1, 10, 'max_depth'),
        (min_samples_leaf, 1, training_rows, 'min_samples_leaf'), (max_features, 0, columns, 'max_features'),
        (seed, 0, _MAX_SEED, 'seed'),
    ):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'RANDOM_FOREST_INVALID_OPTIONS: {name} must be an integer in [{low}, {high}]')
    features = max_features or math.isqrt(columns)
    levels = (training_rows - 1).bit_length() + 1
    if n_trees * training_rows * max_depth * (features * levels + 1) > 100_000_000:
        raise ValueError('RANDOM_FOREST_WORK_LIMIT: the requested forest exceeds the native work budget')
    return features


def _decode(packed: bytes, expected: tuple[int, ...], n_trees: int):
    prefix = 'RANDOM_FOREST'
    error = 'RANDOM_FOREST_BUILD_INVALID: native forest returned an invalid receipt'
    entries = len(packed) // 8 if type(packed) is bytes else 0
    width = len(_NODE_FIELDS)
    if not _HEADER_WIDTH + n_trees * (1 + width) <= entries <= _HEADER_WIDTH + n_trees + _MAX_NODES * width:
        raise RuntimeError(error)
    values = _native_vector(packed, entries, prefix=prefix)
    if not np.array_equal(values[:_HEADER_WIDTH-1], expected):
        raise RuntimeError(error)
    sizes = values[_HEADER_WIDTH:_HEADER_WIDTH + n_trees]
    if not ((sizes >= 1) & (sizes <= (1 << (expected[2] + 1)) - 1) & (sizes == np.floor(sizes))).all():
        raise RuntimeError(error)
    count = int(np.sum(sizes))
    if entries != _HEADER_WIDTH + n_trees + count * width:
        raise RuntimeError(error)
    nodes = values[_HEADER_WIDTH + n_trees:].reshape(count, width)
    return float(values[_HEADER_WIDTH-1]), sizes.astype(np.intp), nodes


def run_random_forest_regression(
    frame: pd.DataFrame, *, outcome: str, predictors: list[str], holdout_fraction: float, n_trees: int = 16,
    max_depth: int = 4, min_samples_leaf: int = 2, max_features: int = 0, seed: int = 0, time_col: str | None = None,
) -> dict:
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    if time_col in names:
        raise ValueError('RANDOM_FOREST_INVALID_COLUMNS: time used to split the sample cannot also be a predictor')
    if pd.api.types.is_bool_dtype(frame[outcome].dtype):
        raise ValueError('RANDOM_FOREST_INVALID_DATA: regression outcome must be real numeric')
    fraction = _holdout(holdout_fraction)
    rows, columns = len(frame), len(names)
    features = validate_random_forest_size(
        rows, columns, training_rows=nominal_training_rows(rows, fraction), n_trees=n_trees, max_depth=max_depth,
        min_samples_leaf=min_samples_leaf, max_features=max_features, seed=seed,
    )
    positions, split = _split(frame, time_col, fraction)
    train_rows = split['train_rows']
    if min_samples_leaf > train_rows:
        raise ValueError('RANDOM_FOREST_INVALID_OPTIONS: keeping equal times together leaves fewer rows than min_samples_leaf')
    values = _sample_values(frame, names, outcome, positions, checkpoint)
    native, receipt = _loaded()
    fit = getattr(native, 'fit_random_forest_regression', None)
    predict = getattr(native, 'predict_random_forest_regression', None)
    if not callable(fit) or not callable(predict):
        raise RuntimeError('RANDOM_FOREST_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench')
    forest = fit(values[:train_rows, :-1].tobytes(), values[:train_rows, -1].tobytes(), train_rows, columns,
                 n_trees, max_depth, min_samples_leaf, features, seed, checkpoint)
    expected = (n_trees, train_rows, max_depth, min_samples_leaf, features, seed, columns)
    baseline, tree_sizes, nodes = _decode(forest, expected, n_trees)
    actual = values[train_rows:, -1]
    fitted = _native_vector(
        predict(values[train_rows:, :-1].tobytes(), actual.size, columns, forest, checkpoint),
        actual.size, prefix='RANDOM_FOREST',
    )
    metrics, baseline_metrics = _holdout_errors(actual, fitted), _holdout_errors(actual, baseline)
    trees = []
    start = 0
    for tree_id, size in enumerate(tree_sizes):
        if checkpoint is not None:
            checkpoint()
        end = start + int(size)
        trees.append({'tree_id': tree_id, 'nodes': [
            {'node_id': node_id, **{name: int(value) if name in _INT_FIELDS else float(value)
                                    for name, value in zip(_NODE_FIELDS, node, strict=True)}}
            for node_id, node in enumerate(nodes[start:end])
        ]})
        start = end
    if checkpoint is not None:
        checkpoint()
    return {
        'schema_version': 1, 'model_type': 'native_random_forest_regression', 'engine': 'cpp17_random_forest_regression',
        'outcome': outcome, 'predictors': names, 'nobs': rows, 'split': split, 'native_build': dict(receipt),
        'metrics': metrics, 'mean_baseline': {'prediction': baseline, **baseline_metrics},
        'model_structure': {'tree_count': n_trees, 'node_count': len(nodes),
                            'leaf_count': int(np.count_nonzero(nodes[:, 0] == -1)), 'depth': int(nodes[:, 4].max())},
        'options': {
            'n_trees': n_trees, 'max_depth': max_depth, 'min_samples_leaf': min_samples_leaf,
            'max_features': features, 'max_features_requested': max_features, 'seed': seed,
            'bootstrap': 'training_rows_with_replacement', 'feature_sampling': 'without_replacement_each_eligible_node',
            'rng': 'splitmix64_independent_per_tree_streams', 'criterion': 'squared_error',
            'aggregation': 'equal_weight_leaf_mean',
        },
        'prediction_basis': {'kind': 'random_forest_regression', 'predictor_order': names, 'trees': trees},
    }
