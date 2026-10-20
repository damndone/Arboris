"""Native ARIMA completion, actual data order, and original M0 time series."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def series():
    rng = np.random.default_rng(20261020)
    y = np.zeros(300)
    for i in range(1, len(y)):
        y[i] = .4*y[i-1]+rng.normal()
    return pd.DataFrame({'time': np.arange(300), 'y': y})


def fit(frame, *, order=(1, 0, 0), horizon=1, time_order='declared_monotonic'):
    from workbench.engine.packs.time_series import fit_arima
    return fit_arima(frame, time_column='time', value_column='y', time_order=time_order,
                     order=order, forecast_horizon=horizon)


def test_arima_evidence_comes_from_the_original_fit_not_a_second_fit():
    result = fit(series())
    native = result['result']['analysis_evidence']
    assert native['contract'] == 'time-series.completion.v1'
    assert native['nobs'] == 300 and native['converged']
    assert native['coefficients']['ar.L1']['std_error'] > 0
    assert native['diagnostics']['ljung_box']['df'] == 9
    assert native['diagnostics']['stationarity']['adf']['status'] == 'computed'
    assert native['diagnostics']['stationarity']['kpss']['status'] == 'computed'
    assert native['diagnostics']['method'] == 'arima_native_innovations_v1'
    assert native['diagnostics']['coefficient_covariance'] == 'opg'


def test_forecast_horizon_and_confidence_do_not_count_as_another_specification():
    frame = series()
    main, horizon = fit(frame), fit(frame, horizon=6)
    changed = fit(frame, order=(2, 0, 0))
    fp = lambda value: value['result']['analysis_evidence']['point_estimation_fingerprint']
    assert fp(main) == fp(horizon)
    assert fp(main) != fp(changed)


def test_sorted_complete_cases_have_ordered_source_positions_and_unchanged_input():
    frame = series().sample(frac=1, random_state=6).reset_index(drop=True)
    frame.loc[4, 'y'] = np.nan
    original = frame.copy(deep=True)
    result = fit(frame, time_order='sort_by_time')
    native = result['result']['analysis_evidence']
    expected = frame.dropna().sort_values('time', kind='stable').index.tolist()
    assert native['ordered_positions'] == expected
    pd.testing.assert_frame_equal(frame, original)
    assert native['diagnostics']['sampling']['regular'] is False


def test_persisted_native_arima_workflow_can_complete_with_real_sensitivity_and_report(tmp_path):
    from workbench.agent.completion import evaluate
    project, contract, evidence = products(tmp_path, series())
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert result['scientific_validity'] == 'not_certified'
    repeated = evaluate(project, contract, {**evidence, 'sensitivity': evidence['models']})
    assert 'time_series:sensitivity:distinct_point_estimation' in repeated['missing']


def products(root, frame):
    from tests.test_data_column_cast import _source_project
    from workbench.agent.workflow import WorkflowExecutor, compile_workflow
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    from workbench.artifacts import sha256_file, write_json, register_artifact
    from workbench.reporting import render_html_report
    project, run, source = _source_project(root, frame)
    run_root = project / 'runs' / run
    write_json(run_root / 'artifacts_index.json', {'schema_version': 1, 'artifacts': []})
    register_artifact(run_root, source, run_root / 'data.csv', 'raw_data', 'ingestion', [])
    target = {'run_id': run, 'node_ref': 'stage:source', 'artifact_id': source}
    preconditions = {'context_version': 'node-operation-context/v1', 'context_fingerprint': 'sha256:arima-source',
        'active_head_run_id': run, 'owner_resolution': 'single_candidate'}
    draft = compile_workflow(workflow_id='native-arima', target=target, preconditions=preconditions,
        steps=[{'step_id': label, 'operation_id': 'time_series.arima', 'spec': {'input_mode': 'frame',
            'column_bindings': {'time': 'time', 'value': 'y'}, 'options': {'time_order': 'declared_monotonic',
                'order': [p, 0, 0], 'trend': 'c'}}} for label, p in [('primary', 1), ('alternate', 2)]],
        available_columns=list(frame.columns))
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed', state.to_dict()
    primary, alternate = (state.steps[label].artifact_ids[0] for label in ['primary', 'alternate'])
    contract = {'playbooks': ['time_series'], 'source': {**target, 'sha256': sha256_file(project / 'runs' / run / 'data.csv')}}
    contract['source'].pop('node_ref')
    evidence = {'models': [{'run_id': run, 'artifact_id': primary}],
        'diagnostics': [{'run_id': run, 'artifact_id': primary}],
        'sensitivity': [{'run_id': run, 'artifact_id': alternate}], 'report': {'run_id': run, 'artifact_id': 'report'}}
    render_html_report({'title': 'Time-series forecast', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
        project / 'runs' / run, artifact_id='report', inputs=[primary, alternate])
    return project, contract, evidence


def test_native_statistics_match_independent_r_and_stata():
    from workbench.engine.packs.time_series.completion import innovation_diagnostics
    root = Path(__file__).parent / 'fixtures/agent_completion/time_series'
    frame = pd.read_csv(root / 'input.csv')
    r = json.loads((root / 'reference_r.json').read_text())
    stata = pd.read_csv(root / 'reference_stata.csv').iloc[0]
    diag = innovation_diagnostics(frame.y, frame.innovation, model_df=1, burn=0)
    for key in ['adf', 'kpss']:
        np.testing.assert_allclose(diag['stationarity'][key]['statistic'], r[key], rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(diag['stationarity']['adf']['statistic'], stata.adf, rtol=1e-7, atol=1e-9)
    for ref in [r, stata]:
        np.testing.assert_allclose(diag['ljung_box']['statistic'], ref['ljung_box'], rtol=1e-7, atol=1e-9)
        np.testing.assert_allclose(diag['ljung_box']['p_value'], ref['ljung_box_p'], rtol=1e-7, atol=1e-9)
        # Stata's native ARCH LM has ddof=0. The fixed product definition uses ddof=1.
        np.testing.assert_allclose(diag['arch_lm']['statistic'], ref['arch_lm_raw']*169/170, rtol=1e-7, atol=1e-9)


def test_constant_short_and_nonfinite_innovations_stay_explicitly_unavailable():
    from workbench.engine.packs.time_series.completion import innovation_diagnostics, stationarity
    for values in [np.ones(30), np.arange(8.)]:
        assert stationarity(values)['adf']['status'] == 'unavailable'
    for innovations in [np.ones(30), np.arange(8.), np.r_[np.nan, np.arange(29.)]]:
        diag = innovation_diagnostics(np.arange(30.), innovations, model_df=1, burn=0)
        assert diag['status'] == 'unavailable'
        assert 'innovations' not in diag


def test_replaced_source_bytes_cannot_reuse_native_arima_evidence(tmp_path):
    from workbench.agent.completion import evaluate
    project, contract, evidence = products(tmp_path, series())
    source = project / 'runs' / contract['source']['run_id'] / 'data.csv'
    source.write_text(source.read_text().replace('0.0', '9.0'))
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'partial'
    assert 'source:changed_or_unavailable' in result['missing']


def test_original_m0_spurious_input_does_not_become_complete_by_fitting_a_forecast(tmp_path):
    from workbench.agent.completion import evaluate
    source = next((Path(__file__).parent / 'fixtures/agent_completion/ts_spurious.goal.r1/project/runs').glob('*/raw_snapshot/ts_spurious.csv'))
    frame = pd.read_csv(source).rename(columns={'month': 'time', 'sales_index': 'y'})
    project, contract, evidence = products(tmp_path, frame)
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'partial'
    assert 'time_series:diagnostics:stationarity_unresolved' in result['missing']
    # This is a diagnostic replay, not a substitute for the advertising-association question.
    assert result['scientific_validity'] == 'not_certified'
