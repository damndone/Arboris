"""Machine completion uses persisted products, never plan step statuses."""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from workbench.artifacts import register_artifact
from workbench.artifacts import sha256_file


def api():
    assert importlib.util.find_spec('workbench.agent.completion') is not None, 'A machine completion owner is required'
    return importlib.import_module('workbench.agent.completion')


def artifact(project, run, name, kind, payload, inputs=()):
    root = project / 'runs' / run
    path = root / f'{name}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')
    index = root / 'artifacts_index.json'
    if not index.exists():
        index.write_text(json.dumps({'artifacts': []}))
    record = register_artifact(root, name, path, kind, 'fixture', list(inputs))
    return {'run_id': run, 'artifact_id': name}, record.sha256


def fixture(project):
    source, digest = artifact(project, 'r', 'data', 'processed_data', {'rows': 'fixture'})
    main, _ = artifact(project, 'r', 'fit', 'model_result', {
        'model_type': 'ols', 'model_id': 'ols_1', 'nobs': 80,
        'coefficients': {'x': {'estimate': 1.2, 'std_error': .2}},
        'point_estimation_fingerprint': 'a' * 64,
        'analysis_sample_fingerprint': 'c' * 64}, ['data'])
    diagnostic, _ = artifact(project, 'r', 'diag', 'model_diagnostic', {
        'model_id': 'ols_1', 'breusch_pagan': {'p_value': .4},
        'cooks_distance': {'max': .02, 'threshold': .05, 'n_high': 0}}, ['fit'])
    sensitivity, _ = artifact(project, 'r', 'alternate', 'model_result', {
        'model_type': 'ols', 'model_id': 'ols_2', 'nobs': 80,
        'coefficients': {'x': {'estimate': 1.1, 'std_error': .25}},
        'point_estimation_fingerprint': 'b' * 64,
        'analysis_sample_fingerprint': 'c' * 64}, ['data'])
    report, _ = artifact(project, 'r', 'report', 'report', {'sections': [{'text': 'Association with uncertainty and limitations.'}]}, ['fit', 'diag', 'alternate'])
    contract = {'playbooks': ['ols'], 'source': {**source, 'sha256': digest}}
    evidence = {'models': [main], 'diagnostics': [diagnostic], 'sensitivity': [sensitivity], 'report': report}
    return contract, evidence


def test_complete_is_an_evidence_check_not_a_scientific_certificate(tmp_path):
    contract, evidence = fixture(tmp_path)
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'requirements_met'
    assert result['missing'] == []
    assert result['scientific_validity'] == 'not_certified'
    assert all(item['sha256'] for item in result['verified_artifacts'])


def test_inspection_distinguishes_ambiguous_primary_and_returns_exact_bindings(tmp_path):
    contract, evidence = fixture(tmp_path)
    evidence['models'].append(evidence['sensitivity'][0])
    before = json.dumps(evidence, sort_keys=True)
    result = api().evaluate(tmp_path, contract, evidence, suggest=True)
    assert result['status'] == 'partial'
    assert result['repair_steps'][0]['reason'] == 'ambiguous_primary'
    assert result['repair_steps'][0]['candidates'] == evidence['models']
    catalog = result['evidence_catalog']
    assert {m['ref']['artifact_id'] for m in catalog['models']} == {'fit', 'alternate'}
    main = next(m for m in catalog['models'] if m['ref']['artifact_id'] == 'fit')
    assert main['diagnostics'] == evidence['diagnostics']
    assert json.dumps(evidence, sort_keys=True) == before
    assert 'evidence_catalog' not in api().evaluate(tmp_path, contract, evidence)


def test_inspection_lists_registered_reports_without_guessing_suffixes(tmp_path):
    contract, evidence = fixture(tmp_path)
    actual = evidence['report'].copy()
    evidence['report']['artifact_id'] = 'invented_report_without_suffix'
    result = api().evaluate(tmp_path, contract, evidence, suggest=True)
    assert result['missing'] == ['report:registered_nonempty']
    assert result['evidence_catalog']['reports'] == [{'ref': actual, 'covers_submitted_evidence': True}]
    assert result['repair_steps'][-1]['reason'] == 'unregistered_or_empty_report'
    assert evidence['report']['artifact_id'] == 'invented_report_without_suffix'


