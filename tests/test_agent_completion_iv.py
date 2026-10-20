"""Native IV evidence, certified inversion, and the actual M0 failure input."""
import hashlib
import json
from pathlib import Path

import pytest


def build_products(root):
    from workbench.projects import create_project
    from workbench.orchestrator import run_workflow
    from workbench.reporting import render_html_report
    from tests.test_agent_completion import artifact
    source = next((Path(__file__).parent / 'fixtures/agent_completion/iv_valid.open.r1/project/runs').glob('*/raw_snapshot/iv_valid.csv'))
    project = create_project(root, 'iv-completion')
    runs = []
    for exog in [['experience'], []]:
        result = run_workflow(project.root, [source], mode='auto', model_type='iv_2sls', y='log_wage',
            x=exog, iv_endog=['education'], iv_instruments=['near_college'], covariance='robust')
        assert result['status'] == 'completed', result
        runs.append(result['run_id'])
    main, alternate = runs
    source_path = project.root / 'runs' / main / 'processed/cleaned_dataset.parquet'
    contract = {'playbooks': ['iv'], 'source': {'run_id': main, 'artifact_id': 'cleaned_dataset',
        'sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()}}
    evidence = {'models': [{'run_id': main, 'artifact_id': 'iv_2sls_1'}],
        'diagnostics': [{'run_id': main, 'artifact_id': 'iv_2sls_1.completion'}],
        'sensitivity': [{'run_id': alternate, 'artifact_id': 'iv_2sls_1'}],
        'report': {'run_id': main, 'artifact_id': 'report'}}
    artifact(project.root, main, 'collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed', 'steps': {
        'primary': {'status': 'completed', 'artifact_ids': [f'{main}:iv_2sls_1', f'{main}:iv_2sls_1.completion',
                                                        f'{alternate}:iv_2sls_1']}}})
    render_html_report({'title': 'IV analysis', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
        project.root / 'runs' / main, artifact_id='report', inputs=['collection'])
    return project.root, contract, evidence


@pytest.fixture(scope='module')
def products(tmp_path_factory):
    return build_products(tmp_path_factory.mktemp('iv-native'))


def test_m0_iv_input_can_reach_native_completion_with_certified_ar(products):
    from workbench.agent.completion import evaluate
    project, contract, evidence = products
    result = evaluate(project, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert result['scientific_validity'] == 'not_certified'
    companion = json.loads((project / 'runs' / contract['source']['run_id'] / 'model_results/iv_2sls_1.completion.json').read_text())
    assert companion['nobs'] == 1500
    diag = companion['diagnostics']['iv']
    assert diag['weak_instruments']['first_stage_f'] is None
    assert diag['weak_instruments']['anderson_rubin_95']['global_certification']['status'] == 'certified'
    assert diag['endogeneity']['test'] == 'wooldridge_regression'


def test_same_iv_fit_is_not_a_sensitivity_comparison(products):
    from workbench.agent.completion import evaluate
    project, contract, evidence = products
    result = evaluate(project, contract, {**evidence, 'sensitivity': evidence['models']})
    assert 'iv:sensitivity:distinct_point_estimation' in result['missing']


def test_iv_singular_and_empty_ar_sets_remain_completion_gaps():
    from workbench.agent.completion_profiles import native_findings
    for kind, reason in [('unavailable', 'ar_unavailable'), ('empty', 'ar_empty_requires_model_revision')]:
        values = [{'diagnostics': {'iv': {'weak_instruments': {'anderson_rubin_95': {'kind': kind}}}}}]
        assert f'iv:diagnostics:{reason}' in native_findings('iv', values)


def test_changed_native_diagnostic_cannot_reuse_the_old_completion_companion(products, tmp_path):
    import shutil
    from workbench.agent.completion import evaluate
    project, contract, evidence = products
    copy = tmp_path / 'copy'
    shutil.copytree(project, copy)
    run = copy / 'runs' / contract['source']['run_id']
    path = run / 'iv_diagnostics.json'
    value = json.loads(path.read_text())
    value['weak_instruments']['anderson_rubin_95'] = {'kind': 'unavailable', 'reason': 'changed'}
    path.write_text(json.dumps(value))
    index_path = run / 'artifacts_index.json'
    index = json.loads(index_path.read_text())
    next(a for a in index['artifacts'] if a['artifact_id'] == 'iv_diagnostics')['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    result = evaluate(copy, contract, evidence)
    assert result['status'] == 'partial' and 'iv:model:iv_2sls' in result['missing']
