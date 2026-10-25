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
    assert any("artifact_id" in note for note in notes)
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


def _genesis_spec(**overrides):
    spec = {"model_family": "panel_ols", "entity_col": "firm", "time_col": "year",
            "branches": [{"branch_id": "firm_fe", "outcome": "y", "predictors": ["x"]}]}
    return {**spec, **overrides}


def test_a_branch_cannot_switch_family_or_panel_effects():
    import pytest
    from workbench.contracts.common.errors import OperationValidationError
    from workbench.agent.workflow_contract_parts import validation

    validate = validation.validate_model_genesis_spec
    spec = _genesis_spec(branches=[{"branch_id": "re", "outcome": "y", "predictors": ["x"], "model_family": "random_effects"}])
    with pytest.raises(OperationValidationError, match="own model.genesis step"):
        validate(spec)


def test_identical_branches_are_refused_as_one_fit():
    import pytest
    from workbench.contracts.common.errors import OperationValidationError
    from workbench.agent.workflow_contract_parts import validation

    validate = validation.validate_model_genesis_spec
    spec = _genesis_spec(branches=[{"branch_id": "pooled_ols", "outcome": "y", "predictors": ["x"]},
                                   {"branch_id": "firm_fe", "outcome": "y", "predictors": ["x"]}])
    with pytest.raises(OperationValidationError, match="same specification"):
        validate(spec)
    validate(_genesis_spec(branches=[{"branch_id": "a", "outcome": "y", "predictors": ["x"]},
                                     {"branch_id": "b", "outcome": "y", "predictors": ["x", "z"]}]))


def test_an_ols_cluster_refusal_names_the_rerun_route():
    from workbench.agent.contract_help import help_for

    assert "model.rerun" in help_for("model.genesis ols does not accept panel entity_col or time_col")
    text = help_for("model.genesis ols model_options does not accept field(s): cluster")
    assert "model.rerun" in text and "accepts" in text
    assert "model.rerun" not in help_for("model.genesis survival_cox model_options does not accept field(s): event_col")


# Hy3 / Step-5 free-route rounds (2026-10-23): variants that mean one thing are corrected with a note.

def _genesis_step(spec):
    return {"operation_id": "operation.multi_step", "operation_version": "v1",
            "target": {"run_id": "r", "node_ref": "stage:cleaned"},
            "changes": {"steps": [{"step_id": "fit", "operation_id": "model.genesis", "spec": spec}]}}


def test_a_step_field_written_in_every_branch_is_moved_to_the_step():
    spec = {"model_family": "iv_2sls", "covariance": "robust", "branches": [
        {"branch_id": "a", "outcome": "y", "predictors": ["x"], "iv_endog": ["edu"], "iv_instruments": ["z"]},
        {"branch_id": "b", "outcome": "y", "predictors": [], "iv_endog": ["edu"], "iv_instruments": ["z"]}]}
    normalized, notes = _normalize(_genesis_step(spec))
    step = normalized["changes"]["steps"][0]["spec"]
    assert step["iv_endog"] == ["edu"] and step["iv_instruments"] == ["z"]
    assert all("iv_endog" not in branch and "iv_instruments" not in branch for branch in step["branches"])
    assert any("iv_endog" in note for note in notes)
    # Branches that disagree are not merged: validation refuses them.
    spec["branches"][1]["iv_endog"] = ["other"]
    kept, _ = _normalize(_genesis_step(spec))
    assert kept["changes"]["steps"][0]["spec"]["branches"][1]["iv_endog"] == ["other"]


def test_explore_columns_and_a_filter_op_mean_selected_columns_and_operator():
    arguments = {"operation_id": "operation.multi_step", "operation_version": "v1", "target": {"run_id": "r", "node_ref": "n"},
                 "changes": {"steps": [{"step_id": "e", "operation_id": "statistical.explore", "spec": {
                     "operation": "summarize_detail", "columns": ["months"],
                     "filters": [{"column": "drug", "op": "eq", "value": 0}]}}]}}
    normalized, notes = _normalize(arguments)
    spec = normalized["changes"]["steps"][0]["spec"]
    assert spec["selected_columns"] == ["months"] and "columns" not in spec
    assert spec["filters"] == [{"column": "drug", "operator": "eq", "value": 0}]
    assert len(notes) == 2
    from workbench.agent.workflow_contract_parts.validation import _validate_step_spec
    _validate_step_spec("statistical.explore", spec)  # the corrected spec is what validation accepts


def test_an_omitted_version_is_the_operations_only_one():
    normalized, notes = _normalize({"operation_id": "operation.multi_step", "target": {"run_id": "r", "node_ref": "n"},
                                    "changes": {"steps": []}})
    assert normalized["operation_version"] == "v1" and notes


