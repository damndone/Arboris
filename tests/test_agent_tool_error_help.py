"""Refusals of the Agent's own input say what to write instead (v1.9.1 smoke findings)."""

from __future__ import annotations

import asyncio
import copy
import json

from jsonschema import Draft202012Validator
import pytest

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


@pytest.mark.parametrize("operation_id", ["model.genesis", "iv.weak_instruments"])
def test_workflow_step_as_root_keeps_refusal_and_points_to_its_workflow_contract(operation_id):
    from workbench.agent.operation_request_refs import wire_schema
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.tools import MAX_VALIDATION_DETAIL_CHARS

    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id="run_operation", version="v1", side_effect="proposal",
        input_schema=wire_schema(OperationRegistry().proposal_tool_schema()),
        handler=lambda arguments, context: calls.append(arguments)))
    arguments = _workflow_request()
    arguments["operation_id"] = operation_id
    original = copy.deepcopy(arguments)

    refused = asyncio.run(registry.execute({"tool_call_id": "wrong-root", "tool_id": "run_operation",
                                           "arguments": arguments}, session_id="s"))

    assert not refused.ok and refused.error == "invalid_tool_arguments"
    assert not calls and arguments == original
    (detail,) = refused.error_details
    assert detail["path"] == "operation_id"
    assert "workflow step" in detail["message"]
    assert "model.rerun" not in json.dumps(detail)
    assert detail["retry_hint"] == {
        "tool_id": "inspect_operation_contract",
        "arguments_patch": {"operation_id": "operation.multi_step", "step_operation_ids": [operation_id]},
    }
    assert len(json.dumps(detail)) <= MAX_VALIDATION_DETAIL_CHARS


def test_workflow_step_inspection_refusal_has_the_same_read_only_retry_hint(tmp_path):
    from tests.test_agent_context_tools import _load_provider_type, _write_project_run
    from workbench.agent.operations import OperationRegistry

    project = tmp_path / "project"
    _write_project_run(project)
    provider = _load_provider_type()(project)
    registry = ToolRegistry()
    for definition in provider.tool_definitions(chain_id="chain-a", session_id="s", operation_registry=OperationRegistry()):
        registry.register(definition)
    arguments = {"owner_run_id": "run-a", "op_node_id": "model:ols_1", "active_head_run_id": "run-a",
                 "operation_id": "model.genesis"}
    original = copy.deepcopy(arguments)

    refused = asyncio.run(registry.execute({"tool_call_id": "wrong-inspect", "tool_id": "inspect_operation_contract",
                                           "arguments": arguments}, session_id="s"))

    assert not refused.ok and refused.error == "invalid_tool_arguments"
    (detail,) = refused.error_details
    assert detail["retry_hint"]["arguments_patch"] == {
        "operation_id": "operation.multi_step", "step_operation_ids": ["model.genesis"]}
    assert "step_operation_ids" in detail["message"] and "model.rerun" not in detail["message"]
    assert arguments == original


@pytest.mark.parametrize("invalid", ["missing-context", "categorical", "model-options"])
def test_panel_family_refusal_describes_the_live_contract_without_switching_family(invalid):
    from workbench.agent.workflow_contract_parts.validation import validate_model_genesis_spec
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
    from workbench.agent.tools import MAX_VALIDATION_DETAIL_CHARS

    spec = {"model_family": "panel_ols", "entity_col": "unit",
            "branches": [{"branch_id": "main", "outcome": "y", "predictors": ["x"]}]}
    if invalid == "missing-context":
        spec.pop("entity_col")
    elif invalid == "categorical":
        spec["branches"][0]["categorical"] = ["group"]
    else:
        spec["model_options"] = {"time_fe": True, "time_effects": True}
    original = copy.deepcopy(spec)
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id="validate_genesis", version="v1", side_effect="none",
        input_schema={"type": "object"}, handler=lambda arguments, context: validate_model_genesis_spec(arguments)))

    refused = asyncio.run(registry.execute({"tool_call_id": "family", "tool_id": "validate_genesis",
                                           "arguments": spec}, session_id="s"))

    assert not refused.ok and refused.error == "OperationValidationError" and spec == original
    message = refused.error_details[0]["message"]
    assert "step.spec context fields: entity_col, time_col" in message
    assert "required (any): entity_col, time_col" in message
    assert "branches[].categorical is not allowed" in message
    contract = MODEL_FAMILY_CONTRACTS["panel_ols"]
    assert "model_options accepts: " + (", ".join(contract.model_options_fields) or "no fields") in message
    assert "step_operation_ids=[\"model.genesis\"]" in message
    assert "model.rerun" not in message and "model_family ols" not in message
    assert len(message) <= MAX_VALIDATION_DETAIL_CHARS


def test_family_guidance_tracks_the_single_contract_declaration(monkeypatch):
    from dataclasses import replace
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS

    contract = MODEL_FAMILY_CONTRACTS["panel_ols"]
    monkeypatch.setitem(MODEL_FAMILY_CONTRACTS, "panel_ols", replace(contract,
        allows_categorical_terms=True, model_options_fields=("fixture_declared_option",),
        model_options_column_fields=()))

    message = help_for("model.genesis panel_ols model_options does not accept field(s): time_effects")

    assert "branches[].categorical is allowed" in message
    assert "model_options accepts: fixture_declared_option" in message
    assert "Did you mean" not in message


def test_ols_cluster_guidance_retains_the_bound_analysis_loop_route():
    message = help_for("model.genesis ols does not accept panel entity_col or time_col")

    assert "model.rerun" in message and "clustered" in message
    assert "Analysis Loop" in message and "server-bound" in message
    assert "preconditions.analysis_loop" in message
    assert "do not invent" in message.lower()


def test_long_family_refusal_keeps_usable_help_within_the_existing_bound():
    from workbench.agent.tools import MAX_VALIDATION_DETAIL_CHARS

    registry = ToolRegistry()
    def refuse(arguments, context):
        raise OperationValidationError("model.genesis panel_ols model_options does not accept field(s): " + "x" * 6000)
    registry.register(ToolDefinition(tool_id="validate_genesis", version="v1", side_effect="none",
        input_schema={"type": "object"}, handler=refuse))

    refused = asyncio.run(registry.execute({"tool_call_id": "long-family", "tool_id": "validate_genesis",
                                           "arguments": {}}, session_id="s"))

    message = refused.error_details[0]["message"]
    assert len(message) <= MAX_VALIDATION_DETAIL_CHARS
    assert "step.spec context fields: entity_col, time_col" in message
    assert "step_operation_ids=[\"model.genesis\"]" in message
