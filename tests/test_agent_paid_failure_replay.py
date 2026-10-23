"""Recorded failure inputs plus scripted repairs through real tools; no model success claim."""
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys

import pytest
from workbench.agent.session import JsonlSessionRepository
from fastapi.testclient import TestClient

from tests.test_agent_eval_headless_transport import runner
from tests.test_agent_routes import _config
from workbench.agent.completion import evaluate
from workbench.agent.model import ModelStreamEvent
from workbench.agent.plans import PlanStore, merge, parse_steps
from workbench.agent.runtime_adapter import headless_runtime_scope
from workbench.app import app
from workbench.artifacts import sha256_file
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

CASES = json.loads((Path(__file__).parent/'fixtures/agent_completion_recovery/paid_failure_patterns.json').read_text())


@pytest.fixture(scope='module', params=CASES, ids=lambda case: case['task_id'])
def native_case(tmp_path_factory, request):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
    from agent_eval.tasks import dev_tasks
    case = request.param
    task = next(t for t in dev_tasks() if t.id == case['task_id'])
    folder = tmp_path_factory.mktemp('paid-failure-input')
    csv = folder/'input.csv'; csv.write_text(task.scenario.frame(task.seed).to_csv(index=False))
    assert sha256_file(csv) == case['input_sha256']
    project = create_project(folder, 'recovery')
    options = {
        'iv': [dict(model_type='iv_2sls', y='log_wage', x=x, iv_endog=['education'],
                    iv_instruments=['near_college'], covariance='robust') for x in [['experience'], []]],
        'panel': [dict(model_type='panel_ols', y='productivity', x=['training'],
                       entity_col='firm', time_col='year', covariance='clustered')],
        'survival': [dict(model_type='survival_cox', y='months', x=x,
                         model_options={'event_column': 'event'}) for x in [['drug', 'age'], ['drug']]],
    }[case['playbook']]
    runs = [run_workflow(project.root, [csv], mode='auto', **spec) for spec in options]
    assert all(r['status'] == 'completed' for r in runs), runs
    model_id = {'iv': 'iv_2sls_1', 'panel': 'panel_ols_1', 'survival': 'survival_cox_1'}[case['playbook']]
    refs = [{'run_id': r['run_id'], 'artifact_id': model_id} for r in runs]
    source = {'run_id': runs[0]['run_id'], 'artifact_id': 'cleaned_dataset',
              'sha256': sha256_file(project.root/'runs'/runs[0]['run_id']/'processed/cleaned_dataset.parquet')}
    contract = {'playbooks': [case['playbook']], 'source': source}
    if case['playbook'] == 'panel':
        # A real nonlinear specification, fixed here before its results are
        # computed. Empty time_col auto-detects year, so it is not a distinct FE.
        from workbench.agent.workflow import compile_workflow, execute_workflow
        draft = compile_workflow(workflow_id='fixed-nonlinearity-comparison',
            target={'run_id': source['run_id'], 'node_ref': 'stage:cleaned', 'artifact_id': source['artifact_id']},
            preconditions={'context_fingerprint': 'panel-replay', 'source_artifact_fingerprint': source['sha256']},
            steps=[{'step_id': 'quadratic', 'operation_id': 'model.genesis', 'spec': {
                'model_family': 'panel_ols', 'entity_col': 'firm', 'time_col': 'year',
                'covariance': 'clustered', 'branches': [{'branch_id': 'quadratic',
                    'outcome': 'productivity', 'predictors': ['training'],
                    'polynomials': [{'column': 'training', 'degree': 2}]}]}}],
            available_columns=list(task.scenario.frame(task.seed).columns))
        state = execute_workflow(project.root, draft)
        assert state.status == 'completed', state.to_dict()
        branch = state.steps['quadratic'].model_branches[0]
        refs.append({'run_id': branch['run_id'], 'artifact_id': branch['model_id']})
    initial = {'models': refs if case['playbook'] != 'survival' else refs[:1],
        'diagnostics': [{**refs[0], 'artifact_id': model_id+'.completion'}], 'sensitivity': refs[1:],
        'report': {'run_id': refs[0]['run_id'],
                   'artifact_id': case['recorded_completion_evidence']['report']['artifact_id']}}
    assert evaluate(project.root, contract, initial)['status'] == 'partial'
    return project.root, case, contract, refs, initial