def test_inspection_never_suggests_changed_or_foreign_products(tmp_path):
    contract, evidence = fixture(tmp_path)
    (tmp_path / 'runs/r/alternate.json').write_text('{}')
    artifact(tmp_path, 'r', 'foreign_fit', 'model_result', {
        'model_type': 'ols', 'model_id': 'foreign', 'nobs': 80,
        'coefficients': {'x': {'estimate': 10, 'std_error': .1}}})
    result = api().evaluate(tmp_path, contract, evidence, suggest=True)
    assert [m['ref']['artifact_id'] for m in result['evidence_catalog']['models']] == ['fit']
    contract['source']['sha256'] = 'f' * 64
    result = api().evaluate(tmp_path, contract, evidence, suggest=True)
    assert not result['evidence_catalog']['models']
    assert not result['evidence_catalog']['reports']


def test_inspection_catalog_is_bounded_and_does_not_certify_alternatives(tmp_path):
    contract, evidence = fixture(tmp_path)
    for i in range(12):
        artifact(tmp_path, 'r', f'other_{i}', 'model_result', {
            'model_type': 'ols', 'model_id': f'ols_other_{i}', 'nobs': 80,
            'coefficients': {'x': {'estimate': i, 'std_error': .2}}}, ['data'])
    result = api().evaluate(tmp_path, contract, evidence, suggest=True)
    catalog = result['evidence_catalog']
    assert len(catalog['models']) == 8 and catalog['omitted_model_count'] == 6
    assert result['status'] == 'requirements_met'
    assert result['scientific_validity'] == 'not_certified'
    assert all(m['ref'] in evidence['models'] or not m['diagnostics'] for m in catalog['models'])


@pytest.mark.parametrize('playbook,required', [
    ('ols', 'ols'), ('survival', 'survival_cox'), ('panel', 'panel'),
    ('did', 'did'), ('iv', 'iv_2sls'), ('time_series', 'time_series'),
    ('lmm', 'linear_mixed_effects'), ('garch', 'arma_garch'),
])
def test_each_playbook_has_a_model_specific_missing_gate(tmp_path, playbook, required):
    contract, _ = fixture(tmp_path)
    contract['playbooks'] = [playbook]
    result = api().evaluate(tmp_path, contract, {})
    assert result['status'] == 'partial'
    assert any(required in item for item in result['missing'])
    assert any('diagnostic' in item for item in result['missing'])
    assert any('sensitivity' in item for item in result['missing'])


def test_imported_ols_cannot_stand_in_for_cox_lmm_or_time_series(tmp_path):
    contract, evidence = fixture(tmp_path)
    for family in ('survival', 'lmm', 'time_series', 'garch'):
        contract['playbooks'] = [family]
        result = api().evaluate(tmp_path, contract, evidence)
        assert result['status'] == 'partial'
        assert any('model:' in item for item in result['missing'])


def test_changed_bytes_stale_source_and_foreign_diagnostics_are_missing(tmp_path):
    contract, evidence = fixture(tmp_path)
    (tmp_path / 'runs/r/fit.json').write_text('{}')
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'partial' and any('model:' in item for item in result['missing'])
    contract, evidence = fixture(tmp_path / 'other')
    contract['source']['sha256'] = 'f' * 64
    assert 'source:changed_or_unavailable' in api().evaluate(tmp_path / 'other', contract, evidence)['missing']
    contract, evidence = fixture(tmp_path / 'third')
    wrong, _ = artifact(tmp_path / 'third', 'r', 'foreign_diag', 'model_diagnostic', {
        'model_id': 'other', 'breusch_pagan': {'p_value': .4},
        'cooks_distance': {'max': .02, 'n_high': 0}}, ['fit'])
    evidence['diagnostics'] = [wrong]
    assert any('diagnostic' in item for item in api().evaluate(tmp_path / 'third', contract, evidence)['missing'])


def test_same_estimate_with_new_standard_errors_is_not_influence_sensitivity(tmp_path):
    contract, evidence = fixture(tmp_path)
    path = tmp_path / 'runs/r/alternate.json'
    value = json.loads(path.read_text())
    value['point_estimation_fingerprint'] = 'a' * 64
    path.write_text(json.dumps(value))
    # Re-registering an identical id is ambiguous, never an alternate source.
    index_path = tmp_path / 'runs/r/artifacts_index.json'
    index = json.loads(index_path.read_text())
    next(a for a in index['artifacts'] if a['artifact_id'] == 'alternate')['sha256'] = sha256_file(path)
    index_path.write_text(json.dumps(index))
    result = api().evaluate(tmp_path, contract, evidence)
    assert result['status'] == 'partial'
    assert 'ols:sensitivity:distinct_point_estimation' in result['missing']