def test_the_completion_check_accepts_the_sha256_it_was_given():
    from workbench.agent.completion import INSPECT_SCHEMA
    assert validation_details(INSPECT_SCHEMA, {"source": {"run_id": "r", "artifact_id": "a", "sha256": "f" * 64}}) == []


def test_a_rerun_contract_read_on_a_data_node_names_the_model_nodes(tmp_path):
    import pytest
    from workbench.agent.chains import ChainStore
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.context_tools_support.requests import InspectOperationContractRequest
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    project = create_project(tmp_path, "rerun-contract")
    source = tmp_path / "data.csv"
    from tests.test_agent_completion_sensitivity import _leverage_frame
    _leverage_frame().to_csv(source, index=False)
    run_id = run_workflow(project.root, [source], mode="auto", model_type="ols", y="rent", x=["density"])["run_id"]
    ChainStore(project.root / "workbench").create_root(chain_id="chain-a", run_family_id="f", active_head_run_id=run_id,
                                                       agent_session_id="s")
    provider = NodeOperationContextProvider(project.root)
    with pytest.raises(Exception, match=r"no contract for model\.rerun@v1 on stage:cleaned .*pass op_node_id model:"):
        provider.inspect_operation_contract(InspectOperationContractRequest(
            request_id="r", owner_run_id=run_id, op_node_id="stage:cleaned", active_head_run_id=run_id,
            operation_id="model.rerun"), operation_registry=OperationRegistry())


def test_a_model_option_one_spelling_from_an_accepted_name_is_that_name():
    spec = {"model_family": "survival_cox", "branches": [{"branch_id": "a", "outcome": "months", "predictors": ["drug"]}],
            "model_options": {"event_col": "event", "tie_method": "efron"}}
    normalized, notes = _normalize(_genesis_step(spec))
    options = normalized["changes"]["steps"][0]["spec"]["model_options"]
    assert options == {"event_column": "event", "tie_method": "efron"}  # not close enough to 'ties': left to refuse
    assert any("event_col is spelled event_column" in note for note in notes)


def _plan_tool(seen):
    return ToolDefinition(tool_id="plan_y", version="v1", side_effect="proposal",
        input_schema={"type": "object", "properties": {"question": {"type": "string"}, "completion": {"type": "object"},
                                                       "completion_evidence": {"type": "object"}},
                      "additionalProperties": False},
        handler=lambda arguments, context: seen.setdefault("arguments", arguments) and {"saved": True})


def test_arguments_written_in_the_models_own_markup_are_split_back_into_fields():
    # Hy3, free-route Auto iv_weak (2026-10-23): two update_plan fields fused into one key.
    seen = {}
    key = ('completion<tool_sep:6124c78e>\n<arg_value:6124c78e>{"playbooks": ["ols"]}</arg_value:6124c78e>\n'
           '<arg_key:6124c78e>completion_evidence')
    result = asyncio.run(_registry(_plan_tool(seen)).execute({"tool_call_id": "c", "tool_id": "plan_y",
        "arguments": {key: '{"models": [{"run_id": "r", "artifact_id": "ols_1"}]}', "question": "q"}}, session_id="s"))
    assert result.ok, result
    assert seen["arguments"] == {"question": "q", "completion": {"playbooks": ["ols"]},
                                 "completion_evidence": {"models": [{"run_id": "r", "artifact_id": "ols_1"}]}}
    assert "tool-call markup" in result.output["workbench_notes"][0]


def test_markup_that_does_not_parse_into_names_and_values_is_left_for_validation():
    seen = {}
    for key in ('completion<tool_sep:1><arg_value:1>{}</arg_value:1>',  # a value without its name
                'question<tool_sep:1><arg_value:1>x</arg_value:1><arg_key:1>completion'):  # a name already given
        result = asyncio.run(_registry(_plan_tool(seen)).execute({"tool_call_id": "c", "tool_id": "plan_y",
            "arguments": {key: "{}", "question": "q"}}, session_id="s"))
        assert not result.ok and result.error == "invalid_tool_arguments", key


def test_nonrobust_covariance_is_the_workbenchs_unadjusted():
    arguments = _genesis_step({"model_family": "ols", "covariance": "non-robust",
                               "branches": [{"branch_id": "b", "covariance": "nonrobust", "outcome": "y", "predictors": ["x"]}]})
    normalized, notes = _normalize(arguments)
    spec = normalized["changes"]["steps"][0]["spec"]
    assert spec["covariance"] == "unadjusted" and spec["branches"][0]["covariance"] == "unadjusted"
    assert arguments["changes"]["steps"][0]["spec"]["branches"][0]["covariance"] == "nonrobust"  # input untouched
    assert len(notes) == 2 and all("unadjusted" in note for note in notes)
