"""Recorded recovery gap: another same-run diagnostic hid the IV companion."""
import asyncio
from copy import deepcopy
import hashlib

import pytest

from tests.test_agent_iv_plan_criteria import _confirm, _iv_frame
from workbench.agent import plans
from workbench.agent.completion import _Products, derive_evidence, evaluate
from workbench.agent.delivery import delivery_lines


@pytest.fixture(scope='module')
def recovery_products(tmp_path_factory):
    from tests import test_read_only_analysis as sample
    from tests.test_data_column_cast import _register_source_node_identity
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sample, '_frame', _iv_frame)
        runtime = sample._Fixture(tmp_path_factory.mktemp('iv-ar-recovery'))
    _register_source_node_identity(runtime.project_root, runtime.run_id)
    record = _confirm(runtime, runtime.propose([{'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
        'model_family': 'iv_2sls', 'covariance': 'robust', 'iv_endog': ['d'], 'iv_instruments': ['z'],
        'branches': [{'branch_id': 'main', 'outcome': 'y', 'predictors': ['w']}]}}]))
    [branch] = record.outputs['workflow_state']['steps']['fit']['model_branches']
    ref = {'run_id': branch['run_id'], 'artifact_id': branch['model_id']}
    correlation = {**ref, 'artifact_id': 'statistical_tests_correlations'}
    assert _Products(runtime.project_root).load(correlation) is not None
    source = {'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id,
        'sha256': hashlib.sha256((runtime.project_root/'runs'/runtime.run_id/'data.csv').read_bytes()).hexdigest()}
    evidence = {'models': [ref], 'diagnostics': [correlation]}
    plan = plans.merge(None, question='Review the fixed IV analysis', criteria=(),
        steps=(plans.PlanStep('fit', 'IV', ('model.genesis',), expected_outputs=('Fitted model', 'AR inversion')),
               plans.PlanStep('report', 'Report', ('report.compose',), expected_outputs=('Source-bound report',))),
        budget=None, allowed_classes=None, completion={'scope':'analysis','playbooks':['iv'],'source':source},
        completion_evidence=evidence)
    runtime.orchestrator.plan_store.save('chain-session', plan)
    return runtime, plan, ref, correlation, record


def test_same_run_correlation_does_not_suppress_the_required_native_companion(recovery_products):
    runtime, plan, ref, correlation, _ = recovery_products
    before = deepcopy(plan.completion_evidence)
    evidence, _ = derive_evidence(runtime.project_root, plan.completion, plan.completion_evidence)
    assert correlation in evidence['diagnostics']
    assert {**ref, 'artifact_id': ref['artifact_id'] + '.completion'} in evidence['diagnostics']
    assert plan.completion_evidence == before


def test_default_delivery_options_keep_the_existing_AR_repair_without_a_catalog(recovery_products):
    runtime, plan, ref, *_ = recovery_products
    companion = {**ref, 'artifact_id': ref['artifact_id'] + '.completion'}
    checked = evaluate(runtime.project_root, plan.completion, {'models':[ref], 'diagnostics':[companion]}, options=True)
    repairs = [r for r in checked.get('repair_steps', []) if r.get('reason') == 'ar_not_requested']
    assert len(repairs) == 1
    assert repairs[0]['operation'] == {'operation_id':'iv.ar_confidence',
        'spec': {'model_run_id':ref['run_id'], 'model_ref':ref['artifact_id']}}
    assert checked['status'] == 'partial'
    assert 'iv:diagnostics:computed_and_model_bound' in checked['missing']
    assert 'iv:sensitivity:distinct_point_estimation' in checked['missing']
    assert 'evidence_catalog' not in checked


def test_real_inspection_and_operation_digest_keep_AR_action_alongside_unbound_criteria(recovery_products):
    from workbench.agent.operation_outcome import outcome_extras
    runtime, plan, ref, _, record = recovery_products
    before = record.to_dict()
    registry = runtime.orchestrator.tool_registry('chain-a')
    result = asyncio.run(registry.execute({'tool_call_id':'inspect-recovery', 'tool_id':'inspect_analysis_completion',
        'arguments':{}}, session_id='chain-session'))
    assert result.ok, result.error
    inspection = result.output
    digest = outcome_extras(runtime.project_root, 'chain-session', record)['delivery']
    for check in (inspection, digest):
        repairs = [r for r in check.get('repair_steps', []) if r.get('reason') == 'ar_not_requested']
        assert len(repairs) == 1
        assert repairs[0]['operation']['spec'] == {'model_run_id':ref['run_id'], 'model_ref':ref['artifact_id']}
        assert check['status'] == 'partial'
        assert check['criteria_verification']['status'] == 'not_machine_checked'
        assert len(check['criteria_verification']['unbound_slots']) == 3
        assert 'iv.ar_confidence' in check['next_step']
    assert 'ar_not_requested' in '\n'.join(delivery_lines(digest))
    assert runtime.orchestrator.operation_store.get(record.record_id).to_dict() == before
