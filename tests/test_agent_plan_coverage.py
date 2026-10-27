"""Only successful operation receipts complete declared plan work."""
import asyncio
from dataclasses import replace

import pytest

from workbench.agent import plans


def _steps():
    return (plans.PlanStep('prepare', 'Recode and test', ('data.recode', 'test.t_tests')),
            plans.PlanStep('next', 'Derive after both operations', ('statistical.derive_numeric',), depends_on=('prepare',)))


def _plan():
    return plans.approve(plans.merge(None, question='Recode and test before deriving.', criteria=[],
        steps=_steps(), budget={'steps': 8}, allowed_classes=None))


@pytest.mark.parametrize('mark', [plans.mark_executed, plans.mark_covered])
def test_receipts_accumulate_until_the_whole_step_is_covered(tmp_path, mark):
    plan = _plan()
    assert plans.scope_for(plan, ['data.recode'])['in_plan']
    partial = mark(plan, ['data.recode'], 'completed')
    assert partial.steps[0].status != 'done'
    assert partial.steps[0].completed_operation_ids == ('data.recode',)
    assert not plans.scope_for(partial, ['statistical.derive_numeric'])['in_plan']
    store = plans.PlanStore(tmp_path)
    store.save('s', partial)
    loaded = plans.PlanStore(tmp_path).current('s')
    assert loaded == partial
    revision = plans.merge(loaded, question=loaded.question, criteria=[], steps=_steps(), budget=None, allowed_classes=None)
    assert revision.steps[0].completed_operation_ids == ('data.recode',)
    repeated = mark(revision, ['data.recode'], 'completed')
    assert repeated.steps[0].completed_operation_ids == ('data.recode',)
    complete = mark(repeated, ['test.t_tests'], 'completed')
    assert complete.steps[0].status == 'done'
    assert set(complete.steps[0].completed_operation_ids) == {'data.recode', 'test.t_tests'}
    assert plans.scope_for(complete, ['statistical.derive_numeric'])['in_plan']


def test_failed_receipt_stays_failed_and_does_not_certify_missing_work():
    partial = plans.mark_executed(_plan(), ['data.recode'], 'completed')
    failed = plans.mark_executed(partial, ['test.t_tests'], 'failed')
    assert failed.steps[0].status == 'failed'
    assert failed.steps[0].completed_operation_ids == ('data.recode',)
    assert plans.mark_executed(failed, ['test.t_tests'], 'completed').steps == failed.steps
    assert not plans.scope_for(failed, ['statistical.derive_numeric'])['in_plan']


def _runtime(tmp_path):
    from tests.test_read_only_analysis import _Fixture
    from tests.test_agent_execution_modes import _with_authority_runner
    runtime = _Fixture(tmp_path)
    runtime.orchestrator.execution_mode = 'auto'
    _with_authority_runner(runtime)
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Recode and test before deriving.'})
    return runtime


def _update(runtime, *, status='pending', coverage=None, first_operations=None):
    steps = [{'step_id': s.step_id, 'title': s.title, 'operation_ids': list(s.operation_ids),
              'depends_on': list(s.depends_on), 'status': status if i == 0 else 'pending'}
             for i, s in enumerate(_steps())]
    if coverage is not None:
        steps[0]['completed_operation_ids'] = coverage
    if first_operations is not None:
        steps[0]['operation_ids'] = first_operations
    return asyncio.run(runtime.orchestrator.tool_registry('chain-a').execute({
        'tool_call_id': 'plan', 'tool_id': 'update_plan', 'arguments': {
            'question': 'Recode and test before deriving.', 'steps': steps,
            'allowed_classes': ['analyze', 'derive']}}, session_id='chain-session'))


def test_actual_partial_remaining_and_downstream_operations_keep_auto_authority_after_reload(tmp_path):
    from tests.test_read_only_analysis import _recode, _t_test
    from workbench.agent.plan_control import PlanControl
    runtime = _runtime(tmp_path)
    assert _update(runtime).output['saved']
    store = runtime.orchestrator.plan_store
    PlanControl(runtime.project_root, runtime.repository, 'chain-session').approve(store.current('chain-session').version)
    first = runtime.propose([_recode()])
    assert first['executed'] and first['authorized_by'] == 'approved_plan'
    partial = plans.PlanStore(runtime.repository.root).current('chain-session')
    assert partial.steps[0].status != 'done'
    assert partial.steps[0].completed_operation_ids == ('data.recode',)
    assert not plans.scope_for(partial, ['statistical.derive_numeric'])['in_plan']
    assert _update(runtime).output['saved']
    assert store.current('chain-session').steps[0].completed_operation_ids == ('data.recode',)
    remaining = runtime.propose([_t_test('test')])
    assert remaining['executed'] and remaining['operation']['status'] == 'completed'
    ready = store.current('chain-session')
    assert ready.steps[0].status == 'done'
    assert plans.scope_for(ready, ['statistical.derive_numeric'])['in_plan']
    downstream = runtime.propose([{'step_id': 'log', 'operation_id': 'statistical.derive_numeric',
        'spec': {'recipes': [{'operator': 'natural_log', 'input_columns': ['wage'], 'output_name': 'log_wage'}]}}])
    assert downstream['executed'] and downstream['authorized_by'] == 'approved_plan'
    assert store.current('chain-session').status == 'completed'


