"""Offline replay of misplaced operation-envelope fields, without provider calls."""

import asyncio
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from workbench.agent.operations import OperationRegistry
from workbench.agent.tools import MAX_VALIDATION_DETAIL_CHARS, ToolDefinition, ToolRegistry
from workbench.agent.toolsets import build_chain_tool_registry


def _request():
    return {
        "operation_id": "operation.multi_step", "operation_version": "v1",
        "target": {"run_id": "source-run", "node_ref": "stage:cleaned"},
        "preconditions": {"context_version": "node-operation-context/v1",
            "context_fingerprint": "source-fingerprint", "active_head_run_id": "source-run",
            "owner_resolution": "single_candidate"},
        "changes": {"steps": [{"step_id": "summary", "operation_id": "statistical.explore",
            "spec": {"operation": "describe", "selected_columns": ["x"]}}]},
        "evidence_refs": ["source-run/stage:cleaned"],
        "expected_effect": ["Summarize the inspected source."], "risks": ["Descriptive only."],
    }


def _registry():
    schema = OperationRegistry().proposal_tool_schema()
    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id="run_operation", version="v1", input_schema=schema,
        side_effect="proposal", handler=lambda arguments, context: calls.append(arguments)))
    return registry, schema, calls


def _execute(registry, arguments):
    return asyncio.run(registry.execute({"tool_call_id": "replay", "tool_id": "run_operation",
        "arguments": arguments}, session_id="session"))


def _apply_example_patch(arguments, patch):
    corrected = copy.deepcopy(arguments)
    for edit in patch:
        path = edit["path"].removeprefix("/").split("/")
        parent = corrected
        for key in path[:-1]:
            parent = parent[key]
        if edit["op"] == "remove":
            del parent[path[-1]]
        else:
            assert edit["op"] == "move"
            origin = edit["from"].removeprefix("/").split("/")
            source = corrected
            for key in origin[:-1]:
                source = source[key]
            parent[path[-1]] = source.pop(origin[-1])
    return corrected


def _patch(result):
    return next(detail["example_arguments_patch"] for detail in result.error_details
        if "example_arguments_patch" in detail)


def test_replay_duplicate_missing_and_misplaced_evidence_keep_the_required_envelope():
    registry, schema, calls = _registry()
    valid = _request()
    duplicate = copy.deepcopy(valid)
    duplicate["changes"]["evidence_refs"] = valid["evidence_refs"][:]
    missing = copy.deepcopy(valid)
    del missing["evidence_refs"]
    misplaced = copy.deepcopy(duplicate)
    del misplaced["evidence_refs"]

    for arguments, expected_patch in (
        (duplicate, [{"op": "remove", "path": "/changes/evidence_refs"}]),
        (missing, None),
        (misplaced, [{"op": "move", "from": "/changes/evidence_refs", "path": "/evidence_refs"}]),
    ):
        original = copy.deepcopy(arguments)
        refused = _execute(registry, arguments)
        assert not refused.ok and refused.error == "invalid_tool_arguments" and not calls
        if expected_patch is None:
            detail = next(d for d in refused.error_details if d["constraint"] == "required")
            assert detail["missing_fields"] == ["evidence_refs"]
            assert "evidence_refs" in detail["required_fields"]
            assert detail["required_paths"] == ["arguments.evidence_refs"]
            assert not any("example_arguments_patch" in d or "example_arguments" in d
                for d in refused.error_details)
            assert arguments == original
            continue
        assert _patch(refused) == expected_patch
        corrected = _apply_example_patch(arguments, _patch(refused))
        assert corrected == valid and Draft202012Validator(schema).is_valid(corrected)
        assert arguments == original
        assert "not executed" in refused.error_details[0]["example_scope"]
        assert "resubmit" in refused.error_details[0]["example_scope"]

    accepted = _execute(registry, valid)
    assert accepted.ok and calls == [valid]


def test_large_envelope_gets_a_bounded_patch_that_preserves_all_source_and_intent_fields():
    registry, schema, calls = _registry()
    arguments = _request()
    arguments["expected_effect"] = ["The declared descriptive summary. " * 70]
    arguments["changes"]["evidence_refs"] = arguments["evidence_refs"][:]
    original = copy.deepcopy(arguments)
    assert len(json.dumps(arguments)) > MAX_VALIDATION_DETAIL_CHARS
    refused = _execute(registry, arguments)
    corrected = _apply_example_patch(arguments, _patch(refused))
    expected = copy.deepcopy(original)
    del expected["changes"]["evidence_refs"]
    assert corrected == expected and Draft202012Validator(schema).is_valid(corrected)
    assert len(json.dumps(refused.error_details[0])) < MAX_VALIDATION_DETAIL_CHARS
    assert arguments == original and not calls


@pytest.mark.parametrize("fault", ["conflicting_refs", "unknown_intent", "missing_target", "empty_misplaced_refs"])
def test_ambiguous_or_incomplete_requests_never_get_an_envelope_correction(fault):
    registry, _, calls = _registry()
    arguments = _request()
    arguments["changes"]["evidence_refs"] = arguments["evidence_refs"][:]
    if fault == "conflicting_refs":
        arguments["changes"]["evidence_refs"] = ["another-source/stage:cleaned"]
    elif fault == "unknown_intent":
        arguments["changes"]["extra_model"] = {"predictors": ["unrequested_control"]}
    elif fault == "missing_target":
        del arguments["target"]
    else:
        del arguments["evidence_refs"]
        arguments["changes"]["evidence_refs"] = []
    original = copy.deepcopy(arguments)
    refused = _execute(registry, arguments)
    assert not refused.ok and refused.error == "invalid_tool_arguments" and not calls
    assert not any("example_arguments_patch" in d or "example_arguments" in d for d in refused.error_details)
    assert arguments == original


def test_run_operation_description_names_the_outer_evidence_position():
    registry = build_chain_tool_registry(context_tools=(),
        proposal_tool_schema=OperationRegistry().proposal_tool_schema,
        update_plan=lambda arguments, context: None, run_operation=lambda arguments, context: None,
        plan_analysis=lambda arguments, context: None, inspect_analysis_completion=lambda arguments, context: None)
    description = next(d["description"] for d in registry.descriptors() if d["tool_id"] == "run_operation")
    assert all(field in description for field in ("evidence_refs", "expected_effect", "risks", "changes"))
    assert "top-level" in description and "inspected" in description


def test_boolean_changes_schema_keeps_ordinary_required_field_feedback():
    registry = ToolRegistry()
    registry.register(ToolDefinition(tool_id="inspect_x", version="v1", side_effect="none",
        input_schema={"type": "object", "required": ["question"],
            "properties": {"question": {"type": "string"}, "changes": True}},
        handler=lambda arguments, context: pytest.fail("invalid arguments executed")))
    refused = asyncio.run(registry.execute({"tool_call_id": "replay", "tool_id": "inspect_x",
        "arguments": {"changes": {}}}, session_id="session"))
    assert not refused.ok and refused.error == "invalid_tool_arguments"
    assert refused.error_details[0]["required_paths"] == ["arguments.question"]
    assert not any("example_arguments_patch" in d for d in refused.error_details)