@pytest.mark.parametrize('bad', ['duplicate', 'path_escape', 'failed_diagnostic', 'unrelated_source', 'empty_report'])
def test_registered_name_or_nonempty_json_is_not_evidence(tmp_path, bad):
    contract, evidence = fixture(tmp_path)
    index_path = tmp_path / 'runs/r/artifacts_index.json'
    index = json.loads(index_path.read_text())
    if bad == 'duplicate':
        index['artifacts'].append(index['artifacts'][1].copy())
    elif bad == 'path_escape':
        index['artifacts'][1]['path'] = '../../outside.json'
    elif bad == 'unrelated_source':
        index['artifacts'][1]['inputs'] = []
    else:
        ref = evidence['diagnostics'][0] if bad == 'failed_diagnostic' else evidence['report']
        path = tmp_path / 'runs/r' / (ref['artifact_id'] + '.json')
        payload = {'model_id': 'ols_1', 'breusch_pagan': {'error': 'unavailable'}, 'cooks_distance': {}} if bad == 'failed_diagnostic' else {'sections': []}
        path.write_text(json.dumps(payload))
        next(a for a in index['artifacts'] if a['artifact_id'] == ref['artifact_id'])['sha256'] = sha256_file(path)
    index_path.write_text(json.dumps(index))
    assert api().evaluate(tmp_path, contract, evidence)['status'] == 'partial'


def test_contract_survives_plan_revision_and_cannot_be_silently_weakened(tmp_path):
    from workbench.agent.plans import Plan, PlanError, PlanStep, merge
    contract, evidence = fixture(tmp_path)
    args = dict(question='q', criteria=[], steps=(PlanStep('a', 'a', ('model.genesis',)),), budget=None, allowed_classes=None)
    plan = merge(None, **args, completion=contract, completion_evidence=evidence)
    updated = merge(plan, **args)
    assert Plan.from_dict(updated.to_dict()).completion == contract
    assert updated.completion_evidence == evidence
    with pytest.raises(PlanError, match='completion'):
        merge(plan, **args, completion={'playbooks': ['lmm'], 'source': contract['source']})
    old = merge(None, **args)
    assert 'completion' not in old.to_dict() and 'completion_evidence' not in old.to_dict()


def test_final_reply_is_replaced_with_visible_missing_items_before_streaming(tmp_path):
    from tests.test_numeric_grounding import _agent
    contract, evidence = fixture(tmp_path)
    evidence['models'] = []
    agent, adapter, repo, events = _agent(tmp_path, ['分析完成。'])
    agent.completion_check = lambda: api().evaluate(tmp_path, contract, evidence)
    answer = asyncio.run(agent.prompt('请做完整分析'))
    assert answer.startswith('部分完成') and 'OLS 主模型' in answer
    assert '分析完成' not in answer
    assert len(adapter.requests) == 1
    visible = [e.payload for e in events.replay('s') if e.event_type in {'message_update', 'message_end'}]
    assert all('分析完成' not in json.dumps(p, ensure_ascii=False) for p in visible)
    assert repo.get_branch('s')[-1].payload['completion_check']['status'] == 'partial'


def test_no_contract_does_not_silently_certify_a_completion_claim(tmp_path):
    from tests.test_numeric_grounding import _agent
    agent, _, _, _ = _agent(tmp_path, ['Analysis complete.'])
    agent.completion_check = lambda: api().evaluate(tmp_path, None, None)
    answer = asyncio.run(agent.prompt('Perform the full analysis'))
    assert answer.startswith('Partially complete') and 'dataset source' in answer


def test_product_registration_and_plan_tool_share_the_final_gate(tmp_path):
    from tests.test_read_only_analysis import _Fixture
    contract, evidence = fixture(tmp_path / 'project')
    f = _Fixture(tmp_path / 'runtime')
    f.orchestrator.context_provider.project_root = tmp_path / 'project'
    registry = f.orchestrator.tool_registry('chain-a')
    call = {'tool_call_id': 'plan', 'tool_id': 'update_plan', 'arguments': {
        'question': 'Complete the source-bound linear analysis',
        'steps': [{'step_id': 'fit', 'title': 'Fit', 'operation_ids': ['model.genesis']}],
        'completion': contract, 'completion_evidence': evidence}}
    result = asyncio.run(registry.execute(call, session_id='chain-session'))
    assert result.ok and result.output['saved']
    check = {'tool_call_id': 'check', 'tool_id': 'inspect_analysis_completion', 'arguments': {}}
    result = asyncio.run(registry.execute(check, session_id='chain-session'))
    assert result.ok and result.output['status'] == 'requirements_met'
    assert f.orchestrator._chain('chain-a')[1].completion_check()['status'] == 'requirements_met'
    assert not asyncio.run(registry.execute(check, session_id='wrong')).ok


