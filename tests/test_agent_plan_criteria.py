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


@pytest.fixture(scope='module')
def symbolic_products(tmp_path_factory):
    from tests import test_read_only_analysis as sample
    rng = np.random.default_rng(602)
    x, z = rng.normal(size=(2, 96))
    frame = pd.DataFrame({'row': np.arange(96), 'x': x, 'z': z,
                          'wage': 2 + x + z / 3 + rng.normal(size=96)})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sample, '_frame', lambda: frame)
        runtime = sample._Fixture(tmp_path_factory.mktemp('criteria-symbolic'))
    fit = {'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
        'model_family': 'ols', 'covariance': 'robust',
        'branches': [{'branch_id': 'main', 'outcome': 'wage', 'predictors': ['x', 'z']}]}}
    describe = {'step_id': 'explore', 'operation_id': 'statistical.explore', 'spec': {
        'operation': 'summarize_detail', 'selected_columns': ['x', 'z'], 'options': {}}}
    fit['depends_on'] = ['explore']
    subset = {'step_id': 'subset', 'operation_id': 'data.subset', 'spec': {
        'columns': ['row', 'x', 'z', 'wage'],
        'filters': [{'column': 'row', 'op': 'not_in', 'value': [0, 1, 2]}]}}
    alternate = deepcopy(fit)
    alternate['step_id'] = 'alternate'
    alternate['spec']['source'] = {'from_step': 'subset', 'output': 'produced_dataset'}
    test = {'step_id': 'joint', 'operation_id': 'model.joint_f_test', 'depends_on': ['alternate', 'explore'], 'spec': {
        'branch_id': 'main', 'term_selectors': [{'kind': 'linear', 'column': 'x'}],
        'source': {'from_step': 'subset', 'output': 'produced_dataset'}}}
    report = {'step_id': 'report', 'operation_id': 'report.compose',
              'depends_on': ['fit', 'alternate', 'joint'], 'spec': {'sections': ['models']}}
    pending = runtime.propose([describe, fit, subset, alternate, test, report])
    proposal = runtime.orchestrator.proposal_store.latest_revision(pending['proposal']['proposal_id'])
    record = runtime.orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type='user', current_context_fingerprint=sample.FINGERPRINT,
        current_active_head_run_id=runtime.run_id)
    record = asyncio.run(runtime.orchestrator.execute_confirmed_operation(record.record_id,
        project_root=runtime.project_root, current_context_fingerprint=sample.FINGERPRINT,
        current_active_head_run_id=runtime.run_id))
    assert record.status == 'completed', record.error
    state = record.outputs['workflow_state']['steps']
    references = {}
    for step_id in ['fit', 'alternate']:
        branch = state[step_id]['model_branches'][0]
        references[step_id] = {'run_id': branch['run_id'], 'artifact_id': branch['model_id']}
    references['subset'] = {k: state['subset']['produced_dataset'][k] for k in ['run_id', 'artifact_id']}
    references['joint'] = {'run_id': runtime.run_id, 'artifact_id': state['joint']['artifact_ids'][0]}
    references['report'] = {'run_id': runtime.run_id, 'artifact_id': next(
        a for a in state['report']['artifact_ids'] if a.endswith('_html'))}
    digest = hashlib.sha256((runtime.project_root / 'runs' / runtime.run_id / 'data.csv').read_bytes()).hexdigest()
    return runtime, record, references, digest


def symbolic_plan(products, change=None, *, approve=True):
    runtime, record, refs, digest = products
    definitions = [{**requirement({k: deepcopy(step[k]) for k in ['step_id', 'operation_id', 'spec']}),
                    'id': step['step_id']} for step in record.changes['steps'] if step['step_id'] != 'explore']
    contract = {'scope': 'analysis', 'playbooks': ['ols'], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id, 'sha256': digest}, 'requirements': definitions}
    evidence = {'models': [refs['fit']], 'sensitivity': [refs['alternate']], 'report': refs['report'],
        'requirements': [{'requirement_id': step['step_id'], 'operation_record_id': record.record_id,
            'workflow_step_id': step['step_id'], 'artifacts': [refs[step['step_id']]]}
            for step in record.changes['steps'] if step['step_id'] != 'explore']}
    if change:
        change(contract, evidence)
    return approved_plan(runtime.project_root, contract, evidence, approve=approve)[0]


