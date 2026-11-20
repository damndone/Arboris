import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from workbench.engine.packs.time_series.errors import TimeSeriesPackError
from workbench.native_cart import run_cart
from workbench.native_portfolio import run_min_variance
from workbench.native_time_series_xreg import run_arimax, run_sarimax
from workbench.native_var import run_var
from workbench.native_build import default_output, manifest_path


def _require_native(name):
    module = Path(__file__).resolve().parents[1] / 'native' / name
    if not manifest_path(default_output(module)).is_file():
        pytest.skip(f'build native/{name} for extension verification')


def xreg_frame(seasonal=False):
    generator = np.random.default_rng(281)
    past, future = 100, 4
    t = np.arange(past + future)
    x = generator.normal(size=len(t))
    errors = generator.normal(scale=0.25, size=past)
    if seasonal:
        errors[:4] += [2.0, -1.0, 3.0, -2.0]
        for i in range(4, past):
            errors[i] += errors[i - 4]
    outcome = np.r_[2.5 * x[:past] + errors, np.full(future, np.nan)]
    return pd.DataFrame({'t': t, 'x': x, 'y': outcome})


@pytest.mark.parametrize('seasonal', [False, True])
def test_known_future_x_changes_only_the_conditioned_forecast(seasonal):
    _require_native('time_series')
    frame = xreg_frame(seasonal)
    estimate = run_sarimax if seasonal else run_arimax
    args = dict(time_col='t', outcome='y', predictors=['x'], forecast_periods=4, holdout_periods=8, ar_order=0)
    if seasonal:
        args.update(seasonal_period=4, seasonal_differences=1)
    first = estimate(frame, **args)
    shifted = frame.copy()
    shifted.loc[100:, 'x'] += 3
    second = estimate(shifted, **args)
    assert first['parameters'] == second['parameters']
    assert first['fit'] == second['fit']
    assert first['holdout'] == second['holdout']
    slope = first['parameters']['exogenous']['x']
    assert slope == pytest.approx(2.5, abs=0.09)
    np.testing.assert_allclose(np.subtract(second['forecast']['mean'], first['forecast']['mean']), 3 * slope,
                               rtol=2e-13, atol=2e-13)
    assert first['forecast']['observation_variance'] == second['forecast']['observation_variance']
    assert first['forecast']['time'] == [100, 101, 102, 103]
    assert first['holdout']['training_steps'] == 92
    assert first['fit']['n_observed'] == 100


def test_exogenous_rows_and_outcomes_have_separate_validation():
    _require_native('time_series')
    frame = xreg_frame()
    args = dict(time_col='t', outcome='y', predictors=['x'], forecast_periods=4, ar_order=0)
    frame.loc[100, 'y'] = 1
    with pytest.raises(TimeSeriesPackError, match='outcomes must be blank'):
        run_arimax(frame, **args)
    frame.loc[100, 'y'] = np.nan
    frame.loc[102, 'x'] = np.nan
    with pytest.raises(TimeSeriesPackError, match='future predictor'):
        run_arimax(frame, **args)


def var_frame():
    generator = np.random.default_rng(351)
    values = generator.normal(size=(100, 2))
    transition = np.array([[0.41, -0.28], [0.17, 0.39]])
    for i in range(1, len(values)):
        values[i] += transition @ values[i - 1]
    return pd.DataFrame({'t': np.arange(len(values)), 'a': values[:, 0], 'b': values[:, 1]})


def test_var_reuses_the_same_fit_for_block_test_and_innovation_responses():
    _require_native('time_series')
    frame = var_frame()
    options = dict(time_col='t', series_columns=['a', 'b'], lag_order=2, forecast_periods=5, holdout_periods=7)
    baseline = run_var(frame, **options)
    result = run_var(frame, **options, irf_periods=5, granger_effect='a', granger_excluded=['b'])
    assert result['fit'] == baseline['fit'] and result['forecast'] == baseline['forecast']
    assert result['holdout'] == baseline['holdout']
    irf = result['local']['impulse_responses']
    np.testing.assert_array_equal(irf['response'][0], np.eye(2))
    np.testing.assert_array_equal(irf['forecast_covariance'][1:], result['local']['forecast_covariance'])
    granger = result['diagnostics']['granger']
    assert granger['df_num'] == 2 and granger['df_den'] == result['fit']['residual_df']
    assert 0 <= granger['p_value'] <= 1
    assert granger['restricted_sse'] >= granger['unrestricted_sse']
    assert set(result['holdout']['metrics']) == {'a', 'b'}


def test_tree_fit_is_frozen_when_only_the_reserved_rows_change():
    _require_native('ridge')
    x = np.linspace(-2, 2, 120)
    frame = pd.DataFrame({'t': range(len(x)), 'x': x, 'class': (x > -0.6).astype(int)})
    options = dict(outcome='class', predictors=['x'], time_col='t', holdout_fraction=0.25, max_depth=2, min_samples_leaf=2)
    before = run_cart(frame, **options)
    changed = frame.copy()
    changed.loc[90:, 'class'] = 0
    after = run_cart(changed, **options)
    assert before['prediction_basis'] == after['prediction_basis']
    assert before['model_structure']['root_predictor'] == 'x'
    assert before['model_structure']['node_count'] == 3
    assert before['metrics']['accuracy'] == 1 and after['metrics']['accuracy'] == 0
    assert before['split']['train_rows'] == 90 and before['split']['test_rows'] == 30


def test_minimum_variance_uses_one_completed_window_and_distinct_covariances():
    _require_native('quant_replay')
    generator = np.random.default_rng(96)
    rows = 90
    frame = pd.DataFrame({'time': np.arange(rows), 'a': generator.normal(0, 0.01, rows), 'b': generator.normal(0, 0.02, rows)})
    options = dict(time_col='time', return_columns=['a', 'b'], end_period=70, window=30, shrinkage_bps=600)
    before = run_min_variance(frame, **options)
    frame.loc[70:, ['a', 'b']] = np.nan
    after = run_min_variance(frame, **options)
    assert before == after
    weights = np.array(list(before['allocation'].values()))
    assert (weights >= 0).all() and weights.sum() == pytest.approx(1, abs=1e-12)
    raw = np.asarray(before['sample_covariance']['matrix'])
    objective = np.asarray(before['objective_covariance']['matrix'])
    np.testing.assert_allclose(raw, frame.iloc[40:70][['a', 'b']].cov(), rtol=2e-12, atol=1e-18)
    np.testing.assert_allclose(objective, 0.94 * raw + 0.06 * raw.trace() / 2 * np.eye(2), rtol=2e-12, atol=1e-18)
    assert weights @ objective @ weights == pytest.approx(before['metrics']['objective_variance'], rel=2e-12)
    assert before['cutoff'] == {'first_period': 41, 'last_period': 70, 'as_of_time': '69'}
