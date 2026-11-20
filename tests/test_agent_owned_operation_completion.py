"""The ordinary Agent runner owns observation until a submitted effect settles."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from workbench.agent import plans
from workbench.agent.chains import ChainStore
from workbench.agent.context_tools import InspectNodeContextRequest, NodeOperationContextProvider
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.events import get_event_manager
from workbench.http.agent_operation_routes import _run_read_only_proposal
from workbench.projects import create_project
from workbench.services import run_service
from workbench.services.rerun_service import RerunService


async def _wait_idle(run_id):
    async def wait():
        while get_event_manager().is_active(run_id):
            await asyncio.sleep(.01)
    await asyncio.wait_for(wait(), 20)


class RerunThenRead:
    def __init__(self, run_id):
        self.run_id = run_id
        self.requests = []
        self.first_status = None
        self.child_run_id = None
        self.coefficients = None

    async def stream(self, request):
        self.requests.append(request)
        number = len(self.requests)
        messages = [json.loads(item['content']) for item in request.messages if item.get('role') == 'tool']
        identity = {'request_id': f'read-{number}', 'owner_run_id': self.run_id,
                    'op_node_id': 'model:ols_1', 'active_head_run_id': self.run_id}
        if number == 1:
            snapshot = self.snapshot
            tool, arguments = 'run_operation', {
                'operation_id': 'model.rerun', 'operation_version': 'v1',
                'target': {'run_id': self.run_id, 'node_ref': 'model:ols_1',
                    'node_hash': snapshot['node_hash'], 'forest_node_key': snapshot['forest_node_key']},
                'preconditions': {key: snapshot[key] for key in
                    ('context_version', 'context_fingerprint', 'active_head_run_id', 'owner_resolution')},
                'changes': {'model_options': {'covariance': 'unadjusted'}},
                'evidence_refs': ['model:ols_1'], 'expected_effect': ['Fit the declared reduced model.'], 'risks': [],
            }
        elif number == 2:
            self.first_status = messages[-1]['output']['operation']['status']
            if self.first_status != 'completed':
                yield ModelStreamEvent.text_delta(request.request_id, 'The operation is not yet verified.')
                yield ModelStreamEvent.done(request.request_id)
                return
            # A rerun has no workflow_state; discover its child through the
            # completed parent receipt, then use the existing coefficient tool.
            assert messages[-1]['output']['results'] == []
            tool, arguments = 'inspect_completed_operations', identity
        elif number == 3:
            records = messages[-1]['output']['completed_operations']
            assert len(records) == 1
            self.child_run_id = records[0]['produced_run_id']
            tool, arguments = 'inspect_project_model_coefficients', {
                'run_ids': [self.child_run_id], 'terms': ['x1']}
        else:
            self.coefficients = messages[-1]
            yield ModelStreamEvent.text_delta(request.request_id, 'The declared model and its evidence are available.')
            yield ModelStreamEvent.done(request.request_id)
            return
        yield ModelStreamEvent.tool_call_delta(request.request_id, {
            'tool_call_id': f'call-{number}', 'tool_id': tool, 'arguments': arguments})
        yield ModelStreamEvent.done(request.request_id, finish_reason='tool_calls')


def _runtime(tmp_path, monkeypatch):
    root = create_project(tmp_path, 'owned-operation').root
    rows = ['y,x1,x2']
    for index in range(2000):
        x1, x2 = index / 20, index % 7
        rows.append(f'{3 + 2*x1 + .3*x2 + (index % 5 - 2)*.01},{x1},{x2}')
    manager = get_event_manager()
    assert manager.try_acquire_slot()
    parent = run_service._submit_run(root,
        form={'mode': 'auto', 'model_type': 'ols', 'y': 'y', 'x': 'x1,x2'},
        upload_bytes=('\n'.join(rows)+'\n').encode(), upload_filename='source.csv',
        started_at=datetime.now(timezone.utc).isoformat())['run_id']
    asyncio.run(_wait_idle(parent))
    assert json.loads((root/'runs'/parent/'run_manifest.json').read_text())['status'] == 'completed'
    repository = JsonlSessionRepository(root/'workbench')
    repository.create_session('main', chain_id='project', role='main')
    repository.create_session('agent', chain_id='source-chain', role='chain')
    adapter = RerunThenRead(parent)
    agent = AgentCore(repository, AgentEventStream(repository.root), adapter, session_id='agent')
    orchestrator = WorkbenchOrchestrator(repository, agent.events, main_session_id='main',
        context_provider=NodeOperationContextProvider(root))
    orchestrator.register_chain('source-chain', 'agent', agent)
    ChainStore(repository.root).create_root(chain_id='source-chain', run_family_id='family',
        active_head_run_id=parent, agent_session_id='agent')
    adapter.snapshot = orchestrator.context_provider.inspect_node_context(InspectNodeContextRequest(
        request_id='source', owner_run_id=parent, op_node_id='model:ols_1', active_head_run_id=parent))
    orchestrator.execution_mode = 'auto'
    orchestrator.execution_policy = 'auto_read_only'
    plan = plans.merge(None, question='Fit the declared reduced model.', criteria=[],
        steps=(plans.PlanStep('rerun', 'Reduced model', ('model.rerun',)),),
        budget={'steps': 1}, allowed_classes=None)
    orchestrator.plan_store.save('agent', plans.approve(plan))
    orchestrator.read_only_runner = lambda proposal, actor=None: _run_read_only_proposal(root, orchestrator, proposal, actor)
    submitted = []
    original = RerunService.submit
    def submit(service, request):
        result = original(service, request)
        submitted.append(result.run_id)
        return result
    monkeypatch.setattr(RerunService, 'submit', submit)
    confirmations = []
    confirm = orchestrator.confirm_proposal
    def confirm_once(*args, **kwargs):
        record = confirm(*args, **kwargs)
        confirmations.append(record.record_id)
        return record
    monkeypatch.setattr(orchestrator, 'confirm_proposal', confirm_once)
    return SimpleNamespace(root=root, parent=parent, repository=repository, agent=agent,
        orchestrator=orchestrator, adapter=adapter, submitted=submitted, confirmations=confirmations)


def test_rerun_tool_binds_minimal_request_and_refuses_stale_head(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    orchestrator = runtime.orchestrator
    orchestrator.execution_mode = "ask"
    registry = orchestrator.tool_registry("source-chain")
    arguments = {
        "operation_id": "model.rerun",
        "target": {"run_id": runtime.parent, "node_ref": "model:ols_1"},
        "preconditions": {"active_head_run_id": runtime.parent},
        "changes": {"model_options": {"covariance": "unadjusted"}},
        "evidence_refs": ["model:ols_1"], "expected_effect": ["Fit the model."], "risks": [],
    }

    def request(call_id, preconditions):
        return asyncio.run(registry.execute({
            "tool_id": "run_operation", "tool_call_id": call_id,
            "arguments": {**arguments, "preconditions": preconditions},
        }, session_id="agent"))

    receipt = request("minimal-rerun", arguments["preconditions"])
    assert receipt.ok and receipt.output["requires_confirmation"], receipt
    proposal = receipt.output["proposal"]
    snapshot = runtime.adapter.snapshot
    for field in ("active_head_run_id", "context_version", "context_fingerprint", "owner_resolution"):
        assert proposal["preconditions"][field] == snapshot[field]
    for field in ("node_hash", "forest_node_key"):
        assert proposal["target"][field] == snapshot[field]
    [published] = orchestrator.proposal_store.proposals_dir.glob("*.jsonl")

    assert request("missing-head", {}).error == "invalid_tool_arguments"
    assert not request("stale-head", {"active_head_run_id": "old-head"}).ok
    assert list(orchestrator.proposal_store.proposals_dir.glob("*.jsonl")) == [published]
    assert not runtime.submitted


def test_auto_rerun_returns_verified_parent_before_agent_reads_its_child(tmp_path, monkeypatch, record_property):
    runtime = _runtime(tmp_path, monkeypatch)
    try:
        asyncio.run(runtime.agent.prompt('Fit the declared reduced model.', budget={'max_steps': 6, 'timeout_s': 30}))
    finally:
        for child in runtime.submitted:
            asyncio.run(_wait_idle(child))
    assert len(runtime.submitted) == 1
    child = runtime.submitted[0]
    assert json.loads((runtime.root/'runs'/child/'run_manifest.json').read_text())['status'] == 'completed'
    assert runtime.adapter.first_status == 'completed'
    [record] = runtime.orchestrator.operation_store.list_records()
    assert record.status == 'completed' and record.verification['passed'] is True
    assert record.effect_status == 'committed' and record.projection_status == 'complete'
    assert record.execution['bindings']['child_run_id'] == child == runtime.adapter.child_run_id
    assert runtime.confirmations == [record.record_id]
    assert runtime.adapter.coefficients['ok'] is True
    [public_model] = runtime.adapter.coefficients['output']['models']
    [public_coefficient] = public_model['coefficients']
    result_path = runtime.root/'runs'/child/'model_results/ols_1.json'
    persisted = json.loads(result_path.read_text())['coefficients']['x1']
    assert public_model['run_id'] == child and public_coefficient['source_id'] == persisted['source_id']
    numbers = ('estimate', 'std_error', 'p_value', 'ci_lower', 'ci_upper')
    bits = {field: float(public_coefficient[field]).hex() for field in numbers}
    assert bits == {field: float(persisted[field]).hex() for field in numbers}
    assert len(runtime.adapter.requests) == 4
    assert runtime.orchestrator.plan_store.current('agent').steps[0].status == 'done'
    record_property('producer_result_sha256', hashlib.sha256(result_path.read_bytes()).hexdigest())
    record_property('public_coefficient_binary64', json.dumps(bits, sort_keys=True))
    record_property('initial_submit_count', len(runtime.submitted))
    record_property('original_confirmation_count', len(runtime.confirmations))


def _run_reduced_model(runtime):
    return asyncio.run(runtime.orchestrator.tool_registry('source-chain').execute({
        'tool_id': 'run_operation', 'tool_call_id': 'rerun', 'arguments': {
            'operation_id': 'model.rerun',
            'target': {'run_id': runtime.parent, 'node_ref': 'model:ols_1'},
            'preconditions': {'active_head_run_id': runtime.parent},
            'changes': {'model_options': {'covariance': 'unadjusted'}},
            'evidence_refs': ['model:ols_1'], 'expected_effect': [], 'risks': [],
        },
    }, session_id='agent'))


@pytest.mark.parametrize('changed', ['form', 'filename', 'upload'])
def test_auto_rerun_dispatch_refuses_changed_saved_inputs(tmp_path, monkeypatch, changed):
    from workbench.lineage.upload_store import store_upload_bytes

    runtime = _runtime(tmp_path, monkeypatch)
    parent_inputs = runtime.root / 'runs' / runtime.parent / 'run_inputs.json'
    submit = RerunService.submit

    def change_saved_inputs(service, request):
        inputs = json.loads(parent_inputs.read_text())
        if changed == 'form':
            inputs['form']['x'] = 'x2'
        elif changed == 'filename':
            inputs['upload']['filename'] = 'renamed.csv'
        else:
            upload = runtime.root / 'data' / 'uploads' / inputs['upload']['sha256']
            other = b'y,x1,x2\n100,0,0\n' + b'\n'.join(upload.read_bytes().splitlines()[2:]) + b'\n'
            inputs['upload']['sha256'] = store_upload_bytes(runtime.root, other, filename='source.csv')
        parent_inputs.write_text(json.dumps(inputs))
        return submit(service, request)

    monkeypatch.setattr(RerunService, 'submit', change_saved_inputs)
    result = _run_reduced_model(runtime)
    assert result.ok and result.output['operation']['status'] == 'failed', result
    [record] = runtime.orchestrator.operation_store.list_records()
    assert 'rerun_input_fingerprint' in record.preconditions and not runtime.submitted
    assert runtime.orchestrator.plan_store.current('agent').status == 'approved'


def test_an_auto_plan_cannot_authorize_an_upload_already_replaced_before_admission(tmp_path, monkeypatch):
    from dataclasses import replace
    from workbench.agent.completion import source_receipt
    from workbench.lineage.upload_store import store_upload_bytes

    runtime = _runtime(tmp_path, monkeypatch)
    source = source_receipt(runtime.root, {'run_id': runtime.parent, 'artifact_id': 'cleaned_dataset'})
    assert source is not None
    store = runtime.orchestrator.plan_store
    store.update('agent', lambda plan: replace(plan, completion={'scope': 'question', 'playbooks': [], 'source': source}))
    parent_inputs = runtime.root / 'runs' / runtime.parent / 'run_inputs.json'
    inputs = json.loads(parent_inputs.read_text())
    upload = runtime.root / 'data' / 'uploads' / inputs['upload']['sha256']
    other = b'y,x1,x2\n100,0,0\n' + b'\n'.join(upload.read_bytes().splitlines()[2:]) + b'\n'
    inputs['upload']['sha256'] = store_upload_bytes(runtime.root, other, filename='source.csv')
    parent_inputs.write_text(json.dumps(inputs))

    result = _run_reduced_model(runtime)
    assert result.ok and result.output.get('requires_confirmation'), result
    assert 'approved plan' in result.output['confirmation_reason']
    assert not runtime.confirmations and not runtime.submitted


def test_rerun_dispatch_consumes_the_same_bytes_it_verified(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    parent_inputs = runtime.root / 'runs' / runtime.parent / 'run_inputs.json'
    original_sha = json.loads(parent_inputs.read_text())['upload']['sha256']
    upload = runtime.root / 'data' / 'uploads' / original_sha
    dispatch_reads = []
    submit = RerunService.submit
    read = Path.read_bytes

    def read_blob(path):
        data = read(path)
        if path == upload:
            dispatch_reads.append(path)
            if len(dispatch_reads) > 1:
                return b'y,x1,x2\n100,0,0\n' + b'\n'.join(data.splitlines()[2:]) + b'\n'
        return data

    def submit_once(service, request):
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'read_bytes', read_blob)
            return submit(service, request)

    monkeypatch.setattr(RerunService, 'submit', submit_once)
    result = _run_reduced_model(runtime)
    assert result.ok and result.output['operation']['status'] == 'completed', result
    [run_id] = runtime.submitted
    child = runtime.root / 'runs' / run_id
    assert dispatch_reads == [upload]
    assert json.loads((child / 'run_inputs.json').read_text())['upload']['sha256'] == original_sha
    assert hashlib.sha256((child / 'raw_snapshot' / 'source.csv').read_bytes()).hexdigest() == original_sha


def test_completed_child_is_reconciled_after_durable_history_rehydration(tmp_path, monkeypatch):
    from workbench import events

    runtime = _runtime(tmp_path, monkeypatch)
    original = runtime.orchestrator.execute_confirmed_operation
    calls = []
    async def execute(record_id, **kwargs):
        calls.append((record_id, kwargs.get('allow_recovery', False)))
        record = await original(record_id, **kwargs)
        if len(calls) == 1:
            await _wait_idle(runtime.submitted[0])
            # A fresh event window has no process-local history. The ordinary
            # register_run path must rehydrate the producer's durable log.
            monkeypatch.setattr(events, '_event_manager', events.EventManager())
        return record
    monkeypatch.setattr(runtime.orchestrator, 'execute_confirmed_operation', execute)
    asyncio.run(runtime.agent.prompt('Fit the declared reduced model.', budget={'max_steps': 6, 'timeout_s': 30}))
    [record] = runtime.orchestrator.operation_store.list_records()
    assert runtime.adapter.first_status == record.status == 'completed'
    assert record.verification['passed'] is True
    assert calls == [(record.record_id, False), (record.record_id, True)]
    assert len(runtime.submitted) == 1 and runtime.confirmations == [record.record_id]


@pytest.mark.parametrize('reason', ['abort', 'timeout'])
def test_owner_stop_keeps_pending_parent_for_original_record_takeover(tmp_path, monkeypatch, reason):
    runtime = _runtime(tmp_path, monkeypatch)
    manager = get_event_manager()
    release = threading.Event()
    observed = None
    original_workflow = run_service._run_workflow
    def held_workflow(*args, **kwargs):
        assert release.wait(20), 'test did not release its real child worker'
        return original_workflow(*args, **kwargs)
    monkeypatch.setattr(run_service, '_run_workflow', held_workflow)
    subscribe = manager.subscribe
    def subscription(run_id):
        result = subscribe(run_id)
        observed.set()
        return result
    monkeypatch.setattr(manager, 'subscribe', subscription)

    async def exercise():
        nonlocal observed
        observed = asyncio.Event()
        task = asyncio.create_task(runtime.agent.prompt('Fit the declared reduced model.',
            budget={'max_steps': 6, 'timeout_s': 30}))
        try:
            await asyncio.wait_for(observed.wait(), 10)
            command_id = runtime.agent._active_command_id
            budget = runtime.agent._budget
            if reason == 'abort':
                await runtime.agent.abort()
            else:
                # This is the existing command-wall timer callback, without a
                # latency assertion or a new timeout introduced by the runner.
                runtime.agent._mark_timeout()
            assert runtime.agent._budget == budget
            await task
            [record] = runtime.orchestrator.operation_store.list_records()
            assert record.status == 'running' and record.verification == {}
            assert record.effect_status == record.projection_status == 'pending'
            confirmation = record.to_dict()['confirmation']
            approval_id = record.execution['approval_id']
            child = record.execution['bindings']['child_run_id']
            assert not manager._subscribers[child]
            messages = [json.loads(entry.payload['content'])
                for entry in runtime.repository.get_branch('agent')
                if entry.entry_type == 'message' and entry.payload.get('role') == 'tool']
            assert messages[-1]['error'] == ('agent_aborted' if reason == 'abort' else 'agent_timeout')
            release.set()
            await _wait_idle(child)
            # Reopen the original stores, retaining approval and operation id;
            # recovery must observe this child rather than submit another one.
            repository = JsonlSessionRepository(runtime.root/'workbench')
            restored = WorkbenchOrchestrator(repository, AgentEventStream(repository.root),
                main_session_id='main', context_provider=NodeOperationContextProvider(runtime.root))
            completed = await restored.execute_confirmed_operation(record.record_id,
                project_root=runtime.root, allow_recovery=True,
                current_context_fingerprint=record.preconditions['context_fingerprint'],
                current_active_head_run_id=record.preconditions['active_head_run_id'])
            assert completed.status == 'completed' and completed.verification['passed'] is True
            assert completed.to_dict()['confirmation'] == confirmation
            assert completed.execution['approval_id'] == approval_id
            assert completed.command_id == command_id
            assert len(runtime.submitted) == 1 and runtime.confirmations == [record.record_id]
            # Domain recovery never rewrites the original cancelled tool return.
            assert [json.loads(entry.payload['content']) for entry in repository.get_branch('agent')
                if entry.entry_type == 'message' and entry.payload.get('role') == 'tool'] == messages
        finally:
            release.set()
            if not task.done():
                await runtime.agent.abort()
                await task
            for child in runtime.submitted:
                await _wait_idle(child)
    asyncio.run(exercise())


def test_actual_child_failure_finalizes_parent_without_results(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError('recorded child computation failure')
    monkeypatch.setattr(run_service, '_run_workflow', fail)
    try:
        asyncio.run(runtime.agent.prompt('Fit the declared reduced model.', budget={'max_steps': 6, 'timeout_s': 30}))
    finally:
        for child in runtime.submitted:
            asyncio.run(_wait_idle(child))
    [record] = runtime.orchestrator.operation_store.list_records()
    assert runtime.adapter.first_status == record.status == 'failed'
    assert record.error['type'] == 'ChildRunFailed' and record.verification['passed'] is False
    assert record.effect_status == 'failed' and record.projection_status == 'complete'
    assert len(runtime.submitted) == 1 and runtime.confirmations == [record.record_id]


def test_completed_event_cannot_bypass_original_child_provenance(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    original = runtime.orchestrator.execute_confirmed_operation
    async def execute(record_id, **kwargs):
        record = await original(record_id, **kwargs)
        if not kwargs.get('allow_recovery'):
            child = runtime.submitted[0]
            await _wait_idle(child)
            path = runtime.root/'runs'/child/'run_inputs.json'
            inputs = json.loads(path.read_text())
            inputs['workbench_context']['fork_id'] = 'different-fork'
            path.write_text(json.dumps(inputs))
        return record
    monkeypatch.setattr(runtime.orchestrator, 'execute_confirmed_operation', execute)
    asyncio.run(runtime.agent.prompt('Fit the declared reduced model.', budget={'max_steps': 6, 'timeout_s': 30}))
    [record] = runtime.orchestrator.operation_store.list_records()
    child = runtime.submitted[0]
    assert json.loads((runtime.root/'runs'/child/'run_manifest.json').read_text())['status'] == 'completed'
    assert runtime.adapter.first_status == record.status == 'failed'
    assert record.verification['passed'] is False
    assert record.verification['checks']['workbench_context'] is False
    assert record.error['type'] == 'VerificationFailed'
    assert len(runtime.submitted) == 1 and runtime.confirmations == [record.record_id]


@pytest.mark.parametrize('status', ['completed', 'submitted'], ids=['terminal-genesis', 'pending-without-child'])
def test_common_runner_preserves_terminal_or_unbound_record(tmp_path, monkeypatch, status):
    from workbench import events
    from workbench.http import agent_operation_routes as routes

    monkeypatch.setattr(routes, '_authoritative_active_head', lambda *args, **kwargs: 'source')
    monkeypatch.setattr(routes, '_current_proposal_context_fingerprint', lambda *args, **kwargs: 'fingerprint')
    def forbidden(*args, **kwargs):
        pytest.fail('a terminal genesis or an unbound pending record has no child event to await')
    monkeypatch.setattr(events, 'get_event_manager', forbidden)
    record = SimpleNamespace(record_id='original-record', status=status,
        to_dict=lambda: {'outputs': {}, 'execution': {}})
    calls = []
    def confirm(*args, **kwargs):
        calls.append('confirm')
        return record
    async def execute(record_id, **kwargs):
        assert record_id == record.record_id and 'allow_recovery' not in kwargs
        calls.append('execute')
        return record
    orchestrator = SimpleNamespace(confirm_proposal=confirm, execute_confirmed_operation=execute)
    proposal = SimpleNamespace(chain_id='chain', preconditions={'active_head_run_id': 'source'},
        proposal_id='proposal', revision=1, fingerprint='proposal-fingerprint')
    assert asyncio.run(_run_read_only_proposal(tmp_path, orchestrator, proposal)) is record
    assert calls == ['confirm', 'execute']