class RepairFromVerifiedBindings:
    """Only provider decisions are scripted; receipts, fitting, approval and reports are real."""
    def __init__(self, case, contract, refs, initial):
        self.case, self.contract, self.refs = case, contract, refs
        self.evidence = copy.deepcopy(initial)
        self.phase = 'draft'; self.requests = []
        self.catalogs = []
        self.config = _config()

    def inspection(self, request):
        message = next(m for m in reversed(request.messages)
                       if m.get('role') == 'tool' and m.get('name') == 'inspect_analysis_completion')
        value = json.loads(message['content'])['output']
        self.catalogs.append(value)
        model = next(m for m in value['evidence_catalog']['models'] if m['ref'] == self.refs[0])
        self.evidence['models'] = [model['ref']]
        self.evidence['diagnostics'] = model['diagnostics']
        reports = [r for r in value['evidence_catalog']['reports'] if r['covers_submitted_evidence']]
        if reports:
            self.evidence['report'] = reports[0]['ref']
        return value

    async def stream(self, request):
        self.requests.append(request)
        if request.response_schema:
            # Fake isolated-review response, not an independent quality score.
            assert not request.tools
            yield ModelStreamEvent.text_delta(request.request_id, json.dumps({'verdict': 'no_issues_found', 'findings': []}))
            yield ModelStreamEvent.done(request.request_id); return
        phase = self.phase
        if phase == 'draft':
            self.phase = 'inspect'
            yield ModelStreamEvent.text_delta(request.request_id, '分析尚有交付缺项。')
            yield ModelStreamEvent.done(request.request_id); return
        if phase in {'inspect', 'after_ar', 'after_report'}:
            self.phase = {'inspect': 'bind', 'after_ar': 'bind_ar', 'after_report': 'bind_report'}[phase]
            tool, arguments = 'inspect_analysis_completion', {}
        elif phase in {'bind', 'bind_ar', 'bind_report'}:
            self.inspection(request)
            self.phase = ('ar' if phase == 'bind' and self.case['playbook'] == 'iv' else
                          'finish' if phase == 'bind_report' else 'report')
            tool, arguments = 'update_plan', {'question': self.case['prompt'],
                'criteria': ['Produce source-bound primary, diagnostics, sensitivity and report.'],
                'steps': [{'step_id': 'analysis', 'title': 'Complete the fixed analysis',
                           'operation_ids': ['model.genesis', 'iv.ar_confidence', 'report.compose']}],
                'completion_evidence': self.evidence}
        elif phase in {'ar', 'report'}:
            source = self.contract['source']
            if phase == 'ar':
                steps = [{'step_id': 'ar', 'operation_id': 'iv.ar_confidence',
                          'spec': {'model_run_id': self.refs[0]['run_id'], 'model_ref': self.refs[0]['artifact_id']}}]
                self.phase = 'after_ar'
            else:
                refs = [{**ref, 'role': role} for role, values in [
                    ('primary', self.evidence['models']), ('diagnostic', self.evidence['diagnostics']),
                    ('sensitivity', self.evidence['sensitivity'])] for ref in values]
                steps = [{'step_id': 'report', 'operation_id': 'report.compose', 'spec': {'result_refs': refs}}]
                self.phase = 'after_report'
            # A real context-tool result supplies the source/approval fingerprint.
            from workbench.agent.context_tools import NodeOperationContextProvider, InspectNodeContextRequest
            context = NodeOperationContextProvider(self.root).inspect_node_context(InspectNodeContextRequest(
                request_id='replay-source', owner_run_id=source['run_id'], op_node_id='stage:cleaned',
                active_head_run_id=source['run_id']))
            tool, arguments = 'run_operation', {'operation_id': 'operation.multi_step', 'operation_version': 'v1',
                'target': {'run_id': source['run_id'], 'node_ref': 'stage:cleaned', 'artifact_id': source['artifact_id']},
                'preconditions': {key: context[key] for key in [
                    'context_version', 'context_fingerprint', 'active_head_run_id', 'owner_resolution']},
                'changes': {'steps': steps}, 'evidence_refs': ['recorded-failure-replay'],
                'expected_effect': ['Complete the missing evidence without refitting'], 'risks': []}
        else:
            yield ModelStreamEvent.text_delta(request.request_id, '分析完成。')
            yield ModelStreamEvent.done(request.request_id); return
        yield ModelStreamEvent.tool_call_delta(request.request_id, {
            'tool_call_id': f'repair-{len(self.requests)}', 'tool_id': tool, 'arguments': arguments})
        yield ModelStreamEvent.done(request.request_id, 'tool_calls')


