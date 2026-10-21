"""Explicit AR uses the native completed IV owner; no provider or default opt-in."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.test_agent_completion_iv import build_products


@pytest.fixture(scope='module')
def products(tmp_path_factory):
    return build_products(tmp_path_factory.mktemp('iv-ar-operation'))


def ar_workflow(project, contract, *, name='explicit-ar'):
    from workbench.agent.workflow import compile_workflow
    return compile_workflow(workflow_id=name,
        target={'run_id': contract['source']['run_id'], 'node_ref': 'stage:cleaned',
                'artifact_id': contract['source']['artifact_id']},
        preconditions={'source_artifact_fingerprint': contract['source']['sha256'],
                       'context_fingerprint': 'iv-ar-offline-fixture'},
        steps=[{'step_id': 'ar', 'operation_id': 'iv.ar_confidence', 'depends_on': [],
                'spec': {'model_run_id': contract['source']['run_id'], 'model_ref': 'iv_2sls_1'}}])


def test_explicit_ar_is_reachable_as_a_shared_read_only_operation():
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    assert 'iv.ar_confidence' in WORKFLOW_STEP_SPEC_CONTRACTS
    declaration = WORKFLOW_STEP_SPEC_CONTRACTS['iv.ar_confidence']
    assert declaration.effect_level == 'read_only'
    assert declaration.model_reference_fields == ('model_ref',)


def test_explicit_ar_persists_bound_evidence_and_does_not_change_old_results(products, monkeypatch):
    from workbench.agent.workflow import execute_workflow
    from workbench.agent.completion import evaluate
    from workbench.artifacts import read_json
    project, contract, evidence = products
    run = project / 'runs' / contract['source']['run_id']
    old = {p: p.read_bytes() for p in [run/'model_results/iv_2sls_1.json',
        run/'model_results/iv_2sls_1.completion.json', run/'iv_diagnostics.json']}
    draft = ar_workflow(project, contract)
    from workbench.services import iv_ar
    monkeypatch.setattr(iv_ar, 'read_analysis_frame',
        lambda *a, **kw: pytest.fail('AR re-read the already loaded, fixed analysis input'))
    state = execute_workflow(project, draft)
    assert state.status == 'completed', state.to_dict()
    [artifact_id] = state.steps['ar'].artifact_ids
    refs = {**evidence, 'diagnostics': [*evidence['diagnostics'],
        {'run_id': run.name, 'artifact_id': artifact_id}]}
    result = evaluate(project, contract, refs)
    assert not any('iv:diagnostics:' in code for code in result['missing'])
    assert result['missing'] == ['report:result_sources']  # Old report cannot claim the new AR.
    for p, raw in old.items():
        assert p.read_bytes() == raw
    index = read_json(run/'artifacts_index.json')
    record = next(a for a in index['artifacts'] if a['artifact_id'] == artifact_id)
    value = read_json(run/record['path'])['result']
    assert value['anderson_rubin_95']['global_certification']['status'] == 'certified'
    assert value['model_sha256'] == hashlib.sha256(old[run/'model_results/iv_2sls_1.json']).hexdigest()
    assert value['completion_sha256'] == hashlib.sha256(old[run/'model_results/iv_2sls_1.completion.json']).hexdigest()
    monkeypatch.setattr(iv_ar, 'compute_ar', lambda *a, **kw: pytest.fail('completed step recomputed AR'))
    assert execute_workflow(project, draft).to_dict() == state.to_dict()
    from workbench.agent.workflow import compile_workflow
    refs_with_roles = [{**ref, 'role': role} for role, refs_ in [
        ('primary', refs['models']), ('diagnostic', refs['diagnostics']), ('sensitivity', refs['sensitivity'])]
        for ref in refs_]
    report_draft = compile_workflow(workflow_id='report-existing-iv-results', target=draft.target,
        preconditions=draft.preconditions, steps=[{'step_id': 'report', 'operation_id': 'report.compose',
            'spec': {'result_refs': refs_with_roles}}])
    report_state = execute_workflow(project, report_draft)
    assert report_state.status == 'completed', report_state.to_dict()
    index = read_json(run/'artifacts_index.json')
    html = next(a for a in index['artifacts'] if a['artifact_id'] in report_state.steps['report'].artifact_ids
                and a['path'].endswith('.html'))
    final = {**refs, 'report': {'run_id': run.name, 'artifact_id': html['artifact_id']}}
    assert evaluate(project, contract, final)['status'] == 'requirements_met'
    text = (run/html['path']).read_text()
    assert 'education' in text and 'anderson_rubin_95' in text and 'primary' in text
    assert value['anderson_rubin_95']['components']
    assert 'anderson_rubin_95.components[0].lower_closed' in text
    assert 'anderson_rubin_95.global_certification.root_brackets[0].lower_rational' in text
    # Rendered coefficient values come from the original packet, not a generated table snapshot.
    from openpyxl import load_workbook
    xlsx = next(a for a in index['artifacts'] if a['artifact_id'] in report_state.steps['report'].artifact_ids
                and a['path'].endswith('.xlsx'))
    rows = list(load_workbook(run/xlsx['path'], data_only=True)['regression_table'].values)
    packet = json.loads(old[run/'model_results/iv_2sls_1.json'])
    column = rows[0].index(f"{run.name}:iv_2sls_1 estimate")
    exported = next(row[column] for row in rows[1:] if row[0] == 'education')
    # Existing XLSX numeric serialization uses 16 significant decimal digits;
    # the source packet's full-precision bytes above must remain unchanged.
    assert exported == float(format(packet['coefficients']['education']['estimate'], '.16g'))


def test_ar_rejects_changed_model_without_publishing_evidence(products, tmp_path):
    from shutil import copytree
    from workbench.agent.workflow import execute_workflow
    project, contract, _ = products
    copied = tmp_path/'project'; copytree(project, copied)
    path = copied/'runs'/contract['source']['run_id']/'model_results/iv_2sls_1.json'
    value = json.loads(path.read_text()); value['coefficients']['education']['estimate'] += 1
    path.write_text(json.dumps(value))
    state = execute_workflow(copied, ar_workflow(copied, contract, name='changed-model'))
    assert state.status == 'failed'
    assert not state.steps['ar'].artifact_ids


@pytest.mark.parametrize('field,value', [('model_run_id', 'foreign-run'), ('confidence_level', .90),
    ('completion_sha256', 'f'*64), ('global_certification', {'status': 'unverified'})])
def test_stale_foreign_or_uncertified_ar_cannot_open_the_completion_gate(products, tmp_path, field, value):
    from shutil import copytree
    from workbench.agent.completion import evaluate
    project, contract, evidence = products
    copied = tmp_path/'project'; copytree(project, copied)
    run = copied/'runs'/contract['source']['run_id']
    index_path = run/'artifacts_index.json'; index = json.loads(index_path.read_text())
    entry = next(a for a in index['artifacts'] if a['artifact_type'] == 'post_estimation')
    path = run/entry['path']; payload = json.loads(path.read_text())
    if field == 'global_certification':
        payload['result']['anderson_rubin_95'][field] = value
    else:
        payload['result'][field] = value
    path.write_text(json.dumps(payload)); entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    result = evaluate(copied, contract, {**evidence, 'diagnostics': [*evidence['diagnostics'],
        {'run_id': run.name, 'artifact_id': entry['artifact_id']}]})
    assert result['status'] == 'partial' and 'iv:diagnostics:ar_unavailable' in result['missing']


def test_report_refuses_a_result_from_a_different_source_before_export(products, tmp_path):
    from shutil import copytree
    from tests.test_agent_completion import artifact
    from workbench.agent.workflow import execute_workflow, compile_workflow
    project, contract, _ = products
    copied = tmp_path/'project'; copytree(project, copied)
    artifact(copied, 'foreign', 'data', 'processed_data', {'other': 'observations'})
    ref, _ = artifact(copied, 'foreign', 'fit', 'model_result', {
        'model_type': 'ols', 'model_id': 'ols_1', 'nobs': 8,
        'coefficients': {'x': {'estimate': 1, 'std_error': .1}}}, ['data'])
    draft = ar_workflow(copied, contract)
    report = compile_workflow(workflow_id='reject-foreign-report', target=draft.target,
        preconditions=draft.preconditions, steps=[{'step_id': 'report', 'operation_id': 'report.compose',
            'spec': {'result_refs': [{**ref, 'role': 'primary'}]}}])
    state = execute_workflow(copied, report)
    assert state.status == 'failed' and not state.steps['report'].artifact_ids
    assert not (copied/'runs'/contract['source']['run_id']/'reports/reject-foreign-report.html').exists()


def test_report_cannot_cover_a_changed_diagnostic_even_if_current_ar_is_still_valid(products, tmp_path):
    from shutil import copytree
    from workbench.agent.completion import evaluate
    project, contract, evidence = products
    copied = tmp_path/'project'; copytree(project, copied)
    run = copied/'runs'/contract['source']['run_id']
    index_path = run/'artifacts_index.json'; index = json.loads(index_path.read_text())
    entry = next(a for a in index['artifacts'] if a['artifact_type'] == 'post_estimation')
    report = next(a for a in index['artifacts'] if a['path'].endswith('report-existing-iv-results.html'))
    path = run/entry['path']; payload = json.loads(path.read_text())
    payload['result']['note'] = 'new diagnostic annotation after export'
    path.write_text(json.dumps(payload)); entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    result = evaluate(copied, contract, {**evidence, 'diagnostics': [*evidence['diagnostics'],
        {'run_id': run.name, 'artifact_id': entry['artifact_id']}],
        'report': {'run_id': run.name, 'artifact_id': report['artifact_id']}})
    assert result['status'] == 'partial' and 'report:result_sources' in result['missing']
    assert not any('iv:diagnostics:' in code for code in result['missing'])


def test_the_gate_binds_one_of_repeated_ar_runs_for_the_primary(tmp_path):
    """Paid fix3 round (iv_weak, Ask): the Agent ran the same AR twice; stored as
    post_estimation, neither was bound and the gate's one-AR rule would refuse two."""
    from workbench.agent.completion import derive_evidence, evaluate
    from workbench.agent.workflow import execute_workflow
    project, contract, evidence = build_products(tmp_path / 'repeat')
    run = contract['source']['run_id']
    artifacts = []
    for name in ('ar-first', 'ar-again'):
        state = execute_workflow(project, ar_workflow(project, contract, name=name))
        assert state.status == 'completed', state.to_dict()
        artifacts += state.steps['ar'].artifact_ids
    named_both = {'models': evidence['models'], 'diagnostics': [
        *evidence['diagnostics'], *({'run_id': run, 'artifact_id': a} for a in artifacts)]}
    for given in ({'models': evidence['models']}, named_both):
        derived, notes = derive_evidence(project, contract, given)
        ars = [d for d in derived['diagnostics'] if d['artifact_id'] in artifacts]
        assert len(ars) == 1
        result = evaluate(project, contract, derived)
        assert not any(code.startswith('iv:diagnostics:') for code in result['missing']), result['missing']
