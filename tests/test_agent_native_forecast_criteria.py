from dataclasses import replace
import asyncio
import json

import pandas as pd
import pytest

from tests.test_agent_execution_modes import _with_authority_runner
from tests.test_read_only_analysis import FINGERPRINT, _Fixture
from workbench.agent.completion import source_receipt
from workbench.agent.delivery import delivery_check
from workbench.agent.plan_control import PlanControl
from workbench.agent.plans import PlanStep, merge
from workbench.artifacts import write_json
from workbench.native_build import default_output, manifest_path


OPERATION = 'time_series.native_arima'
@pytest.fixture
def forecast_frame():
    from workbench.native_time_series import _MODULE
    if not manifest_path(default_output(_MODULE)).is_file():
        pytest.skip("build with native/time_series/build.py to exercise forecast criteria")
    return pd.DataFrame({"t": range(120), "y": [i / 2 + i % 3 for i in range(120)]})


def confirm_ask(fixture, receipt):
    assert receipt['requires_confirmation'], receipt
    proposal = receipt['proposal']
    confirmed = fixture.orchestrator.confirm_proposal(
        proposal['proposal_id'], revision=proposal['revision'], fingerprint=proposal['fingerprint'],
        actor_type='user', current_context_fingerprint=FINGERPRINT, current_active_head_run_id=fixture.run_id,
    )
    return asyncio.run(fixture.orchestrator.execute_confirmed_operation(
        confirmed.record_id, project_root=fixture.project_root, current_context_fingerprint=FINGERPRINT,
        current_active_head_run_id=fixture.run_id,
    ))


