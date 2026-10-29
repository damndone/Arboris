"""An inferred panel index must retain an explicitly requested time control.

The 56-row fixture matches the retained local virtual-copy investigation.
Existing R/Stata references remain in fixtures/panel_cluster and
fixtures/agent_completion/panel; these checks add exact within-engine parity.
"""
import struct

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics.runner import run_panel_ols

pytest.importorskip('linearmodels')


def _frame():
    firm, period = np.repeat(np.arange(8), 7), np.tile(np.arange(7), 8)
    training = ((firm * 7 + period * 3) % 11) / 4 + ((firm * period) % 5) / 8
    noise = (((firm + 2) * (period + 1)) % 13 - 6) / 32
    return pd.DataFrame(dict(
        firm=['firm_' + str(i) for i in firm], year=2011 + period,
        training=training,
        productivity=2.75 + firm * .75 + training * .625 + period * .125 + noise,
        region=['region_' + str(i % 4) for i in firm],
    ))


def _bits(value):
    if isinstance(value, (float, np.floating)):
        return struct.pack('>d', float(value))
    if isinstance(value, np.ndarray):
        return (value.shape, _bits(value.tolist()))
    if isinstance(value, dict):
        return {key: _bits(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_bits(item) for item in value]
    return value


def _signature(primary, fitted):
    result = dict(primary=primary)
    for name in ('params', 'std_errors', 'tstats', 'pvalues', 'cov', 'resids',
                 'fitted_values', 'estimated_effects'):
        result[name] = getattr(fitted, name).to_numpy()
    result['conf_int'] = fitted.conf_int().to_numpy()
    for name in ('nobs', 'df_model', 'df_resid', 'rsquared', 'rsquared_within',
                 'rsquared_between', 'rsquared_overall', 's2', 'loglik',
                 'resid_ss', 'model_ss', 'total_ss'):
        result[name] = getattr(fitted, name)
    for name in ('f_statistic', 'f_statistic_robust'):
        test = getattr(fitted, name)
        result[name] = {key: getattr(test, key, None) for key in ('stat', 'pval', 'df', 'df_denom', 'dist_name')}
    return _bits(result)


def _compare_to_entity_only_reference(frame, *, covariance='clustered', cluster_col=None,
                                      expected_time='year'):
    before = frame.copy(deep=True)
    options = dict(y='productivity', x=['training', 'year'], entity='firm',
                   time_effects=False, model_id='panel_binding', covariance=covariance,
                   cluster_col=cluster_col)
    reference, old_fit = run_panel_ols(frame, time=None, **options)
    actual, fitted = run_panel_ols(frame, time='year', **options)
    assert _signature(actual, fitted) == _signature(reference, old_fit)
    assert list(fitted.params.index) == ['Intercept', 'training', 'year']
    assert actual['entity_col'] == 'firm' and actual['time_col'] is None
    index = fitted.model.dependent.index
    assert index.names == ['firm', expected_time]
    columns = ['productivity', 'training', 'year']
    if covariance == 'clustered':
        columns.append(cluster_col or 'firm')
    selected = frame.dropna(subset=columns)
    assert actual['nobs'] == len(selected)
    if expected_time == 'year':
        assert index.tolist() == list(zip(selected.firm, selected.year))
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    return actual, fitted


@pytest.mark.parametrize('case', ['entity', 'region', 'time', 'robust', 'unadjusted',
                                  'missing_entity_cluster', 'missing_region_cluster'])
def test_time_control_matches_original_entity_fe_bits(case):
    frame = _frame()
    covariance, cluster = 'clustered', None
    if case in ('region', 'missing_region_cluster'):
        cluster = 'region'
    elif case == 'time':
        cluster = 'year'
    elif case in ('robust', 'unadjusted'):
        covariance = case
    if case.startswith('missing_'):
        for row, column in ((0, 'productivity'), (8, 'training'), (16, 'year')):
            frame.loc[row, column] = np.nan
        if cluster == 'region':
            frame.loc[24, 'region'] = None
        else:
            frame.loc[24, 'firm'] = None
    _compare_to_entity_only_reference(frame, covariance=covariance, cluster_col=cluster)


def test_shuffled_time_control_keeps_actual_diagnostic_order_and_kernel():
    from workbench.contracts.model.inference_kernel import kernel_from_fitted
    from workbench.engine.panel_diagnostics import panel_evidence

    frame = _frame().iloc[(np.arange(56) * 17) % 56].copy()
    primary, fitted = _compare_to_entity_only_reference(frame)
    reference, old_fit = run_panel_ols(frame, y='productivity', x=['training', 'year'],
        entity='firm', time=None, time_effects=False, model_id='panel_binding')
    options = dict(model_id='panel_binding', model_type='panel_ols', nobs=primary['nobs'])
    kernel = kernel_from_fitted(fitted, **options)
    assert kernel is not None and _bits(kernel) == _bits(kernel_from_fitted(old_fit, **options))
    diagnostic, positions, _ = panel_evidence(fitted, primary, frame, y='productivity',
        x=['training', 'year'], entity='firm', time='year')
    assert positions.tolist() == list(range(56))
    assert diagnostic['n_times'] == 7 and diagnostic['adjacent_pairs'] == 48
    assert diagnostic['pairing'] == 'adjacent_observed_times_within_entity'
    ids = fitted.model.dependent.entity_ids[:, 0]
    years = fitted.model.dependent.index.get_level_values(1).to_numpy()
    residuals = fitted.resids.to_numpy()
    left, right = [], []
    for entity_id in np.unique(ids):
        rows = np.flatnonzero(ids == entity_id)
        ordered = rows[np.argsort(years[rows], kind='stable')]
        left.extend(residuals[ordered[:-1]])
        right.extend(residuals[ordered[1:]])
    assert _bits(diagnostic['adjacent_residual_correlation']) == _bits(float(np.corrcoef(left, right)[0, 1]))


def test_duplicate_entity_times_keep_the_existing_synthetic_order():
    frame = _frame()
    frame.loc[1, 'year'] = frame.loc[0, 'year']
    _compare_to_entity_only_reference(frame, expected_time='_panel_time')


def test_time_effects_do_not_silently_drop_the_same_time_trend():
    from linearmodels.panel.utility import AbsorbingEffectError

    frame = _frame()
    before = frame.copy(deep=True)
    with pytest.raises(AbsorbingEffectError, match='year'):
        run_panel_ols(frame, y='productivity', x=['training', 'year'], entity='firm',
                      time='year', time_effects=True, model_id='panel_binding')
    pd.testing.assert_frame_equal(frame, before, check_exact=True)


def test_entity_only_workflow_retains_the_continuous_time_control(tmp_path):
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    source = tmp_path / 'panel.csv'
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, 'panel-binding')
    completed = run_workflow(project.root, [source], mode='auto', model_type='panel_ols',
        y='productivity', x=['training', 'year'], entity_col='firm')
    assert completed['status'] == 'completed', completed
    models = project.root / 'runs' / completed['run_id'] / 'model_results'
    primary = read_json(models / 'panel_ols_1.json')
    assert list(primary['coefficients']) == ['Intercept', 'training', 'year']
    assert primary['time_col'] is None
    diagnostic = read_json(models / 'panel_ols_1.completion.json')['diagnostics']['panel']
    assert diagnostic['n_times'] == 7 and diagnostic['adjacent_pairs'] == 48
