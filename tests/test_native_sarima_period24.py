import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench import native_time_series, native_time_series_xreg
from workbench.engine.packs.time_series.errors import TimeSeriesPackError
from workbench.native_build import artifact_names, default_output, manifest_path
from workbench.native_research import validate_native_research_size


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
PERIOD = 24
HORIZON = 30
HISTORY = 110


@pytest.fixture
def verified_native(monkeypatch):
    private = os.environ.get('WORKBENCH_NATIVE_TIME_SERIES_TEST_OUTPUT')
    output = Path(private).resolve() if private else default_output(MODULE)
    if not private and not any(path.exists() or path.is_symlink() for path in (
        output / artifact_names(MODULE)[0], manifest_path(output),
    )):
        pytest.skip('run native/time_series/build.py for the Rust checks')
    monkeypatch.setattr(native_time_series, 'default_output', lambda _: output)
    native_time_series._load_once.cache_clear()
    try:
        _, receipt = native_time_series._loaded()
        yield receipt
    finally:
        native_time_series._load_once.cache_clear()


def levels(seed, start):
    observations = np.empty(HISTORY)
    for i in range(HISTORY):
        seed = 16807 * seed % 2147483647
        if i < PERIOD:
            observations[i] = start + (i % 7) * .75
        else:
            observations[i] = observations[i - PERIOD] + (seed - 1073741823) / 1073741824
    return observations


def hourly_frame():
    clock = pd.date_range('2025-01-01', periods=HISTORY + HORIZON, freq='h', tz='UTC')
    values = np.r_[levels(173, 30.), np.full(HORIZON, np.nan)]
    values[[35, 61, 62, 108, 109]] = np.nan
    return pd.DataFrame({'time': clock.strftime('%Y-%m-%dT%H:%M:%SZ'), 'y': values})


def hourly_exogenous_frame():
    frame = hourly_frame()
    t = np.arange(1, len(frame) + 1)
    frame['promotion'] = np.sin(.17 * t) + .012 * t
    frame.loc[HISTORY:, 'promotion'] += 1.4
    frame['load'] = np.cos(.27 * t) + .15 * np.sin(.05 * t)
    frame.loc[:HISTORY - 1, 'y'] = (
        levels(274, 13.) + 2.7 * frame['promotion'].iloc[:HISTORY] - 1.2 * frame['load'].iloc[:HISTORY]
    )
    frame.loc[[46, 66, 107, 109], 'y'] = np.nan
    return frame


def run(frame, **options):
    return native_time_series.run_sarima(
        frame, time_col='time', outcome='y',
        **({'ar_order': 0, 'seasonal_period': PERIOD, 'forecast_periods': HORIZON} | options),
    )


def run_x(frame, **options):
    return native_time_series_xreg.run_sarimax(
        frame, time_col='time', outcome='y', predictors=['promotion', 'load'],
        **({'ar_order': 0, 'seasonal_period': PERIOD, 'forecast_periods': HORIZON} | options),
    )


def validate_preview(historical_rows, predictors=(), **options):
    bindings = {'time_col': 'time', 'outcome': 'y'}
    options = {
        'ar_order': 0, 'seasonal_differences': 1,
        'seasonal_period': PERIOD, 'forecast_periods': HORIZON,
    } | options
    operation = 'time_series.native_sarima'
    rows = historical_rows
    if predictors:
        bindings['predictors'] = list(predictors)
        operation = 'time_series.native_sarimax'
        rows += options['forecast_periods']
    spec = {'operation_id': operation, 'input_mode': 'frame', 'column_bindings': bindings, 'options': options}
    validate_native_research_size(operation, spec, rows)


@pytest.mark.parametrize(('predictors', 'capacity'), [((), 102), (('promotion',), 101)])
def test_daily_preview_refuses_model_above_native_setup_budget(predictors, capacity):
    options = {'ar_order': 2, 'seasonal_ar_order': 1, 'seasonal_differences': 0}
    with pytest.raises(TimeSeriesPackError) as error:
        validate_preview(100, predictors, **options)
    assert error.value.reason_code == 'TIME_SERIES_SIZE_LIMIT'
    assert 'full historical fit (100 rows)' in str(error.value)
    assert f'requires at least 144 likelihood evaluations but its native work budget allows {capacity}' in str(error.value)

    validate_preview(100, predictors, **(options | {'seasonal_period': 12}))


@pytest.mark.parametrize(('predictors', 'deterministic', 'max_history'), [
    ((), 'none', 538),
    (('promotion',), 'none', 448),
    (('promotion', 'load'), 'mean', 443),
])
def test_daily_preview_checks_full_fit_beyond_admissible_holdout_prefix(predictors, deterministic, max_history):
    options = {
        'seasonal_ar_order': 1, 'seasonal_differences': 0, 'seasonal_ma_order': 1,
        'deterministic': deterministic, 'holdout_periods': 12,
    }
    validate_preview(max_history, predictors, **options)
    with pytest.raises(TimeSeriesPackError) as error:
        validate_preview(max_history + 1, predictors, **options)
    assert error.value.reason_code == 'TIME_SERIES_SIZE_LIMIT'
    assert f'full historical fit ({max_history + 1} rows)' in str(error.value)
    assert 'requires at least 98 likelihood evaluations but its native work budget allows 97' in str(error.value)

    with pytest.raises(TimeSeriesPackError, match=rf'holdout training fit \({max_history + 1} rows\)'):
        validate_preview(max_history + 13, predictors, **options)