@pytest.mark.parametrize('mode', ['ask', 'auto'])
def test_recorded_family_failures_recover_via_real_common_tools_without_nudges(native_case, tmp_path, monkeypatch, runner, mode):
    from shutil import copytree
    original, case, contract, refs, initial = native_case
    root = tmp_path/'project'; copytree(original, root)
    adapter = RepairFromVerifiedBindings(case, contract, refs, initial); adapter.root = root
    def forbidden(*args, **kwargs):
        pytest.fail('offline replay attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    with headless_runtime_scope(adapter_factory=lambda config: adapter, config=_config()):
        with TestClient(app, base_url='http://127.0.0.1') as client:
            params = {'project_root': str(root)}
            response = client.post('/agent/sessions', params=params, json={'role': 'chain',
                'chain_id': f"run:{contract['source']['run_id']}", 'run_id': contract['source']['run_id'],
                'context_packet': {}, 'focus': {'kind': 'node', 'id': 'stage:cleaned',
                    'run_id': contract['source']['run_id'], 'label': 'Fixed analysis source'}})
            assert response.status_code == 200, response.text
            session = response.json()['session_id']; store = PlanStore(root/'workbench')
            store.save(session, merge(None, question=case['prompt'],
                criteria=['Produce source-bound primary, diagnostics, sensitivity and report.'],
                steps=parse_steps([{'step_id': 'analysis', 'title': 'Complete the fixed analysis',
                    'operation_ids': ['model.genesis', 'iv.ar_confidence', 'report.compose']}],
                    {'model.genesis', 'iv.ar_confidence', 'report.compose'}),
                budget=None, allowed_classes=None, completion=contract, completion_evidence=initial))
            result = runner._turn(client, root, session, case['prompt'], 'proposal_only', mode, transport='headless')
            confirmations = 0; approvals = 0
            for _ in range(5):
                if mode == 'auto' and runner._approve_plan_if_waiting(client, root, session):
                    approvals += 1
                else:
                    pending = runner._pending_proposals(client, root, session)
                    if not pending:
                        break
                    head = runner._active_head(client, root, session, contract['source']['run_id'])
                    for proposal in pending:
                        receipt = runner._confirm(client, root, session, head, proposal)
                        assert receipt['status'] == 'completed', receipt
                        confirmations += 1
                result = runner._turn(client, root, session, None, 'proposal_only', mode, transport='headless')
            plan = store.current(session)
            checked = evaluate(root, plan.completion, plan.completion_evidence)
            assert checked['status'] == 'requirements_met', (checked['missing'], result, adapter.phase)
            assert '分析完成' in result['reply']
            assert confirmations == ((2 if case['playbook'] == 'iv' else 1) if mode == 'ask'
                                     else (1 if case['playbook'] == 'iv' else 0))
            assert approvals == (1 if mode == 'auto' else 0)
            if mode == 'ask':
                # v1.9.1: the confirmation's result message carries the delivery check.
                told = [entry.payload['content'] for entry in JsonlSessionRepository(root/'workbench').get_branch(session)
                        if entry.entry_type == 'custom_message' and entry.payload.get('name') == 'workbench_operation_result']
                assert told and all('Delivery check after this operation' in content for content in told)
            from workbench.agent.operations import OperationRecordStore
            # Child receipts retain their parent's workflow authority; count
            # the user/plan authorization once, on the enclosing proposal.
            records = [record for record in OperationRecordStore(root/'workbench', create=False).list_records()
                       if record.operation_id == 'operation.multi_step']
            assert len(records) == (2 if case['playbook'] == 'iv' else 1)
            assert all(record.status == 'completed' for record in records)
            assert sum(record.actor_type == 'user' for record in records) == confirmations
            assert all(record.actor_type in {'user', 'approved_plan'} for record in records)
            # The recorded report id lacked its format suffix; the gate drops it, names it, and
            # binds the composed report that covers the evidence (no second update_plan).
            assert adapter.catalogs and adapter.catalogs[-1]['status'] == 'requirements_met'
            assert 'report' in adapter.catalogs[-1]['bound_by_workbench']
            assert plan.completion == contract
