"""Approved deliverables reuse producer evidence without creating execution receipts."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
import numpy as np
import pandas as pd

from tests.test_agent_completion import fixture as completion_fixture
from workbench.agent import plans
from workbench.agent.delivery import delivery_check
from workbench.agent.plan_control import PlanControl
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.task_requirements import RequirementBinder


def approved_plan(root, contract, evidence, *, criteria=None, outputs=None, approve=True):
    repository = JsonlSessionRepository(root / 'workbench')
    session_id = 'plan_' + uuid4().hex[:10]
    repository.create_session(session_id, chain_id='chain', role='chain')
    repository.append(session_id, 'message', {'role': 'user', 'content': 'Please complete the full analysis.'})
    plan = plans.merge(None, question='Complete the analysis', criteria=criteria or ['Estimate the fixed specification'],
        steps=(plans.PlanStep('fit', 'Fit', ('model.genesis',), expected_outputs=tuple(outputs or ['Registered model'])),),
        budget=None, allowed_classes=None, completion=contract, completion_evidence=evidence)
    plan = replace(plan, task_requirements=RequirementBinder(repository).bind(session_id, None))
    store = plans.PlanStore(repository.root)
    store.save(session_id, plan)
    if approve:
        PlanControl(root, repository, session_id).approve(plan.version)
    return store.current(session_id), repository


def requirement(operation=None):
    return {'id': 'fit', 'covers': [{'criterion_index': 0}, {'step_id': 'fit', 'output_index': 0}],
        'operation': operation or {'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
            'model_family': 'ols', 'covariance': 'unadjusted',
            'branches': [{'branch_id': 'main', 'outcome': 'y', 'predictors': ['x']}]}},
        'allow_not_applicable': False}


def test_legacy_approved_text_cannot_become_complete_from_a_playbook_pass(tmp_path):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    checked = delivery_check(tmp_path, plan)
    assert checked['status'] == 'partial'
    assert checked['playbook_status'] == 'requirements_met'
    assert checked['criteria_verification']['unbound_slots'] == [
        {'criterion_index': 0}, {'step_id': 'fit', 'output_index': 0}]
    assert plan.steps[0].completed_operation_ids == ()


@pytest.mark.parametrize('approved', [False, True])
def test_unbound_slots_can_gain_machine_definitions_but_need_explicit_approval(tmp_path, approved):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    if not approved:
        plan = replace(plan, status='draft', approved_version=None, approved_at=None)
    revised = plans.merge(plan, question=plan.question, criteria=list(plan.criteria), steps=plan.steps,
        budget=None, allowed_classes=None, completion={**contract, 'requirements': [requirement()]})
    assert revised.status == ('needs_approval' if approved else 'draft')
    assert revised.completion['source'] == contract['source']
    assert plan.completion == contract


def test_changed_expected_output_is_a_new_approved_obligation(tmp_path):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    changed = replace(plan.steps[0], expected_outputs=('A different registered deliverable',))
    revised = plans.merge(plan, question=plan.question, criteria=list(plan.criteria), steps=(changed,),
                          budget=None, allowed_classes=None)
    assert revised.status == 'needs_approval'


def test_evidence_updates_do_not_reopen_approval(tmp_path):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    revised = plans.merge(plan, question=plan.question, criteria=list(plan.criteria), steps=plan.steps,
        budget=None, allowed_classes=None, completion_evidence={**deepcopy(evidence), 'requirements': []})
    assert revised.status == 'approved' and revised.approved_version == plan.approved_version
    assert revised.steps == plan.steps


def test_invalid_scientific_definition_is_a_plan_input_error(tmp_path):
    contract, evidence = completion_fixture(tmp_path)
    invalid = requirement()
    invalid['operation']['spec']['covariance'] = 'invented_covariance'
    with pytest.raises(plans.PlanError, match='covariance'):
        approved_plan(tmp_path, {**contract, 'requirements': [invalid]}, evidence)


def test_execution_progress_and_empty_exploration_do_not_change_deliverable_basis(tmp_path):
    from workbench.agent.plan_criteria import basis
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    progressed = replace(plan.steps[0], status='done', completed_operation_ids=('model.genesis',))
    revised = replace(plan, steps=(progressed, plans.PlanStep('extra', 'Explore', ('statistical.explore',))))
    assert basis(revised) == basis(plan)


@pytest.mark.parametrize('change', ['requirements', 'criteria', 'outputs', 'evidence', 'progress'])
def test_completed_plan_reopens_only_for_changed_obligations(tmp_path, change):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    completed = replace(plan, status='completed')
    arguments = {'question': plan.question, 'criteria': list(plan.criteria), 'steps': plan.steps,
                 'budget': None, 'allowed_classes': None}
    if change == 'requirements':
        arguments['completion'] = {**contract, 'requirements': [requirement()]}
    elif change == 'criteria':
        arguments['criteria'] = ['A changed obligation']
    elif change == 'outputs':
        arguments['steps'] = (replace(plan.steps[0], expected_outputs=('A changed output',)),)
    elif change == 'evidence':
        arguments['completion_evidence'] = {**evidence, 'requirements': []}
    else:
        arguments['steps'] = (replace(plan.steps[0], status='running'),)
    revised = plans.merge(completed, **arguments)
    widened = change in {'requirements', 'criteria', 'outputs'}
    assert revised.status == ('needs_approval' if widened else 'completed')
    if widened:
        assert plans.approve(revised).approved_version == revised.version


@pytest.fixture(scope='module')
def actual_panel(tmp_path_factory):
    from tests import test_read_only_analysis as sample
    root = tmp_path_factory.mktemp('criteria-panel')
    rng = np.random.default_rng(416)
    groups = np.repeat(np.arange(32), 4)
    times = np.tile(np.arange(4), 32)
    x = rng.normal(size=len(groups))
    frame = pd.DataFrame({'region': groups, 'group': times, 'x': x,
                          'wage': groups / 7 + times / 4 + x + rng.normal(size=len(groups))})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sample, '_frame', lambda: frame)
        runtime = sample._Fixture(root)
    op = {'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
        'model_family': 'panel_ols', 'entity_col': 'region', 'time_col': 'group', 'covariance': 'clustered',
        'branches': [{'branch_id': 'main', 'outcome': 'wage', 'predictors': ['x']}]}}
    alternate = deepcopy(op)
    alternate['step_id'] = 'alternate'
    alternate['spec'].pop('time_col')
    steps = [op, alternate, {'step_id': 'report', 'operation_id': 'report.compose',
                            'depends_on': ['fit', 'alternate'], 'spec': {'sections': ['models']}}]
    pending = runtime.propose(steps)
    assert pending['requires_confirmation']
    proposal = runtime.orchestrator.proposal_store.latest_revision(pending['proposal']['proposal_id'])
    record = runtime.orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type='user', current_context_fingerprint=sample.FINGERPRINT,
        current_active_head_run_id=runtime.run_id)
    completed = asyncio.run(runtime.orchestrator.execute_confirmed_operation(record.record_id,
        project_root=runtime.project_root, current_context_fingerprint=sample.FINGERPRINT,
        current_active_head_run_id=runtime.run_id))
    assert completed.status == 'completed', completed.error
    # Select the actual registered model with its producer-owned workflow context.
    model_states = completed.outputs['workflow_state']['steps']
    models = [{'run_id': model_states[key]['model_branches'][0]['run_id'], 'artifact_id': 'panel_ols_1'}
              for key in ['fit', 'alternate']]
    assert len(models) == 2
    source = runtime.project_root / 'runs' / runtime.run_id / 'data.csv'
    return runtime, op, completed, models, hashlib.sha256(source.read_bytes()).hexdigest()


def test_real_panel_products_can_be_verified_without_rerunning_or_marking_steps_done(actual_panel):
    runtime, op, record, models, digest = actual_panel
    contract = {'scope': 'analysis', 'playbooks': ['panel'], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id, 'sha256': digest},
        'requirements': [requirement(op)]}
    evidence = {'models': [models[0]], 'sensitivity': [models[1]], 'requirements': [{
        'requirement_id': 'fit', 'operation_record_id': record.record_id, 'workflow_step_id': 'fit',
        'artifacts': models[:1]}]}
    plan, _ = approved_plan(runtime.project_root, contract, evidence)
    before = json.dumps(record.to_dict(), sort_keys=True)
    checked = delivery_check(runtime.project_root, plan)
    assert checked['criteria_verification']['status'] == 'requirements_met'
    assert checked['status'] == 'requirements_met', checked['missing']
    assert checked['criteria_verification']['requirements'][0]['verified_artifacts']
    assert plan.steps[0].completed_operation_ids == ()
    assert json.dumps(runtime.orchestrator.operation_store.get(record.record_id).to_dict(), sort_keys=True) == before


def panel_plan(actual_panel, *, approve=True, change=None):
    runtime, op, record, models, digest = actual_panel
    contract = {'scope': 'analysis', 'playbooks': ['panel'], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id, 'sha256': digest},
        'requirements': [requirement(deepcopy(op))]}
    evidence = {'models': [models[0]], 'sensitivity': [models[1]], 'requirements': [{
        'requirement_id': 'fit', 'operation_record_id': record.record_id, 'workflow_step_id': 'fit',
        'artifacts': models[:1]}]}
    if change:
        change(contract, evidence)
    return approved_plan(runtime.project_root, contract, evidence, approve=approve)[0]


def test_ask_reuses_exact_human_confirmed_results_without_separate_plan_approval(actual_panel):
    runtime, *_ = actual_panel
    plan = panel_plan(actual_panel, approve=False)
    assert plan.approved_version is None
    checked = delivery_check(runtime.project_root, plan)
    assert checked['status'] == 'requirements_met', checked['criteria_verification']


@pytest.mark.parametrize('missing_record', [False, True])
def test_one_verification_reads_a_shared_record_once_and_rechecks_next_time(actual_panel, monkeypatch, missing_record):
    from workbench.agent import operation_records, proposals
    runtime, _, record, models, digest = actual_panel
    ops = [s for s in record.changes['steps'] if s['step_id'] in {'fit', 'alternate'}]
    definitions = [{**requirement({k: op[k] for k in ['step_id', 'operation_id', 'spec']}), 'id': op['step_id']}
                   for op in ops]
    contract = {'scope': 'analysis', 'playbooks': ['panel'], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id, 'sha256': digest}, 'requirements': definitions}
    record_id = 'oprec_missing' if missing_record else record.record_id
    evidence = {'models': [models[0]], 'sensitivity': [models[1]], 'requirements': [
        {'requirement_id': op['step_id'], 'operation_record_id': record_id,
         'workflow_step_id': op['step_id'], 'artifacts': [ref]} for op, ref in zip(ops, models)]}
    plan, _ = approved_plan(runtime.project_root, contract, evidence)
    counts = {'record': 0, 'proposal': 0}
    for module, kind, identity in [(operation_records, 'record', record_id), (proposals, 'proposal', record.proposal_id)]:
        original = module.read_jsonl
        def read(path, *, _original=original, _kind=kind, _identity=identity):
            if path.stem == _identity:
                counts[_kind] += 1
            return _original(path)
        monkeypatch.setattr(module, 'read_jsonl', read)
    for round_number in (1, 2):
        checked = delivery_check(runtime.project_root, plan)['criteria_verification']
        assert checked['status'] == ('partial' if missing_record else 'requirements_met'), checked
        assert [row['status'] for row in checked['requirements']] == [
            'unverified' if missing_record else 'verified'] * 2
        assert counts == {'record': round_number, 'proposal': 0 if missing_record else round_number}


@pytest.mark.parametrize('change,reason', [
    (lambda c, e: c['requirements'][0]['operation']['spec'].update(covariance='robust'), 'scientific_spec_changed'),
    (lambda c, e: e['requirements'][0].update(workflow_step_id='alternate'), 'scientific_spec_changed'),
    (lambda c, e: e['requirements'][0].update(operation_record_id='oprec_absent'), 'unknown operation record'),
    (lambda c, e: c['requirements'][0]['operation'].update(operation_id='diagnostics.vif', spec={
        'input_mode': 'typed', 'column_bindings': {'design': ['wage', 'x']}, 'options': {}}), 'verifier_not_available'),
    (lambda c, e: c['source'].update(sha256='0' * 64), 'unverified'),
])
def test_success_receipts_cannot_cover_an_unrelated_or_changed_deliverable(actual_panel, change, reason):
    runtime, *_ = actual_panel
    plan = panel_plan(actual_panel, change=change)
    checked = delivery_check(runtime.project_root, plan)
    assert checked['status'] == 'partial'
    row = checked['criteria_verification']['requirements'][0]
    assert row['status'] == 'unverified' and reason in row['reason']


def test_expected_outputs_need_their_own_explicit_coverage(actual_panel):
    runtime, *_ = actual_panel
    plan = panel_plan(actual_panel, change=lambda c, e: c['requirements'][0].update(covers=[{'criterion_index': 0}]))
    checked = delivery_check(runtime.project_root, plan)
    assert checked['status'] == 'partial'
    assert checked['criteria_verification']['unbound_slots'] == [{'step_id': 'fit', 'output_index': 0}]


def test_registered_report_reuses_the_existing_result_coverage_check(actual_panel):
    runtime, _, record, models, digest = actual_panel
    report_op = next(s for s in record.changes['steps'] if s['step_id'] == 'report')
    report_ref = {'run_id': runtime.run_id, 'artifact_id': next(
        name for name in record.outputs['workflow_state']['steps']['report']['artifact_ids'] if name.endswith('_html'))}
    contract = {'scope': 'analysis', 'playbooks': ['panel'], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id, 'sha256': digest},
        'requirements': [requirement({k: report_op[k] for k in ['step_id', 'operation_id', 'spec']})]}
    evidence = {'models': [models[0]], 'sensitivity': [models[1]], 'report': report_ref, 'requirements': [{
        'requirement_id': 'fit', 'operation_record_id': record.record_id, 'workflow_step_id': 'report',
        'artifacts': [report_ref]}]}
    plan, _ = approved_plan(runtime.project_root, contract, evidence,
                            criteria=['Compose the result-bound report'], outputs=['Registered report'])
    checked = delivery_check(runtime.project_root, plan)
    assert checked['status'] == 'requirements_met', checked['criteria_verification']


def test_changed_registered_model_bytes_invalidate_an_old_success_receipt(actual_panel):
    runtime, _, _, models, _ = actual_panel
    plan = panel_plan(actual_panel)
    path = runtime.project_root / 'runs' / models[0]['run_id'] / 'model_results/panel_ols_1.json'
    original = path.read_bytes()
    try:
        path.write_bytes(original + b' ')
        checked = delivery_check(runtime.project_root, plan)
        assert checked['status'] == 'partial'
        assert checked['criteria_verification']['requirements'][0]['status'] == 'unverified'
    finally:
        path.write_bytes(original)


def test_an_empty_legacy_plan_cannot_claim_full_analysis_with_no_machine_definition(tmp_path):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    checked = delivery_check(tmp_path, replace(plan, criteria=(), steps=()))
    assert checked['status'] == 'partial'


@pytest.mark.parametrize('language,claim,kept,label', [
    ('en', 'Analysis complete.', 'Existing findings are retained.', 'approved criteria'),
    ('zh', '分析完成。', '已有结果保留。', '已批准的判据'),
])
def test_final_publication_keeps_findings_and_explains_unverified_obligations(tmp_path, language, claim, kept, label):
    from workbench.agent.completion import publication
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    checked = delivery_check(tmp_path, plan)
    rendered = publication(kept + '\n' + claim, checked, language)
    assert kept in rendered and label in rendered
    assert claim not in rendered
