"""A missing sensitivity fit comes with fits the Agent can propose as given (free-route round off3, 2026-10-22).

iv_weak.goal reported iv:sensitivity:distinct_point_estimation 28 times with no
repair step; leverage.goal composed its report three times and never refitted
without its high-influence rows. Both ended on the nudge budget. The options are
derived from the primary's own specification and validated before they are
offered; replayed on the recorded leverage project, the influence refit gave the
generator's clean-row slope (1.2764 for 1.276) and the gate then asked only for
the report.
"""
import asyncio
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from tests.operation_request_fixtures import admit_proposal
from tests.test_agent_workflow_integration import IdleAdapter
from workbench.agent.completion import derive_evidence, evaluate
from workbench.agent.completion_sensitivity import influence_option, primary_specification, specification_options


def _leverage_frame():
    rng = np.random.default_rng(7)
    x = rng.normal(10, 2, 80)
    y = 5 + 1.0 * x + rng.normal(0, 2, 80)
    x[:3], y[:3] = [30, 32, 35], [5, 4, 6]
    return pd.DataFrame({'city': [f'city_{i}' for i in range(80)], 'density': x.round(3), 'rent': y.round(3)})


def _fit(tmp_path, frame):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    project = create_project(tmp_path, 'leverage')
    source = tmp_path / 'leverage.csv'
    frame.to_csv(source, index=False)
    result = run_workflow(project.root, [source], mode='auto', model_type='ols', y='rent', x=['density'],
                          covariance='robust')
    assert result['status'] == 'completed', result
    run_id = result['run_id']
    data = project.root / 'runs' / run_id / 'processed/cleaned_dataset.parquet'
    contract = {'playbooks': ['ols'], 'source': {'run_id': run_id, 'artifact_id': 'cleaned_dataset',
                                                'sha256': hashlib.sha256(data.read_bytes()).hexdigest()}}
    return project.root, run_id, contract


@pytest.fixture
def fitted(tmp_path):
    return _fit(tmp_path, _leverage_frame())


def _check(project, contract):
    evidence, notes = derive_evidence(project, contract, None)
    return evaluate(project, contract, evidence, options=True), notes


def test_the_offered_influence_refit_meets_both_sensitivity_requirements(fitted, tmp_path):
    project, run_id, contract = fitted
    checked, notes = _check(project, contract)
    assert {'ols:sensitivity:distinct_point_estimation', 'ols:sensitivity:influence_sample_comparison'} <= set(checked['missing'])
    option = checked['sensitivity_options'][0]
    subset, refit = option['workflow']['steps']
    (rule,) = subset['spec']['filters']
    diagnostic = json.loads((project / 'runs' / run_id / 'model_results/diagnostics_ols_1.json').read_text())['cooks_distance']
    # The rows the fit's own diagnostic counts, named by the column that identifies them.
    assert rule['column'] == 'city' and rule['op'] == 'not_in' and len(rule['value']) == diagnostic['n_high']
    assert {'city_0', 'city_1', 'city_2'} <= set(rule['value'])
    assert refit['spec']['branches'][0]['predictors'] == ['density'] and refit['spec']['covariance'] == 'robust'

    assert _run_option(project, run_id, option, tmp_path).status == 'completed'
    checked, notes = _check(project, contract)
    # The refit on the subset is a variant of the fit on the source, which stays primary.
    assert checked['missing'] == ['report:registered_nonempty'], checked['missing']
    assert 'ols:primary' in notes['bound_by_workbench'] and 'sensitivity_options' not in checked


def _run_option(project, run_id, option, tmp_path):
    async def run_option():
        from workbench.agent.chains import ChainStore
        from workbench.agent.context_tools import NodeOperationContextProvider
        from workbench.agent.core import AgentCore
        from workbench.agent.events import AgentEventStream
        from workbench.agent.orchestrator import WorkbenchOrchestrator
        from workbench.agent.session import JsonlSessionRepository

        workbench_root = tmp_path / 'agent-workbench'
        repository = JsonlSessionRepository(workbench_root)
        repository.create_session('main-session', chain_id='project', role='main')
        repository.create_session('chain-session', chain_id='chain-a', role='chain')
        events = AgentEventStream(workbench_root)
        orchestrator = WorkbenchOrchestrator(repository, events, main_session_id='main-session',
                                             context_provider=NodeOperationContextProvider(project))
        orchestrator.register_chain('chain-a', 'chain-session', AgentCore(repository, events, IdleAdapter(), session_id='chain-session'))
        ChainStore(workbench_root).create_root(chain_id='chain-a', run_family_id='family', active_head_run_id=run_id,
                                               agent_session_id='chain-session')
        target = dict(option['workflow']['target'], artifact_id='cleaned_dataset')
        fingerprint = 'nocv1:offered'
        proposal = admit_proposal(orchestrator, chain_id='chain-a', operation_id='operation.multi_step', target=target,
            preconditions={'context_version': 'node-operation-context/v1', 'context_fingerprint': fingerprint,
                           'active_head_run_id': run_id, 'owner_resolution': 'single_candidate'},
            changes={'steps': option['workflow']['steps']}, evidence_refs=['diagnostics_ols_1'],
            expected_effect=['refit without high-influence rows'], risks=['smaller sample'])
        record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
            actor_type='user', current_context_fingerprint=fingerprint, current_active_head_run_id=run_id)
        return await orchestrator.execute_confirmed_operation(record.record_id, project_root=project,
            current_context_fingerprint=fingerprint, current_active_head_run_id=run_id)

    return asyncio.run(run_option())