def test_model_cannot_submit_coverage_or_promote_a_partial_step_to_done(tmp_path):
    from tests.test_read_only_analysis import _recode
    from workbench.agent.plan_control import PlanControl
    runtime = _runtime(tmp_path)
    forged = _update(runtime, coverage=['data.recode', 'test.t_tests'])
    assert not forged.ok
    assert runtime.orchestrator.plan_store.current('chain-session') is None
    assert _update(runtime).output['saved']
    plan = runtime.orchestrator.plan_store.current('chain-session')
    PlanControl(runtime.project_root, runtime.repository, 'chain-session').approve(plan.version)
    assert runtime.propose([_recode()])['executed']
    fake_done = _update(runtime, status='done')
    assert fake_done.ok and not fake_done.output['saved']
    saved = runtime.orchestrator.plan_store.current('chain-session')
    assert saved.steps[0].status != 'done'
    assert not plans.scope_for(saved, ['statistical.derive_numeric'])['in_plan']


def test_legacy_done_without_receipt_coverage_is_preserved_but_does_not_release_dependencies():
    legacy = replace(_plan(), steps=(replace(_steps()[0], status='done'), _steps()[1]))
    original = legacy.to_dict()
    original['steps'][0].pop('completed_operation_ids', None)
    loaded = plans.Plan.from_dict(original)
    assert loaded.steps[0].status == 'done'
    scope = plans.scope_for(loaded, ['statistical.derive_numeric'])
    assert not scope['in_plan']
    assert scope['plan_recovery']['code'] == 'PLAN_EXECUTION_COVERAGE_UNVERIFIED'
    assert scope['plan_recovery']['steps'][0]['missing_operation_ids'] == ['data.recode', 'test.t_tests']
    revised = plans.merge(loaded, question=loaded.question, criteria=[], steps=_steps(), budget=None, allowed_classes=None)
    assert revised.steps[0].status == 'done'  # No automatic reopening/rerun of old work.


def test_explanatory_steps_without_declared_computations_can_still_be_done():
    plan = plans.approve(plans.merge(None, question='q', criteria=[], budget=None, allowed_classes=None,
        steps=(plans.PlanStep('note', 'Read the instructions', (), status='done'),
               plans.PlanStep('run', 'Recode', ('data.recode',), depends_on=('note',)))))
    assert plans.scope_for(plan, ['data.recode'])['in_plan']


def test_legacy_coverage_gap_is_returned_on_the_actual_confirmation_path_without_rerun(tmp_path):
    runtime = _runtime(tmp_path)
    legacy = replace(_plan(), steps=(replace(_steps()[0], status='done'), _steps()[1]))
    runtime.orchestrator.plan_store.save('chain-session', legacy)
    before = legacy.to_dict()
    response = runtime.propose([{'step_id': 'log', 'operation_id': 'statistical.derive_numeric',
        'spec': {'recipes': [{'operator': 'natural_log', 'input_columns': ['wage'], 'output_name': 'log_wage'}]}}])
    assert response['requires_confirmation']
    assert response['plan_recovery']['code'] == 'PLAN_EXECUTION_COVERAGE_UNVERIFIED'
    assert 'original bound operation receipts' in response['plan_recovery']['guidance']
    assert runtime.orchestrator.operation_store.list_records() == []
    assert runtime.orchestrator.plan_store.current('chain-session').to_dict() == before
    narrowed = _update(runtime, status='done', first_operations=[])
    assert narrowed.ok and not narrowed.output['saved']


@pytest.mark.parametrize('remaining_declaration', [['data.recode'], []])
def test_model_cannot_remove_unexecuted_work_from_a_partially_covered_step(tmp_path, remaining_declaration):
    from tests.test_read_only_analysis import _recode
    from workbench.agent.plan_control import PlanControl
    runtime = _runtime(tmp_path)
    assert _update(runtime).output['saved']
    current = runtime.orchestrator.plan_store.current('chain-session')
    PlanControl(runtime.project_root, runtime.repository, 'chain-session').approve(current.version)
    assert runtime.propose([_recode()])['executed']
    rejected = _update(runtime, status='done', first_operations=remaining_declaration)
    assert rejected.ok and not rejected.output['saved']
    saved = runtime.orchestrator.plan_store.current('chain-session')
    assert saved.steps[0].operation_ids == ('data.recode', 'test.t_tests')
    assert saved.steps[0].completed_operation_ids == ('data.recode',)
    assert not plans.scope_for(saved, ['statistical.derive_numeric'])['in_plan']


