from __future__ import annotations

import ctypes
import math

import numpy as np

from . import native_time_series as common
from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series_abi import DOUBLE, SIZE

MAX_ETS_TREND_ROWS = 100_000
MAX_ETS_TREND_AUTO_ROWS = 2_000
_MIN_GAIN, _MAX_GAIN = 0.0001, 0.9999
_MIN_PHI, _MAX_PHI = 0.8, 0.98
_GAIN_MODES = {"fixed": 0, "estimate": 1}


def validate_ets_trend_size(rows, holdout_periods, free_gains=0):
    common._option_periods(holdout_periods, "holdout_periods", 0, common.MAX_HOLDOUT_PERIODS)
    maximum = MAX_ETS_TREND_AUTO_ROWS if free_gains else MAX_ETS_TREND_ROWS
    minimum = (4, 24, 40)[free_gains]
    if rows > maximum:
        raise TimeSeriesPackError("TIME_SERIES_SIZE_LIMIT", f"ETS trend supports at most {maximum} rows")
    if rows - holdout_periods < minimum:
        count = minimum if free_gains else "four"
        raise TimeSeriesPackError("TIME_SERIES_TOO_FEW_OBSERVATIONS", f"ETS trend requires at least {count} training outcomes")


def _validate_phi(phi):
    if phi != 1.0 and not _MIN_PHI <= phi <= _MAX_PHI:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", f"phi must equal one or lie in [{_MIN_PHI}, {_MAX_PHI}]")
    return phi


def validate_ets_trend_parameters(alpha, beta, phi):
    alpha = common._option_number(alpha, "alpha")
    beta = common._option_number(beta, "beta")
    phi = common._option_number(phi, "phi")
    if not _MIN_GAIN <= beta <= alpha <= _MAX_GAIN:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", f"require {_MIN_GAIN} <= beta <= alpha <= {_MAX_GAIN}")
    return alpha, beta, _validate_phi(phi)


def _fit(symbol, values, future, critical, smoothing, model, modes):
    alpha, beta, phi = smoothing
    arguments = (_GAIN_MODES[modes[0]], alpha, _GAIN_MODES[modes[1]], beta, phi) if modes else smoothing
    estimates = np.empty(15 if modes else 7, dtype=np.float64)
    forecast = np.empty((len(future), 2), dtype=np.float64)
    error = SIZE(-1)
    with common._native_checkpoint() as poll:
        status = symbol(
            values.ctypes.data_as(DOUBLE), values.size, *arguments, len(future),
            estimates.ctypes.data_as(DOUBLE), estimates.size, forecast.ctypes.data_as(DOUBLE), forecast.size,
            ctypes.byref(error), poll,
        )
    if status:
        if status == 1 and error.value < values.size:
            raise TimeSeriesPackError("TIME_SERIES_NON_FINITE_VALUE", f"{model} requires a complete outcome at row {error.value}")
        unidentified = ("unidentified innovation variance, initial state, or smoothing profile" if modes
                        else "no identifiable positive innovation variance or initial state")
        code, message = {
            1: ("TIME_SERIES_BAD_INPUT", f"{model} rejected its input layout"),
            2: ("TIME_SERIES_NUMERIC_FAILURE", f"{model} exceeded its numerical range"),
            3: ("TIME_SERIES_TOO_FEW_OBSERVATIONS", f"{model} has too few training outcomes"),
            4: ("TIME_SERIES_ETS_TREND_UNIDENTIFIED", f"{model} has {unidentified}"),
            5: ("TIME_SERIES_ETS_TREND_NONCONVERGENCE", f"{model} search did not verify a stable interior gain estimate"),
            6: ("TIME_SERIES_SIZE_LIMIT", f"{model} specification exceeds the native limits"),
            8: ("TIME_SERIES_ETS_TREND_BOUNDARY", f"{model} search could not separate the best gain estimate from a boundary"),
        }.get(status, ("TIME_SERIES_NATIVE_EXECUTION_ERROR", f"native {model} did not return a verified result"))
        raise TimeSeriesPackError(code, message)
    if not np.isfinite(estimates).all() or not np.isfinite(forecast).all():
        raise TimeSeriesPackError("TIME_SERIES_NUMERIC_FAILURE", f"native {model} returned a nonfinite result")
    initial_level, initial_slope, final_level, final_slope, variance, likelihood, n = map(float, estimates[:7])
    k = 3 + (modes.count("estimate") if modes else 0)
    fit = {
        "initial_level": initial_level, "initial_slope": initial_slope,
        "final_level": final_level, "final_slope": final_slope,
        "innovation_variance": variance, "log_likelihood": likelihood,
        "n_observed": int(n), "n_effective": int(n), "n_missing": 0,
        "aic": 2.0 * (k - likelihood), "bic": k * math.log(n) - 2.0 * likelihood,
    }
    if modes:
        alpha, beta, free, evaluations, gradient, curvature, boundary_gap, agreements = map(float, estimates[7:])
        fit["estimated_parameter_count"] = k
        fit["optimizer_diagnostics"] = {
            "free_gain_count": int(free), "likelihood_evaluations": int(evaluations),
            "max_free_derivative": gradient, "minimum_profile_curvature": curvature,
            "boundary_log_variance_gap": boundary_gap, "agreeing_searches": int(agreements),
        }
    parameters = {"alpha": alpha, "beta": beta, "phi": phi}
    return parameters, fit, common._interval_forecast(forecast, future, critical, model)