def _write_form(project, run_id, **form):
    path = project / 'runs' / run_id / 'run_inputs.json'
    inputs = json.loads(path.read_text())
    path.write_text(json.dumps({**inputs, 'form': {**inputs['form'], **form}}))


def test_each_option_drops_one_predictor_and_never_the_focal_one(fitted):
    project, run_id, _ = fitted
    _write_form(project, run_id, model_type='iv_2sls', x='age,city_size,coast', iv_endog='["density"]',
                iv_instruments='["rainfall"]', focal_x='coast')
    spec, focal = primary_specification(project, run_id)
    assert spec['iv_endog'] == ['density'] and spec['iv_instruments'] == ['rainfall'] and focal == ['coast']
    options = specification_options(project, {'run_id': run_id, 'artifact_id': 'ols_1'}, {'model_id': 'ols_1'})
    kept = [option['workflow']['steps'][0]['spec']['branches'][0]['predictors'] for option in options]
    assert kept == [['city_size', 'coast'], ['age', 'coast']]
    assert all(option['workflow']['target']['node_ref'] == 'stage:cleaned' for option in options)


def test_a_specification_it_cannot_copy_exactly_gets_no_options(fitted):
    project, run_id, _ = fitted
    _write_form(project, run_id, weights='population')
    assert primary_specification(project, run_id) is None
    assert specification_options(project, {'run_id': run_id, 'artifact_id': 'ols_1'}, {'model_id': 'ols_1'}) == []


def test_rows_are_named_by_an_identifying_column_or_else_by_position(fitted):
    project, run_id, _ = fitted
    path = next((project / 'runs' / run_id / 'processed').glob('cleaned_dataset.*'))
    frame = pd.read_parquet(path).assign(city='same')
    frame.to_parquet(path)
    index = project / 'runs' / run_id / 'artifacts_index.json'
    data = json.loads(index.read_text())
    for item in data['artifacts']:
        if item.get('path') == str(path.relative_to(project / 'runs' / run_id)):
            item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index.write_text(json.dumps(data))
    # Without an identifying column the rows are named by position (Hy3 Auto iv_weak looped on no option).
    option = influence_option(project, {'run_id': run_id, 'artifact_id': 'ols_1'}, {'model_id': 'ols_1'}, 0.05)
    subset = option['workflow']['steps'][0]['spec']
    assert 'filters' not in subset and subset['columns'] == ['rent', 'density']
    assert {0, 1, 2} <= set(subset['exclude_row_indices']) and 'zero-based rows: 0, 1, 2' in option['label']


def test_a_refit_the_data_rules_out_becomes_a_disclosure_not_a_loop(fitted, monkeypatch):
    project, run_id, contract = fitted
    monkeypatch.setattr('workbench.agent.completion_sensitivity.MAX_INFLUENCE_ROWS', 10)
    checked, _ = _check(project, contract)
    assert 'ols:sensitivity:influence_sample_comparison' not in checked['missing']
    assert checked['disclosures'] == [{'requirement': 'ols:sensitivity:influence_sample_comparison',
                                       'reason': 'rows_above_limit', 'action': checked['disclosures'][0]['action']}]
    assert 'ols:sensitivity:distinct_point_estimation' in checked['missing']


def test_the_offered_positional_refit_meets_the_influence_requirement(tmp_path):
    project, run_id, contract = _fit(tmp_path, _leverage_frame().drop(columns='city'))
    checked, _ = _check(project, contract)
    option = checked['sensitivity_options'][0]
    assert option['workflow']['steps'][0]['spec']['exclude_row_indices'][:3] == [0, 1, 2]
    assert _run_option(project, run_id, option, tmp_path).status == 'completed'
    checked, _ = _check(project, contract)
    assert checked['missing'] == ['report:registered_nonempty'], checked['missing']
