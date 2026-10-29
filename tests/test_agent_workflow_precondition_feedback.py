"""Generic managed-head conflicts are actionable; internal faults stay opaque."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from workbench.agent.chains import ChainStore
from workbench.agent.context_tools_support.tool_specs import chain_tool_specs
from workbench.agent.operations import OperationRegistry
from workbench.agent.orchestration_proposals import OrchestrationProposals
from workbench.agent.orchestration_tools import OrchestrationTools
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolDefinition, ToolRegistry


class Binding(OrchestrationTools, OrchestrationProposals):
    pass


def binding(tmp_path, snapshot):
    host = Binding()
    host.repository = JsonlSessionRepository(tmp_path/'workbench')
    host.repository.create_session('conversation', chain_id='chain', role='chain')
    ChainStore(host.repository.root).create_root(chain_id='chain', run_family_id='family',
        active_head_run_id='seed-run', agent_session_id='conversation')
    host.context_provider = SimpleNamespace(inspect_node_context=snapshot)
    return host


def arguments(head='branch-run'):
    return {'operation_id':'operation.multi_step','operation_version':'v1',
        'target':{'run_id':'branch-run','node_ref':'stage:cleaned','artifact_id':'cleaned_dataset'},
        'preconditions':{'active_head_run_id':head,'context_version':'node-operation-context/v1',
            'context_fingerprint':'original','owner_resolution':'single_candidate'},
        'changes':{'steps':[{'step_id':'summary','operation_id':'statistical.explore',
            'spec':{'operation':'summarize','selected_columns':['income']}}]},
        'evidence_refs':[],'expected_effect':['Summarize selected data.'],'risks':['No causal inference.']}


def execute(host, submitted):
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id='run_operation',version='v1',side_effect='proposal',
        input_schema=OperationRegistry().proposal_tool_schema(),
        handler=lambda args,ctx:host._bind_workflow_preconditions(args,session_id=ctx.session_id)))
    return asyncio.run(registry.execute({'tool_call_id':'proposal-call','tool_id':'run_operation',
        'arguments':submitted},session_id='conversation'))


def test_branch_as_head_refusal_names_durable_head_and_original_source_without_rebinding(tmp_path):
    def forbidden(request):
        raise AssertionError('conflicting head must not reach source inspection')
    host = binding(tmp_path, forbidden)
    submitted = arguments()
    saved = copy.deepcopy(submitted)
    result = execute(host, submitted)
    assert not result.ok and result.error == 'ToolVisibleError'
    message = result.error_details[0]['message']
    assert 'ACTIVE_HEAD_MISMATCH' in message
    assert 'seed-run' in message and 'branch-run' in message and 'stage:cleaned' in message
    assert 'inspect_node_context' in message and 'owner_run_id' in message
    assert 'active_head_run_id' in message and 'not executed' in message
    read_args, _ = json.JSONDecoder().raw_decode(message.split('inspect_node_context ', 1)[1])
    read_schema = chain_tool_specs(top_level_operation_ids=[])['inspect_node_context']['input_schema']
    Draft202012Validator(read_schema).validate(read_args)
    assert read_args == {'owner_run_id':'branch-run','op_node_id':'stage:cleaned',
                         'active_head_run_id':'seed-run'}
    assert submitted == saved
    assert ChainStore(host.repository.root).resolve_active_head('chain') == 'seed-run'


@pytest.mark.parametrize('phase', ['metadata', 'snapshot'])
def test_unknown_internal_valueerror_is_not_input_feedback_and_has_correlated_local_trace(tmp_path, caplog, phase):
    original = ValueError('private backend failure, not agent input')
    def fail(*args):
        raise original
    host = binding(tmp_path, fail)
    if phase == 'metadata':
        host.repository.get_metadata = fail
    result = execute(host, arguments('seed-run'))
    assert not result.ok and result.error == 'ValueError'
    assert result.error_details is None
    payload = result.to_payload()
    assert payload.get('error_id') and original.args[0] not in str(payload)
    records = [record for record in caplog.records if getattr(record,'error_id',None) == payload['error_id']]
    assert len(records) == 1 and records[0].exc_info[1] is original
    assert records[0].tool_id == 'run_operation' and records[0].tool_call_id == 'proposal-call'


def test_correct_head_still_inspects_exact_original_target(tmp_path):
    seen = []
    def snapshot(request):
        seen.append(request)
        return {'context_version':'node-operation-context/v1','context_fingerprint':'fresh',
                'owner_resolution':'single_candidate','active_head_run_id':'seed-run'}
    submitted = arguments('seed-run')
    result = execute(binding(tmp_path, snapshot), submitted)
    assert result.ok and result.output['target'] == submitted['target']
    assert seen[0].owner_run_id == 'branch-run' and seen[0].op_node_id == 'stage:cleaned'
    assert result.output['preconditions']['context_fingerprint'] == 'fresh'


def test_same_recorded_call_failure_has_identical_replayed_payload_and_local_trace(tmp_path, caplog):
    original = ValueError('private execution detail')
    def fail(request):
        raise original
    host = binding(tmp_path, fail)
    first = execute(host, arguments('seed-run')).to_payload()
    second = execute(host, arguments('seed-run')).to_payload()
    assert first == second
    assert first['error_id'] and original.args[0] not in json.dumps(first)
    matching = [record for record in caplog.records if getattr(record,'error_id',None) == first['error_id']]
    assert len(matching) == 2 and all(record.exc_info[1] is original for record in matching)


def test_error_correlation_separates_call_identity_without_hashing_input_or_private_message():
    registry = ToolRegistry()
    def fail(arguments, context):
        raise ValueError(arguments['private'])
    for tool_id in ('first_tool', 'second_tool'):
        registry.register(ToolDefinition(tool_id=tool_id, version='v1', side_effect='proposal',
            input_schema={'type':'object'}, handler=fail))
    def invoke(session='s1', call='call1', tool='first_tool', private='first private value'):
        return asyncio.run(registry.execute({'tool_call_id':call,'tool_id':tool,
            'arguments':{'private':private}},session_id=session)).to_payload()
    original = invoke()
    assert invoke(private='different input and failure detail') == original
    identities = [invoke(session='s2')['error_id'], invoke(call='call2')['error_id'],
                  invoke(tool='second_tool')['error_id'], original['error_id']]
    assert len(set(identities)) == 4
