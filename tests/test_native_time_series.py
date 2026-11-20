"""Scientific and verified-build checks for the native local-level operation."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from statsmodels.tsa.statespace.kalman_filter import FILTER_CONVENTIONAL, INVERT_UNIVARIATE, KalmanFilter

from workbench import native_time_series as local_level
from workbench.checks.ar_cancellation import cancellation_scope
from workbench.engine.packs.time_series.errors import TimeSeriesPackError
from workbench.native_build import artifact_names, default_output, manifest_path, verify_build
from workbench.tabular_io import read_table


PARAMETERS = dict(process_variance=0.5, observation_variance=2.0, initial_mean=3.0, initial_variance=2.0)
MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}


@pytest.fixture
def native_manifest():
    out = default_output(MODULE)
    artifacts = [manifest_path(out), *(out / name for name in artifact_names(MODULE))]
    if not any(path.exists() or path.is_symlink() for path in artifacts):
        pytest.skip('run native/time_series/build.py for the real Rust checks')
    return verify_build(MODULE, out)


def run(values, *, time=None, **options):
    data = pd.DataFrame({'t': range(len(values)) if time is None else time, 'y': values})
    return local_level.run_local_level(data, time_col='t', outcome='y', **(PARAMETERS | options))


def reference(values, *, parameters=PARAMETERS, concentrate_scale=False):
    model = KalmanFilter(
        1, 1, design=np.ones((1, 1)), transition=np.ones((1, 1)), selection=np.ones((1, 1)),
        state_cov=np.array([[parameters['process_variance']]]),
        obs_cov=np.array([[parameters['observation_variance']]]),
        filter_method=FILTER_CONVENTIONAL, inversion_method=INVERT_UNIVARIATE,
        timing_init_predicted=True, loglikelihood_burn=0,
    )
    model.initialize_known(np.array([parameters['initial_mean']]), np.array([[parameters['initial_variance']]]))
    model.bind(np.array(values, dtype=float)[:, None])
    model.filter_concentrated = concentrate_scale
    return model.filter(), model.loglike()


@pytest.mark.parametrize('values,variances', [
    ([np.nan, 7.0, np.nan, 6.0, 8.0, np.nan], {}),
    ([7.0, np.nan, 6.0, 8.0], {'initial_variance': 0.0}),
    ([7.0, 6.0, 8.0], {'process_variance': 0.0, 'observation_variance': 0.0001}),
])
def test_native_filter_and_forecasts_match_statsmodels(native_manifest, values, variances):
    horizon, level = 3, 0.8
    result = run(values, forecast_periods=horizon, confidence_level=level, **variances)
    expected, log_likelihood = reference([*values, *([np.nan] * horizon)], parameters=PARAMETERS | variances)
    n = len(values)
    rows = result['fit']['trace']['rows']
    fields = {
        'predicted_mean': expected.predicted_state[0, :n],
        'predicted_variance': expected.predicted_state_cov[0, 0, :n],
        'filtered_mean': expected.filtered_state[0, :n],
        'filtered_variance': expected.filtered_state_cov[0, 0, :n],
        'innovation': expected.forecasts_error[0, :n],
        'innovation_variance': expected.forecasts_error_cov[0, 0, :n],
        'log_likelihood': expected.llf_obs[:n],
    }
    for field, observed in fields.items():
        np.testing.assert_allclose(np.array([row[field] for row in rows], dtype=float), observed, **TOLERANCE)
    assert result['fit']['log_likelihood'] == pytest.approx(log_likelihood, rel=2e-12, abs=2e-12)
    assert result['fit']['n_missing'] == np.isnan(values).sum()
    assert result['forecast']['time'] == [n, n + 1, n + 2]
    forecast = result['forecast']
    mean, variance = expected.forecasts[0, n:], expected.forecasts_error_cov[0, 0, n:]
    margin = norm.ppf((1.0 + level) / 2.0) * np.sqrt(variance)
    np.testing.assert_allclose(forecast['mean'], mean, **TOLERANCE)
    np.testing.assert_allclose(forecast['observation_variance'], variance, **TOLERANCE)
    np.testing.assert_allclose(forecast['state_variance'], expected.predicted_state_cov[0, 0, n:-1], **TOLERANCE)
    np.testing.assert_allclose(forecast['lower'], mean - margin, **TOLERANCE)
    np.testing.assert_allclose(forecast['upper'], mean + margin, **TOLERANCE)
    assert result['engine']['abi_version'] == 1
    for key in ('binary_sha256', 'source_sha256', 'build_identity_sha256'):
        assert result['engine'][key] == native_manifest[key]
    json.dumps(result, allow_nan=False)


def test_holdout_is_fixed_origin_and_scores_only_observed_points(native_manifest):
    # t=0 posterior (5, 1), t=1 missing. Held-out forecast variance starts at 4.
    base = run([7.0, np.nan, 6.0, np.nan, 8.0], holdout_periods=3)
    changed = run([7.0, np.nan, -6.0, 4.0, -8.0], holdout_periods=3)
    diagnostic = base['holdout']
    assert diagnostic['forecast'] == changed['holdout']['forecast']
    assert base['forecast']['mean'] != changed['forecast']['mean']
    assert diagnostic['training_steps'] == 2 and diagnostic['origin_time'] == 1
    assert diagnostic['status'] == 'completed'
    assert diagnostic['n_observed'] == 2 and diagnostic['n_missing'] == 1
    assert diagnostic['forecast']['time'] == [2, 3, 4]
    assert diagnostic['forecast']['mean'] == [5.0, 5.0, 5.0]
    assert diagnostic['forecast']['observation_variance'] == [4.0, 4.5, 5.0]
    assert diagnostic['metrics'] == pytest.approx({
        'mae': 2.0, 'rmse': np.sqrt(5.0), 'interval_coverage': 1.0,
        'naive_mae': 1.0, 'naive_rmse': 1.0,
    })


def test_holdout_all_missing_returns_a_forecast_and_explicit_status(native_manifest):
    diagnostic = run([7.0, 6.0, np.nan, np.nan], holdout_periods=2)['holdout']
    assert diagnostic['status'] == 'no_observed_holdout'
    assert diagnostic['metrics'] is None
    assert len(diagnostic['forecast']['mean']) == 2


@pytest.mark.parametrize('frequency', ['MS', 'ME', 'QS-JAN', 'QE-DEC', 'YS-JAN', 'YE-DEC', 'h'])
def test_datetime_cadence_preserves_calendar_or_fixed_periods(native_manifest, frequency):
    dates = pd.date_range('2023-11-01', periods=6, freq=frequency, tz='America/New_York')
    result = run([7.0, 6.0, np.nan, 8.0], time=dates[:4], forecast_periods=2, holdout_periods=2)
    assert result['forecast']['time'] == [time.isoformat() for time in dates[4:]]
    assert result['holdout']['forecast']['time'] == [time.isoformat() for time in dates[2:4]]


@pytest.mark.parametrize('dates,forecast', [
    (['2024-01-31', '2024-02-29', '2024-03-31'], '2024-04-30T00:00:00'),
    (['2024-01-01T07:00', '2024-01-01T08:00', '2024-01-01T09:00'], '2024-01-01T10:00:00'),
    (['2024-01-31T00:00:00+05:30', '2024-02-29T00:00:00+05:30', '2024-03-31T00:00:00+05:30'],
     '2024-04-30T00:00:00+05:30'),
    (['2024-01-01T07:00:00Z', '2024-01-01T08:00:00Z', '2024-01-01T09:00:00+00:00'],
     '2024-01-01T10:00:00+00:00'),
])
def test_read_table_iso_csv_dates_keep_cadence_and_missing_rows(native_manifest, dates, forecast):
    payload = 't,y\n' + '\n'.join(f'{date},{value}' for date, value in zip(dates, ['7', '', '6'], strict=True))
    frame = read_table(BytesIO(payload.encode()), suffix='.csv')
    assert frame['t'].tolist() == dates
    result = local_level.run_local_level(frame, time_col='t', outcome='y', **PARAMETERS)
    assert result['policy']['cadence']['input'] == 'iso8601'
    assert result['fit']['n_missing'] == 1
    assert result['forecast']['time'] == [forecast]


@pytest.mark.parametrize('dates', [
    ['01/02/2024', '01/03/2024'],
    ['2024-01-01', '2024-01-02T00:00:00'],
    ['2024-01-01T00:00:00', '2024-01-02T00:00:00Z'],
    ['2024-01-01T00:00:00+01:00', '2024-01-02T00:00:00+02:00'],
    ['2024-02-28', '2024-02-30'],
    ['2024', '2025'],
])
def test_iso_time_refuses_ambiguous_or_invalid_strings(dates):
    with pytest.raises(TimeSeriesPackError) as failure:
        run([7.0, 6.0], time=dates)
    assert failure.value.reason_code == 'TIME_SERIES_INVALID_TIME'


def test_numeric_float32_cadence_and_bounded_trace(native_manifest):
    n = 520
    time = pd.Series((np.arange(n) * 0.1).astype(np.float32), dtype='Float32')
    result = run([7.0] * n, time=time, forecast_periods=2)
    assert result['forecast']['time'] == pytest.approx([52.0, 52.1], rel=1e-6)
    trace = result['fit']['trace']
    assert trace['first_index'] == n - 512 and trace['total_steps'] == n
    assert len(trace['rows']) == 512
    assert 'y' not in trace['rows'][0]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('values,time,options,code', [
    ([3.0], None, {}, 'TIME_SERIES_TOO_FEW_OBSERVATIONS'),
    ([3.0, 4.0], [2, 1], {}, 'TIME_SERIES_ORDER_INVALID'),
    ([3.0, 4.0], [1, 1], {}, 'TIME_SERIES_ORDER_INVALID'),
    ([3.0, 4.0, 5.0], [1, 2, 4], {}, 'TIME_SERIES_IRREGULAR_TIME'),
    ([3.0, 4.0, 5.0], [1.0, 1.1, 1.4], {}, 'TIME_SERIES_IRREGULAR_TIME'),
    ([3.0, 4.0], [1, np.nan], {}, 'TIME_SERIES_NON_FINITE_TIME'),
    ([3.0, 4.0], [False, True], {}, 'TIME_SERIES_INVALID_TIME'),
    ([3.0, 4.0], [2**53, 2**53 + 1], {}, 'TIME_SERIES_INVALID_TIME'),
    ([3.0, 4.0], [2**53 - 2, 2**53 - 1], {}, 'TIME_SERIES_INVALID_TIME'),
    ([3.0, np.inf], None, {}, 'TIME_SERIES_NON_FINITE_VALUE'),
    ([3.0, '4.0'], None, {}, 'TIME_SERIES_NON_NUMERIC_VALUE'),
    ([np.nan, np.nan], None, {}, 'TIME_SERIES_NO_OBSERVATIONS'),
    ([np.nan, 3.0], None, {'holdout_periods': 1}, 'TIME_SERIES_NO_TRAINING_OBSERVATIONS'),
    ([3.0, 4.0], None, {'holdout_periods': 2}, 'TIME_SERIES_INVALID_OPTION'),
    ([3.0, 4.0], None, {'forecast_periods': 201}, 'TIME_SERIES_INVALID_OPTION'),
    ([3.0, 4.0], None, {'observation_variance': 0}, 'TIME_SERIES_INVALID_OPTION'),
    ([3.0, 4.0], None, {'process_variance': True}, 'TIME_SERIES_INVALID_OPTION'),
    ([3.0, 4.0], None, {'initial_variance': -1}, 'TIME_SERIES_INVALID_OPTION'),
    ([3.0, 4.0], None, {'initial_mean': float('inf')}, 'TIME_SERIES_INVALID_OPTION'),
    ([3.0, 4.0], None, {'confidence_level': 1.0}, 'TIME_SERIES_INVALID_OPTION'),
])
def test_invalid_data_and_options_are_typed(values, time, options, code):
    with pytest.raises(TimeSeriesPackError) as failure:
        run(values, time=time, **options)
    assert failure.value.reason_code == code


def test_native_numeric_overflow_is_typed_and_does_not_return_a_result(native_manifest):
    with pytest.raises(TimeSeriesPackError, match='row 1') as failure:
        run([0.0, 1e308], initial_mean=0.0, initial_variance=0.0, observation_variance=1.0)
    assert failure.value.reason_code == 'TIME_SERIES_NUMERIC_FAILURE'


def test_filter_retains_a_small_analytic_posterior_at_extreme_variance_ratio(native_manifest):
    result = run([1.0, 1.0], process_variance=0.0, observation_variance=1e-308,
                 initial_mean=1.0, initial_variance=1e308)
    first, second = result['fit']['trace']['rows']
    assert first['filtered_variance'] == 1e-308
    assert second['filtered_variance'] == 5e-309
    assert result['fit']['final_state']['mean'] == 1.0


def test_cutoff_is_checked_after_native_computation(native_manifest, monkeypatch):
    original = local_level._loaded
    interrupted = RuntimeError('cancelled by the caller')
    native_loaded = False
    checked_after_load = False

    def load():
        nonlocal native_loaded
        native_loaded = True
        return original()

    def check():
        nonlocal checked_after_load
        if native_loaded:
            if checked_after_load:
                raise interrupted
            checked_after_load = True

    monkeypatch.setattr(local_level, '_loaded', load)
    with cancellation_scope(check), pytest.raises(RuntimeError) as failure:
        run([1.0, 2.0])
    assert failure.value is interrupted


def test_missing_and_unverified_builds_fail_before_load(monkeypatch, tmp_path):
    monkeypatch.setattr(local_level, 'default_output', lambda _module: tmp_path)
    monkeypatch.setattr(local_level, '_load_once', local_level._load_once.__wrapped__)
    monkeypatch.setattr(local_level.ctypes, 'CDLL', lambda _path: pytest.fail('an unverified binary was opened'))
    with pytest.raises(TimeSeriesPackError) as failure:
        run([7.0, 6.0])
    assert failure.value.reason_code == 'TIME_SERIES_NATIVE_BUILD_MISSING'
    (tmp_path / artifact_names(MODULE)[0]).write_bytes(b'unverified library')
    with pytest.raises(TimeSeriesPackError) as failure:
        run([7.0, 6.0])
    assert failure.value.reason_code == 'TIME_SERIES_NATIVE_BUILD_INVALID'


def test_a_changed_binary_cannot_reuse_the_cached_build_attestation(native_manifest, monkeypatch):
    assert run([7.0, 6.0])['engine']['binary_sha256'] == native_manifest['binary_sha256']
    identity = local_level._file_identity

    def changed(path):
        *stable, change_time = identity(path)
        return (*stable, change_time + 1)

    monkeypatch.setattr(local_level, '_file_identity', changed)
    with pytest.raises(TimeSeriesPackError, match='restart the application') as failure:
        run([7.0, 6.0])
    assert failure.value.reason_code == 'TIME_SERIES_NATIVE_BUILD_INVALID'


def run_fit(values, **options):
    frame = pd.DataFrame({'t': range(len(values)), 'y': values})
    parameters = {'variance_ratio': .4, 'initial_mean': 2., 'relative_initial_variance': .2} | options
    return local_level.run_local_level_fit(frame, time_col='t', outcome='y', **parameters)


@pytest.mark.parametrize('ratio,prior,values,holdout', [
    (.4, .2, [2., 5., -1., 3., 4.], 0),
    (.4, .2, [np.nan, 5., np.nan, 3., 100., -50.], 2),
    (0., 2.5, [0., np.nan, 3., 3., 3.], 1),
    (4., 0., [-1., np.nan, -2., -1.5, 1., -100.], 1),
])
def test_native_fit_matches_statsmodels_concentrated_scale_and_fixed_filter(native_manifest, ratio, prior, values, holdout):
    split = len(values) - holdout
    results = run_fit(values, variance_ratio=ratio, relative_initial_variance=prior,
                      holdout_periods=holdout, forecast_periods=3)
    unit = {'process_variance': ratio, 'observation_variance': 1., 'initial_mean': 2., 'initial_variance': prior}
    expected, likelihood = reference(values[:split], parameters=unit, concentrate_scale=True)
    estimate = results['estimation']
    assert estimate['method'] == 'gaussian_concentrated_ml_fixed_ratio'
    assert estimate['training_steps'] == split
    assert estimate['n_observed'] == np.isfinite(values[:split]).sum()
    assert estimate['n_missing'] == split - estimate['n_observed']
    assert estimate['variance_ratio'] == ratio and estimate['relative_initial_variance'] == prior
    assert estimate['training_log_likelihood'] == pytest.approx(likelihood, rel=2e-12, abs=2e-12)
    scale = results['parameters']['observation_variance']
    assert scale == pytest.approx(expected.scale, rel=2e-12, abs=2e-12)
    assert results['parameters']['process_variance'] == ratio * scale
    assert results['parameters']['initial_variance'] == prior * scale
    fixed = run(values, **results['parameters'], holdout_periods=holdout, forecast_periods=3)
    assert all(results[key] == fixed[key] for key in ('fit', 'forecast', 'holdout', 'engine'))
    assert results['policy']['parameter_mode'] == 'estimated_common_scale'
    assert results['policy']['forecast_interval'] == 'gaussian_observation_plugin'
    json.dumps(results, allow_nan=False)


def test_fitted_noise_ignores_held_out_values(native_manifest):
    left = run_fit([2., np.nan, 3., 4., 5., 8.], holdout_periods=2)
    right = run_fit([2., np.nan, 3., 4., -55., np.nan], holdout_periods=2)
    assert left['estimation'] == right['estimation'] and left['parameters'] == right['parameters']
    assert left['holdout']['forecast'] == right['holdout']['forecast']
    assert left['forecast']['mean'] != right['forecast']['mean']


@pytest.mark.parametrize('values,options,code', [
    ([2., np.nan, 2.], {}, 'TIME_SERIES_SCALE_UNIDENTIFIED'),
    ([1., np.nan, 7.], {'holdout_periods': 1}, 'TIME_SERIES_INSUFFICIENT_TRAINING_OBSERVATIONS'),
    ([1., 7.], {'variance_ratio': -1}, 'TIME_SERIES_INVALID_OPTION'),
    ([1., 7.], {'relative_initial_variance': -1}, 'TIME_SERIES_INVALID_OPTION'),
    ([1e-200, 0.], {'initial_mean': 0., 'variance_ratio': 0., 'relative_initial_variance': 0.}, 'TIME_SERIES_NUMERIC_FAILURE'),
])
def test_scale_fit_abnormal_inputs_have_explicit_status(native_manifest, values, options, code):
    with pytest.raises(TimeSeriesPackError) as failure:
        run_fit(values, **options)
    assert failure.value.reason_code == code
