from __future__ import annotations

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, _arima_fit, _holdout_metrics, _loaded, _numeric_buffer, _numeric_design, _option_periods,
    _prediction_level, _series_columns, _time_grid, _time_label, validate_arima_size,
    validate_sarima_size,
)


def validate_xreg_size(rows, predictors, order, seasonal_order, deterministic, forecast_periods, holdout_periods):
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    historical_rows = rows - forecast_periods
    if seasonal_order is not None:
        validate_sarima_size(historical_rows, *order, *seasonal_order, deterministic, holdout_periods, predictors=predictors)
        return
    p, d, q = order
    _option_periods(p, 'ar_order', 0, 3)
    _option_periods(q, 'ma_order', 0, 3)
    if p + q > 4:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'the combined AR and MA order cannot exceed four for ARIMAX')
    if historical_rows > 10_000:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', 'ARIMAX supports at most 10000 historical time rows')
    validate_arima_size(historical_rows, *order, deterministic, holdout_periods)
    minimum = d + 2 * (p + q) + predictors + int(deterministic != 'none') + 2
    if historical_rows - holdout_periods < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'need at least {minimum} historical training rows for the regression')


def run_arimax(
    frame: pd.DataFrame, *, time_col: str, outcome: str, predictors: list[str], forecast_periods: int,
    ar_order: int = 1, differences: int = 0, ma_order: int = 0, deterministic: str = 'none',
    holdout_periods: int = 0, confidence_level: float = 0.95,
):
    return _run(frame, time_col, outcome, predictors, (ar_order, differences, ma_order), None, deterministic,
                forecast_periods, holdout_periods, confidence_level)


def run_sarimax(
    frame: pd.DataFrame, *, time_col: str, outcome: str, predictors: list[str], forecast_periods: int,
    seasonal_period: int, ar_order: int = 1, differences: int = 0, ma_order: int = 0,
    seasonal_ar_order: int = 0, seasonal_differences: int = 1, seasonal_ma_order: int = 0, deterministic: str = 'none',
    holdout_periods: int = 0, confidence_level: float = 0.95,
):
    return _run(frame, time_col, outcome, predictors, (ar_order, differences, ma_order),
                (seasonal_ar_order, seasonal_differences, seasonal_ma_order, seasonal_period), deterministic,
                forecast_periods, holdout_periods, confidence_level)


def _run(frame, time_col, outcome, predictors, order, seasonal_order, deterministic, horizon, holdout_periods, confidence):
    if not isinstance(predictors, (list, tuple)) or not 1 <= len(predictors) <= 4:
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'choose one to four distinct predictors separate from time and outcome')
    time_series, outcomes = _series_columns(frame, time_col, outcome, lambda rows: validate_xreg_size(
        rows, len(predictors), order, seasonal_order, deterministic, horizon, holdout_periods))
    level, critical = _prediction_level(confidence)
    time, _, cadence = _time_grid(time_series, 0)
    historical = len(frame) - horizon
    training = historical - holdout_periods
    values = _numeric_buffer(outcomes)
    if not np.isnan(values[historical:]).all():
        raise TimeSeriesPackError('TIME_SERIES_FUTURE_OUTCOME', 'outcomes must be blank on all declared future predictor rows')
    observed = ~np.isnan(values[:historical])
    if np.isinf(values[:historical]).any() or not observed[:training].any():
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', 'historical outcomes must include observed finite training values and no infinity')
    design = _numeric_design(frame, predictors, excluded=(time_col, outcome))
    library, engine = _loaded()
    holdout = None
    if holdout_periods:
        _, holdout_fit, predicted = _arima_fit(
            library, values[:training], order, deterministic, [_time_label(item) for item in time[training:historical]],
            critical, seasonal_order, (predictors, design[:training], design[training:historical]),
        )
        count, metrics = _holdout_metrics(values[:historical], observed, training, predicted,
                                          seasonal_period=seasonal_order[-1] if seasonal_order is not None else None)
        holdout = {'status': 'completed' if count else 'no_observed_holdout', 'training_steps': training,
                   'training_observed': holdout_fit['n_observed'], 'origin_time': _time_label(time[training - 1]),
                   'n_observed': count, 'n_missing': holdout_periods - count, 'forecast': predicted, 'metrics': metrics}
    parameters, fit, forecast = _arima_fit(
        library, values[:historical], order, deterministic, [_time_label(item) for item in time[historical:]],
        critical, seasonal_order, (predictors, design[:historical], design[historical:]),
    )
    policy = {
        'time_col': time_col, 'outcome': outcome, 'predictors': list(predictors), 'cadence': cadence, 'order': list(order),
        'deterministic': deterministic, 'confidence_level': level, 'estimation': 'gaussian_innovations_profile_ml',
        'future_regressors': 'supplied_in_aligned_suffix', 'forecast_interval': 'gaussian_plugin_given_regressors',
        'holdout_method': 'training_prefix_fit_given_held_out_regressors',
        'missing': 'skip_historical_outcome_keep_time_and_require_complete_predictors',
    }
    if seasonal_order is not None:
        policy.update(seasonal_order=list(seasonal_order), holdout_baseline='last_observed_training_seasonal_phase')
    return {
        'schema_version': 1, 'model': 'sarimax' if seasonal_order is not None else 'arimax',
        'engine': engine, 'parameters': parameters, 'fit': fit, 'policy': policy, 'forecast': forecast, 'holdout': holdout,
    }
