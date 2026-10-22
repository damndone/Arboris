"""The harness absorbs harmless argument variations and says what it did (free-route round, 2026-10-22).

35 tool calls were refused in 8 tasks; most were node identity the backend binds
anyway, or identity a read tool does not take. Each correction is reported back
to the model as ``workbench_notes``; anything ambiguous is still refused.
"""
import asyncio

from workbench.agent.operations import OperationRegistry, normalize_operation_target
from workbench.agent.tools import ToolDefinition, ToolRegistry, ToolVisibleError, tool_note, validation_details


def _target_schema(operation_id):
    schema = OperationRegistry().proposal_tool_schema()
    return next(s for s in schema["oneOf"] if s["properties"]["operation_id"]["const"] == operation_id)["properties"]["target"]


def test_backend_bound_identity_is_optional_for_every_node_operation():
    for operation_id in ("operation.multi_step", "model.rerun", "metadata.edit", "graph.fork"):
        target = _target_schema(operation_id)
        assert not {"node_hash", "forest_node_key"} & set(target["required"]), operation_id
        assert {"node_hash", "forest_node_key"} <= set(target["properties"]), operation_id
    assert "artifact_id" not in _target_schema("operation.multi_step")["required"]
    # A data step outside a workflow is not bound by the backend: it still names its artifact.
    assert "artifact_id" in _target_schema("data.subset")["required"]


def _normalize(arguments):
    notes = []
    from workbench.agent import tools
    token = tools._TOOL_NOTES.set(notes)
    try:
        return normalize_operation_target(OperationRegistry(), arguments), notes
    finally:
        tools._TOOL_NOTES.reset(token)


def test_identity_an_operation_does_not_use_is_dropped_with_a_note():
    arguments = {"operation_id": "model.rerun", "target": {"run_id": "r", "node_ref": "model:ols_1", "artifact_id": "ols_1"}}
    normalized, notes = _normalize(arguments)
    assert normalized["target"] == {"run_id": "r", "node_ref": "model:ols_1"}
    assert notes and "artifact_id" in notes[0]
    workflow = {"operation_id": "operation.multi_step",
                "target": {"run_id": "r", "node_ref": "stage:cleaned", "node_hash": "h", "forest_node_key": "k"}}
    normalized, notes = _normalize(workflow)
    assert normalized["target"] == {"run_id": "r", "node_ref": "stage:cleaned"}


def test_node_id_means_node_ref_but_a_contradiction_is_left_for_validation():
    normalized, notes = _normalize({"operation_id": "operation.multi_step", "target": {"run_id": "r", "node_id": "stage:cleaned"}})
    assert normalized["target"] == {"run_id": "r", "node_ref": "stage:cleaned"} and notes
    contradictory, _ = _normalize({"operation_id": "operation.multi_step",
                                   "target": {"run_id": "r", "node_ref": "stage:cleaned", "node_id": "stage:raw"}})
    assert contradictory["target"]["node_id"] == "stage:raw"


def _registry(definition):
    registry = ToolRegistry()
    registry.register(definition)
    return registry


def test_a_read_tool_ignores_identity_it_does_not_take_and_says_so():
    seen = {}
    definition = ToolDefinition(tool_id="inspect_analysis_completion", version="v1", side_effect="none",
        input_schema={"type": "object", "properties": {"source": {"type": "object"}}, "additionalProperties": False},
        handler=lambda arguments, context: seen.setdefault("arguments", arguments) and {"status": "partial"})
    result = asyncio.run(_registry(definition).execute({"tool_call_id": "c", "tool_id": "inspect_analysis_completion",
        "arguments": {"owner_run_id": "r", "op_node_id": "model:ols_1", "active_head_run_id": "r"}}, session_id="s"))
    assert result.ok and seen["arguments"] == {}
    assert "ignored" in result.output["workbench_notes"][0]


