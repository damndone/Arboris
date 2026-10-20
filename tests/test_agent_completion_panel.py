"""Panel delivery evidence describes within-unit residuals, not pooled OLS."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SOURCE = Path(__file__).parent / 'fixtures/admission/panel_ols/data.csv'


def test_panel_rows_residuals_and_absorbed_parameter_rank_are_native():
    from workbench.econometrics.runner import run_panel_ols
    from workbench.engine.panel_diagnostics import panel_evidence
    frame = pd.read_csv(SOURCE).sample(frac=1, random_state=19).reset_index(drop=True)
    frame = frame.drop(frame.index[[2, 8, 19]]).reset_index(drop=True)
    frame['region'] = frame.g % 10
    frame.loc[4, 'region'] = np.nan
    primary, fitted = run_panel_ols(frame, y='y', x=['x1', 'x2'], entity='g', time='time',
                                    cluster_col='region', model_id='p')
    result, positions, definition = panel_evidence(fitted, primary, frame, y='y', x=['x1', 'x2'],
                                                   entity='g', time='time', cluster='region')
    assert result['status'] == 'computed'
    assert result['method'] == 'panel_within_residual_descriptive_v1'
    assert 4 not in positions and len(positions) == len(frame)-1
    np.testing.assert_allclose(result['residuals'], fitted.resids.to_numpy(), rtol=0, atol=0)
    assert result['total_parameter_rank'] == fitted.df_model
    assert result['residual_df'] == fitted.df_resid
    assert result['cluster_count'] == 10
    assert result['cluster_count_assessment'] == 'caution'
    assert result['pairing'] == 'adjacent_observed_times_within_entity'
    assert result['serial_dependence_test'] == 'not_performed'
    assert definition['entity_effects'] and definition['time_effects']


def build_products(root, source=SOURCE, *, covariance='clustered', x=None, kind='panel_ols'):
    from workbench.projects import create_project
    from workbench.orchestrator import run_workflow
    from workbench.reporting import render_html_report
    from tests.test_agent_completion import artifact
    project = create_project(root, 'panel-completion')
    model_id = kind + '_1'
    extra = {'did_mode': 'cohort', 'did_cohort_col': 'first_treat'} if kind == 'did' else {}
    runs = []
    for columns in x or [['x1', 'x2'], ['x1']]:
        result = run_workflow(project.root, [source], mode='auto', model_type=kind, y='y',
            x=columns, entity_col='g', time_col='time', covariance=covariance, **extra)
        assert result['status'] == 'completed', result
        runs.append(result['run_id'])
    main, alternate = runs
    data = project.root / 'runs' / main / 'processed/cleaned_dataset.parquet'
    contract = {'playbooks': ['did' if kind == 'did' else 'panel'], 'source': {'run_id': main, 'artifact_id': 'cleaned_dataset',
        'sha256': hashlib.sha256(data.read_bytes()).hexdigest()}}
    evidence = {'models': [{'run_id': main, 'artifact_id': model_id}],
        'diagnostics': [{'run_id': main, 'artifact_id': model_id + '.completion'}],
        'sensitivity': [{'run_id': alternate, 'artifact_id': model_id}],
        'report': {'run_id': main, 'artifact_id': 'report'}}
    artifact(project.root, main, 'collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed', 'steps': {
        'primary': {'status': 'completed', 'artifact_ids': [f'{main}:{model_id}', f'{main}:{model_id}.completion',
                                                        f'{alternate}:{model_id}']}}})
    render_html_report({'title': 'Panel analysis', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
        project.root / 'runs' / main, artifact_id='report', inputs=['collection'])
    return project.root, contract, evidence


@pytest.fixture(scope='module')
def products(tmp_path_factory):
    return build_products(tmp_path_factory.mktemp('panel-native'))


def test_native_panel_completion_requires_actual_residuals_clusters_and_changed_fit(products):
    from workbench.agent.completion import evaluate
    project, contract, evidence = products
    checked = evaluate(project, contract, evidence)
    assert checked['status'] == 'requirements_met', checked['missing']
    assert checked['scientific_validity'] == 'not_certified'
    repeated = evaluate(project, contract, {**evidence, 'sensitivity': evidence['models']})
    assert 'panel:sensitivity:distinct_point_estimation' in repeated['missing']


def test_hc_without_clustering_does_not_certify_fixed_t_panel_completion(tmp_path):
    from workbench.agent.completion import evaluate
    project, contract, evidence = build_products(tmp_path, covariance='robust')
    result = evaluate(project, contract, evidence)
    assert 'panel:diagnostics:within_dependence_inference_unverified' in result['missing']


def test_did_missing_preleads_is_not_reported_as_parallel_trends_not_rejected():
    from workbench.engine.did_diagnostics import _parallel_trends
    result = _parallel_trends({'pre_period_terms': []})
    assert result['verdict'] == 'unavailable'
    assert result['reason'] == 'no_estimable_pre_period_leads'


def test_native_did_restrictions_are_machine_readable_completion_gaps():
    from workbench.agent.completion_profiles import native_findings
    diag = {'parallel_trends': {'verdict': 'unavailable', 'n_pre_leads': 0, 'pvalue': None},
            'interpretation_restriction': 'Staggered TWFE is not a generic ATT.'}
    findings = native_findings('did', [{'diagnostics': {'did': diag}}])
    assert 'did:diagnostics:pretrends_unavailable' in findings
    assert 'did:diagnostics:staggered_interpretation_requires_revision' in findings


def test_balanced_two_way_residuals_agree_with_hand_double_demeaning():
    from workbench.econometrics.runner import run_panel_ols
    from workbench.engine.panel_diagnostics import panel_evidence
    frame = pd.DataFrame({'g': [0, 0, 0, 1, 1, 1], 'time': [0, 1, 2, 0, 1, 2], 'y': [1., 2., 4., 2., 5., 7.]})
    primary, fitted = run_panel_ols(frame, y='y', x=[], entity='g', time='time', model_id='p')
    diag, positions, _ = panel_evidence(fitted, primary, frame, y='y', x=[], entity='g', time='time')
    np.testing.assert_allclose(diag['residuals'], np.array([2, -1, -1, -2, 1, 1])/3, rtol=1e-12, atol=1e-12)
    assert positions == list(range(6))
    assert diag['total_parameter_rank'] == 4 and diag['residual_df'] == 2
    assert diag['adjacent_pairs'] == 4


@pytest.mark.parametrize('case', ['two_way', 'one_way', 'unbalanced'])
def test_native_residuals_and_rank_match_independent_r_and_stata(case):
    from workbench.econometrics.runner import run_panel_ols
    from workbench.engine.panel_diagnostics import panel_evidence
    root = Path(__file__).parent / 'fixtures/agent_completion/panel'
    reference = json.loads((root / 'residual_reference_r.json').read_text())['cases'][case]
    source = pd.read_csv(SOURCE)
    frame = source.iloc[reference['retained_positions']].reset_index(drop=True)
    time = None if case == 'one_way' else 'time'
    primary, fitted = run_panel_ols(frame, y='y', x=['x1', 'x2'], entity='g', time=time, model_id='p')
    diag, positions, _ = panel_evidence(fitted, primary, frame, y='y', x=['x1', 'x2'], entity='g', time=time)
    stata = pd.read_csv(root / 'residual_reference_stata.csv')
    stata = stata[stata['case'] == case]
    assert stata.source_position.tolist() == reference['retained_positions']
    np.testing.assert_allclose(diag['residuals'], reference['residuals'], rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(diag['residuals'], stata.residual, rtol=1e-7, atol=1e-9)
    assert diag['total_parameter_rank'] == reference['parameter_rank']
    assert diag['residual_df'] == reference['residual_df']
    assert positions == list(range(len(frame)))
    if case == 'one_way':
        assert diag['adjacent_pairs'] == 0 and diag['adjacent_residual_correlation'] is None


def test_few_cluster_native_fit_keeps_an_explicit_completion_gap(tmp_path):
    from workbench.agent.completion import evaluate
    frame = pd.read_csv(SOURCE)
    source = tmp_path / 'few.csv'
    frame[frame.g <= 8].to_csv(source, index=False)
    project, contract, evidence = build_products(tmp_path, source=source)
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'partial'
    assert result['missing'] == ['panel:diagnostics:few_clusters_inference_unverified']


@pytest.mark.parametrize('source,expected', [
    ('admission/did/data.csv', 'did:diagnostics:pretrends_unavailable'),
    ('panel_cluster/staggered.csv', 'did:diagnostics:staggered_interpretation_requires_revision')])
def test_actual_native_did_producer_retains_unavailable_and_staggered_restrictions(tmp_path, source, expected):
    from workbench.projects import create_project
    from workbench.orchestrator import run_workflow
    from workbench.agent.completion_profiles import native_findings
    project = create_project(tmp_path, 'did')
    result = run_workflow(project.root, [Path(__file__).parent / 'fixtures' / source],
        mode='auto', model_type='did', y='y', x=[], entity_col='g', time_col='time',
        did_mode='cohort', did_cohort_col='first_treat')
    assert result['status'] == 'completed'
    run = project.root / 'runs' / result['run_id']
    evidence = json.loads((run / 'model_results/did_1.completion.json').read_text())
    assert evidence['diagnostics']['panel']['status'] == 'computed'
    assert expected in native_findings('did', [evidence])
    native = json.loads((run / 'did_diagnostics.json').read_text())
    assert evidence['diagnostics']['did'] == native
    assert evidence['diagnostic_artifact_sha256']['did_diagnostics'] == hashlib.sha256((run / 'did_diagnostics.json').read_bytes()).hexdigest()


def test_native_single_cohort_did_can_complete_with_explicit_preperiod_evidence(tmp_path):
    from workbench.agent.completion import evaluate
    # Balanced paired patterns give known zero pre-treatment differences;
    # this is a deterministic delivery example, not a coverage simulation.
    rows = []
    for g in range(40):
        for t in range(8):
            pair = g % 20
            x1, x2 = np.sin(pair*.7+t), np.cos(pair+2*t)
            treatment = g < 20 and t >= 4
            y = .4*g+.1*t+2*treatment+.3*x1-.2*x2+.05*np.cos((pair+1)*(t+1))
            rows.append({'g': g, 'time': t, 'y': y, 'x1': x1, 'x2': x2,
                         'first_treat': 4 if g < 20 else 0})
    source = tmp_path / 'single_cohort.csv'
    pd.DataFrame(rows).to_csv(source, index=False)
    project, contract, evidence = build_products(tmp_path, source=source, kind='did')
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert result['scientific_validity'] == 'not_certified'


def test_panel_raw_inputs_scripts_and_native_references_are_content_bound():
    manifest = json.loads((Path(__file__).parent / 'fixtures/agent_completion/panel/manifest.json').read_text())
    for path, digest in manifest['repository_files'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert manifest['tolerance'] == {'rtol': 1e-7, 'atol': 1e-9}
