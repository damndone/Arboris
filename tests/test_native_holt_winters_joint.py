import math
import os
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from workbench import native_time_series, native_time_series_ets as ets
from workbench.checks.ar_cancellation import cancellation_scope
from workbench.engine.packs.time_series.errors import TimeSeriesPackError
from workbench.native_build import artifact_names, default_output, manifest_path


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
R_GAINS = (0.44066600468412837, 0.2608600697847554, 0.41492285816608288)
R_FORECAST = (
    (-13.934680865677278, 1.0149756485480694),
    (-13.488446186032133, 1.3283103544135888),
    (-12.665777265893871, 1.7847089460680285),
    (-14.24984664055455, 2.4109952003104311),
    (-17.730005632621648, 3.7128852898324394),
    (-17.2837709529765, 4.7594181996478948),
    (-16.461102032838241, 6.0563101024484407),
    (-18.045171407498923, 7.6303847750331206),
)


@pytest.fixture
def native_receipt(monkeypatch):
    private = os.environ.get('WORKBENCH_NATIVE_TIME_SERIES_TEST_OUTPUT')
    out = Path(private).resolve() if private else default_output(MODULE)
    if not private and not any(path.exists() or path.is_symlink() for path in (
        out / artifact_names(MODULE)[0], manifest_path(out),
    )):
        pytest.skip('run native/time_series/build.py for the Rust checks')
    monkeypatch.setattr(native_time_series, 'default_output', lambda _: out)
    native_time_series._load_once.cache_clear()
    try:
        _, receipt = native_time_series._loaded()
        yield receipt
    finally:
        native_time_series._load_once.cache_clear()


def portable_simulation():
    seed = 775
    seasonal = [-2., .5, 1., .5]
    level, trend = 15., .4
    values = []
    for index in range(160):
        innovation = 0.
        for _ in range(12):
            seed = seed * 16807 % 2147483647
            innovation += seed / 2147483647
        innovation -= 6.
        phase = index % 4
        prediction = level + trend
        values.append(prediction + seasonal[phase] + innovation)
        level = prediction + .38 * innovation
        trend += .38 * .25 * innovation
        seasonal[phase] += (1. - .38) * .53 * innovation
    return np.array(values)


def run(values, *, clock=None, **options):
    time = np.arange(len(values)) if clock is None else clock
    frame = pd.DataFrame({'time': time, 'y': values})
    return ets.run_holt_winters_fit_joint(
        frame, time_col='time', outcome='y', **({'season_period': 4} | options),
    )


def test_joint_r_forecast_and_holdout_use_separate_fits(native_receipt):
    values = portable_simulation()
    dates = pd.date_range('1920-03-31', periods=len(values), freq=pd.offsets.QuarterEnd(startingMonth=3))
    result = run(values, clock=dates, holdout_periods=8, forecast_periods=2, confidence_level=.9)
    prefix = run(values[:-8], clock=dates[:-8], forecast_periods=8, confidence_level=.9)
    changed = values.copy()
    changed[-8:] += [.2, -.3, .1, -.4, .3, .1, -.1, .2]
    repeated = run(changed, clock=dates, holdout_periods=8, forecast_periods=2, confidence_level=.9)

    holdout = result['holdout']
    assert result['engine'] == native_receipt
    assert holdout['forecast'] == prefix['forecast'] == repeated['holdout']['forecast']
    assert holdout['training_parameters'] == prefix['parameters'] == repeated['holdout']['training_parameters']
    assert holdout['training_estimation'] == prefix['estimation'] == repeated['holdout']['training_estimation']
    assert holdout['training_fit'] == {k: v for k, v in prefix['fit'].items() if k != 'trace'}
    assert holdout['training_fit'] == repeated['holdout']['training_fit']
    assert result['parameters'] != repeated['parameters']
    assert result['forecast'] != repeated['forecast']
    assert holdout['metrics'] != repeated['holdout']['metrics']
    assert holdout['origin_time'] == dates[-9].isoformat()
    assert holdout['forecast']['time'] == [date.isoformat() for date in dates[-8:]]
    assert result['forecast']['time'] == [
        (dates[-1] + step * pd.offsets.QuarterEnd(startingMonth=3)).isoformat() for step in (1, 2)
    ]
    assert result['fit']['n_effective'] == 152
    assert holdout['training_fit']['n_effective'] == 144
    assert holdout['training_fit']['sse'] == pytest.approx(145.39748729528628, rel=0, abs=1e-9)
    assert result['policy']['initialization'] == 'two_complete_cycles'
    assert result['policy']['smoothing_parameterization'] == 'traditional_holt_winters_weights'

    np.testing.assert_allclose(list(prefix['parameters'].values()), R_GAINS, rtol=0, atol=4e-7)
    predicted = holdout['forecast']
    reference = np.asarray(R_FORECAST)
    actual = np.column_stack([predicted['mean'], predicted['observation_variance']])
    np.testing.assert_allclose(actual, reference, rtol=0, atol=5e-7)
    margin = -NormalDist().inv_cdf(.05) * np.sqrt(actual[:, 1])
    np.testing.assert_allclose(predicted['upper'], actual[:, 0] + margin, rtol=0, atol=1e-12)
    np.testing.assert_allclose(predicted['lower'], actual[:, 0] - margin, rtol=0, atol=1e-12)
    naive = np.tile(values[-12:-8], 2)
    assert holdout['metrics']['naive_rmse'] == pytest.approx(
        np.sqrt(np.mean((values[-8:] - naive) ** 2)), rel=0, abs=1e-12,
    )


def test_boundary_fit_is_reported_without_fallback(native_receipt):
    phases = (-2., .5, 1., .5)
    values = [30. + .15*t + phases[t % 4]*(1. + .05*t) + .25*math.sin(.9*t) for t in range(120)]
    with pytest.raises(TimeSeriesPackError) as error:
        run(values)
    assert error.value.reason_code == 'TIME_SERIES_HOLT_WINTERS_BOUNDARY'


def test_owner_cancellation_propagates_during_joint_search(native_receipt):
    failure = RuntimeError('owner stops joint Holt-Winters')
    polls = 0

    def stop():
        nonlocal polls
        polls += 1
        if polls == 20:
            raise failure

    with cancellation_scope(stop), pytest.raises(RuntimeError) as error:
        run(portable_simulation())
    assert error.value is failure
    assert polls == 20


@pytest.mark.parametrize(('values', 'options', 'reason'), [
    (np.arange(31.), {}, 'TIME_SERIES_TOO_FEW_OBSERVATIONS'),
    (np.arange(35.), {'holdout_periods': 4}, 'TIME_SERIES_TOO_FEW_OBSERVATIONS'),
    (np.arange(100.), {'season_period': 25}, 'TIME_SERIES_INVALID_OPTION'),
    (np.arange(2_001.), {}, 'TIME_SERIES_SIZE_LIMIT'),
    (np.arange(40.), {'clock': [*range(39), 50]}, 'TIME_SERIES_IRREGULAR_TIME'),
    (np.r_[np.arange(39.), np.nan], {}, 'TIME_SERIES_NON_FINITE_VALUE'),
])
def test_joint_rejects_invalid_input_before_loading(monkeypatch, values, options, reason):
    monkeypatch.setattr(ets, '_loaded', lambda: pytest.fail('invalid request reached the native loader'))
    with pytest.raises(TimeSeriesPackError) as error:
        run(values, **options)
    assert error.value.reason_code == reason
