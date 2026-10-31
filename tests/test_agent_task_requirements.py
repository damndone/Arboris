"""Original user requirements survive plan edits, continuation and reload."""
import asyncio
from dataclasses import replace

import pytest

from tests.test_agent_completion import artifact
from tests.test_read_only_analysis import _Fixture


def _call(runtime, arguments):
    return asyncio.run(runtime.orchestrator.tool_registry('chain-a').execute({
        'tool_call_id': 'plan', 'tool_id': 'update_plan', 'arguments': arguments},
        session_id='chain-session')).output


def _arguments(runtime, **extra):
    return {'question': 'Classify the variable.', 'steps': [
        {'step_id': 'summary', 'title': 'Tabulate', 'operation_ids': ['statistical.explore']}],
        **extra}


def _focused(runtime):
    ref, _ = artifact(runtime.project_root, runtime.run_id, 'summary', 'statistical_exploration', {
        'schema_version': 'statistical-exploration.v1',
        'result': {'operation': 'tabulate', 'rows': [{'variable': 'group', 'value': 'a', 'count': 30}]}},
        [runtime.artifact_id])
    return _arguments(runtime, completion={'scope': 'question', 'playbooks': [], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id}},
        completion_evidence={'results': [ref]})


@pytest.mark.parametrize('user_text,missing', [
    ('Perform the full analysis, diagnostics, sensitivity and report.', 'task_scope:full_analysis_required'),
    ('Estimate the ATC.', 'target:requested_estimand_unbound'),
])
def test_continue_cannot_erase_original_request_before_first_contract(tmp_path, user_text, missing):
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': user_text})
    assert _call(runtime, _arguments(runtime, question=user_text))['saved']
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Continue.'})
    result = _call(runtime, _focused(runtime))
    assert not result['saved'] and missing in result['error']


def test_original_request_is_bound_even_when_no_plan_existed_until_continue(tmp_path):
    runtime = _Fixture(tmp_path)
    for text in ['Perform the full analysis.', 'Continue.']:
        runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': text})
    result = _call(runtime, _focused(runtime))
    assert not result['saved'] and 'task_scope:full_analysis_required' in result['error']


def test_legacy_plan_migrates_from_user_trace_and_reload_keeps_requirements(tmp_path, monkeypatch):
    from workbench.agent.plans import PlanStore
    from workbench.agent.delivery import delivery_check
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Classify the variable.'})
    assert _call(runtime, _focused(runtime))['saved']
    plan = runtime.orchestrator.plan_store.current('chain-session')
    runtime.orchestrator.plan_store.save('chain-session', replace(plan, task_requirements=None))
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Also estimate ATC.'})
    assert runtime.orchestrator._completion_check('chain-session')['status'] == 'partial'
    restored = PlanStore(runtime.repository.root).current('chain-session')
    assert restored.task_requirements['estimands'] == ['ATC']
    assert 'Also estimate' not in str(restored.task_requirements)
    # The completion reader consumes persisted typed constraints, without a session scan.
    monkeypatch.setattr(runtime.repository, 'get_branch', lambda *a, **k: pytest.fail('full-history scan'))
    check = delivery_check(runtime.project_root, restored)
    assert 'target:requested_estimand_unbound' in check['missing']
    del runtime.orchestrator._task_requirement_binder
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Continue.'})
    assert 'target:requested_estimand_unbound' in runtime.orchestrator._completion_check('chain-session')['missing']


def test_legacy_plan_without_real_user_evidence_is_unverified(tmp_path):
    runtime = _Fixture(tmp_path)
    assert _call(runtime, _focused(runtime))['saved']
    result = runtime.orchestrator._completion_check('chain-session')
    assert result['status'] == 'partial' and 'task_requirements:unverified' in result['missing']


def test_only_human_question_revision_can_replace_bound_requirements(tmp_path):
    from workbench.agent.plan_control import PlanControl
    from workbench.agent.plans import approve
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Perform the full analysis.'})
    assert _call(runtime, _arguments(runtime, question='Perform the full analysis.'))['saved']
    assert _call(runtime, _arguments(runtime))['saved']  # Agent wording changes no server requirement.
    before = runtime.orchestrator.plan_store.current('chain-session')
    assert before.task_requirements['scope'] == 'analysis'
    runtime.orchestrator.plan_store.save('chain-session', approve(before))
    new_question = 'Classify only the recorded variable.'
    changed = PlanControl(runtime.project_root, runtime.repository, 'chain-session').revise(
        before.version, {'question': new_question})['plan']
    assert changed['task_requirements']['scope'] == 'question'
    assert changed['status'] == 'needs_approval'
    assert changed['approved_version'] != changed['version']
    assert _call(runtime, {**_focused(runtime), 'question': new_question})['saved']
    assert runtime.orchestrator._completion_check('chain-session')['status'] == 'requirements_met'