def test_high_influence_requires_a_changed_sample_not_just_different_controls(tmp_path):
    contract, evidence = fixture(tmp_path)
    path = tmp_path / 'runs/r/diag.json'
    value = json.loads(path.read_text())
    value['cooks_distance']['n_high'] = 3
    path.write_text(json.dumps(value))
    index_path = tmp_path / 'runs/r/artifacts_index.json'
    index = json.loads(index_path.read_text())
    next(a for a in index['artifacts'] if a['artifact_id'] == 'diag')['sha256'] = sha256_file(path)
    index_path.write_text(json.dumps(index))
    result = api().evaluate(tmp_path, contract, evidence)
    assert 'ols:sensitivity:influence_sample_comparison' in result['missing']


def test_tool_call_narration_cannot_claim_a_missing_model_complete(tmp_path):
    from tests.test_numeric_grounding import _agent, INSPECT
    agent, adapter, _, events = _agent(tmp_path, [INSPECT, 'Analysis complete.'])
    agent.completion_check = lambda: api().evaluate(tmp_path, None, None)
    answer = asyncio.run(agent.prompt('Perform the analysis'))
    assert answer.startswith('Partially complete')
    assert len(adapter.requests) == 2
    assert not any('Analysis complete' in json.dumps(e.payload) for e in events.replay('s')
                   if e.event_type in {'message_update', 'message_end'})


M0_ROOT = Path(__file__).parent / 'fixtures' / 'agent_completion'
M0_CASES = json.loads((M0_ROOT / 'manifest.json').read_text())


@pytest.mark.parametrize('case', M0_CASES, ids=lambda case: case['task'])
def test_m0_original_failures_replay_without_provider_or_heldout(tmp_path, case):
    import gzip
    import hashlib
    import shutil
    from tests.test_numeric_grounding import _agent
    project = tmp_path / 'original-project'
    shutil.copytree(M0_ROOT / case['task'] / 'project', project)
    # Large raw recordings are losslessly packed in Git. Always expand the
    # archive, even when this checkout retains its original local raw copy.
    for relative, digest in case.get('packed_files', {}).items():
        assert sha256_file(project / relative) == digest
    for packed in project.rglob('*.gz'):
        packed.with_suffix('').write_bytes(gzip.decompress(packed.read_bytes()))
    for relative, digest in case['files'].items():
        assert sha256_file(project / relative) == digest
    raw = (M0_ROOT / case['task'] / 'final-entry.json').read_text().rstrip('\n')
    assert hashlib.sha256(raw.encode()).hexdigest() == case['final_entry_sha256']
    original = json.loads(raw)['payload']['content']
    result = api().evaluate(project, case['contract'], case['evidence'])
    assert result['status'] == 'partial'
    assert not any(item.startswith('source:') for item in result['missing'])
    expected = {'ols': 'ols:sensitivity:', 'survival': 'survival:model:survival_cox',
                'lmm': 'lmm:model:linear_mixed_effects', 'time_series': 'time_series:diagnostics:',
                'garch': 'garch:sensitivity:', 'iv': 'iv:sensitivity:'}[case['playbook']]
    assert any(item.startswith(expected) for item in result['missing'])
    agent, adapter, repo, events = _agent(tmp_path, [original])
    agent.completion_check = lambda: api().evaluate(project, case['contract'], case['evidence'])
    answer = asyncio.run(agent.prompt('请汇报这项完整分析的完成情况', budget={'max_steps': 1}))
    assert answer.startswith('部分完成')
    assert len(adapter.requests) == 1
    assert all('分析完成' not in json.dumps(e.payload, ensure_ascii=False) for e in events.replay('s')
               if e.event_type in {'message_update', 'message_end'})
    assert repo.get_branch('s')[-1].payload['completion_check']['status'] == 'partial'


