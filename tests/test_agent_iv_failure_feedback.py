"""Offline regressions for the recorded IV tool failures, using generic bindings."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from workbench.agent.operations import OperationRegistry
from workbench.agent.tools import ToolDefinition, ToolRegistry


def _execute(registry, tool_id, arguments, *, call_id="offline"):
    return asyncio.run(registry.execute(
        {"tool_call_id": call_id, "tool_id": tool_id, "arguments": arguments},
        session_id="offline-session",
    ))


def test_long_string_changes_reports_expected_and_actual_types_before_the_excerpt():
    from tests.test_agent_tool_error_help import _workflow_request
    from workbench.agent.tools import MAX_VALIDATION_MESSAGE_CHARS

    executed = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        tool_id="run_operation", version="v1", side_effect="proposal",
        input_schema=OperationRegistry().proposal_tool_schema(),
        handler=lambda arguments, context: executed.append(arguments),
    ))
    request = _workflow_request()
    request["changes"]["steps"][0]["spec"]["selected_columns"] = ["column_" + "x" * 1200]
    request["changes"] = json.dumps(request["changes"])
    original = copy.deepcopy(request)

    refused = _execute(registry, "run_operation", request)

    assert not refused.ok and refused.error == "invalid_tool_arguments"
    assert not executed and request == original
    detail = next(d for d in refused.error_details if d["path"] == "changes" and d["constraint"] == "type")
    assert detail["expected_type"] == "object"
    assert detail["actual_type"] == "string"
    assert detail["message"].startswith("changes: expected object, got string")
    assert len(detail["message"]) <= MAX_VALIDATION_MESSAGE_CHARS
    assert len(json.dumps(detail)) < 1200
    # Correction keeps the same tool/strict schema; strings are never auto-decoded.
    request["changes"] = json.loads(request["changes"])
    accepted = _execute(registry, "run_operation", request, call_id="corrected")
    assert accepted.ok and executed == [request]


@pytest.fixture
def context_tools(tmp_path):
    from tests.test_agent_context_tools import _load_provider_type, _write_project_run

    project = tmp_path / "project"
    _write_project_run(project)
    operations = OperationRegistry()
    provider = _load_provider_type()(project)
    registry = ToolRegistry()
    for definition in provider.tool_definitions(
        chain_id="chain-a", session_id="offline-session", operation_registry=operations,
    ):
        registry.register(definition)
    return registry, operations


def _inspect(registry, operation_id="model.rerun", *, steps=None):
    arguments = {
        "owner_run_id": "run-a", "op_node_id": "model:ols_1",
        "active_head_run_id": "run-a", "operation_id": operation_id,
    }
    if steps is not None:
        arguments["step_operation_ids"] = steps
    result = _execute(registry, "inspect_operation_contract", arguments)
    assert result.ok, result.to_payload()
    return result.output["contract"]


def test_rerun_inspection_only_advertises_fields_accepted_by_the_actual_tool(context_tools):
    registry, operations = context_tools
    contract = _inspect(registry)
    proposal = next(branch for branch in operations.proposal_tool_schema()["oneOf"]
                    if branch["properties"]["operation_id"].get("const") == "model.rerun")
    normal_patch = proposal["properties"]["changes"]["oneOf"][0]
    advertised = {control["key"] for control in contract["editable_schema"]}

    assert advertised <= set(normal_patch["properties"])
    assert {"model_type", "model_options"} <= advertised
    assert "x" not in advertised
    # The agent projection must not remove capabilities from the manual node contract.
    from workbench.lineage.op_contract import resolve_operation_contract
    manual = resolve_operation_contract(stage="model", manifest={"model_routing": {
        "requested_model_type": "ols", "effective_model_type": "ols",
    }})
    assert "x" in {control["key"] for control in manual.editable_schema}


def test_rerun_family_switch_requirements_point_new_bindings_to_the_existing_workflow(context_tools):
    registry, _ = context_tools
    contract = _inspect(registry)
    model_control = next(control for control in contract["editable_schema"] if control["key"] == "model_type")
    assert "iv_2sls" in {option["value"] for option in model_control["options"]}
    requirements = contract["family_switch_requirements"]["iv_2sls"]
    assert {"iv_endog", "iv_instruments"} <= set(requirements["required_fields"])
    assert {"iv_endog", "iv_instruments"} <= set(requirements["not_writable_fields"])
    guidance = contract["family_switch_guidance"]
    assert "retained" in guidance and "model_options" in guidance
    assert "operation.multi_step" in guidance and "model.genesis" in guidance
    assert len(json.dumps(contract)) < 65536

    # Follow the advertised existing route: bindings belong to the genesis spec,
    # not to a newly invented rerun envelope or a top-level genesis operation.
    workflow = _inspect(registry, "operation.multi_step", steps=["model.genesis"])
    genesis = workflow["step_vocabulary"]["step_operations"]["model.genesis"]
    assert {"iv_endog", "iv_instruments"} <= set(genesis["fields"])
    assert "branches" in genesis["required"]


def _model_workflow_steps(model_ref):
    return [
        {"step_id": "fit", "operation_id": "model.genesis", "spec": {
            "model_family": "iv_2sls", "iv_endog": ["endogenous"],
            "iv_instruments": ["instrument"],
            "branches": [{"branch_id": "main_branch", "outcome": "outcome", "predictors": []}],
        }},
        {"step_id": "inference", "operation_id": "iv.ar_confidence",
         "spec": {"model_ref": model_ref}},
    ]


def _compile(steps):
    from workbench.agent.workflow import compile_workflow

    return compile_workflow(
        workflow_id="offline-model-binding", target={"run_id": "source", "node_ref": "stage:cleaned",
                                                     "artifact_id": "cleaned_dataset"},
        preconditions={"source_artifact_fingerprint": "source-hash", "context_fingerprint": "offline"},
        steps=steps,
    )


def test_bare_branch_refusal_teaches_the_existing_plan_local_reference_via_the_tool(context_tools):
    registry, _ = context_tools
    executed = []

    def compile_only(arguments, context):
        draft = _compile(arguments["steps"])
        executed.append(draft)
        return {"status": "compiled"}

    registry.register(ToolDefinition(tool_id="compile_workflow", version="v1", side_effect="none",
                                     input_schema={"type": "object"}, handler=compile_only))
    refused = _execute(registry, "compile_workflow", {"steps": _model_workflow_steps("main_branch")})
    assert not refused.ok and not executed
    message = refused.error_details[0]["message"]
    from workbench.agent.tools import MAX_VALIDATION_MESSAGE_CHARS
    assert len(message) <= MAX_VALIDATION_MESSAGE_CHARS
    assert "step:<producer>:<branch>" in message
    assert "inspect_operation_contract" in message
    assert "operation.multi_step" in message and "iv.ar_confidence" in message
    contract = _inspect(registry, "operation.multi_step", steps=["iv.ar_confidence"])
    assert "step:<producer>:<branch>" in contract["step_vocabulary"]["step_operations"]["iv.ar_confidence"]["fields"]["model_ref"]

    corrected = _execute(registry, "compile_workflow",
                         {"steps": _model_workflow_steps("step:fit:main_branch")}, call_id="corrected")
    assert corrected.ok and len(executed) == 1
    assert "fit" in executed[0].steps[1].depends_on


@pytest.mark.parametrize("reference", ["step:missing:main_branch", "step:fit:missing_branch"])
def test_reference_guidance_does_not_accept_unknown_producers_or_branches(reference):
    from workbench.contracts.common.errors import OperationValidationError

    with pytest.raises(OperationValidationError):
        _compile(_model_workflow_steps(reference))
