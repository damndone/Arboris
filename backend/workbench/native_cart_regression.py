from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .checks.ar_cancellation import current_check
from .native_cart import validate_cart_size
from .native_ridge import (
    _binary64_arithmetic, _columns, _holdout, _loaded, _metrics, _native_vector, _sample_values, _split,
    nominal_training_rows,
)


_NODE_FIELDS = ('feature_index', 'threshold', 'left_id', 'right_id', 'depth', 'training_rows',
                'training_mean', 'training_mse', 'mse_gain')
_INT_FIELDS = frozenset(('feature_index', 'left_id', 'right_id', 'depth', 'training_rows'))


def _holdout_errors(actual: np.ndarray, predicted: np.ndarray | float) -> dict:
    with _binary64_arithmetic(prefix='CART_REGRESSION'):
        metrics = _metrics(actual, predicted, None)
    rmse = metrics['rmse']
    mse = rmse * rmse
    if not math.isfinite(mse) or (mse == 0 and np.any(actual != predicted)):
        raise ValueError('CART_REGRESSION_NUMERICAL_RANGE: holdout MSE is outside the binary64 range')
    return {'mse': mse, 'rmse': rmse, 'mae': metrics['mae']}


def run_cart_regression(
    frame: pd.DataFrame, *, outcome: str, predictors: list[str], holdout_fraction: float,
    max_depth: int = 4, min_samples_leaf: int = 1, time_col: str | None = None,
) -> dict:
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    if time_col in names:
        raise ValueError('CART_REGRESSION_INVALID_COLUMNS: time used to split the sample cannot also be a predictor')
    if pd.api.types.is_bool_dtype(frame[outcome].dtype):
        raise ValueError('CART_REGRESSION_INVALID_DATA: regression outcome must be real numeric')
    fraction = _holdout(holdout_fraction)
    rows, columns = len(frame), len(names)
    validate_cart_size(rows, columns, max_depth, min_samples_leaf, nominal_training_rows(rows, fraction))
    positions, split = _split(frame, time_col, fraction)
    train_rows = split['train_rows']
    if min_samples_leaf > train_rows:
        raise ValueError('CART_REGRESSION_INVALID_LEAF: keeping equal times together leaves fewer rows than min_samples_leaf')

    values = _sample_values(frame, names, outcome, positions, checkpoint)
    native, receipt = _loaded()
    fit, predict = getattr(native, 'fit_cart_regression', None), getattr(native, 'predict_cart_regression', None)
    if not callable(fit) or not callable(predict):
        raise RuntimeError('CART_REGRESSION_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench')
    tree = fit(values[:train_rows, :-1].tobytes(), values[:train_rows, -1].tobytes(), train_rows, columns,
               max_depth, min_samples_leaf, checkpoint)
    width = len(_NODE_FIELDS)
    count = len(tree) // (8 * width) if type(tree) is bytes else 0
    if not 1 <= count <= (1 << (max_depth + 1)) - 1:
        raise RuntimeError('CART_REGRESSION_BUILD_INVALID: native fit returned an invalid node count')
    nodes = _native_vector(tree, count * width, prefix='CART_REGRESSION').reshape(count, width)
    actual = values[train_rows:, -1]
    predicted = _native_vector(
        predict(values[train_rows:, :-1].tobytes(), actual.size, columns, tree, checkpoint),
        actual.size, prefix='CART_REGRESSION',
    )
    leaves = nodes[:, 0] == -1
    depth = int(nodes[:, 4].max())
    if nodes[0, 5] != train_rows or depth > max_depth or np.any(nodes[leaves, 5] < min_samples_leaf):
        raise RuntimeError('CART_REGRESSION_BUILD_INVALID: native node table did not match the training boundaries')
    baseline = float(nodes[0, 6])
    metrics, baseline_metrics = _holdout_errors(actual, predicted), _holdout_errors(actual, baseline)
    root = names[int(nodes[0, 0])] if nodes[0, 0] >= 0 else None
    basis = {'kind': 'regression', 'predictor_order': names, 'nodes': [
        {'node_id': index, **{key: int(value) if key in _INT_FIELDS else float(value)
                             for key, value in zip(_NODE_FIELDS, row, strict=True)}}
        for index, row in enumerate(nodes)
    ]}
    if checkpoint is not None:
        checkpoint()
    return {
        'schema_version': 1, 'model_type': 'native_cart_regression', 'engine': 'cpp17_cart_regression',
        'outcome': outcome, 'predictors': names, 'nobs': rows, 'split': split, 'native_build': dict(receipt),
        'metrics': metrics, 'mean_baseline': {'prediction': baseline, **baseline_metrics},
        'model_structure': {'node_count': count, 'leaf_count': int(np.count_nonzero(leaves)), 'depth': depth,
                            'root_predictor': root},
        'options': {'max_depth': max_depth, 'min_samples_leaf': min_samples_leaf, 'criterion': 'squared_error',
                    'leaf_prediction': 'training_mean', 'tie_break': 'predictor_order_then_lower_cut_at_resolution'},
        'prediction_basis': basis,
    }
