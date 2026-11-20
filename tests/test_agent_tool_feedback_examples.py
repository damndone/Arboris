"""F4 format failures get schema-valid examples without rewriting requests."""
import asyncio
import copy
import json

import pytest

from jsonschema import Draft202012Validator
from workbench.agent.operations import OperationRegistry
from workbench.agent.tools import ToolDefinition, ToolRegistry


def request():
    return {'operation_id':'model.rerun','operation_version':'v1',
        'target':{'run_id':'r1','node_ref':'model:lmm','node_hash':'hash','forest_node_key':'node'},
        'preconditions':{'context_version':'node-operation-context/v1','context_fingerprint':'source',
            'active_head_run_id':'r1','owner_resolution':'single_candidate'},
        'changes':{'model_type':'linear_mixed_effects','model_options':{'old':'literal option','new':'literal option'}},
        'evidence_refs':[],'expected_effect':['Refit the declared model.'],'risks':['Model uncertainty may change.']}


def execute(arguments):
    schema = OperationRegistry().proposal_tool_schema()
    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id='run_operation',version='v1',input_schema=schema,
        side_effect='proposal',handler=lambda args,ctx:calls.append(args)))
    result = asyncio.run(registry.execute({'tool_call_id':'bad','tool_id':'run_operation','arguments':arguments},session_id='s'))
    assert calls == []
    return result, schema


def test_m0_old_new_model_type_gets_a_valid_shape_example_not_an_execution():
    original = request()
    assert Draft202012Validator(OperationRegistry().proposal_tool_schema()).is_valid(original)
    original['changes']['model_type'] = {'old':'linear_mixed_effects','new':'linear_mixed_effects'}
    saved = copy.deepcopy(original)
    result, schema = execute(original)
    assert result.ok is False and result.error == 'invalid_tool_arguments'
    example = next(d['example_arguments'] for d in result.error_details if 'example_arguments' in d)
    assert Draft202012Validator(schema).is_valid(example)
    assert example['changes']['model_type'] == 'linear_mixed_effects'
    assert example['changes']['model_options'] == original['changes']['model_options']
    assert example['target'] == original['target'] and example['preconditions'] == original['preconditions']
    assert original == saved


def test_control_changes_are_not_silently_removed_to_manufacture_a_valid_example():
    arguments = request()
    arguments['changes']['x'] = ['new_control']
    arguments['changes']['model_type'] = {'old':'linear_mixed_effects','new':'linear_mixed_effects'}
    result, _ = execute(arguments)
    assert result.ok is False
    assert not any('example_arguments' in d for d in result.error_details)
    assert any('model_options' in d.get('allowed_fields',[]) for d in result.error_details)


def test_json_text_changes_with_one_meaning_are_decoded_with_a_note_and_nothing_else_is_rewritten():
    arguments = request()
    intended = copy.deepcopy(arguments['changes'])
    arguments['changes'] = json.dumps(intended)
    saved = copy.deepcopy(arguments)
    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id='run_operation',version='v1',input_schema=OperationRegistry().proposal_tool_schema(),
        side_effect='proposal',handler=lambda args,ctx:calls.append(args) or {'saved':True}))
    result = asyncio.run(registry.execute({'tool_call_id':'text','tool_id':'run_operation','arguments':arguments},session_id='s'))
    assert result.ok and calls == [{**saved, 'changes': intended}]
    assert 'JSON text' in result.output['workbench_notes'][0]
    assert arguments == saved


@pytest.mark.parametrize('text', ['{"model_type":', '[]', 'null',
    '{"model_type":"ols","model_type":"linear_mixed_effects"}',
    '{"model_type":"linear_mixed_effects","model_options":{"x":NaN}}',
    '{"model_type":"linear_mixed_effects","unknown_control":["z"]}',
    ' '*4001+'{}'])
def test_ambiguous_invalid_or_oversized_json_changes_remain_refused_without_example(text):
    arguments = request()
    arguments['changes'] = text
    result, _ = execute(arguments)
    assert not result.ok and result.error == 'invalid_tool_arguments'
    assert not any('example_arguments' in d for d in result.error_details)


def test_json_exponent_overflow_never_emits_an_infinite_correction_example():
    arguments = request()
    arguments['changes'] = '{"model_type":"linear_mixed_effects","model_options":{"x":1e309}}'
    result, _ = execute(arguments)
    assert not result.ok and result.error == 'invalid_tool_arguments'
    assert not any('example_arguments' in d for d in result.error_details)
    json.dumps(result.to_payload(), allow_nan=False)