@pytest.mark.parametrize(('historical_rows', 'predictors', 'options'), [
    (110, (), {}),
    (110, ('promotion', 'load'), {'holdout_periods': 12}),
    (264, (), {'seasonal_differences': 0, 'seasonal_ar_order': 1, 'deterministic': 'mean'}),
    (264, (), {'seasonal_differences': 0, 'seasonal_ma_order': 1}),
])
def test_daily_preview_admits_verified_seasonal_cases(historical_rows, predictors, options):
    validate_preview(historical_rows, predictors, **options)


def test_hourly_period_24_preserves_time_and_missing_phase_uncertainty(verified_native):
    frame = hourly_frame()
    result = run(frame.iloc[:HISTORY])
    assert result['engine'] == verified_native
    assert result['policy']['seasonal_order'] == [0, 1, 0, 24]
    assert result['policy']['cadence']['kind'] == 'datetime'
    assert pd.Timedelta(result['policy']['cadence']['step']) == pd.Timedelta(hours=1)
    assert result['fit']['n_observed'] == 105 and result['fit']['n_effective'] == 81
    assert result['fit']['log_likelihood'] == pytest.approx(-68.685303501556945, rel=0, abs=3e-11)
    assert result['fit']['innovation_variance'] == pytest.approx(.31110781202509663, rel=0, abs=3e-11)
    assert result['forecast']['time'] == [time.isoformat() for time in pd.to_datetime(frame['time'].iloc[HISTORY:])]
    actual = frame['y'].to_numpy()
    for index, (mean, variance) in enumerate(zip(result['forecast']['mean'], result['forecast']['observation_variance'])):
        target = HISTORY + index
        last = next(t for t in range(target - PERIOD, -1, -PERIOD) if np.isfinite(actual[t]))
        assert mean == pytest.approx(actual[last], rel=0, abs=3e-11)
        assert variance == pytest.approx(.31110781202509663 * ((target-last)/PERIOD), rel=0, abs=3e-11)


def test_daily_seasonal_regression_uses_known_future_x_and_independent_holdout(verified_native):
    frame = hourly_exogenous_frame()
    result = run_x(frame, holdout_periods=12)
    np.testing.assert_allclose(
        list(result['parameters']['exogenous'].values()), [2.7118079619830433, -1.389888485668145],
        rtol=0, atol=3e-11,
    )
    assert result['fit']['n_effective'] == 82
    assert result['fit']['log_likelihood'] == pytest.approx(-75.106336087327222, rel=0, abs=3e-11)
    assert result['forecast']['mean'][-1] == pytest.approx(22.51190189940942, rel=0, abs=3e-11)
    changed_future = frame.copy()
    changed_future.loc[HISTORY+4, 'promotion'] += .75
    scenario = run_x(changed_future, holdout_periods=12)
    assert scenario['fit'] == result['fit'] and scenario['parameters'] == result['parameters']
    assert scenario['holdout'] == result['holdout']
    assert scenario['forecast']['observation_variance'] == result['forecast']['observation_variance']
    expected_shift = np.zeros(HORIZON)
    expected_shift[4] = .75 * 2.7118079619830433
    np.testing.assert_allclose(
        np.asarray(scenario['forecast']['mean']) - result['forecast']['mean'], expected_shift,
        rtol=0, atol=3e-11,
    )

    changed_holdout = frame.copy()
    changed_holdout.loc[HISTORY-12:HISTORY-1, 'y'] += np.linspace(-.5, .6, 12)
    revised = run_x(changed_holdout, holdout_periods=12)
    assert revised['holdout']['forecast'] == result['holdout']['forecast']
    assert revised['holdout']['metrics'] != result['holdout']['metrics']
    assert revised['parameters'] != result['parameters']


@pytest.mark.parametrize(('options', 'reason'), [
    ({'seasonal_period': 23}, 'TIME_SERIES_INVALID_OPTION'),
    ({'seasonal_ar_order': 1}, 'TIME_SERIES_SIZE_LIMIT'),
])
def test_period_24_does_not_extend_other_periods_or_state_bound(monkeypatch, options, reason):
    monkeypatch.setattr(native_time_series, '_loaded', lambda: pytest.fail('invalid request reached the native loader'))
    with pytest.raises(TimeSeriesPackError) as error:
        run(hourly_frame().iloc[:HISTORY], **options)
    assert error.value.reason_code == reason


def test_daily_regression_refuses_missing_anchor_and_future_predictor(verified_native):
    frame = hourly_exogenous_frame()
    frame.loc[23, 'y'] = np.nan
    with pytest.raises(TimeSeriesPackError) as anchor:
        run_x(frame)
    assert anchor.value.reason_code == 'TIME_SERIES_MISSING_SEASONAL_ANCHOR'
    assert 'row 23' in str(anchor.value)

    frame = hourly_exogenous_frame()
    frame.loc[HISTORY+4, 'load'] = np.nan
    with pytest.raises(TimeSeriesPackError) as predictor:
        run_x(frame)
    assert predictor.value.reason_code == 'TIME_SERIES_INVALID_REGRESSOR'
    assert "future predictor 'load' requires a finite value at row 4" in str(predictor.value)