def test_resume_rechecks_products_before_publishing_an_old_final_payload(tmp_path, monkeypatch):
    from tests.test_agent_core_restart import setup, ProcessLost
    from tests.test_numeric_grounding import ScriptedAdapter

    async def scenario():
        contract, evidence = fixture(tmp_path / 'project')
        core, store, _ = setup(tmp_path, ScriptedAdapter(['Analysis complete.']))
        core.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        async def lost(*args, **kwargs):
            raise ProcessLost()
        monkeypatch.setattr(core, '_finish_assistant', lost)
        with pytest.raises(ProcessLost):
            await core.prompt('Perform the analysis', budget={'max_steps': 2, 'timeout_s': 30})
        [record] = store.list_active()
        (tmp_path / 'project/runs/r/fit.json').write_text('{}')
        adapter = ScriptedAdapter([])
        resumed, fresh, repo = setup(tmp_path, adapter, create=False)
        resumed.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        answer = await resumed.resume(record.turn_id)
        assert answer.startswith('Partially complete')
        assert not adapter.requests and fresh.get(record.turn_id).steps_used == 1
        last = [e for e in repo.get_branch('session-a') if e.entry_type == 'message'][-1]
        assert last.payload['completion_check']['status'] == 'partial'
        visible = [e.payload for e in resumed.events.replay('session-a') if e.event_type == 'message_end']
        assert all('Analysis complete' not in json.dumps(item) for item in visible)
    asyncio.run(scenario())


def test_completion_tool_output_has_a_fixed_bound_even_with_maximum_references(tmp_path):
    contract, evidence = fixture(tmp_path)
    for i in range(24):
        ref, _ = artifact(tmp_path, 'r', 'diagnostic-' + str(i) + 'x' * 180, 'model_diagnostic', {
            'model_id': 'ols_1', 'breusch_pagan': {'p_value': .4},
            'cooks_distance': {'max': .02, 'n_high': 0}}, ['fit'])
        evidence.setdefault('diagnostics', []).append(ref)
    evidence['diagnostics'] = evidence['diagnostics'][-24:]
    result = api().evaluate(tmp_path, contract, evidence)
    assert len(json.dumps(result).encode()) < 12_000
    assert len(result['verified_artifacts']) <= 8
    assert result['verified_artifact_count'] > len(result['verified_artifacts'])



def test_terminal_checkpoint_recovery_does_not_reissue_stale_completion(tmp_path, monkeypatch):
    from tests.test_agent_core_restart import setup, ProcessLost
    from tests.test_numeric_grounding import ScriptedAdapter
    async def scenario():
        contract, evidence = fixture(tmp_path / 'project')
        core, store, _ = setup(tmp_path, ScriptedAdapter(['Analysis complete.']))
        core.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        original = store.transition
        def lost(turn_id, status, **kwargs):
            if status == 'completed':
                raise ProcessLost()
            return original(turn_id, status, **kwargs)
        monkeypatch.setattr(store, 'transition', lost)
        with pytest.raises(ProcessLost):
            await core.prompt('Perform the analysis', budget={'max_steps': 1, 'timeout_s': 30})
        [record] = store.list_active()
        (tmp_path / 'project/runs/r/fit.json').write_text('{}')
        adapter = ScriptedAdapter([])
        resumed, fresh, _ = setup(tmp_path, adapter, create=False)
        resumed.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        assert (await resumed.resume(record.turn_id)).startswith('Partially complete')
        assert not adapter.requests and fresh.get(record.turn_id).steps_used == 1
    asyncio.run(scenario())


def test_source_receipt_is_discoverable_without_reading_or_guessing_file_paths(tmp_path):
    from tests.test_read_only_analysis import _Fixture
    contract, _ = fixture(tmp_path / 'project')
    f = _Fixture(tmp_path / 'runtime')
    f.orchestrator.context_provider.project_root = tmp_path / 'project'
    source = {k: v for k, v in contract['source'].items() if k != 'sha256'}
    call = {'tool_call_id': 'source', 'tool_id': 'inspect_analysis_completion', 'arguments': {'source': source}}
    result = asyncio.run(f.orchestrator.tool_registry('chain-a').execute(call, session_id='chain-session'))
    assert result.ok and result.output['source'] == contract['source']
    assert 'rows' not in json.dumps(result.output)


def test_invalid_source_contract_does_not_freeze_an_unrepairable_plan(tmp_path):
    from tests.test_read_only_analysis import _Fixture
    contract, _ = fixture(tmp_path / 'project')
    contract['source']['sha256'] = 'f' * 64
    f = _Fixture(tmp_path / 'runtime')
    f.orchestrator.context_provider.project_root = tmp_path / 'project'
    call = {'tool_call_id': 'plan', 'tool_id': 'update_plan', 'arguments': {
        'question': 'q', 'completion': contract,
        'steps': [{'step_id': 'fit', 'title': 'Fit', 'operation_ids': ['model.genesis']}]}}
    result = asyncio.run(f.orchestrator.tool_registry('chain-a').execute(call, session_id='chain-session'))
    assert result.ok and not result.output['saved']
    assert f.orchestrator.plan_store.current('chain-session') is None


