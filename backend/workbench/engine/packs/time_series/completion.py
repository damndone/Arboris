"""Native time-series delivery evidence with explicit test definitions.

Tests describe the executed transformation and residuals. They do not select a
new model, prove stationarity/causality, or certify predictive coverage.
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.stats.stattools import jarque_bera
from statsmodels.tsa.stattools import adfuller, kpss

from workbench.canonical import sha256_canonical


def stationarity(values):
    values = np.asarray(values, dtype=float)
    policy = {'regression': 'c', 'adf_lags': 4, 'autolag': None, 'kpss_lags': 4}
    if len(values) < 14 or np.ptp(values) == 0:
        return {'policy': policy, 'adf': {'status': 'unavailable', 'reason': 'short_or_constant_series'},
                'kpss': {'status': 'unavailable', 'reason': 'short_or_constant_series'}}
    adf = adfuller(values, regression='c', maxlag=4, autolag=None)
    with warnings.catch_warnings(record=True):
        statistic, p, lags, critical = kpss(values, regression='c', nlags=4)
    return {'policy': policy,
        'adf': {'status': 'computed', 'statistic': float(adf[0]), 'p_value': float(adf[1]),
                'null': 'unit_root', 'p_value_status': 'mackinnon_approximation', 'nobs': int(adf[3])},
        'kpss': {'status': 'computed', 'statistic': float(statistic), 'p_value': float(p),
                 'null': 'level_stationarity', 'lags': int(lags),
                 'p_value_status': 'upper_bound' if p >= .1 else 'lower_bound' if p <= .01 else 'approximate'}}


def innovation_diagnostics(values, innovations, *, model_df, burn):
    errors = np.asarray(innovations, dtype=float)[burn:]
    result = {'burn_in': int(burn), 'residual_n': len(errors), 'model_df': int(model_df),
              'stationarity': stationarity(values),
              'innovations_sha256': sha256_canonical([float(e) if np.isfinite(e) else None for e in errors])}
    if not np.isfinite(errors).all() or len(errors) < 14 or np.ptp(errors) == 0:
        return result | {'status': 'unavailable', 'reason': 'nonfinite_or_short_innovations'}
    lag = min(10, len(errors)//5)
    if lag <= model_df:
        return result | {'status': 'unavailable', 'reason': 'diagnostic_lag_not_above_model_df'}
    lb = acorr_ljungbox(errors, lags=[lag], model_df=model_df, return_df=True).iloc[0]
    arch = het_arch(errors, nlags=lag, ddof=model_df)
    jb = jarque_bera(errors)
    return result | {'status': 'computed',
        'ljung_box': {'statistic': float(lb.lb_stat), 'p_value': float(lb.lb_pvalue),
            'lags': lag, 'df': lag-model_df, 'null': 'zero_autocorrelation_through_lag'},
        'arch_lm': {'statistic': float(arch[0]), 'p_value': float(arch[1]), 'lags': lag, 'ddof': model_df},
        'normality': {'statistic': float(jb[0]), 'p_value': float(jb[1]), 'test': 'jarque_bera',
            'interpretation': 'Rejection is distribution evidence, not an automatic model failure.'}}


def ordered_positions(frame, prepared):
    positions = np.asarray(prepared.retained_positions)
    if prepared.time_order == 'sort_by_time':
        permutation = np.argsort(frame.iloc[positions][prepared.time_column].to_numpy(), kind='stable')
        positions = positions[permutation]
    return positions.tolist()


def input_fingerprint(prepared):
    return sha256_canonical({'times': [str(t) for t in prepared.frame[prepared.time_column]],
        'values': prepared.frame[list(prepared.value_columns)].to_numpy(dtype=float).tolist(),
        'variables': list(prepared.value_columns), 'time_column': prepared.time_column})


def arima_evidence(fitted, prepared, frame, *, order, seasonal_order, trend):
    values = prepared.frame[prepared.value_columns[0]].to_numpy(dtype=float)
    transformed = values.copy()
    for _ in range(seasonal_order[1]):
        transformed = transformed[seasonal_order[3]:]-transformed[:-seasonal_order[3]]
    for _ in range(order[1]):
        transformed = np.diff(transformed)
    burn = max(int(fitted.loglikelihood_burn), int(fitted.filter_results.nobs_diffuse))
    innovations = fitted.filter_results.standardized_forecasts_error[0]
    diag = innovation_diagnostics(transformed, innovations,
        model_df=order[0]+order[2]+seasonal_order[0]+seasonal_order[2], burn=burn)
    times = prepared.frame[prepared.time_column]
    if pd.api.types.is_numeric_dtype(times):
        delta = np.diff(times.to_numpy(dtype=float))
        regular = bool(np.allclose(delta, delta[0], rtol=1e-12, atol=0))
        pattern = None
    else:
        pattern = pd.infer_freq(pd.DatetimeIndex(times))
        regular = pattern is not None
    diag.update(method='arima_native_innovations_v1', coefficient_covariance=fitted.cov_type,
        residual_definition='standardized_one_step_forecast_innovations_after_initialization',
        sampling={'regular': regular, 'observed_calendar_pattern': pattern, 'fills_or_interpolates': False},
        tested_transformation={'order': list(order), 'seasonal_order': list(seasonal_order)},
        ar_stationary=bool(np.all(np.abs(fitted.arroots) > 1)),
        ma_invertible=bool(np.all(np.abs(fitted.maroots) > 1)))
    positions = ordered_positions(frame, prepared)
    definition = {'input': input_fingerprint(prepared), 'order': list(order),
                  'seasonal_order': list(seasonal_order), 'trend': trend}
    return {'contract': 'time-series.completion.v1', 'model_type': 'arima', 'nobs': len(values),
        'time_column': prepared.time_column,
        'converged': bool(fitted.mle_retvals.get('converged', False)),
        'coefficients': {name: {'estimate': float(value), 'std_error': float(se) if np.isfinite(se) else None}
            for name, value, se in zip(fitted.param_names, fitted.params, fitted.bse, strict=True)},
        'input_fingerprint': input_fingerprint(prepared), 'ordered_positions': positions,
        'point_estimation_fingerprint': sha256_canonical(definition),
        'analysis_sample_fingerprint': sha256_canonical(positions), 'diagnostics': diag,
        'scientific_validity': 'not_certified'}