def test_human_can_revise_partial_work_but_must_approve_again_without_rerunning_it(tmp_path):
    from tests.test_read_only_analysis import _recode
    from workbench.agent.plan_control import PlanControl
    runtime = _runtime(tmp_path)
    assert _update(runtime).output['saved']
    control = PlanControl(runtime.project_root, runtime.repository, 'chain-session')
    control.approve(runtime.orchestrator.plan_store.current('chain-session').version)
    assert runtime.propose([_recode()])['executed']
    before = runtime.orchestrator.plan_store.current('chain-session')
    records = runtime.orchestrator.operation_store.list_records()
    changed = control.revise(before.version, {'steps': [
        {'step_id': 'prepare', 'title': 'Only the completed recode is needed', 'operation_ids': ['data.recode']},
        {'step_id': 'next', 'title': 'Derive after recode', 'operation_ids': ['statistical.derive_numeric'], 'depends_on': ['prepare']},
    ]})['plan']
    assert changed['status'] == 'needs_approval'
    assert changed['steps'][0]['completed_operation_ids'] == ['data.recode']
    pending = runtime.orchestrator.plan_store.current('chain-session')
    assert not plans.scope_for(pending, ['statistical.derive_numeric'])['in_plan']
    control.approve(changed['version'])
    approved = runtime.orchestrator.plan_store.current('chain-session')
    assert plans.scope_for(approved, ['statistical.derive_numeric'])['in_plan']
    assert runtime.orchestrator.operation_store.list_records() == records


def test_model_cannot_drop_a_partly_executed_step_or_supply_the_human_revision_flag(tmp_path):
    from tests.test_read_only_analysis import _recode
    from workbench.agent.plan_control import PlanControl
    runtime = _runtime(tmp_path)
    assert _update(runtime).output['saved']
    control = PlanControl(runtime.project_root, runtime.repository, 'chain-session')
    control.approve(runtime.orchestrator.plan_store.current('chain-session').version)
    assert runtime.propose([_recode()])['executed']
    registry = runtime.orchestrator.tool_registry('chain-a')
    arguments = {'steps': [{'step_id': 'next', 'title': 'Skip the rest',
                           'operation_ids': ['statistical.derive_numeric']}]}
    def call(args):
        return asyncio.run(registry.execute({'tool_call_id': 'drop', 'tool_id': 'update_plan',
            'arguments': args}, session_id='chain-session'))
    forged = call({**arguments, 'human_revision': True})
    assert not forged.ok
    dropped = call(arguments)
    assert dropped.ok and not dropped.output['saved']
    saved = runtime.orchestrator.plan_store.current('chain-session')
    assert saved.steps[0].completed_operation_ids == ('data.recode',)
    assert saved.steps[0].operation_ids == ('data.recode', 'test.t_tests')


def test_changing_an_existing_dependency_needs_reapproval_but_progress_keeps_auto_authority(tmp_path):
    from tests.test_read_only_analysis import _recode
    from workbench.agent.plan_control import PlanControl
    runtime = _runtime(tmp_path)
    assert _update(runtime).output['saved']
    store = runtime.orchestrator.plan_store
    control = PlanControl(runtime.project_root, runtime.repository, 'chain-session')
    control.approve(store.current('chain-session').version)
    assert runtime.propose([_recode()])['executed']
    progress = _update(runtime, status='running')
    assert progress.output['saved'] and progress.output['plan']['status'] == 'approved'
    assert 'approval_reopened' not in progress.output
    partial = store.current('chain-session')
    assert partial.steps[0].completed_operation_ids == ('data.recode',)
    assert not plans.scope_for(partial, ['statistical.derive_numeric'])['in_plan']
    arguments = {'steps': [
        {'step_id': 'prepare', 'title': 'Recode and test', 'operation_ids': ['data.recode', 'test.t_tests'], 'status': 'running'},
        {'step_id': 'next', 'title': 'Derive now', 'operation_ids': ['statistical.derive_numeric'], 'depends_on': []},
    ], 'allowed_classes': ['analyze', 'derive']}
    rewired = asyncio.run(runtime.orchestrator.tool_registry('chain-a').execute({
        'tool_call_id': 'rewire', 'tool_id': 'update_plan', 'arguments': arguments}, session_id='chain-session'))
    assert rewired.ok and rewired.output['saved']
    assert rewired.output['plan']['status'] == 'needs_approval'
    assert 'approval_reopened' in rewired.output
    changed = store.current('chain-session')
    assert changed.steps[0].operation_ids == partial.steps[0].operation_ids
    assert changed.steps[0].completed_operation_ids == ('data.recode',)
    assert not plans.scope_for(changed, ['statistical.derive_numeric'])['in_plan']
    records = runtime.orchestrator.operation_store.list_records()
    control.approve(changed.version)
    assert runtime.orchestrator.operation_store.list_records() == records
    approved = store.current('chain-session')
    assert plans.scope_for(approved, ['statistical.derive_numeric'])['in_plan']
    result = runtime.propose([{'step_id': 'log', 'operation_id': 'statistical.derive_numeric',
        'spec': {'recipes': [{'operator': 'natural_log', 'input_columns': ['wage'], 'output_name': 'log_wage'}]}}])
    assert result['executed'] and result['authorized_by'] == 'approved_plan'
