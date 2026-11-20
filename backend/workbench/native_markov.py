from __future__ import annotations

import ctypes
import math
from statistics import NormalDist

import numpy as np

from . import native_time_series as common
from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series_abi import DOUBLE, SIZE

MAX_ROWS = 10_000
MIN_OBSERVED = 24
_TRACE_FIELDS = (
    "predicted_low", "filtered_low", "smoothed_low", "one_step_mean",
    "one_step_variance", "log_likelihood",
)


def validate_markov_size(rows: int, holdout_periods: int) -> None:
    common._option_periods(holdout_periods, "holdout_periods", 0, common.MAX_HOLDOUT_PERIODS)
    if rows > MAX_ROWS:
        raise TimeSeriesPackError("TIME_SERIES_SIZE_LIMIT", f"Markov switching supports at most {MAX_ROWS} rows")
    if rows - holdout_periods < MIN_OBSERVED:
        raise TimeSeriesPackError("TIME_SERIES_TOO_FEW_OBSERVATIONS", "Markov switching requires 24 training outcomes")


def _native_fit(library, values, horizon, trace_rows):
    estimates = np.empty(12, dtype=np.float64)
    trace = np.empty((trace_rows, 6), dtype=np.float64)
    forecast = np.empty((horizon, 4), dtype=np.float64)
    error = SIZE()
    with common._native_checkpoint() as poll:
        status = library.arboris_markov_switching_fit(
            values.ctypes.data_as(DOUBLE), values.size, horizon, trace_rows,
            estimates.ctypes.data_as(DOUBLE), estimates.size, trace.ctypes.data_as(DOUBLE), trace.size,
            forecast.ctypes.data_as(DOUBLE), forecast.size, ctypes.byref(error), poll,
        )
    if status:
        code, message = {
            1: ("TIME_SERIES_BAD_INPUT", f"Markov switching rejected input at position {error.value}"),
            2: ("TIME_SERIES_NUMERIC_FAILURE", "Markov switching exceeded its numerical range"),
            3: ("TIME_SERIES_TOO_FEW_OBSERVATIONS", "Markov switching requires 24 observed training outcomes"),
            4: ("TIME_SERIES_MARKOV_UNIDENTIFIED", "regimes collapsed, were weakly identified, or had competing fits"),
            5: ("TIME_SERIES_MARKOV_NONCONVERGENCE", "an interior Markov switching fit was not found"),
            6: ("TIME_SERIES_SIZE_LIMIT", "Markov switching exceeded the work limit"),
        }.get(status, ("TIME_SERIES_NATIVE_EXECUTION_ERROR", "native Markov switching did not return a verified result"))
        raise TimeSeriesPackError(code, message)
    if not all(np.isfinite(array).all() for array in (estimates, trace, forecast)):
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "native Markov switching returned a nonfinite result")
    return estimates, trace, forecast


def _mixture_bounds(low_mean, high_mean, variance, weights, level):
    deviation = math.sqrt(variance)
    gap = (high_mean - low_mean) / deviation
    if not math.isfinite(gap) or gap <= 0:
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "Markov mixture means cannot be standardized")
    tail = (1.0 - level) / 2.0
    critical = -NormalDist().inv_cdf(tail)
    root_two = math.sqrt(2.0)
    limits = []
    for upper in (False, True):
        start = critical if upper else -critical
        left, right = start, start + gap
        sign = 1.0 if upper else -1.0
        for _ in range(100):
            middle = left + (right - left) / 2.0
            if middle in (left, right):
                break
            probability = 0.5 * (
                weights[0] * math.erfc(sign * middle / root_two)
                + weights[1] * math.erfc(sign * (middle - gap) / root_two)
            )
            if (probability > tail) == upper:
                left = middle
            else:
                right = middle
        limits.append(low_mean + deviation * (left + (right - left) / 2.0))
    if not all(map(math.isfinite, limits)) or limits[0] > limits[1]:
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", "Markov mixture interval exceeded its numerical range")
    return limits