def run_ets_trend(
    frame, *, time_col, outcome, alpha, beta, phi=1.0,
    forecast_periods=1, holdout_periods=0, confidence_level=0.95,
):
    smoothing = validate_ets_trend_parameters(alpha, beta, phi)
    return _run(frame, time_col, outcome, smoothing, None, forecast_periods, holdout_periods, confidence_level)


def run_ets_trend_auto(
    frame, *, time_col, outcome, phi=1.0, alpha=None, beta=None,
    forecast_periods=1, holdout_periods=0, confidence_level=0.95,
):
    if alpha is not None and beta is not None:
        raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", "leave alpha or beta unset to estimate it, or use Additive ETS trend")
    modes = tuple("estimate" if value is None else "fixed" for value in (alpha, beta))
    gains = []
    for name, value in (("alpha", alpha), ("beta", beta)):
        gain = 0.0 if value is None else common._option_number(value, name)
        width = gain - _MIN_GAIN if name == "alpha" else _MAX_GAIN - gain
        if value is not None and (not _MIN_GAIN <= gain <= _MAX_GAIN or width < 0.004):
            raise TimeSeriesPackError("TIME_SERIES_INVALID_OPTION", f"fixed {name} must leave a free gain range of at least 0.004")
        gains.append(gain)
    smoothing = (*gains, _validate_phi(common._option_number(phi, "phi")))
    return _run(frame, time_col, outcome, smoothing, modes, forecast_periods, holdout_periods, confidence_level)


def _run(frame, time_col, outcome, smoothing, modes, forecast_periods, holdout_periods, confidence_level):
    free_gains = modes.count("estimate") if modes else 0
    trend = "A" if smoothing[2] == 1.0 else "Ad"
    model = f"ETS(A,{trend},N)"
    time, observations = common._series_columns(
        frame, time_col, outcome, lambda rows: validate_ets_trend_size(rows, holdout_periods, free_gains),
    )
    common._option_periods(forecast_periods, "forecast_periods", 1, common.MAX_FORECAST_PERIODS)
    level, critical = common._prediction_level(confidence_level)
    data = common._prepare_series(time, observations, forecast_periods, holdout_periods)
    if data.n_observed != len(data.values):
        row = np.flatnonzero(~data.observed)[0]
        raise TimeSeriesPackError("TIME_SERIES_NON_FINITE_VALUE", f"{model} requires a complete outcome at row {row}")
    library, engine = common._loaded()
    symbol = library.arboris_ets_trend_fit_auto if modes else library.arboris_ets_trend_fit
    holdout = None
    if holdout_periods:
        start = data.train_size
        labels = [common._time_label(t) for t in data.time[start:]]
        training_parameters, training_fit, prediction = _fit(symbol, data.values[:start], labels, critical, smoothing, model, modes)
        count, metrics = common._holdout_metrics(data.values, data.observed, start, prediction)
        holdout = {
            "status": "completed", "training_steps": start, "training_observed": training_fit["n_observed"],
            "origin_time": common._time_label(data.time[start - 1]), "n_observed": count, "n_missing": 0,
            "training_fit": training_fit, "forecast": prediction, "metrics": metrics,
        }
        if modes:
            holdout["training_parameters"] = training_parameters
    parameters, fit, forecast = _fit(symbol, data.values, data.future, critical, smoothing, model, modes)
    policy = {
        "time_col": time_col, "outcome": outcome, "cadence": data.cadence, "components": ["A", trend, "N"],
        "smoothing_parameters": "fixed_innovations_coefficients", "initialization": "conditional_ml_initial_level_and_slope",
        "estimation": "conditional_gaussian_innovations_ml", "variance_estimation": "innovation_sse_over_n",
        "confidence_level": level, "missing": "reject", "forecast_interval": "gaussian_conditional_on_fitted_parameters",
        "holdout_method": "training_prefix_fit_fixed_origin",
    }
    if modes:
        policy.update(
            smoothing_parameters="profiled_innovations_coefficients",
            smoothing_modes={"alpha": modes[0], "beta": modes[1], "phi": "fixed"},
            optimizer="bounded_interior_profile_likelihood",
        )
    return {
        "schema_version": 1, "model": f"ets_a_{trend.lower()}_n", "model_name": model, "engine": engine,
        "parameters": parameters, "fit": fit, "policy": policy,
        "forecast": forecast, "holdout": holdout,
    }
