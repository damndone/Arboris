"""Refusals of the Agent's own input say what to write instead (v1.9.1 smoke findings)."""

from __future__ import annotations

import asyncio
import copy

from jsonschema import Draft202012Validator

from workbench.agent.contract_help import help_for
from workbench.agent.toolsets import _UPDATE_PLAN_SCHEMA
from workbench.agent.tools import ToolDefinition, ToolRegistry, validation_details
from workbench.contracts.common.errors import OperationValidationError


def test_an_unexpected_field_names_the_allowed_ones_and_the_likely_one():
    details = validation_details(_UPDATE_PLAN_SCHEMA, {
        "question": "q", "criteria": ["c"],
        "steps": [{"step_id": "s1", "title": "t", "operation_ids": [], "dependencies": ["s0"]}]})
    (detail,) = details
    assert detail["constraint"] == "additionalProperties"
    assert "depends_on" in detail["allowed_fields"]
    assert detail["did_you_mean"] == {"dependencies": "depends_on"}


def test_a_family_option_refusal_lists_the_accepted_options():
    text = help_for("model.genesis survival_cox model_options does not accept field(s): event_col")
    assert "accepts: event_column" in text and "required: event_column" in text
    assert "event_col -> event_column" in text
    assert help_for("model.genesis survival_cox model_options requires: event_column").startswith(
        " survival_cox model_options accepts:")
    assert help_for("an unrelated refusal") == ""
    assert help_for("model.genesis no_such_family model_options does not accept field(s): x") == ""


def test_the_help_reaches_the_model_through_a_tool_call():
    def refuse(arguments, context):
        raise OperationValidationError("model.genesis survival_cox model_options does not accept field(s): event_col")

    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id="propose", version="v1", input_schema={"type": "object"},
                                     side_effect="none", scope_requirements=(), handler=refuse))
    result = asyncio.run(registry.execute({"tool_call_id": "c1", "tool_id": "propose", "arguments": {}},
                                          session_id="s"))
    assert result.ok is False
    assert "Did you mean event_col -> event_column?" in result.error_details[0]["message"]


def test_wrong_version_reports_the_requested_operations_constraints_together():
    from workbench.agent.operations import OperationRegistry

    schema = OperationRegistry().proposal_tool_schema()
    arguments = _workflow_request()
    assert Draft202012Validator(schema).is_valid(arguments)
    arguments['operation_version'] = '1'
    arguments['target'].pop('node_ref')
    original = copy.deepcopy(arguments)
    details = validation_details(schema, arguments)
    assert any(d['path'] == 'operation_version' and d['constraint'] == 'const' for d in details), details
    assert any(d['path'] == 'target' and 'node_ref' in d['message'] for d in details), details
    assert not any('workflow_id' in d['message'] or 'step_id' in d['message'] for d in details), details
    assert not Draft202012Validator(schema).is_valid(arguments)
    assert arguments == original


def test_wrong_version_is_not_executed_or_implicitly_upgraded():
    from workbench.agent.operations import OperationRegistry

    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id='run_operation', version='v1',
        input_schema=OperationRegistry().proposal_tool_schema(), side_effect='proposal',
        handler=lambda args, context: calls.append(args)))
    arguments = _workflow_request()
    arguments['operation_version'] = '1'
    refused = asyncio.run(registry.execute({'tool_call_id': 'wrong', 'tool_id': 'run_operation',
                                           'arguments': arguments}, session_id='session'))
    assert not refused.ok and not calls
    assert any(d.get('path') == 'operation_version' for d in refused.error_details), refused
    arguments['operation_version'] = 'v1'
    accepted = asyncio.run(registry.execute({'tool_call_id': 'fixed', 'tool_id': 'run_operation',
                                            'arguments': arguments}, session_id='session'))
    assert accepted.ok and calls == [arguments]


def _workflow_request():
    return {'operation_id': 'operation.multi_step', 'operation_version': 'v1',
        'target': {'run_id': 'r', 'node_ref': 'stage:cleaned'},
        'preconditions': {'context_version': 'node-operation-context/v1', 'context_fingerprint': 'source',
                          'active_head_run_id': 'r', 'owner_resolution': 'single_candidate'},
        'changes': {'steps': [{'step_id': 'summary', 'operation_id': 'statistical.explore',
                               'spec': {'operation': 'tabulate', 'selected_columns': ['x']}}]},
        'evidence_refs': [], 'expected_effect': ['Tabulate x.'], 'risks': []}


def test_unknown_contract_version_is_visible_with_registered_versions_but_internal_faults_are_not():
    from workbench.agent.operations import OperationRegistry

    registry = ToolRegistry()
    operations = OperationRegistry()
    def lookup(arguments, context):
        return operations.require(arguments['operation_id'], arguments['operation_version'])
    registry.register(ToolDefinition(tool_id='inspect_operation_contract', version='v1',
        input_schema={'type': 'object'}, side_effect='none', handler=lookup))
    result = asyncio.run(registry.execute({'tool_call_id': 'version', 'tool_id': 'inspect_operation_contract',
        'arguments': {'operation_id': 'operation.multi_step', 'operation_version': '1'}}, session_id='s'))
    assert not result.ok and result.error == 'UnknownOperationError'
    assert result.error_details and 'registered versions: v1' in result.error_details[0]['message'], result
    assert 'operation.multi_step@1' in result.error_details[0]['message']
    def internal(arguments, context):
        raise RuntimeError('private internal detail')
    registry.register(ToolDefinition(tool_id='inspect_internal', version='v1',
        input_schema={'type': 'object'}, side_effect='none', handler=internal))
    failure = asyncio.run(registry.execute({'tool_call_id': 'internal', 'tool_id': 'inspect_internal',
                                           'arguments': {}}, session_id='s'))
    assert not failure.ok and failure.error_details is None
    assert 'private internal detail' not in str(failure.to_payload())
