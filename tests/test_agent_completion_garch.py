"""Production-child diagnostics cannot borrow the training-only parent's fit."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.models.arma_garch.test_pack_runtime import _source, _options, _context, _Recorder


def native_fit(root, frame, *, strategy='joint', q=0, variance_p=1):
    from workbench.engine.context import RunEnv
    from workbench.engine.packs.arma_garch.runner import fit_from_context
    ctx = _context(frame)
    options = _options()
    options['estimation_strategy'] = strategy
    options['arma']['q'] = q
    options['variance']['garch_p'] = variance_p
    options['validation']['validation_n'] = 2
    ctx.artifacts['_model_options'] = options
    root.mkdir(parents=True, exist_ok=True)
    (root / 'artifacts_index.json').write_text('{"artifacts": []}')
    _, result, _ = fit_from_context(ctx, RunEnv(run_root=root, run_id=root.name, recorder=_Recorder()))
    return result


@pytest.mark.parametrize('strategy,q', [('joint', 0), ('sequential', 0), ('joint', 1)])
def test_full_sample_child_has_own_native_diagnostics_and_standard_errors(tmp_path, strategy, q):
    result = native_fit(tmp_path, _source(200), strategy=strategy, q=q)
    assert result['fit_scope'] == 'training_only'
    child = result['production_child']
    native = child['analysis_evidence']
    assert native['fit_scope'] == 'all_available_observations'
    assert native['nobs'] == 200
    assert native['model_id'] == 'arma_garch_1:production-final'
    assert native['coefficients'] and all(row['std_error'] >= 0 for row in native['coefficients'].values())
    diag = native['diagnostics']
    assert diag['method'] == 'garch_production_standardized_innovations_v1'
    assert diag['status'] == 'computed'
    assert diag['residual_n'] == 200-diag['burn_in']
    assert 'squared_ljung_box' in diag and 'innovations' not in diag
    assert native['scientific_validity'] == 'not_certified'


def test_changed_validation_settings_are_not_a_new_production_specification(tmp_path):
    from workbench.engine.packs.arma_garch.completion import point_fingerprint
    from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
    from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
    frame = _source(200)
    payload = _options()
    contract = ArmaGarchAnalysisContract.from_dict(payload)
    prepared = prepare_arma_garch_input(frame, contract)
    spec = {'mean_order': [1, 0], 'mean_constant': True, 'variance_model': 'garch',
            'variance_order': [1, 1], 'innovation_distribution': 'normal',
            'resolved_strategy': 'joint_ar_garch', 'hold_back': 1, 'transform': 'level'}
    first = point_fingerprint(prepared, spec)
    payload['validation']['validation_n'] = 10
    second = prepare_arma_garch_input(frame, ArmaGarchAnalysisContract.from_dict(payload))
    assert point_fingerprint(second, spec) == first
    assert point_fingerprint(prepared, {**spec, 'variance_order': [2, 1]}) != first


def products(root, frame, *, semantics='business_or_trading_observations'):
    from tests.test_data_column_cast import _source_project
    from workbench.agent.workflow import WorkflowExecutor, compile_workflow
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    from workbench.artifacts import register_artifact, write_json, sha256_file
    from workbench.reporting import render_html_report
    project, run, source = _source_project(root, frame)
    run_root = project / 'runs' / run
    write_json(run_root / 'artifacts_index.json', {'schema_version': 1, 'artifacts': []})
    register_artifact(run_root, source, run_root / 'data.csv', 'raw_data', 'ingestion', [])
    options = _options()
    for name in ['dataset_ref', 'time_column', 'value_column']:
        options.pop(name)
    options['validation']['validation_n'] = 2
    options['time_index_semantics'] = semantics
    draft = compile_workflow(workflow_id='garch-completion',
        target={'run_id': run, 'node_ref': 'stage:source', 'artifact_id': source},
        preconditions={'context_version': 'node-operation-context/v1', 'context_fingerprint': 'sha256:garch-source',
            'active_head_run_id': run, 'owner_resolution': 'single_candidate'},
        steps=[{'step_id': label, 'operation_id': 'model.time_series.arma_garch', 'spec': {
            'input_mode': 'frame', 'column_bindings': {'time': 'when', 'value': 'value'},
            'options': {**options, 'arma': {**options['arma'], 'constant_mode': constant}}}}
            for label, constant in [('primary', 'include'), ('alternate', 'exclude')]],
        available_columns=list(frame.columns))
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed', state.to_dict()
    primary, alternate = (state.steps[label].artifact_ids[0] for label in ['primary', 'alternate'])
    contract = {'playbooks': ['garch'], 'source': {'run_id': run, 'artifact_id': source,
        'sha256': sha256_file(run_root / 'data.csv')}}
    evidence = {'models': [{'run_id': run, 'artifact_id': primary}],
        'diagnostics': [{'run_id': run, 'artifact_id': primary}],
        'sensitivity': [{'run_id': run, 'artifact_id': alternate}],
        'report': {'run_id': run, 'artifact_id': 'report'}}
    render_html_report({'title': 'Production volatility', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
        run_root, artifact_id='report', inputs=[primary, alternate])
    return project, contract, evidence


@pytest.fixture(scope='module')
def native_products(tmp_path_factory):
    return products(tmp_path_factory.mktemp('native-garch'), _source(300))


def test_persisted_garch_workflow_checks_production_child_and_real_sensitivity(native_products):
    from workbench.agent.completion import evaluate
    project, contract, evidence = native_products
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert result['scientific_validity'] == 'not_certified'
    duplicate = evaluate(project, contract, {**evidence, 'sensitivity': evidence['models']})
    assert 'garch:sensitivity:distinct_point_estimation' in duplicate['missing']


def test_original_m0_garch_input_replays_through_native_production_diagnostics(tmp_path):
    from workbench.agent.completion import evaluate
    source = next((Path(__file__).parent / 'fixtures/agent_completion/ts_garch.goal.r1/project/runs').glob('*/raw_snapshot/ts_garch.csv'))
    frame = pd.read_csv(source).rename(columns={'day': 'when', 'return_pct': 'value'})
    project, contract, evidence = products(tmp_path, frame, semantics='observation_order')
    result = evaluate(project, contract, evidence)
    assert not any(':model:' in m or ':sensitivity:' in m or m.startswith('report:') or 'native_profile' in m for m in result['missing']), result['missing']
    assert result['scientific_validity'] == 'not_certified'
    # Real assumption failures, if present, remain visible, without retuning.
    assert all(m.startswith('garch:diagnostics:') for m in result['missing'])


def test_reindexed_changed_child_diagnostic_cannot_reuse_original_fit_receipt(native_products, tmp_path):
    import hashlib
    import shutil
    from workbench.agent.completion import evaluate
    project, contract, evidence = native_products
    copy = tmp_path / 'copy'
    shutil.copytree(project, copy)
    run = copy / 'runs' / contract['source']['run_id']
    index = json.loads((run / 'artifacts_index.json').read_text())
    record = next(a for a in index['artifacts'] if a['artifact_id'] == evidence['models'][0]['artifact_id'])
    path = run / record['path']
    wrapper = json.loads(path.read_text())
    wrapper['result']['result']['production_child']['analysis_evidence']['diagnostics']['arch_lm']['p_value'] = .999
    wrapper['result_sha256'] = hashlib.sha256(json.dumps(wrapper['result'], ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    path.write_text(json.dumps(wrapper))
    record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (run / 'artifacts_index.json').write_text(json.dumps(index))
    result = evaluate(copy, contract, evidence)
    assert result['status'] == 'partial' and 'garch:model:arma_garch' in result['missing']


def test_garch_rejections_remain_explicit_and_normality_is_not_an_automatic_failure():
    from workbench.agent.completion_profiles import native_findings
    base = {'variance_parameters_valid': True, 'significance_level': .01,
        'stationarity': {'adf': {'p_value': .001}, 'kpss': {'p_value': .1}},
        'normality': {'p_value': 1e-20}, 'ljung_box': {'p_value': .5},
        'squared_ljung_box': {'p_value': .5}, 'arch_lm': {'p_value': .5}}
    assert native_findings('garch', [{'diagnostics': {'garch': base}}]) == []
    for key, expected in [('variance_parameters_valid', 'invalid_variance_parameters'),
                          ('arch_lm', 'remaining_arch_requires_revision'),
                          ('ljung_box', 'mean_correlation_requires_revision')]:
        altered = {**base, key: False if key == 'variance_parameters_valid' else {'p_value': .001}}
        assert f'garch:diagnostics:{expected}' in native_findings('garch', [{'diagnostics': {'garch': altered}}])


def test_nonstationary_production_mean_cannot_pass_the_completion_gate():
    from workbench.agent.completion_profiles import native_findings
    diag = {'variance_parameters_valid': True, 'significance_level': .01, 'mean_stationary': False,
            'mean_invertible': True, 'stationarity': {'adf': {'p_value': .001}, 'kpss': {'p_value': .1}}}
    assert 'garch:diagnostics:inadmissible_mean_roots' in native_findings('garch', [{'diagnostics': {'garch': diag}}])


def test_garch_diagnostics_on_exact_stata_standardized_series_match_independent_r():
    from workbench.engine.packs.arma_garch.completion import fitted_evidence
    from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
    fixture = Path(__file__).parent / 'fixtures/arma_garch_joint/oracle_v1'
    series = pd.read_csv(fixture / 'series_garch11_constant.csv')
    values = pd.read_csv(fixture / 'data_garch11_constant.csv').y
    oracle = json.loads((fixture / 'stata_garch11_constant_opg.json').read_text())
    reference = json.loads((Path(__file__).parent / 'fixtures/agent_completion/time_series/garch_reference_r.json').read_text())
    z = series.residual_opg / np.sqrt(series.variance_opg)
    native = fitted_evidence(values, z, burn=0, model_df=2,
        estimates=oracle['parameters'], standard_errors=oracle['standard_errors'],
        variance_spec=VarianceCandidateSpec.create(model='garch', p=1, q=1, distribution='normal'),
        variance_parameters={'omega': oracle['parameters']['omega'], 'alpha[1]': oracle['parameters']['arch1'],
                             'beta[1]': oracle['parameters']['garch1']})
    for key in ['ljung_box', 'squared_ljung_box', 'arch_lm']:
        np.testing.assert_allclose(native['diagnostics'][key]['statistic'], reference[key], rtol=1e-7, atol=1e-9)
        np.testing.assert_allclose(native['diagnostics'][key]['p_value'], reference[key+'_p'], rtol=1e-7, atol=1e-9)


def test_diagnostic_reference_materials_and_original_stata_inputs_are_content_bound():
    import hashlib
    manifest = json.loads((Path(__file__).parent / 'fixtures/agent_completion/time_series/manifest.json').read_text())
    for path, digest in manifest['repository_files'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert manifest['tolerance'] == {'rtol': 1e-7, 'atol': 1e-9}