@pytest.mark.parametrize('user_text,missing', [
    ('Perform the full analysis.', 'task_scope:full_analysis_required'),
    ('Estimate the ATC.', 'target:requested_estimand_unbound'),
])
def test_criteria_route_edit_with_same_question_preserves_original_requirements(tmp_path, user_text, missing):
    from fastapi.testclient import TestClient
    from workbench.app import app
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': user_text})
    assert _call(runtime, _arguments(runtime))['saved']
    before = runtime.orchestrator.plan_store.current('chain-session')
    with TestClient(app) as client:
        response = client.patch('/agent/sessions/chain-session/plan',
            params={'project_root': str(runtime.project_root)}, json={'version': before.version,
            'question': before.question, 'criteria': ['Report the recorded variable type.']})
    assert response.status_code == 200, response.text
    changed = response.json()['plan']
    assert changed['task_requirements'] == before.task_requirements
    rejected = _call(runtime, _focused(runtime))
    assert not rejected['saved'] and missing in rejected['error']


def test_model_cannot_supply_server_requirements_in_update_plan(tmp_path):
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Perform the full analysis.'})
    result = _call(runtime, _arguments(runtime, task_requirements={
        'status': 'verified', 'scope': 'question', 'estimands': []}))
    assert result is None  # Tool input-schema rejection, before the handler runs.
    assert runtime.orchestrator.plan_store.current('chain-session') is None


def test_repeated_completion_reads_only_new_session_entries(tmp_path, monkeypatch):
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Classify the variable.'})
    assert _call(runtime, _focused(runtime))['saved']
    for _ in range(30):
        runtime.repository.append('chain-session', 'message', {'role': 'assistant', 'content': 'Intermediate result.'})
    original = runtime.repository.get_entry
    reads = []
    def read(ref):
        reads.append(ref)
        return original(ref)
    monkeypatch.setattr(runtime.repository, 'get_entry', read)
    assert runtime.orchestrator._completion_check('chain-session')['status'] == 'requirements_met'
    assert len(reads) == 30
    reads.clear()
    assert runtime.orchestrator._completion_check('chain-session')['status'] == 'requirements_met'
    assert not reads


@pytest.mark.parametrize('source_hash', ['verified', 'omitted', 'incorrect'])
def test_user_can_expand_focused_task_into_a_full_analysis_needing_new_approval(tmp_path, source_hash):
    from workbench.agent.plans import approve
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Classify the variable.'})
    assert _call(runtime, _focused(runtime))['saved']
    previous = runtime.orchestrator.plan_store.current('chain-session')
    runtime.orchestrator.plan_store.save('chain-session', approve(previous))
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Now perform the full analysis.'})
    expanded = {**previous.completion, 'scope': 'analysis', 'playbooks': ['ols']}
    if source_hash != 'verified':
        expanded = {**expanded, 'source': {k: v for k, v in previous.completion['source'].items() if k != 'sha256'}}
        if source_hash == 'incorrect':
            expanded['source']['sha256'] = '0' * 64
    result = _call(runtime, _arguments(runtime, completion=expanded))
    assert result['saved'], result
    plan = runtime.orchestrator.plan_store.current('chain-session')
    assert plan.completion == {**expanded, 'source': previous.completion['source']}
    assert plan.completion_evidence is None
    assert plan.status == 'needs_approval' and plan.approved_version != plan.version
    assert plan.task_requirements['scope'] == 'analysis'
    check = runtime.orchestrator._completion_check('chain-session')
    assert check['status'] == 'partial'  # A summary is not a completed full analysis.


def test_agent_cannot_expand_contract_without_user_request_or_change_its_source(tmp_path):
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Classify the variable.'})
    assert _call(runtime, _focused(runtime))['saved']
    previous = runtime.orchestrator.plan_store.current('chain-session')
    result = _call(runtime, _arguments(runtime, completion={**previous.completion, 'scope': 'analysis',
                                                          'playbooks': ['ols']}))
    assert not result['saved']
    assert runtime.orchestrator.plan_store.current('chain-session') == previous
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Now perform the full analysis.'})
    other, _ = artifact(runtime.project_root, runtime.run_id, 'other_source', 'raw_data', {}, [])
    result = _call(runtime, _arguments(runtime, completion={**previous.completion, 'scope': 'analysis',
        'playbooks': ['ols'], 'source': other}))
    assert not result['saved']
    assert runtime.orchestrator.plan_store.current('chain-session') == previous


def test_a_target_the_person_did_not_ask_for_is_refused_and_a_requested_one_is_kept(tmp_path):
    # IV Auto, 2026-10-31: the Agent volunteered ATE on an IV question; no producer can certify it.
    runtime = _Fixture(tmp_path)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Can this sentence be written?'})
    source = {'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id}
    target = {'estimand': 'ATE', 'outcome': 'y', 'treatment': 'x'}
    result = _call(runtime, _arguments(runtime, completion={'scope': 'question', 'playbooks': [], 'source': source,
                                                            'target': target}))
    assert not result['saved'] and 'was not requested' in result['error']
    runtime = _Fixture(tmp_path / 'requested')
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Estimate the ATE.'})
    source = {'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id}
    assert _call(runtime, _arguments(runtime, completion={'scope': 'question', 'playbooks': [], 'source': source,
                                                          'target': target}))['saved']
