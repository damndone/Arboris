"""Native report and cross-run provenance adapters for the completion gate."""
from __future__ import annotations

import json

import pytest

from tests.test_agent_completion import api, artifact, fixture
from workbench.artifacts import sha256_file
from workbench.lineage.run_inputs import write_run_inputs
from workbench.reporting import render_html_report


def test_real_html_report_is_checked_through_its_registered_sources(tmp_path):
    contract, evidence = fixture(tmp_path)
    run = tmp_path / 'runs/r'
    render_html_report({'title': 'Completion report', 'facts': ['Recorded estimates'], 'claims': [],
                        'warnings': [], 'descriptive_stats': []}, run,
                       artifact_id='native_report', inputs=['fit', 'diag', 'alternate'])
    evidence['report'] = {'run_id': 'r', 'artifact_id': 'native_report'}
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert result['scientific_validity'] == 'not_certified'


def _transformed_source(project):
    contract, evidence = fixture(project)
    original, digest = artifact(project, 'origin', 'data', 'raw_data', {'rows': 'original observations'})
    contract['source'] = {**original, 'sha256': digest}
    run = project / 'runs/r'
    index_path = run / 'artifacts_index.json'
    index = json.loads(index_path.read_text())
    data = next(a for a in index['artifacts'] if a['artifact_id'] == 'data')
    data['artifact_type'] = 'raw_data'
    index_path.write_text(json.dumps(index))
    write_run_inputs(run, form={'model_type': 'ols'},
        upload={'sha256': data['sha256'], 'filename': 'data.json'}, rerun_of=None,
        from_node=None, rerun_reason='derived source', override_hash=None, dag_hash='fixture',
        dataset_source={'source_run_id': 'origin', 'op_node_id': 'stage:source',
                        'source_artifact_id': 'data', 'source_sha256': digest})
    return contract, evidence, run


def test_transformed_child_follows_the_real_run_input_source_binding(tmp_path):
    contract, evidence, run = _transformed_source(tmp_path)
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert any(item['sha256'] == sha256_file(run / 'run_inputs.json') for item in result['verified_lineage'])


def test_a_lineage_label_without_its_current_parent_digest_is_not_a_binding(tmp_path):
    contract, evidence, run = _transformed_source(tmp_path)
    path = run / 'run_inputs.json'
    value = json.loads(path.read_text())
    value['dataset_source']['source_sha256'] = 'f' * 64
    path.write_text(json.dumps(value))
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'partial' and 'ols:model:ols' in result['missing']


def test_native_collection_uses_completed_qualified_artifact_references(tmp_path):
    contract, evidence = fixture(tmp_path)
    artifact(tmp_path, 'report-run', 'collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed',
        'workflow_id': 'wf', 'workflow_plan_fingerprint': 'fixture',
        'steps': {'fit': {'status': 'completed', 'artifact_ids': ['r:fit', 'r:diag', 'r:alternate']}},
        'exploration_log': []})
    render_html_report({'title': 'Workflow report', 'facts': [], 'claims': [],
                        'warnings': [], 'descriptive_stats': []}, tmp_path / 'runs/report-run',
                       artifact_id='native_report', inputs=['collection'])
    evidence['report'] = {'run_id': 'report-run', 'artifact_id': 'native_report'}
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']


def test_pending_collection_steps_do_not_become_report_provenance(tmp_path):
    contract, evidence = fixture(tmp_path)
    artifact(tmp_path, 'report-run', 'collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed',
        'workflow_id': 'wf', 'workflow_plan_fingerprint': 'fixture',
        'steps': {'fit': {'status': 'pending', 'artifact_ids': ['r:fit', 'r:diag', 'r:alternate']}},
        'exploration_log': []})
    render_html_report({'title': 'Workflow report', 'facts': [], 'claims': [],
                        'warnings': [], 'descriptive_stats': []}, tmp_path / 'runs/report-run',
                       artifact_id='native_report', inputs=['collection'])
    evidence['report'] = {'run_id': 'report-run', 'artifact_id': 'native_report'}
    assert api().evaluate(tmp_path, contract, evidence)['status'] == 'partial'