def test_human_can_explicitly_correct_completion_contract_with_new_approval(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from workbench.app import app
    from tests.test_agent_plan_controls import fixture as plan_fixture
    root, repo, store, plan = plan_fixture(tmp_path)
    contract, evidence = fixture(root)
    store.save('session-a', replace(plan, completion=contract, completion_evidence=evidence))
    with TestClient(app) as client:
        assert client.post('/agent/sessions/session-a/plan/approve', params={'project_root': str(root)},
                           json={'version': plan.version}).status_code == 200
        corrected = {**contract, 'playbooks': ['survival']}
        response = client.patch('/agent/sessions/session-a/plan', params={'project_root': str(root)},
                                json={'version': plan.version, 'completion': corrected})
    assert response.status_code == 200, response.text
    revised = response.json()['plan']
    assert revised['completion'] == corrected and revised['status'] == 'needs_approval'
    assert 'completion_evidence' not in revised
    assert store.current('session-a').completion == corrected


def test_single_result_answers_and_ordinary_tool_narration_do_not_require_full_analysis(tmp_path):
    from tests.test_numeric_grounding import _agent, INSPECT
    agent, _, _, events = _agent(tmp_path, [INSPECT, 'The available p value is 0.098.'])
    agent.completion_check = lambda: api().evaluate(tmp_path, None, None)
    answer = asyncio.run(agent.prompt('What p value was returned?'))
    assert answer == 'The available p value is 0.098.'
    assert 'partial' not in json.dumps([e.payload for e in events.replay('s') if e.event_type == 'message_end'])


@pytest.mark.parametrize('claim', ['全部完成。', '已完成全部分析。', 'I have finished the analysis.',
                                  'All requested analyses have been completed.', 'Everything is done.'])
def test_completion_phrasings_cannot_bypass_missing_contract(tmp_path, claim):
    from tests.test_numeric_grounding import _agent
    agent, _, _, _ = _agent(tmp_path, [claim])
    agent.completion_check = lambda: api().evaluate(tmp_path, None, None)
    answer = asyncio.run(agent.prompt('Please perform the full analysis'))
    assert answer.startswith('Partially complete')


def test_completed_single_operation_is_not_a_full_analysis_claim(tmp_path):
    from tests.test_numeric_grounding import _agent
    agent, _, _, _ = _agent(tmp_path, ['导入全部完成。'])
    agent.completion_check = lambda: api().evaluate(tmp_path, None, None)
    assert asyncio.run(agent.prompt('导入完成了吗？')) == '导入全部完成。'


def test_active_incomplete_plan_also_blocks_generic_done_after_continue(tmp_path):
    from tests.test_numeric_grounding import _agent
    contract, evidence = fixture(tmp_path / 'project')
    evidence['models'] = []
    agent, _, _, _ = _agent(tmp_path, ['全部完成。'])
    agent.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
    answer = asyncio.run(agent.prompt('继续'))
    assert answer.startswith('部分完成') and '全部完成' not in answer


def test_recovering_the_same_partial_answer_does_not_duplicate_the_notice(tmp_path, monkeypatch):
    from tests.test_agent_core_restart import setup, ProcessLost
    from tests.test_numeric_grounding import ScriptedAdapter
    async def scenario():
        contract, evidence = fixture(tmp_path / 'project')
        evidence['models'] = []
        core, store, _ = setup(tmp_path, ScriptedAdapter(['Analysis complete.']))
        core.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        async def lost(*args, **kwargs):
            raise ProcessLost()
        monkeypatch.setattr(core, '_finish_assistant', lost)
        with pytest.raises(ProcessLost):
            await core.prompt('Perform the full analysis', budget={'max_steps': 1, 'timeout_s': 30})
        [record] = store.list_active()
        adapter = ScriptedAdapter([])
        resumed, _, _ = setup(tmp_path, adapter, create=False)
        resumed.completion_check = lambda: api().evaluate(tmp_path / 'project', contract, evidence)
        answer = await resumed.resume(record.turn_id)
        assert answer.count('Partially complete') == 1
        assert not adapter.requests
    asyncio.run(scenario())
