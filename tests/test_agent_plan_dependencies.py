"""Plan authority and completion share one dependency-ready step selection."""

from dataclasses import replace

import pytest

from workbench.agent import plans


def _approved(*steps):
    return plans.approve(plans.merge(None, question='q', criteria=[], budget={'steps': 5},
                                    allowed_classes=None, steps=steps))


@pytest.mark.parametrize('dependency_status', ['pending', 'running', 'awaiting', 'skipped', 'failed', 'unknown'])
def test_unsuccessful_dependency_blocks_authority_and_completion(dependency_status):
    plan = _approved(
        plans.PlanStep('source', 'Source', ('model.genesis',), status=dependency_status),
        plans.PlanStep('child', 'Child', ('data.recode',), depends_on=('source',)),
    )
    assert plans.scope_for(plan, ['data.recode'])['in_plan'] is False
    assert plans.mark_executed(plan, ['data.recode'], 'completed').steps == plan.steps


def test_missing_dependency_is_not_treated_as_success_when_loading_a_plan():
    plan = _approved(plans.PlanStep('child', 'Child', ('data.recode',), depends_on=('missing',)))
    loaded = plans.Plan.from_dict(plan.to_dict())
    assert plans.scope_for(loaded, ['data.recode'])['in_plan'] is False
    assert plans.mark_executed(loaded, ['data.recode'], 'completed').steps == loaded.steps


@pytest.mark.parametrize('open_status', ['pending', 'running', 'awaiting'])
def test_all_dependencies_must_be_done_and_independent_steps_remain_selectable(open_status):
    plan = _approved(
        plans.PlanStep('a', 'A', ('model.genesis',)),
        plans.PlanStep('b', 'B', ('test.t_tests',), status='skipped'),
        plans.PlanStep('blocked', 'Blocked', ('data.recode',), depends_on=('a', 'b'), status=open_status),
        plans.PlanStep('independent', 'Independent', ('statistical.derive_numeric',), status=open_status),
    )
    plan = plans.mark_executed(plan, ['model.genesis'], 'completed')
    assert plans.scope_for(plan, ['data.recode'])['in_plan'] is False
    assert plans.scope_for(plan, ['statistical.derive_numeric'])['in_plan'] is True
    done = plans.mark_executed(plan, ['statistical.derive_numeric'], 'completed')
    assert [step.status for step in done.steps][-2:] == [open_status, 'done']
    ready = replace(plan, steps=tuple(replace(step, status='pending') if step.step_id == 'b' else step for step in plan.steps))
    ready = plans.mark_executed(ready, ['test.t_tests'], 'completed')
    assert plans.scope_for(ready, ['data.recode'])['in_plan'] is True
    assert plans.mark_executed(ready, ['data.recode'], 'completed').steps[2].status == 'done'


def test_a_request_cannot_stitch_authority_from_multiple_plan_steps():
    plan = _approved(
        plans.PlanStep('recode', 'Recode', ('data.recode',)),
        plans.PlanStep('test', 'Test', ('test.t_tests',)),
    )
    request = ['data.recode', 'test.t_tests']
    assert plans.scope_for(plan, request)['in_plan'] is False
    assert plans.mark_executed(plan, request, 'completed').steps == plan.steps
    whole_step = plans.PlanStep('workflow', 'Workflow', tuple(request))
    covered = replace(plan, steps=(*plan.steps, whole_step))
    assert plans.scope_for(covered, request)['in_plan'] is True
    assert [step.status for step in plans.mark_executed(covered, request, 'completed').steps] == ['pending', 'pending', 'done']


@pytest.mark.parametrize('result_status, expected', [('completed', 'done'), ('failed', 'failed')])
def test_selection_skips_blocked_duplicates_and_preserves_ready_plan_order(result_status, expected):
    plan = _approved(
        plans.PlanStep('source', 'Source', ('model.genesis',)),
        plans.PlanStep('blocked', 'Blocked', ('data.recode',), depends_on=('source',)),
        plans.PlanStep('first-ready', 'First ready', ('data.recode',)),
        plans.PlanStep('next-ready', 'Next ready', ('data.recode',)),
    )
    assert plans.scope_for(plan, ['data.recode'])['in_plan'] is True
    updated = plans.mark_executed(plan, ['data.recode'], result_status)
    assert [step.status for step in updated.steps] == ['pending', 'pending', expected, 'pending']


@pytest.mark.parametrize('terminal', ['done', 'skipped', 'failed'])
def test_closed_steps_and_empty_requests_cannot_supply_plan_authority(terminal):
    plan = _approved(plans.PlanStep('closed', 'Closed', ('data.recode',), status='pending' if terminal == 'done' else terminal))
    if terminal == 'done':
        plan = plans.mark_executed(plan, ['data.recode'], 'completed')
    assert plans.scope_for(plan, ['data.recode'])['in_plan'] is False
    assert plans.scope_for(plan, [])['in_plan'] is False
    assert plans.mark_executed(plan, [], 'completed').steps == plan.steps


def test_auto_orchestrator_requires_dependency_success_before_using_plan_authority(tmp_path):
    from tests.test_agent_execution_modes import _with_authority_runner
    from tests.test_read_only_analysis import _Fixture, _recode, _explore

    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    fixture.orchestrator.execution_mode = 'auto'
    store = fixture.orchestrator.plan_store
    plan = _approved(
        plans.PlanStep('inspect', 'Inspect', ('statistical.explore',)),
        plans.PlanStep('recode', 'Recode', ('data.recode',), depends_on=('inspect',)),
    )
    store.save('chain-session', plan)
    blocked = fixture.propose([_recode()])
    assert blocked.get('requires_confirmation') is True, blocked
    assert seen == []
    assert fixture.orchestrator.operation_store.list_records() == []
    assert store.current('chain-session').steps == plan.steps

    inspection = fixture.propose([_explore('inspect', 'region')])
    assert inspection['executed'] and inspection['operation']['status'] == 'completed'
    result = fixture.propose([_recode()])
    assert result['executed'] is True and result['authorized_by'] == 'approved_plan'
    assert seen == ['read_only_policy', 'approved_plan']
    assert [step.status for step in store.current('chain-session').steps] == ['done', 'done']
    assert store.current('chain-session').status == 'completed'