def test_a_tool_that_changes_state_still_refuses_unknown_fields():
    definition = ToolDefinition(tool_id="write_thing", version="v1", side_effect="artifact",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda arguments, context: {"done": True})
    result = asyncio.run(_registry(definition).execute({"tool_call_id": "c", "tool_id": "write_thing",
        "arguments": {"owner_run_id": "r"}}, session_id="s"))
    assert not result.ok and result.error == "invalid_tool_arguments"


def test_notes_from_a_handler_reach_the_model():
    def handler(arguments, context):
        tool_note("read run r2 under head r1")
        return {"value": 1}
    definition = ToolDefinition(tool_id="inspect_x", version="v1", side_effect="none",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False}, handler=handler)
    result = asyncio.run(_registry(definition).execute({"tool_call_id": "c", "tool_id": "inspect_x", "arguments": {}},
                                                      session_id="s"))
    assert result.output == {"value": 1, "workbench_notes": ["read run r2 under head r1"]}


def test_a_refused_analysis_loop_intent_shows_its_reason():
    from workbench.analysis_loop.plan import PlanValidationError
    from workbench.agent.tools import _is_agent_input_fault

    assert _is_agent_input_fault(PlanValidationError("COMPARISON_TARGET_REQUIRED: pass target.result_id", code="x"))
    assert not _is_agent_input_fault(RuntimeError("internal"))
    assert issubclass(ToolVisibleError, Exception)


def test_a_read_naming_a_branch_of_the_head_as_the_head_reads_it_under_the_head(tmp_path):
    import json
    from workbench.agent.chains import ChainStore
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent import tools

    root = tmp_path / "project"
    for run, source in (("run-b", None), ("run-c", "run-b"), ("run-x", None)):
        (root / "runs" / run).mkdir(parents=True)
        manifest = {"run_id": run, **({"dataset_source": {"source_run_id": source}} if source else {})}
        (root / "runs" / run / "run_manifest.json").write_text(json.dumps(manifest))
    ChainStore(root / "workbench").create_root(chain_id="chain-a", run_family_id="legacy-family:run-b",
                                               active_head_run_id="run-b", agent_session_id="s")
    provider = NodeOperationContextProvider(root)
    notes = []
    token = tools._TOOL_NOTES.set(notes)
    try:
        assert provider._tool_active_head("chain-a", "run-c", "run-c") == "run-b"
        assert notes and "run-c" in notes[0]
        # Not derived from the head, or a different owner: still refused.
        for requested, owner in (("run-x", "run-x"), ("run-c", "run-b")):
            try:
                provider._tool_active_head("chain-a", requested, owner)
            except ToolVisibleError as exc:
                assert str(exc).startswith("ACTIVE_HEAD_MISMATCH")
            else:
                raise AssertionError(f"{requested} was accepted")
    finally:
        tools._TOOL_NOTES.reset(token)


def test_a_single_string_for_a_list_of_strings_is_a_one_item_list():
    seen = {}
    definition = ToolDefinition(tool_id="plan_x", version="v1", side_effect="proposal",
        input_schema={"type": "object", "properties": {"completion": {"type": "object", "properties": {
            "playbooks": {"type": "array", "items": {"type": "string"}}}}, "count": {"type": "integer"}},
            "additionalProperties": False},
        handler=lambda arguments, context: seen.setdefault("arguments", arguments) and {"saved": True})
    result = asyncio.run(_registry(definition).execute({"tool_call_id": "c", "tool_id": "plan_x",
        "arguments": {"completion": {"playbooks": "iv"}}}, session_id="s"))
    assert result.ok and seen["arguments"] == {"completion": {"playbooks": ["iv"]}}
    assert "one-item list" in result.output["workbench_notes"][0]
    # Other type errors are not guessed at.
    refused = asyncio.run(_registry(definition).execute({"tool_call_id": "c", "tool_id": "plan_x",
        "arguments": {"count": "three"}}, session_id="s"))
    assert not refused.ok
