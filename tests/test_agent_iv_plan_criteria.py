"""Typed IV/AR evidence from real Ask and approved Auto producer workflows."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from workbench.agent import plans
from workbench.agent.completion import _Products, CompletionEvidenceError, validate_completion_evidence
from workbench.agent.plan_control import PlanControl
from workbench.agent.plan_criteria import verify
from workbench.agent.task_requirements import RequirementBinder
from workbench.canonical import sha256_canonical


def _confirm(runtime, pending):
    from tests.test_read_only_analysis import FINGERPRINT
    proposal = runtime.orchestrator.proposal_store.latest_revision(pending['proposal']['proposal_id'])
    record = runtime.orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type='user', current_context_fingerprint=FINGERPRINT,
        current_active_head_run_id=runtime.run_id)
    completed = asyncio.run(runtime.orchestrator.execute_confirmed_operation(record.record_id,
        project_root=runtime.project_root, current_context_fingerprint=FINGERPRINT,
        current_active_head_run_id=runtime.run_id))
    assert completed.status == 'completed', completed.error
    return completed


def _plan(runtime, operations, proofs):
    definitions = [{'id': op['step_id'], 'covers': [{'criterion_index': i}],
        'operation': {key: deepcopy(op[key]) for key in ('step_id', 'operation_id', 'spec')}}
        for i, op in enumerate(operations)]
    path = runtime.project_root / 'runs' / runtime.run_id / 'data.csv'
    contract = {'scope': 'analysis', 'playbooks': ['iv'], 'source': {
        'run_id': runtime.run_id, 'artifact_id': runtime.artifact_id,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, 'requirements': definitions}
    plan = plans.merge(None, question='Check the fixed IV model and its AR inversion',
        criteria=['The executed IV specification', 'The computed AR inversion'],
        steps=(plans.PlanStep('ar', 'AR', ('iv.ar_confidence',)),), budget=None, allowed_classes=None,
        completion=contract, completion_evidence={'requirements': proofs})
    return replace(plan, task_requirements=RequirementBinder(runtime.repository).bind('chain-session', None))


def _proof(record, step, refs):
    return {'requirement_id': step, 'operation_record_id': record.record_id,
            'workflow_step_id': step, 'artifacts': refs}


def _iv_frame():
    rng = np.random.default_rng(659)
    w, z, u, v = rng.normal(size=(4, 96))
    d = .7*z + .3*w + v
    return pd.DataFrame({'y': 1.1*d + .5*w + u, 'd': d, 'w': w, 'z': z})


@pytest.fixture(scope='module', params=['ask', 'auto'])
def iv_products(tmp_path_factory, request):
    from tests import test_read_only_analysis as sample
    from tests.test_agent_execution_modes import _with_authority_runner
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sample, '_frame', _iv_frame)
        runtime = sample._Fixture(tmp_path_factory.mktemp('typed-iv-' + request.param))
    runtime.repository.append('chain-session', 'message', {'role': 'user', 'content': 'Please complete the full analysis.'})
    fit = {'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
        'model_family': 'iv_2sls', 'covariance': 'robust', 'iv_endog': ['d'], 'iv_instruments': ['z'],
        'branches': [{'branch_id': 'main', 'outcome': 'y', 'predictors': ['w']}]}}
    symbolic_ar = {'step_id': 'ar', 'operation_id': 'iv.ar_confidence', 'depends_on': ['fit'],
                   'spec': {'model_ref': 'step:fit:main'}}
    if request.param == 'ask':
        pending = runtime.propose([fit, symbolic_ar])
        assert pending['requires_confirmation']
        fit_record = ar_record = _confirm(runtime, pending)
        ar = symbolic_ar
    else:
        pending = runtime.propose([fit])
        assert pending['requires_confirmation']  # model.genesis keeps its high floor.
        fit_record = _confirm(runtime, pending)
    branch = fit_record.outputs['workflow_state']['steps']['fit']['model_branches'][0]
    model_ref = {'run_id': branch['run_id'], 'artifact_id': branch['model_id']}
    fit_proof = _proof(fit_record, 'fit', [model_ref])
    if request.param == 'auto':
        ar = {'step_id': 'ar', 'operation_id': 'iv.ar_confidence', 'spec': {
            'model_run_id': model_ref['run_id'], 'model_ref': model_ref['artifact_id']}}
        fixed = _plan(runtime, [fit, ar], [fit_proof])
        runtime.orchestrator.plan_store.save('chain-session', fixed)
        PlanControl(runtime.project_root, runtime.repository, 'chain-session').approve(fixed.version)
        runtime.orchestrator.execution_mode = 'auto'
        _with_authority_runner(runtime)
        receipt = runtime.propose([ar])
        assert receipt['executed'], receipt
        ar_record = runtime.orchestrator.operation_store.get(receipt['operation']['record_id'])
        assert ar_record.actor_type not in {'user', 'human_ui', 'human_cli'}
    state = ar_record.outputs['workflow_state']['steps']['ar']
    [artifact_id] = state['artifact_ids']
    ar_ref = {'run_id': runtime.run_id, 'artifact_id': artifact_id}
    ar_proof = _proof(ar_record, 'ar', [ar_ref])
    if request.param == 'ask':
        plan = _plan(runtime, [fit, ar], [fit_proof, ar_proof])
    else:
        plan = runtime.orchestrator.plan_store.current('chain-session')
        plan = replace(plan, completion_evidence={'requirements': [fit_proof, ar_proof]})
    return runtime, plan, model_ref, ar_ref, fit_record, ar_record


def _check(products, plan=None):
    runtime, original, *_ = products
    return verify(runtime.project_root, plan or original, _Products(runtime.project_root))


def test_new_IV_completion_publishes_small_actual_point_definition(iv_products):
    runtime, _, ref, *_ = iv_products
    products = _Products(runtime.project_root)
    model = products.load(ref)
    assert model.payload['y_column'] is None  # Do not rewrite the old model packet.
    companion = products.load({**ref, 'artifact_id': ref['artifact_id'] + '.completion'})
    definition = companion.payload.get('point_definition')
    assert isinstance(definition, dict), 'actual fitted IV definition was discarded'
    assert definition == {'family': 'iv_2sls', 'intercept': True, 'outcome': ['y'],
        'exogenous': ['Intercept', 'w'], 'endogenous': ['d'], 'instruments': ['z'],
        'actual_design_sha256': definition['actual_design_sha256']}
    assert len(definition['actual_design_sha256']) == 64
    assert sha256_canonical(definition) == companion.payload['point_estimation_fingerprint']


def test_typed_IV_and_AR_use_the_real_confirmed_products_without_reexecution(iv_products):
    runtime, plan, _, _, fit, ar = iv_products
    before = [json.dumps(record.to_dict(), sort_keys=True) for record in (fit, ar)]
    checked = _check(iv_products)
    assert checked['status'] == 'requirements_met', checked
    assert [r['status'] for r in checked['requirements']] == ['verified', 'verified']
    assert [json.dumps(runtime.orchestrator.operation_store.get(record.record_id).to_dict(), sort_keys=True)
            for record in (fit, ar)] == before
    if ar.actor_type == 'user':
        assert plan.approved_version is None
    else:
        assert plan.approved_version is not None


def test_AR_in_results_is_rejected_with_an_exact_diagnostics_role_hint(iv_products):
    runtime, plan, model, ar, *_ = iv_products
    wrong = {'models': [model], 'results': [ar]}
    before = deepcopy(wrong)
    with pytest.raises(CompletionEvidenceError) as caught:
        validate_completion_evidence(runtime.project_root, plan.completion, wrong)
    assert 'completion_evidence.diagnostics' in str(caught.value)
    assert ar['artifact_id'] in str(caught.value)
    assert wrong == before
    corrected = {'models': [model], 'diagnostics': [ar]}
    assert validate_completion_evidence(runtime.project_root, plan.completion, corrected) == corrected


def _project_payload(monkeypatch, ref, change):
    """Only project bounded metadata read from independently produced fixtures."""
    original = _Products.load
    def load(self, wanted):
        value = original(self, wanted)
        if value is not None and wanted == ref:
            payload = deepcopy(value.payload)
            change(payload)
            return replace(value, payload=payload)
        return value
    monkeypatch.setattr(_Products, 'load', load)


@pytest.mark.parametrize('change', ['missing', 'changed', 'roles'])
def test_IV_runtime_definition_is_required_and_bound_to_the_actual_fit(iv_products, monkeypatch, change):
    _, _, ref, *_ = iv_products
    def alter(value):
        if change == 'missing':
            value.pop('point_definition')
        elif change == 'changed':
            value['point_definition']['outcome'] = ['z']
        else:
            value['point_definition']['endogenous'], value['point_definition']['instruments'] = ['z'], ['d']
            value['point_estimation_fingerprint'] = sha256_canonical(value['point_definition'])
    _project_payload(monkeypatch, {**ref, 'artifact_id': ref['artifact_id'] + '.completion'}, alter)
    checked = _check(iv_products)
    assert checked['status'] == 'partial'
    assert checked['requirements'][0]['reason'] == 'iv_runtime_definition_unverified'


@pytest.mark.parametrize('change,reason', [
    ('source', 'iv_ar_published_source_unverified'),
    ('step', 'iv_ar_published_source_unverified'),
    ('execution', 'iv_ar_published_source_unverified'),
    ('model', 'iv_ar_model_binding_unverified'),
    ('covariance', 'iv_ar_model_binding_unverified'),
    ('point', 'iv_ar_model_binding_unverified'),
    ('sample', 'iv_ar_model_binding_unverified'),
    ('certificate', 'iv_ar_global_certificate_unverified'),
    ('input', 'iv_ar_original_input_unverified'),
    ('bounds', 'iv_ar_original_input_unverified'),
])
def test_AR_requires_its_actual_source_model_and_full_input_certificate(iv_products, monkeypatch, change, reason):
    _, _, _, ref, *_ = iv_products
    def alter(value):
        result = value['result']
        region = result['anderson_rubin_95']
        if change == 'source':
            value['source']['sha256'] = '0' * 64
        elif change == 'step':
            value['source']['workflow_step_id'] = 'fit'
        elif change == 'execution':
            value['execution']['plan_fingerprint'] = 'sha256:' + '0' * 64
        elif change == 'model':
            result['model_run_id'] = 'other_model_owner'
        elif change == 'covariance':
            result['covariance'] = 'unadjusted'
        elif change in {'point', 'sample'}:
            result['point_estimation_fingerprint' if change == 'point' else 'analysis_sample_fingerprint'] = '0' * 64
        elif change == 'certificate':
            region['global_certification']['status'] = 'certified_on_defined_domain'
        elif change == 'input':
            region['computation']['certification_target'] = 'rounded_moments'
        else:
            region['global_certification']['reduction'].pop('moment_bounds')
    _project_payload(monkeypatch, ref, alter)
    checked = _check(iv_products)
    assert checked['status'] == 'partial'
    assert checked['requirements'][0]['status'] == 'verified'
    assert checked['requirements'][1]['reason'] == reason


def test_nonterminal_parent_cannot_be_replaced_by_its_completed_AR_child(iv_products, monkeypatch):
    from workbench.agent.operation_records import OperationRecordStore
    *_, record = iv_products
    original = OperationRecordStore.get
    monkeypatch.setattr(OperationRecordStore, 'get', lambda self, record_id:
        replace(record, status='running') if record_id == record.record_id else original(self, record_id))
    checked = _check(iv_products)
    assert checked['status'] == 'partial'
    assert checked['requirements'][1]['reason'] == 'operation_not_completed_and_verified'


def test_AR_proof_must_select_the_artifact_published_by_that_step(iv_products):
    _, plan, model, ar, *_ = iv_products
    evidence = deepcopy(plan.completion_evidence)
    evidence['requirements'][1]['artifacts'] = [model, ar]
    checked = _check(iv_products, replace(plan, completion_evidence=evidence))
    assert checked['status'] == 'partial'
    assert checked['requirements'][1]['reason'] == 'iv_ar_published_source_unverified'


def test_machine_AR_requires_the_original_approved_basis_not_late_result_ids(iv_products):
    _, plan, *_, record = iv_products
    if record.actor_type == 'user':
        pytest.skip('Ask uses the original full human request confirmation')
    contract = deepcopy(plan.completion)
    contract['requirements'][1]['operation']['spec']['model_run_id'] = 'another_owner'
    checked = _check(iv_products, replace(plan, completion=contract))
    assert checked['status'] == 'partial'
    assert checked['requirements'][0]['status'] == 'verified'  # The fit was explicitly human-confirmed.
    assert checked['requirements'][1]['reason'] == 'executed_scientific_spec_changed'
    checked = _check(iv_products, replace(plan, question=plan.question + ' Changed after approval.'))
    assert checked['status'] == 'partial'
    assert checked['requirements'][1]['reason'] == 'human_request_confirmation_or_approved_basis_required'


def test_role_hint_does_not_generalize_to_other_post_estimation_contracts(iv_products, monkeypatch):
    runtime, plan, model, ar, *_ = iv_products
    _project_payload(monkeypatch, ar, lambda value: value['result'].update(contract='another.post-estimation.v1'))
    with pytest.raises(CompletionEvidenceError) as caught:
        validate_completion_evidence(runtime.project_root, plan.completion, {'models': [model], 'results': [ar]})
    assert 'completion_evidence.diagnostics' not in str(caught.value)


def test_each_verification_reopens_registered_evidence_and_preserves_receipts(iv_products, tmp_path):
    from shutil import copytree
    runtime, plan, _, ar, *_ = iv_products
    project = tmp_path / 'copied-fixture'
    copytree(runtime.project_root, project)
    assert verify(project, plan, _Products(project))['status'] == 'requirements_met'
    index = json.loads((project / 'runs' / ar['run_id'] / 'artifacts_index.json').read_text())
    entry = next(a for a in index['artifacts'] if a['artifact_id'] == ar['artifact_id'])
    path = project / 'runs' / ar['run_id'] / entry['path']
    path.write_bytes(path.read_bytes() + b' ')
    checked = verify(project, plan, _Products(project))
    assert checked['status'] == 'partial'
    assert checked['requirements'][1]['reason'] == 'iv_ar_published_source_unverified'


def test_a_real_successful_report_is_not_AR_execution_or_AR_proof(iv_products, monkeypatch):
    runtime, plan, model, ar, *_ = iv_products
    monkeypatch.setattr(runtime.orchestrator, 'execution_mode', 'ask')
    pending = runtime.propose([{'step_id': 'report', 'operation_id': 'report.compose', 'spec': {
        'result_refs': [{**model, 'role': 'primary'}, {**ar, 'role': 'diagnostic'}]}}])
    assert pending['requires_confirmation']
    record = _confirm(runtime, pending)
    state = record.outputs['workflow_state']['steps']['report']
    products = _Products(runtime.project_root)
    report = next({'run_id': runtime.run_id, 'artifact_id': artifact_id}
        for artifact_id in state['artifact_ids']
        if products.load({'run_id': runtime.run_id, 'artifact_id': artifact_id}).artifact_type == 'report')
    evidence = deepcopy(plan.completion_evidence)
    evidence['requirements'][1]['artifacts'] = [report]
    checked = _check(iv_products, replace(plan, completion_evidence=evidence))
    assert checked['requirements'][1]['reason'] == 'iv_ar_published_source_unverified'
    evidence['requirements'][1] = {**_proof(record, 'report', [report]), 'requirement_id': 'ar'}
    checked = _check(iv_products, replace(plan, completion_evidence=evidence))
    assert checked['requirements'][1]['reason'] == 'executed_scientific_spec_changed'


@pytest.mark.parametrize('covariance', ['robust', 'unadjusted'])
def test_typed_AR_keeps_the_existing_exact_fallback_and_homoskedastic_producers(tmp_path, monkeypatch, covariance):
    from tests import test_read_only_analysis as sample
    from workbench.checks import ar_verified
    monkeypatch.setattr(sample, '_frame', _iv_frame)
    runtime = sample._Fixture(tmp_path)
    fit = {'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
        'model_family': 'iv_2sls', 'covariance': covariance, 'iv_endog': ['d'], 'iv_instruments': ['z'],
        'branches': [{'branch_id': 'main', 'outcome': 'y', 'predictors': ['w']}]}}
    ar = {'step_id': 'ar', 'operation_id': 'iv.ar_confidence', 'depends_on': ['fit'],
          'spec': {'model_ref': 'step:fit:main'}}
    if covariance == 'robust':
        def uncertain(*_args):
            raise ar_verified.VerificationUncertain('test_original_exact_certificate_reader')
        # Select the existing fallback boundary; the producer and estimator remain real.
        monkeypatch.setattr(ar_verified, 'verify_polynomials', uncertain)
    record = _confirm(runtime, runtime.propose([fit, ar]))
    states = record.outputs['workflow_state']['steps']
    [branch] = states['fit']['model_branches']
    model = {'run_id': branch['run_id'], 'artifact_id': branch['model_id']}
    [ar_id] = states['ar']['artifact_ids']
    ar_ref = {'run_id': runtime.run_id, 'artifact_id': ar_id}
    plan = _plan(runtime, [fit, ar], [_proof(record, 'fit', [model]), _proof(record, 'ar', [ar_ref])])
    checked = verify(runtime.project_root, plan, _Products(runtime.project_root))
    assert checked['status'] == 'requirements_met', checked
    region = _Products(runtime.project_root).load(ar_ref).payload['result']['anderson_rubin_95']
    if covariance == 'robust':
        assert region['computation']['path'] == 'exact_fallback'
    else:
        assert region['method'] == 'homoskedastic'
    assert region['global_certification']['algorithm'] == 'sturm_sign_decomposition_v1'
