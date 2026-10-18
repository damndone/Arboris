"""Public plan approval fixes exact criteria before granting plan authority."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tests.test_agent_continue_route import _session
from tests.test_agent_routes import _config
from workbench import analysis_ledger
from workbench.agent import plans
from workbench.agent.session import JsonlSessionRepository
from workbench.app import app


def _fixture(tmp_path, monkeypatch):
    from workbench.http import agent_routes
    root = tmp_path / 'project'
    root.mkdir()
    monkeypatch.setattr(agent_routes, 'load_llm_config', _config)
    client = TestClient(app, base_url='http://127.0.0.1', raise_server_exceptions=False)
    session = _session(client, root)
    store = plans.PlanStore(root / 'workbench')
    draft = plans.merge(None, question='Does x predict y?', criteria=['Report estimate and uncertainty'],
                        steps=(plans.PlanStep('fit', 'Fit', ('model.genesis',)),),
                        budget={'steps': 2}, allowed_classes=None)
    store.save(session, draft)
    def no_provider(*args, **kwargs):
        raise AssertionError('Approval never initializes or calls a provider')
    monkeypatch.setattr(agent_routes, 'load_llm_config', no_provider)
    monkeypatch.setattr(agent_routes, 'OpenAICompatibleModelAdapter', no_provider)
    def approve(version=draft.version):
        return client.post(f'/agent/sessions/{session}/plan/approve',
                           params={'project_root': str(root)}, json={'version': version})
    return root, session, store, draft, approve


def test_approval_records_exact_criteria_once_and_stale_version_records_nothing(tmp_path, monkeypatch):
    root, session, store, draft, approve = _fixture(tmp_path, monkeypatch)
    assert approve(99).status_code == 409
    assert analysis_ledger.read(root) == []
    response = approve()
    assert response.status_code == 200, response.text
    [event] = analysis_ledger.read(root)
    assert event['event_type'] == 'criteria_fixed'
    assert event['session_id'] == session
    assert event['plan_id'] == draft.plan_id and event['plan_version'] == draft.version
    assert event['plan_snapshot'] == draft.to_dict()
    assert event['inferential_steps'] == 0 and event['steps'] == []
    assert event['at'] <= store.current(session).approved_at
    assert approve().json() == response.json()
    assert len(analysis_ledger.read(root)) == 1
    assert len(store.history(session)) == 2
    messages = JsonlSessionRepository(root / 'workbench').get_branch(session)
    assert sum(e.payload.get('message_type') == 'agent_plan_approved' for e in messages) == 1


def test_ledger_failure_cannot_grant_plan_authority(tmp_path, monkeypatch):
    root, session, store, draft, approve = _fixture(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise OSError('test ledger write failure')
    monkeypatch.setattr(analysis_ledger, 'record_plan_event_once', fail)
    assert approve().status_code == 500
    assert store.current(session) == draft
    assert not any(e.payload.get('message_type') == 'agent_plan_approved'
                   for e in JsonlSessionRepository(root / 'workbench').get_branch(session))


def test_failed_plan_commit_retries_the_same_criteria_event(tmp_path, monkeypatch):
    root, session, store, draft, approve = _fixture(tmp_path, monkeypatch)
    original = plans.PlanStore._append
    def fail(self, session_id, plan):
        raise OSError('test before plan append')
    monkeypatch.setattr(plans.PlanStore, '_append', fail)
    assert approve().status_code == 500
    [intent] = analysis_ledger.read(root)
    assert store.current(session) == draft
    monkeypatch.setattr(plans.PlanStore, '_append', original)
    assert approve().status_code == 200
    assert analysis_ledger.read(root) == [intent]


def test_failed_session_notice_is_repaired_without_reapproving_or_duplicate_criteria(tmp_path, monkeypatch):
    root, session, store, draft, approve = _fixture(tmp_path, monkeypatch)
    original = JsonlSessionRepository.append_once
    def fail(self, session_id, entry_type, payload, **kwargs):
        if payload.get('message_type') == 'agent_plan_approved':
            raise OSError('test notice failure')
        return original(self, session_id, entry_type, payload, **kwargs)
    monkeypatch.setattr(JsonlSessionRepository, 'append_once', fail)
    assert approve().status_code == 500
    assert store.current(session).status == 'approved'
    [event] = analysis_ledger.read(root)
    monkeypatch.setattr(JsonlSessionRepository, 'append_once', original)
    assert approve().status_code == 200
    assert len(store.history(session)) == 2
    assert analysis_ledger.read(root) == [event]


def test_plan_mutations_serialize_current_version_across_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    import time
    store = plans.PlanStore(tmp_path)
    draft = plans.merge(None, question='q', criteria=[], steps=(plans.PlanStep('a', 'A', ('model.genesis',)),),
                        budget=None, allowed_classes=None)
    store.save('s', draft)
    def change(_):
        other = plans.PlanStore(tmp_path)
        def increment(previous):
            time.sleep(.01)
            return replace(previous, version=previous.version + 1)
        return other.update('s', increment).version
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions = list(pool.map(change, range(4)))
    assert sorted(versions) == [2, 3, 4, 5]
    assert [p.version for p in store.history('s')] == [1, 2, 3, 4, 5]


def test_changed_question_is_audited_before_replacing_the_plan(tmp_path):
    import asyncio
    from tests.test_read_only_analysis import _Fixture
    fixture = _Fixture(tmp_path)
    store = fixture.orchestrator.plan_store
    draft = plans.merge(None, question='old question', criteria=['criterion'],
                        steps=(plans.PlanStep('fit', 'Fit', ('model.genesis',)),),
                        budget=None, allowed_classes=None)
    store.save('chain-session', plans.approve(draft))
    result = asyncio.run(fixture.orchestrator.tool_registry('chain-a').execute({
        'tool_call_id': 'change', 'tool_id': 'update_plan', 'arguments': {
            'question': 'new question', 'criteria': ['criterion'],
            'steps': [{'step_id': 'fit', 'title': 'Fit', 'operation_ids': ['model.genesis']}]}
    }, session_id='chain-session'))
    assert result.ok and result.output['saved']
    [event] = analysis_ledger.read(fixture.project_root)
    assert event['event_type'] == 'question_change'
    assert event['plan_snapshot']['question'] == 'new question'
    assert store.current('chain-session').status == 'needs_approval'


def test_execution_completion_does_not_overwrite_a_plan_edited_during_the_operation(tmp_path):
    from tests.test_read_only_analysis import _Fixture, _recode
    from tests.test_agent_execution_modes import _with_authority_runner
    fixture = _Fixture(tmp_path)
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = 'auto'
    _with_authority_runner(fixture)
    execute = orchestrator.read_only_runner
    store = orchestrator.plan_store
    draft = plans.merge(None, question='q', criteria=['original'],
                        steps=(plans.PlanStep('recode', 'Recode', ('data.recode',)),),
                        budget=None, allowed_classes=None)
    store.save('chain-session', plans.approve(draft))
    async def edit_and_execute(proposal, actor):
        store.update('chain-session', lambda old: plans.merge(
            old, question='new q', criteria=['new criterion'], steps=old.steps,
            budget=None, allowed_classes=None))
        return await execute(proposal, actor)
    orchestrator.read_only_runner = edit_and_execute
    receipt = fixture.propose([_recode()])
    assert receipt['executed'] is True and receipt['operation']['status'] == 'completed'
    assert receipt['plan_update_conflict'] is True
    current = store.current('chain-session')
    assert current.version == 2 and current.question == 'new q'
    assert current.criteria == ('new criterion',) and current.status == 'needs_approval'
    assert current.steps[0].status == 'pending'


def test_question_change_retry_reuses_first_intent_snapshot_after_plan_write_failure(tmp_path, monkeypatch):
    import asyncio
    from tests.test_read_only_analysis import _Fixture
    fixture = _Fixture(tmp_path)
    store = fixture.orchestrator.plan_store
    draft = plans.merge(None, question='old question', criteria=['criterion'],
                        steps=(plans.PlanStep('fit', 'Fit', ('model.genesis',)),),
                        budget=None, allowed_classes=None)
    store.save('chain-session', plans.approve(draft))
    registry = fixture.orchestrator.tool_registry('chain-a')
    call = {'tool_call_id': 'change', 'tool_id': 'update_plan', 'arguments': {
        'question': 'new question', 'criteria': ['criterion'],
        'steps': [{'step_id': 'fit', 'title': 'Fit', 'operation_ids': ['model.genesis']}]}}
    original = plans.PlanStore._append
    def fail(self, session_id, plan):
        raise OSError('test question plan append failure')
    monkeypatch.setattr(plans.PlanStore, '_append', fail)
    assert not asyncio.run(registry.execute(call, session_id='chain-session')).ok
    [intent] = analysis_ledger.read(fixture.project_root)
    monkeypatch.setattr(plans.PlanStore, '_append', original)
    # A later wall time must not create a different intent for the same change.
    monkeypatch.setattr(plans, '_now', lambda: '2099-01-01T00:00:00.000+00:00')
    retry = asyncio.run(registry.execute(call, session_id='chain-session'))
    assert retry.ok and retry.output['saved'], retry
    assert analysis_ledger.read(fixture.project_root) == [intent]
    assert store.current('chain-session').to_dict() == intent['plan_snapshot']


def _process_increment_plan(workbench_root):
    from dataclasses import replace
    store = plans.PlanStore(Path(workbench_root))
    def increment(previous):
        import time
        time.sleep(.02)
        return replace(previous, version=previous.version + 1)
    return store.update('s', increment).version


def test_plan_mutations_serialize_across_spawned_processes(tmp_path):
    import multiprocessing
    store = plans.PlanStore(tmp_path)
    draft = plans.merge(None, question='q', criteria=[], steps=(plans.PlanStep('a', 'A', ('model.genesis',)),),
                        budget=None, allowed_classes=None)
    store.save('s', draft)
    with multiprocessing.get_context('spawn').Pool(2) as pool:
        versions = pool.map(_process_increment_plan, [str(tmp_path)] * 4)
    assert sorted(versions) == [2, 3, 4, 5]
    assert [p.version for p in store.history('s')] == [1, 2, 3, 4, 5]


def test_legacy_approval_does_not_invent_a_criteria_event(tmp_path, monkeypatch):
    root, session, store, draft, approve = _fixture(tmp_path, monkeypatch)
    store.save(session, plans.approve(draft))
    assert approve().status_code == 409
    assert analysis_ledger.read(root) == []


def test_research_intent_conflict_is_explicit_not_overwritten(tmp_path):
    draft = plans.merge(None, question='q', criteria=['first'],
                        steps=(plans.PlanStep('a', 'A', ('model.genesis',)),),
                        budget=None, allowed_classes=None)
    event = analysis_ledger.record_plan_event_once(tmp_path, session_id='s', event_type='criteria_fixed',
                                                  plan_snapshot=draft.to_dict())
    other = {**draft.to_dict(), 'criteria': ['changed']}
    with pytest.raises(ValueError, match='conflicts'):
        analysis_ledger.record_plan_event_once(tmp_path, session_id='s', event_type='criteria_fixed', plan_snapshot=other)
    assert analysis_ledger.read(tmp_path) == [event]
