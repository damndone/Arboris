"""Select a Ridge penalty on a chronological validation block and score one final holdout."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .checks.ar_cancellation import current_check
from .native_ridge import (
    _MAX_FEATURES, _MAX_WORK, _binary64_arithmetic, _columns, _holdout, _keep_time_ties, _loaded,
    _native_vector, _number, _ridge_from_sample, _sample_values, _scale, _split, _time_order,
    nominal_training_rows, validate_prediction_size,
)


DEFAULT_ALPHA_GRID = (.01, .1, 1., 10., 100.)
_MAX_CANDIDATES = 16


def _grid(values) -> tuple[float, ...]:
    error = 'RIDGE_SELECTION_INVALID_GRID: provide 2 to 16 distinct finite positive alphas'
    if not isinstance(values, (list, tuple)) or not 2 <= len(values) <= _MAX_CANDIDATES:
        raise ValueError(error)
    grid = tuple(_number(value, error=error) for value in values)
    if any(alpha <= 0 for alpha in grid) or len(set(grid)) != len(grid):
        raise ValueError(error)
    return grid


def validate_ridge_selection_size(
    rows: int, columns: int, *, alpha_grid=DEFAULT_ALPHA_GRID, validation_fraction: float = .25,
    holdout_fraction: float = .2,
) -> tuple[tuple[float, ...], float, float]:
    grid = _grid(alpha_grid)
    error = 'RIDGE_SELECTION_INVALID_VALIDATION: validation_fraction must be strictly between zero and one'
    validation = _number(validation_fraction, error=error)
    if not 0 < validation < 1:
        raise ValueError(error)
    holdout = _holdout(holdout_fraction)
    if not 1 <= columns <= _MAX_FEATURES:
        raise ValueError('RIDGE_SELECTION_WORK_LIMIT: choose 1 to 512 predictors')
    validate_prediction_size(rows, columns, elastic_net=False)
    refit_rows = nominal_training_rows(rows, holdout)
    fit_rows = nominal_training_rows(refit_rows, validation)
    candidates = len(grid)
    work = columns**2 * (candidates * fit_rows + refit_rows) + candidates * (refit_rows - fit_rows) * columns
    if work > _MAX_WORK:
        raise ValueError('RIDGE_SELECTION_WORK_LIMIT: candidate fits, validation and final refit exceed the work budget')
    return grid, validation, holdout


def _select_candidate(method, values, fit_rows, refit_rows, alphas, checkpoint):
    with _binary64_arithmetic(prefix='RIDGE_SELECTION'):
        train_x, validation_x, *_ = _scale(values[:fit_rows, :-1], values[fit_rows:refit_rows, :-1])
        fit_y = values[:fit_rows, -1]
        response_magnitude = float(np.max(np.abs(fit_y))) or 1.0
        normalized_y = fit_y / response_magnitude
    result = _native_vector(
        method(train_x.tobytes(), normalized_y.tobytes(), validation_x.tobytes(), values[fit_rows:refit_rows, -1].tobytes(),
               fit_rows, refit_rows-fit_rows, values.shape[1]-1, np.asarray(alphas, dtype=np.float64).tobytes(),
               response_magnitude, checkpoint),
        len(alphas)+1, prefix='RIDGE_SELECTION',
    )
    losses = result[1:].tolist()
    best = min(range(len(alphas)), key=lambda index: (losses[index], -alphas[index]))
    if (result[1:] < 0).any() or result[0] != best:
        raise RuntimeError('RIDGE_SELECTION_BUILD_INVALID: native validation errors and selected alpha disagree')
    return best, losses


def run_ridge_selection(
    frame: pd.DataFrame, *, outcome: str, predictors: list[str], time_col: str | None = None,
    alpha_grid=DEFAULT_ALPHA_GRID, validation_fraction: float = .25, holdout_fraction: float = .2,
) -> dict:
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    grid, validation_fraction, holdout_fraction = validate_ridge_selection_size(
        len(frame), len(names), alpha_grid=alpha_grid, validation_fraction=validation_fraction,
        holdout_fraction=holdout_fraction,
    )
    time_order = _time_order(frame, time_col) if time_col is not None else None
    positions, split = _split(frame, time_col, holdout_fraction, time_order=time_order)
    refit_rows = split['train_rows']
    fit_rows = nominal_training_rows(refit_rows, validation_fraction)
    boundary_times = {'fit_last_time': None, 'validation_first_time': None, 'validation_last_time': None}
    if time_order is not None:
        _, ordered, label = time_order
        fit_rows = _keep_time_ties(ordered[:refit_rows], fit_rows)
        boundary_times = {
            'fit_last_time': label(positions[fit_rows-1]),
            'validation_first_time': label(positions[fit_rows]),
            'validation_last_time': split['train_last_time'],
        }
    values = _sample_values(frame, names, outcome, positions, checkpoint)
    native, receipt = _loaded()
    select = getattr(native, 'select_ridge', None)
    if not callable(select):
        raise RuntimeError('RIDGE_SELECTION_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench')
    best, losses = _select_candidate(select, values, fit_rows, refit_rows, grid, checkpoint)
    selected = grid[best]
    result = _ridge_from_sample(native, receipt, values, names, outcome, split, selected, checkpoint)
    result['model_type'] = 'native_ridge_selection'
    result['engine'] = 'cpp17_ridge_selection'
    result['selection'] = {
        'criterion': 'validation_rmse', 'fit_rows': fit_rows, 'validation_rows': refit_rows-fit_rows,
        'refit_rows': refit_rows, 'validation_fraction_requested': validation_fraction,
        'validation_fraction_actual': (refit_rows-fit_rows)/refit_rows, 'selected_alpha': selected,
        'selected_validation_rmse': losses[best], 'tie_break': 'largest_alpha',
        'candidates': [{'alpha': alpha, 'validation_rmse': loss} for alpha, loss in zip(grid, losses, strict=True)],
    }
    result['prediction_basis']['selection_times'] = boundary_times
    return result
