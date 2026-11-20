from __future__ import annotations

import ctypes
import math

import numpy as np

from . import native_time_series as common
from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series_abi import DOUBLE, SIZE

MAX_ARFIMA_ROWS = 1_000
DIFFERENCE_LIMIT = 0.45
_DIFFERENCE_MODES = {"fixed": 0, "estimate": 1}
_MEAN_MODES = {"none": 0, "mean": 1}
_MODEL = "ARFIMA(0,d,0)"


def validate_arfima_size(rows, difference, holdout_periods):
    common._option_periods(holdout_periods, "holdout_periods", 0, common.MAX_HOLDOUT_PERIODS)
    if rows > MAX_ARFIMA_ROWS:
        raise TimeSeriesPackError("TIME_SERIES_SIZE_LIMIT", f"{_MODEL} supports at most {MAX_ARFIMA_ROWS} rows")
    minimum = 24 if difference is None else 3
    if rows - holdout_periods < minimum:
        raise TimeSeriesPackError("TIME_SERIES_TOO_FEW_OBSERVATIONS", f"{_MODEL} requires at least {minimum} training outcomes")


def _fit(symbol, values, future, critical, difference_mode, difference, deterministic):
    estimates = np.empty(7, dtype=np.float64)
    forecast = np.empty((len(future), 2), dtype=np.float64)
    error = SIZE()
    with common._native_checkpoint() as poll:
        status = symbol(
            values.ctypes.data_as(DOUBLE), values.size, len(future), _DIFFERENCE_MODES[difference_mode], difference,
            _MEAN_MODES[deterministic], estimates.ctypes.data_as(DOUBLE), estimates.size,
            forecast.ctypes.data_as(DOUBLE), forecast.size, ctypes.byref(error), poll,
        )
    if status:
        code, message = {
            1: ("TIME_SERIES_BAD_INPUT", f"{_MODEL} rejected input at position {error.value}"),
            2: ("TIME_SERIES_NUMERIC_FAILURE", f"{_MODEL} exceeded its numerical range"),
            3: ("TIME_SERIES_TOO_FEW_OBSERVATIONS", f"{_MODEL} has too few training outcomes"),
            4: ("TIME_SERIES_ARFIMA_UNIDENTIFIED", f"{_MODEL} likelihood is degenerate or has competing optima"),
            5: ("TIME_SERIES_ARFIMA_NONCONVERGENCE", f"{_MODEL} did not find an identified interior optimum for d"),
            6: ("TIME_SERIES_SIZE_LIMIT", f"{_MODEL} specification exceeds the native work limit"),
        }.get(status, ("TIME_SERIES_NATIVE_EXECUTION_ERROR", f"native {_MODEL} did not return a verified result"))
        raise TimeSeriesPackError(code, message)
    if not np.isfinite(estimates).all() or not np.isfinite(forecast).all():
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", f"native {_MODEL} returned a nonfinite result")
    d, mean, innovation, marginal, likelihood, n, evaluations = map(float, estimates)
    k = 1 + int(difference_mode == "estimate") + int(deterministic == "mean")
    fit = {
        "n_observed": int(n), "n_effective": int(n), "n_missing": 0,
        "innovation_variance": innovation, "marginal_variance": marginal,
        "log_likelihood": likelihood, "likelihood_evaluations": int(evaluations),
        "aic": 2.0 * (k - likelihood), "bic": k * math.log(n) - 2.0 * likelihood,
    }
    return {"order": [0, d, 0], "mean": mean}, fit, common._interval_forecast(forecast, future, critical, _MODEL)


def run_arfima(
    frame, *, time_col, outcome, difference=None, deterministic="mean",
    forecast_periods=1, holdout_periods=0, confidence_level=0.95,
):
    if type(deterministic) is not str or deterministic not in _MEAN_MODES:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "deterministic must be mean or none")
    difference_mode = "estimate" if difference is None else "fixed"
    d = 0.0 if difference is None else common._option_number(difference, "difference")
    if abs(d) > DIFFERENCE_LIMIT:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", f"fixed d must be in [-{DIFFERENCE_LIMIT}, {DIFFERENCE_LIMIT}]")
    time, observations = common._series_columns(
        frame, time_col, outcome, lambda rows: validate_arfima_size(rows, difference, holdout_periods),
    )
    common._option_periods(forecast_periods, "forecast_periods", 1, common.MAX_FORECAST_PERIODS)
    level, critical = common._prediction_level(confidence_level)
    data = common._prepare_series(time, observations, forecast_periods, holdout_periods)
    if data.n_observed != len(data.values):
        row = np.flatnonzero(~data.observed)[0]
        raise TimeSeriesPackError("TIME_SERIES_NON_FINITE_VALUE", f"{_MODEL} requires a complete outcome at row {row}")
    library, engine = common._loaded()
    symbol = library.arboris_arfima_fit
    holdout = None
    if holdout_periods:
        start = data.train_size
        labels = [common._time_label(t) for t in data.time[start:]]
        training_parameters, training_fit, prediction = _fit(
            symbol, data.values[:start], labels, critical, difference_mode, d, deterministic,
        )
        count, metrics = common._holdout_metrics(data.values, data.observed, start, prediction)
        holdout = {
            "status": "completed", "training_steps": start, "training_observed": training_fit["n_observed"],
            "origin_time": common._time_label(data.time[start - 1]), "n_observed": count, "n_missing": 0,
            "training_parameters": training_parameters, "training_fit": training_fit,
            "forecast": prediction, "metrics": metrics,
        }
    parameters, fit, forecast = _fit(symbol, data.values, data.future, critical, difference_mode, d, deterministic)
    return {
        "schema_version": 1, "model": "arfima_0_d_0", "engine": engine, "parameters": parameters, "fit": fit,
        "policy": {
            "time_col": time_col, "outcome": outcome, "cadence": data.cadence, "order": parameters["order"],
            "difference_mode": difference_mode, "fractional_difference": parameters["order"][1],
            "deterministic": deterministic,
            "confidence_level": level, "estimation": "exact_finite_sample_stationary_gaussian_innovations_ml",
            "missing": "reject", "forecast_interval": "gaussian_conditional_on_fitted_parameters",
            "holdout_method": "training_prefix_fit_fixed_origin",
        },
        "forecast": forecast, "holdout": holdout,
    }
