from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .checks.ar_cancellation import current_check
from .native_ridge import (
    _classification_metrics, _columns, _holdout, _loaded, _native_vector, _sample_values, _split, nominal_training_rows,
)


_NODE_FIELDS = ('feature_index', 'threshold', 'left_id', 'right_id', 'depth', 'training_rows',
                'training_positives', 'probability', 'gini_gain')
_INT_FIELDS = frozenset(('feature_index', 'left_id', 'right_id', 'depth', 'training_rows', 'training_positives'))


def validate_cart_size(rows, columns, max_depth, min_samples_leaf, training_rows):
    if not 1 <= columns <= 64 or not 3 <= rows <= 100_000 or rows * (columns + 1) > 1_000_000:
        raise ValueError('CART_WORK_LIMIT: at most 100000 rows, 64 predictors, and 1000000 input cells')
    if type(max_depth) is not int or not 1 <= max_depth <= 10:
        raise ValueError('CART_INVALID_DEPTH: max_depth must be an integer from 1 to 10')
    if type(min_samples_leaf) is not int or not 1 <= min_samples_leaf <= training_rows:
        raise ValueError('CART_INVALID_LEAF: min_samples_leaf must be an integer no greater than the training rows')
    if training_rows * columns * max_depth * ((training_rows - 1).bit_length() + 1) > 100_000_000:
        raise ValueError('CART_WORK_LIMIT: training shape exceeds the native split search budget')


def run_cart(
    frame: pd.DataFrame, *, outcome: str, predictors: list[str], holdout_fraction: float,
    max_depth: int = 4, min_samples_leaf: int = 1, time_col: str | None = None,
):
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    fraction = _holdout(holdout_fraction)
    rows, columns = len(frame), len(names)
    validate_cart_size(rows, columns, max_depth, min_samples_leaf, nominal_training_rows(rows, fraction))
    positions, split = _split(frame, time_col, fraction)
    train_rows = split['train_rows']
    if min_samples_leaf > train_rows:
        raise ValueError('CART_INVALID_LEAF: keeping equal times together leaves fewer training rows than min_samples_leaf')
    if time_col in names:
        raise ValueError('CART_INVALID_COLUMNS: time used to split the sample cannot also be a predictor')
    if pd.api.types.is_bool_dtype(frame[outcome].dtype):
        raise ValueError('CART_INVALID_LABELS: outcome must contain only numeric 0 and 1')
    values = _sample_values(frame, names, outcome, positions, checkpoint)
    train_y, actual = values[:train_rows, -1], values[train_rows:, -1]
    if not np.logical_or(actual == 0.0, actual == 1.0).all():
        raise ValueError('CART_INVALID_LABELS: outcome must contain only numeric 0 and 1')
    native, receipt = _loaded()
    fit, predict = getattr(native, 'fit_cart', None), getattr(native, 'predict_cart', None)
    if not callable(fit) or not callable(predict):
        raise RuntimeError('CART_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench')
    tree = fit(values[:train_rows, :-1].tobytes(), train_y.tobytes(), train_rows, columns, max_depth,
               min_samples_leaf, checkpoint)
    width = len(_NODE_FIELDS)
    count = len(tree) // (8 * width) if type(tree) is bytes else 0
    if not 1 <= count <= (1 << (max_depth + 1)) - 1:
        raise RuntimeError('CART_BUILD_INVALID: native fit returned an invalid node count')
    nodes = _native_vector(tree, count * width, prefix='CART').reshape(count, width)
    predicted = _native_vector(
        predict(values[train_rows:, :-1].tobytes(), actual.size, columns, tree, checkpoint), actual.size, prefix='CART',
    )
    if not ((0 < predicted) & (predicted < 1)).all():
        raise RuntimeError('CART_BUILD_INVALID: native scoring returned a probability outside the smoothing contract')
    train_positives, test_positives = int(np.count_nonzero(train_y)), int(np.count_nonzero(actual))
    scores = np.log(predicted) - np.log1p(-predicted)
    baseline_score = math.log(train_positives) - math.log(train_rows - train_positives)
    metrics = _classification_metrics(actual, scores, test_positives)
    baseline = _classification_metrics(actual, baseline_score, test_positives)
    structure = {'node_count': count, 'leaf_count': int(np.count_nonzero(nodes[:, 0] == -1)),
                 'depth': int(nodes[:, 4].max()), 'root_predictor': names[int(nodes[0, 0])] if nodes[0, 0] >= 0 else None}
    return {
        'schema_version': 1, 'model_type': 'native_cart', 'engine': 'cpp17_cart',
        'outcome': outcome, 'predictors': names, 'nobs': rows, 'split': split, 'metrics': metrics,
        'prevalence_baseline': {'probability': train_positives / train_rows, **baseline},
        'roc_auc_reason': 'single_class_test_outcome' if metrics['roc_auc'] is None else None,
        'native_build': dict(receipt), 'model_structure': structure, 'classification_threshold': 0.5,
        'options': {'max_depth': max_depth, 'min_samples_leaf': min_samples_leaf,
                    'criterion': 'gini', 'leaf_probability': 'laplace_smoothed', 'tie_break': 'predictor_order_then_lower_cut'},
        'prediction_basis': {'predictor_order': names, 'nodes': [
            {'node_id': index, **{key: int(value) if key in _INT_FIELDS else float(value)
                                 for key, value in zip(_NODE_FIELDS, row, strict=True)}}
            for index, row in enumerate(nodes)
        ]},
    }