def _forecast(estimates, rows, labels, level):
    low, high, variance = map(float, estimates[:3])
    weights = rows[:, :2]
    bounds = []
    for row in weights:
        common.check_cancellation()
        bounds.append(_mixture_bounds(low, high, variance, row, level))
    return {
        "steps": list(range(1, len(labels) + 1)), "time": labels,
        "probability_low": weights[:, 0].tolist(), "probability_high": weights[:, 1].tolist(),
        "mean": rows[:, 2].tolist(), "observation_variance": rows[:, 3].tolist(),
        "lower": [row[0] for row in bounds], "upper": [row[1] for row in bounds],
    }


def _fit_summary(estimates):
    low, high, variance, stay_low, stay_high, likelihood, observed, iterations, count_low, count_high, final_low, final_high = map(float, estimates)
    return {
        "mean_low": low, "mean_high": high, "shared_variance": variance,
        "p_low_low": stay_low, "p_high_high": stay_high, "log_likelihood": likelihood,
        "n_observed": int(observed), "optimizer_iterations": int(iterations),
        "expected_observed_low": count_low, "expected_observed_high": count_high,
        "last_filtered_low": final_low, "last_filtered_high": final_high,
        "aic": 2.0 * (5.0 - likelihood), "bic": 5.0 * math.log(observed) - 2.0 * likelihood,
    }


def run_markov_switching(frame, *, time_col, outcome, forecast_periods=1, holdout_periods=0, confidence_level=0.95):
    time, observations = common._series_columns(
        frame, time_col, outcome, lambda rows: validate_markov_size(rows, holdout_periods),
    )
    common._option_periods(forecast_periods, "forecast_periods", 1, common.MAX_FORECAST_PERIODS)
    level = common._option_number(confidence_level, "confidence_level")
    if not 0.0 < level < 1.0:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "require 0 < confidence_level < 1")
    data = common._prepare_series(time, observations, forecast_periods, holdout_periods)
    library, engine = common._loaded()
    holdout = None
    if holdout_periods:
        start = data.train_size
        estimates, _, rows = _native_fit(library, data.values[:start], holdout_periods, 0)
        prediction = _forecast(estimates, rows, [common._time_label(t) for t in data.time[start:]], level)
        count, metrics = common._holdout_metrics(data.values, data.observed, start, prediction)
        holdout = {
            "status": "completed" if count else "no_observed_holdout",
            "training_steps": start, "training_observed": int(estimates[6]),
            "origin_time": common._time_label(data.time[start - 1]),
            "n_observed": count, "n_missing": holdout_periods - count,
            "forecast": prediction, "metrics": metrics,
        }
    trace_rows = min(len(data.values), common.MAX_TRACE_ROWS)
    estimates, trace, rows = _native_fit(library, data.values, forecast_periods, trace_rows)
    first = len(data.values) - trace_rows
    trace_result = dict(zip(_TRACE_FIELDS, trace.T.tolist(), strict=True))
    trace_result.update(first_index=first, total_steps=len(data.values),
                        time=[common._time_label(time) for time in data.time[first:]])
    return {
        "schema_version": 1, "model": "markov_switching_mean", "engine": engine,
        "fit": {**_fit_summary(estimates), "n_missing": len(data.values) - int(estimates[6]), "trace": trace_result},
        "forecast": _forecast(estimates, rows, data.future, level), "holdout": holdout,
        "policy": {
            "time_col": time_col, "outcome": outcome, "cadence": data.cadence,
            "initial_state": "stationary_from_fitted_transition", "state_order": "mean_low_then_high",
            "observation_distribution": "two_normal_components_shared_variance",
            "predicted_information": "strictly_earlier_training_observations",
            "filtered_information": "training_observations_through_row",
            "smoothed_information": "all_training_observations",
            "confidence_level": level, "forecast_interval": "conditional_two_normal_mixture_quantiles",
            "future_origin": "full_training_final_filtered_state",
            "holdout_method": "training_prefix_fit_fixed_origin", "missing": "skip_measurement_keep_time",
        },
    }
    return public, local
