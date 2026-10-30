"""Prepared only: real producer replay; never a free-text scientific oracle."""
from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from tests.test_agent_iv_plan_criteria import iv_products as _iv_products, _confirm
from workbench.agent.completion import _Products
from workbench.agent.context_tools import InspectOperationArtifactRequest, InspectResultSummaryRequest


@pytest.fixture(scope='module', params=['ask', 'auto'])
def iv_products(tmp_path_factory, request):
    from tests import test_read_only_analysis as sample
    from tests.test_data_column_cast import _register_source_node_identity
    original = sample._source_project
    def indexed_source(*args, **kwargs):
        project, run_id, artifact_id = original(*args, **kwargs)
        _register_source_node_identity(project, run_id)
        return project, run_id, artifact_id
    with pytest.MonkeyPatch.context() as patch:
        # Register the existing node before execution; leave its record/scope intact.
        patch.setattr(sample, '_source_project', indexed_source)
        return _iv_products.__wrapped__(tmp_path_factory, request)


def _ar_view(runtime, record, ref):
    return runtime.orchestrator.context_provider.inspect_operation_artifact(
        InspectOperationArtifactRequest(request_id='ar-meaning', owner_run_id=record.target['run_id'],
            op_node_id=record.target['node_ref'], active_head_run_id=runtime.run_id,
            operation_record_id=record.record_id, artifact_id=ref['artifact_id']),
        chain_id='chain-a', session_id='chain-session')['artifact_evidence']


def test_real_AR_public_reader_keeps_topology_certificate_scope_and_bindings(iv_products):
    runtime, _, model, ar, _, record = iv_products
    artifact = _Products(runtime.project_root).load(ar)
    before = deepcopy(artifact.payload)
    stored = before['result']
    view = _ar_view(runtime, record, ar)
    public = view['result']
    region = public['anderson_rubin_95']
    assert view['evidence_ref']['sha256'] == artifact.sha256
    assert public['source'] == before['source']
    for field in ('model_id', 'model_run_id', 'model_sha256', 'completion_sha256',
                  'point_estimation_fingerprint', 'analysis_sample_fingerprint', 'covariance',
                  'confidence_level', 'scientific_validity'):
        assert public[field] == stored[field]
    assert public['model_run_id'] == model['run_id']
    original = stored['anderson_rubin_95']
    assert region['kind'] == original['kind']
    assert region['method'] == original['method']
    assert region['components'] == original['components']
    assert region['components_omitted'] == 0 and region['component_details_omitted'] is False
    assert region['coverage_certified'] is False
    for field in ('status', 'algorithm', 'arithmetic'):
        assert region['global_certification'][field] == original['global_certification'][field]
    assert region['global_certification']['status'] == 'certified'
    assert region['computation']['certification_target'] == 'original_binary64_observations'
    assert public['scientific_validity'] == 'not_certified'
    assert 'moment_bounds' not in json.dumps(public)
    assert 'inspect_operation_artifact' in public['interpretation_limits']['reader']
    assert 'not independently recompute' in public['interpretation_limits']['proof']
    assert 'first_stage_statistic' not in public
    assert len(json.dumps(public)) < 10_000
    assert artifact.payload == before


def test_result_summary_reads_first_stage_fields_without_reconstructing_F_or_df(iv_products):
    runtime, _, ref, *_ = iv_products
    run = runtime.project_root / 'runs' / ref['run_id']
    payload = json.loads((run / 'model_results' / ('checks_' + ref['artifact_id'] + '.json')).read_text())
    original = next(c for c in payload['checks'] if c['check_id'] == 'iv.first_stage_strength')['evidence']
    summary = runtime.orchestrator.context_provider.inspect_result_summary(
        InspectResultSummaryRequest(request_id='first-stage-meaning', owner_run_id=ref['run_id'],
            op_node_id='model:' + ref['artifact_id'], active_head_run_id=ref['run_id']))['result_summary']
    check = next(c for c in summary['checks'] if c['check_id'] == 'iv.first_stage_strength')['evidence']
    assert check['test'] == original['test']
    assert check['first_stage_statistic'] == original['first_stage_statistic']
    assert check['reference_distribution'] == original['reference_distribution']
    assert check['covariance'] == original['covariance']
    assert original['first_stage_f'] is None and 'first_stage_f' not in check
    for field in ('df', 'numerator_df', 'denominator_df'):
        assert (field in check) == (field in original)
    assert 'anderson_rubin_95' not in check  # No duplicate certificate read or recomputation.