@pytest.mark.parametrize('case,reason', [
    ('matched', None),
    ('exploratory_after_diagnostic', None),
    ('different_request', 'executed_scientific_spec_changed'),
    ('unapproved_basis', 'approved_requirement_basis_unverified'),
    ('retrospective_approval', 'native_forecast_preapproval_unverified'),
    ('wrong_artifact', 'native_forecast_producer_unverified'),
    ('missing_holdout', 'native_forecast_holdout_unverified'),
])
def test_approved_native_forecast_verifies_exact_delivery(tmp_path, monkeypatch, forecast_frame, case, reason):
    frame = forecast_frame
    if case == 'missing_holdout':
        frame.loc[frame.index[-40:], 'y'] = float('nan')
    monkeypatch.setattr('tests.test_read_only_analysis._frame', lambda: frame)
    fixture = _Fixture(tmp_path)
    project = fixture.project_root
    source = source_receipt(project, {'run_id': fixture.run_id, 'artifact_id': fixture.artifact_id})
    assert source is not None
    run = project / 'runs' / fixture.run_id
    write_json(run / 'run_inputs.json', {'upload': {'sha256': source['sha256']}})
    if case == 'exploratory_after_diagnostic':
        fixture.orchestrator.execution_mode = 'ask'
        diagnostic = {'step_id': 'lag_diagnostic', 'operation_id': 'time_series.correlogram',
                      'spec': {'input_mode': 'frame', 'column_bindings': {'time_col': 't', 'outcome': 'y'},
                               'options': {'max_lag': 24}}}
        earlier = confirm_ask(fixture, fixture.propose([diagnostic]))
        assert earlier.status == 'completed'
    options = {'ar_order': 0, 'differences': 1, 'ma_order': 0, 'deterministic': 'none',
               'forecast_periods': 6, 'holdout_periods': 40, 'confidence_level': .9}
    step = {'step_id': 'forecast', 'operation_id': OPERATION,
            'spec': {'input_mode': 'frame', 'column_bindings': {'time_col': 't', 'outcome': 'y'}, 'options': options}}
    obligation = {'id': 'forecast-delivery', 'covers': [{'criterion_index': 0}], 'operation': step}
    contract = {'playbooks': ['time_series'], 'source': source, 'requirements': [obligation]}
    draft = merge(None, question='Forecast the regular series under the declared ARIMA model.',
                  criteria=['Six periods, 90% prediction intervals, and a chronological 40-period holdout.'],
                  steps=(PlanStep('forecast', 'Run the declared native forecast', (OPERATION,)),),
                  allowed_classes=['derive'], budget={'steps': 6}, completion=contract)
    fixture.orchestrator.plan_store.save('chain-session', draft)
    control = PlanControl(project, fixture.repository, 'chain-session')
    retrospective = case == 'retrospective_approval'
    if not retrospective:
        control.approve(draft.version)
    fixture.orchestrator.execution_mode = 'ask' if retrospective else 'auto'
    fixture.orchestrator.execution_policy = 'auto_read_only'
    authorities = _with_authority_runner(fixture)

    executed_options = {**options, 'confidence_level': .95} if case == 'different_request' else options
    submitted = {**step, 'spec': {**step['spec'], 'options': executed_options}}
    receipt = fixture.propose([submitted])
    if retrospective:
        assert receipt['requires_confirmation'] and not authorities
        record = confirm_ask(fixture, receipt)
        assert record.status == 'completed' and record.execution['research_specification']['reason'] == 'criteria_not_fixed'
        [executed] = fixture.orchestrator.context_provider.executed_workflow_results(record)
        control.approve(fixture.orchestrator.plan_store.current('chain-session').version)
    else:
        assert receipt['executed'] and receipt['operation']['status'] == 'completed', receipt
        assert authorities == ['approved_plan']
        record = fixture.orchestrator.operation_store.get(receipt['operation']['record_id'])
        freeze = record.execution['research_specification']
        if case == 'exploratory_after_diagnostic':
            assert freeze['specification_status'] == 'exploratory'
            assert freeze['reason'] == 'prior_result_on_same_original_data'
        else:
            assert freeze['specification_status'] == 'pre_specified'
        [executed] = receipt['results']
    [artifact] = executed['artifacts']
    ref = {'run_id': fixture.run_id, 'artifact_id': artifact['artifact_id']}
    index = json.loads((run / 'artifacts_index.json').read_bytes())
    [entry] = [item for item in index['artifacts'] if item['artifact_id'] == ref['artifact_id']]
    from workbench.native_research import read_native_result_bytes

    verified_bytes = read_native_result_bytes(run, entry, run / entry['path'], OPERATION)
    assert verified_bytes is not None
    result = json.loads(verified_bytes)
    assert result['request']['options'] == executed_options
    assert result['result']['forecast']['steps'] == options['forecast_periods']
    assert result['result']['policy']['confidence_level'] == executed_options['confidence_level']
    assert result['result']['holdout']['n_observed'] == (0 if case == 'missing_holdout' else options['holdout_periods'])
    assert len(result['local_detail']['forecast']['steps']) == options['forecast_periods']
    assert len(result['local_detail']['holdout_forecast']['steps']) == options['holdout_periods']

    plan = fixture.orchestrator.plan_store.current('chain-session')
    if case == 'unapproved_basis':
        plan = replace(plan, status='draft', approved_version=None, approved_at=None)
    proof_ref = {'run_id': fixture.run_id, 'artifact_id': fixture.artifact_id} if case == 'wrong_artifact' else ref
    evidence = {'results': [ref], 'requirements': [{'requirement_id': obligation['id'],
                'operation_record_id': record.record_id, 'workflow_step_id': step['step_id'], 'artifacts': [proof_ref]}]}
    result = delivery_check(project, replace(plan, completion_evidence=evidence), session_id='chain-session')
    assert result['status'] == 'partial'
    assert any(reason.startswith('time_series:model:') for reason in result['missing'])
    assert result['scientific_validity'] == 'not_certified'
    [criterion] = result['criteria_verification']['requirements']
    if reason is None:
        assert criterion['status'] == 'verified', criterion
        assert criterion['verified_artifacts'] == [{**ref, 'sha256': entry['sha256']}]
    else:
        assert criterion['status'] == 'unverified' and criterion['reason'] == reason, criterion
        assert not criterion['verified_artifacts']