@pytest.mark.parametrize('approve', [False, True])
def test_symbolic_source_joint_f_and_report_reuse_real_products_after_restart(symbolic_products, monkeypatch, approve):
    from workbench.agent import workflow_runtime, postestimation_steps
    from workbench.agent.completion import _Products
    from workbench.agent.plan_criteria import verify
    runtime, record, *_ = symbolic_products
    plan = symbolic_plan(symbolic_products, approve=approve)
    def forbidden(*args, **kwargs):
        pytest.fail('delivery verification attempted execution or fitting')
    monkeypatch.setattr(workflow_runtime, 'build_workflow_step_executor', forbidden)
    monkeypatch.setattr(postestimation_steps, '_resolve_model_binding', forbidden)
    records_before = [r.to_dict() for r in runtime.orchestrator.operation_store.list_records()]
    first = verify(runtime.project_root, plan, _Products(runtime.project_root), plan.completion_evidence)
    assert first['status'] == 'requirements_met', first
    assert {row['id'] for row in first['requirements'] if row['status'] == 'verified'} == {
        'fit', 'subset', 'alternate', 'joint', 'report'}
    restored = plans.Plan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert verify(runtime.project_root, restored, _Products(runtime.project_root), restored.completion_evidence) == first
    assert [r.to_dict() for r in runtime.orchestrator.operation_store.list_records()] == records_before
    assert plan.steps[0].completed_operation_ids == ()


@pytest.mark.parametrize('change,reason', [
    ('upstream_spec', 'upstream_scientific_spec_changed'),
    ('source_identity', 'model_input_source_unverified'),
    ('source_sha', 'produced_dataset_unverified'),
    ('missing_binding', 'produced_dataset_unverified'),
    ('branch', 'model_branch_ambiguous'),
    ('model_id', 'single_model_binding_unverified'),
    ('model_packet', 'model_or_source_unverified'),
    ('kernel', 'inference_kernel_unverified'),
    ('missing_kernel', 'inference_kernel_unverified'),
    ('joint_model', 'joint_f_model_binding_unverified'),
    ('joint_covariance', 'joint_f_model_binding_unverified'),
    ('joint_branch', 'joint_f_model_binding_unverified'),
    ('joint_selectors', 'typed_joint_f_result_unverified'),
])
def test_symbolic_binding_rejects_changed_or_missing_provenance(symbolic_products, monkeypatch, change, reason):
    from workbench.agent.completion import _Products
    from workbench.agent.plan_criteria import verify
    from workbench.agent.operation_records import OperationRecordStore
    runtime, record, refs, _ = symbolic_products
    plan = symbolic_plan(symbolic_products)
    changed = deepcopy(record.outputs)
    states = changed['workflow_state']['steps']
    if change == 'upstream_spec':
        def revise(contract, evidence):
            next(d for d in contract['requirements'] if d['id'] == 'subset')['operation']['spec']['filters'][0]['value'] = [0, 1]
        plan = symbolic_plan(symbolic_products, revise)
    elif change == 'source_identity':
        # Same bytes under another registered identity cannot replace the
        # exact source the model's persisted input declaration names.
        from workbench.artifacts import read_json, register_artifact
        root = runtime.project_root / 'runs' / runtime.run_id
        index = root / 'artifacts_index.json'
        original = index.read_bytes()
        entry = next(a for a in read_json(index)['artifacts'] if a['artifact_id'] == refs['subset']['artifact_id'])
        register_artifact(root, 'same_bytes_other_source', root / entry['path'], 'derived_data', 'fixture', entry['inputs'])
        states['subset']['produced_dataset']['artifact_id'] = 'same_bytes_other_source'
        states['subset']['artifact_ids'].append('same_bytes_other_source')
    elif change == 'source_sha':
        states['subset']['produced_dataset']['content_sha256'] = '0' * 64
    elif change == 'missing_binding':
        states['subset']['produced_dataset'] = None
    elif change == 'branch':
        states['alternate']['model_branches'].append(deepcopy(states['alternate']['model_branches'][0]))
    elif change == 'model_id':
        states['alternate']['model_branches'][0]['model_id'] = None
    elif change.startswith('joint_') or change in {'missing_kernel', 'model_packet'}:
        # The typed result remains real; simulate an origin read that names
        # the other completed model instead of its selected dependency.
        original_load = _Products.load
        def load(self, ref):
            value = original_load(self, ref)
            if (change == 'missing_kernel' and ref.get('run_id') == refs['alternate']['run_id']
                    and ref.get('artifact_id') == 'inference_kernel_' + refs['alternate']['artifact_id']):
                return None
            if change == 'model_packet' and ref == refs['alternate'] and value:
                return replace(value, payload={**value.payload, 'model_id': 'ols_2'})
            if change.startswith('joint_') and ref == refs['joint'] and value:
                payload = deepcopy(value.payload)
                if change == 'joint_model':
                    payload['source']['model_run_id'] = refs['fit']['run_id']
                elif change == 'joint_covariance':
                    payload['result']['covariance'] = 'unadjusted'
                elif change == 'joint_branch':
                    payload['result']['branch_id'] = 'another_branch'
                else:
                    payload['result']['term_selectors'] = [{'kind': 'linear', 'column': 'z'}]
                return replace(value, payload=payload)
            return value
        monkeypatch.setattr(_Products, 'load', load)
    else:
        states['alternate']['model_branches'][0]['inference_kernel_sha256'] = '0' * 64
    original_get = OperationRecordStore.get
    monkeypatch.setattr(OperationRecordStore, 'get', lambda self, identity:
        replace(record, outputs=changed) if identity == record.record_id else original_get(self, identity))
    try:
        checked = verify(runtime.project_root, plan, _Products(runtime.project_root), plan.completion_evidence)
        assert checked['status'] == 'partial', checked
        assert any(reason in row['reason'] for row in checked['requirements']), checked
    finally:
        if change == 'source_identity':
            index.write_bytes(original)