def test_real_service_whole_line_is_a_certified_set_not_an_implied_first_stage_value(tmp_path, monkeypatch):
    from tests import test_read_only_analysis as sample
    from tests.test_data_column_cast import _register_source_node_identity
    # Orthogonal contrasts above the default minimum, with a nonzero weak relation:
    # producer fixture, unrelated to any task data, rubric or requested answer.
    z = np.tile([1., -1., 1., -1., 1., -1., 1., -1.], 8)
    x = np.tile([1., 1., -1., -1., 1., 1., -1., -1.], 8)
    y = np.tile([1., 1., 1., 1., -1., -1., -1., -1.], 8)
    frame = pd.DataFrame({'outcome': y + z/64, 'endogenous': x + z/64, 'instrument': z})
    monkeypatch.setattr(sample, '_frame', lambda: frame)
    runtime = sample._Fixture(tmp_path)
    _register_source_node_identity(runtime.project_root, runtime.run_id)
    record = _confirm(runtime, runtime.propose([
        {'step_id': 'fit', 'operation_id': 'model.genesis', 'spec': {
            'model_family': 'iv_2sls', 'covariance': 'robust', 'iv_endog': ['endogenous'],
            'iv_instruments': ['instrument'],
            'branches': [{'branch_id': 'main', 'outcome': 'outcome', 'predictors': []}]}},
        {'step_id': 'ar', 'operation_id': 'iv.ar_confidence', 'depends_on': ['fit'],
         'spec': {'model_ref': 'step:fit:main'}}]))
    [artifact_id] = record.outputs['workflow_state']['steps']['ar']['artifact_ids']
    view = _ar_view(runtime, record, {'run_id': runtime.run_id, 'artifact_id': artifact_id})['result']
    region = view['anderson_rubin_95']
    assert region['kind'] == 'whole_line'
    assert region['components'] == [{'lower': None, 'upper': None, 'lower_closed': False,
        'upper_closed': False, 'lower_root': None, 'upper_root': None}]
    assert region['global_certification']['status'] == 'certified'
    assert region['coverage_certified'] is False and view['scientific_validity'] == 'not_certified'
    assert 'does not supply or imply' in view['interpretation_limits']['set']


def test_component_limit_is_explicit_and_does_not_disguise_a_partial_projection(iv_products):
    from workbench.agent.context_tools_support.summaries import _public_operation_artifact_result
    runtime, _, _, ref, *_ = iv_products
    # Transport-budget fixture only, not a scientific AR result or a saved artifact.
    wrapper = deepcopy(_Products(runtime.project_root).load(ref).payload)
    component = wrapper['result']['anderson_rubin_95']['components'][0]
    wrapper['result']['anderson_rubin_95']['components'] = [deepcopy(component) for _ in range(17)]
    projected, omitted = _public_operation_artifact_result('post_estimation', wrapper)
    assert len(projected['anderson_rubin_95']['components']) == 16
    assert projected['anderson_rubin_95']['components_omitted'] == 1
    assert 'full_ar_certificate' in omitted


def test_a_matching_raw_p_value_does_not_certify_its_attached_interpretation(iv_products):
    from workbench.agent.statistical_claims import check_model_claims
    runtime, _, ref, *_ = iv_products
    model = _Products(runtime.project_root).load(ref).payload
    term = next(name for name in model['coefficients'] if name != 'Intercept')
    claim = {'field': 'p_value', 'term': term, 'reported': model['coefficients'][term]['p_value'],
             'text': 'This p-value proves that the point estimate is meaningless.'}
    result = check_model_claims(runtime.orchestrator.context_provider,
        run_id=ref['run_id'], model_id=ref['artifact_id'], claims=[claim])
    assert result['status'] == 'provided_claims_match'  # Values only; this is NOT prose approval.
    assert result['checks'][0]['text'] == claim['text']
    assert any('wording' in limit and 'not been verified' in limit for limit in result['limitations'])


def test_missing_analysis_guidance_keeps_partial_and_the_original_confirmation_floor(iv_products):
    from workbench.agent.delivery import delivery_check
    runtime, plan, *_ = iv_products
    evidence = deepcopy(plan.completion_evidence)
    evidence['requirements'] = evidence['requirements'][:1]
    incomplete = replace(plan, completion_evidence=evidence)
    result = delivery_check(runtime.project_root, incomplete)
    assert result['status'] == 'partial'
    assert result['criteria_verification']['requirements'][1]['status'] == 'unverified'
    assert 'truly missing' in result['next_step']
    assert 'original permissions and approval path' in result['next_step']
    assert 'merely to repair its binding' in result['next_step']
    fit = deepcopy(plan.completion['requirements'][0]['operation'])
    fit['step_id'] = 'missing_scientific_comparison'
    fit['spec']['branches'][0]['predictors'] = []
    pending = runtime.propose([fit])
    assert pending['requires_confirmation']  # Also in Auto: model.genesis retains its high floor.
    assert plan.criteria == incomplete.criteria
    assert plan.completion == incomplete.completion


def test_both_protocols_explain_interpretation_and_machine_check_limits():
    from workbench.agent.protocol import CHAIN_AGENT_PROTOCOL, MAIN_AGENT_PROTOCOL
    for protocol in (CHAIN_AGENT_PROTOCOL, MAIN_AGENT_PROTOCOL):
        assert 'Failure to reject does not establish' in protocol
        assert 'whole_line' in protocol and 'rejects no' in protocol and 'candidate' in protocol
        assert 'text field is not parsed' in protocol
        assert 'changing only the covariance estimator is an inference comparison' in protocol
        assert 'genuinely missing' in protocol
        assert 'Workbench checks every number' not in protocol