def _native_ols_products(project, covariance='unadjusted'):
    import numpy as np
    import pandas as pd
    from workbench.artifacts import register_artifact
    from workbench.econometrics.runner import run_ols
    from workbench.econometrics.diagnostics import compute_diagnostics

    run = project / 'runs/r'
    run.mkdir(parents=True)
    (run / 'artifacts_index.json').write_text(json.dumps({'artifacts': []}))
    rng = np.random.default_rng(2317)
    frame = pd.DataFrame({'x': rng.normal(size=100), 'group': np.repeat(np.arange(10), 10),
                          'time': np.arange(100)})
    frame['y'] = 2 + .7 * frame['x'] + rng.normal(size=100)
    path = run / 'observations.csv'
    frame.to_csv(path, index=False)
    frame = pd.read_csv(path)
    source = register_artifact(run, 'data', path, 'raw_data', 'native_fixture', [])
    options = {'cluster_col': 'group'} if covariance == 'clustered' else (
        {'hac_time_order': 'time', 'hac_lags': 1} if covariance == 'hac' else {})
    primary, fitted = run_ols(frame, 'y', ['x'], False, 'ols_1', covariance=covariance, **options)
    main, _ = artifact(project, 'r', 'fit', 'model_result', primary, ['data'])
    diag, _ = artifact(project, 'r', 'diag', 'model_diagnostic',
                       compute_diagnostics(fitted, fitted.model.exog, 'ols_1'), ['fit'])
    subset_path = run / 'subset.csv'
    frame.iloc[:-10].to_csv(subset_path, index=False)
    register_artifact(run, 'subset', subset_path, 'derived_data', 'native_fixture', ['data'])
    subset = pd.read_csv(subset_path)
    alternate, _ = run_ols(subset, 'y', ['x'], False, 'ols_2', covariance=covariance, **options)
    sensitivity, _ = artifact(project, 'r', 'alternate', 'model_result', alternate, ['subset'])
    render_html_report({'title': 'Native estimates', 'facts': [], 'claims': [],
                        'warnings': [], 'descriptive_stats': []}, run,
                       artifact_id='native_report', inputs=['fit', 'diag', 'alternate'])
    return {'playbooks': ['ols'], 'source': {'run_id': 'r', 'artifact_id': 'data', 'sha256': source.sha256}}, {
        'models': [main], 'diagnostics': [diag], 'sensitivity': [sensitivity],
        'report': {'run_id': 'r', 'artifact_id': 'native_report'}}


def test_native_ols_fit_diagnostics_sample_comparison_and_html_report(tmp_path):
    contract, evidence = _native_ols_products(tmp_path)
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']
    assert result['scientific_validity'] == 'not_certified'


@pytest.mark.parametrize('covariance', ['clustered', 'hac'])
def test_existing_ols_covariance_variants_keep_their_actual_native_identity(tmp_path, covariance):
    contract, evidence = _native_ols_products(tmp_path, covariance)
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'requirements_met', result['missing']


def test_an_existing_derived_dataset_can_be_selected_as_the_frozen_source(tmp_path):
    ref, digest = artifact(tmp_path, 'r', 'derived', 'derived_data', {'fixture': 'derived observations'})
    assert api().source_receipt(tmp_path, ref) == {**ref, 'sha256': digest}


def test_lineage_cannot_attach_an_unrelated_child_upload_to_a_real_parent(tmp_path):
    contract, evidence, run = _transformed_source(tmp_path)
    path = run / 'run_inputs.json'
    value = json.loads(path.read_text())
    value['upload']['sha256'] = 'f' * 64
    path.write_text(json.dumps(value))
    assert 'ols:model:ols' in api().evaluate(tmp_path, contract, evidence)['missing']


def test_conflicting_persisted_source_declarations_are_not_silently_preferred(tmp_path):
    contract, evidence, run = _transformed_source(tmp_path)
    path = run / 'run_inputs.json'
    value = json.loads(path.read_text())
    value['source_lineage'] = {'dataset_source': {**value['dataset_source'], 'source_artifact_id': 'other'}}
    path.write_text(json.dumps(value))
    assert 'ols:model:ols' in api().evaluate(tmp_path, contract, evidence)['missing']


def test_recovery_reports_newly_verified_delivery_without_reusing_partial_text(tmp_path, monkeypatch):
    import asyncio
    from tests.test_agent_core_restart import setup, ProcessLost
    from tests.test_numeric_grounding import ScriptedAdapter

    async def scenario():
        contract, evidence = _native_ols_products(tmp_path / 'project')
        report = evidence.pop('report')
        core, store, _ = setup(tmp_path, ScriptedAdapter(['The estimates are recorded.']))
        core.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        async def lost(*args, **kwargs):
            raise ProcessLost()
        monkeypatch.setattr(core, '_finish_assistant', lost)
        with pytest.raises(ProcessLost):
            await core.prompt('Perform the full analysis', budget={'max_steps': 1, 'timeout_s': 30})
        [record] = store.list_active()
        evidence['report'] = report
        adapter = ScriptedAdapter([])
        resumed, fresh, repo = setup(tmp_path, adapter, create=False)
        resumed.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        answer = await resumed.resume(record.turn_id)
        assert answer.startswith('Required delivery evidence is now verified')
        assert 'Partially complete' not in answer
        last = [entry for entry in repo.get_branch('session-a') if entry.entry_type == 'message'][-1]
        assert last.payload['completion_check']['status'] == 'requirements_met'
        assert not adapter.requests and fresh.get(record.turn_id).steps_used == 1
    asyncio.run(scenario())