def test_machine_source_binding_needs_an_exact_approved_upstream_definition(symbolic_products, monkeypatch):
    from workbench.agent import plan_criteria
    from workbench.agent.completion import _Products
    runtime, record, *_ = symbolic_products
    def remove_upstream(contract, evidence):
        contract['requirements'] = [d for d in contract['requirements'] if d['id'] != 'subset']
        evidence['requirements'] = [p for p in evidence['requirements'] if p['requirement_id'] != 'subset']
    plan = symbolic_plan(symbolic_products, remove_upstream)
    original = plan_criteria._validated_record
    def machine_record(root, identity):
        found, workflow, digest = original(root, identity)
        return replace(found, actor_type='approved_plan'), workflow, digest
    monkeypatch.setattr(plan_criteria, '_validated_record', machine_record)
    checked = plan_criteria.verify(runtime.project_root, plan, _Products(runtime.project_root), plan.completion_evidence)
    assert checked['status'] == 'partial'
    assert any('upstream_scientific_definition_unverified' in row['reason'] for row in checked['requirements'])


def test_machine_verification_allows_unbound_descriptive_ordering_dependencies(symbolic_products, monkeypatch):
    from workbench.agent import plan_criteria
    from workbench.agent.completion import _Products
    runtime, *_ = symbolic_products
    plan = symbolic_plan(symbolic_products)
    assert all(d['operation']['step_id'] != 'explore' for d in plan.completion['requirements'])
    original = plan_criteria._validated_record
    def machine_record(root, identity):
        found, workflow, digest = original(root, identity)
        return replace(found, actor_type='approved_plan'), workflow, digest
    # Exercise the Auto proof branch with real executed producer outputs; do
    # not create another receipt or change the original human confirmation.
    monkeypatch.setattr(plan_criteria, '_validated_record', machine_record)
    checked = plan_criteria.verify(runtime.project_root, plan, _Products(runtime.project_root), plan.completion_evidence)
    assert checked['status'] == 'requirements_met', checked


def test_implicit_dataset_input_is_not_certified_as_the_workflow_target(symbolic_products):
    from workbench.agent.completion import _Products
    from workbench.agent.plan_criteria import _step_source
    runtime, record, *_ = symbolic_products
    plan = symbolic_plan(symbolic_products)
    consumer = deepcopy(next(s for s in record.changes['steps'] if s['step_id'] == 'alternate'))
    consumer['spec'].pop('source')
    consumer['depends_on'] = ['subset']
    definitions = {d['operation']['step_id']: d['operation'] for d in plan.completion['requirements']}
    with pytest.raises(ValueError, match='implicit_dataset_source_unverified'):
        _step_source(_Products(runtime.project_root), record, consumer, plan.completion['source'], definitions)


@pytest.mark.parametrize('field,value', [('sampling_weight', 'row'), ('model_options', {})])
def test_model_reader_cannot_certify_scientific_fields_missing_from_producer_binding(symbolic_products, field, value):
    from workbench.agent.completion import _Products
    from workbench.agent.plan_criteria import _model_output
    runtime, record, refs, digest = symbolic_products
    operations = {s['step_id']: s for s in record.changes['steps']}
    declaration = deepcopy(operations['fit'])
    declaration['spec'][field] = value
    # At the typed-reader boundary, a real unweighted fit cannot certify a
    # request field absent from its published scientific binding. No receipt
    # or project file is changed to make this declaration an executed request.
    with pytest.raises(ValueError, match='model_scientific_fields_unverified'):
        _model_output(_Products(runtime.project_root), {'operation': declaration}, record,
            record.outputs['workflow_state']['steps']['fit'], [refs['fit']],
            {'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id, 'sha256': digest}, operations)
