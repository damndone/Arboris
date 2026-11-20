"""Offline replay of misplaced operation-envelope fields, without provider calls."""

import asyncio
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from workbench.agent.operations import OperationRegistry
from workbench.agent.tools import (
    MAX_VALIDATION_DETAIL_CHARS, MAX_VALIDATION_MESSAGE_CHARS, ToolDefinition, ToolRegistry,
)
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



def test_a_step_closed_with_the_wrong_bracket_is_named_with_the_bracket_to_write():
    """QRData 352 (08cfac50 round): `"depends_on": ["x"]]}` three times; the step object was never closed."""
    registry, _, calls = _registry()
    arguments = _request()
    arguments["changes"] = '{"steps": [{"step_id": "fit", "operation_id": "model.genesis", "spec": {}, "depends_on": ["prep"]]}}'

    refused = _execute(registry, arguments)

    assert not refused.ok and not calls
    detail = next(d for d in refused.error_details if d["path"] == "changes")
    assert "']' comes before the object opened last is closed; write '}' first" in detail["message"]
    assert len(detail["message"]) <= MAX_VALIDATION_MESSAGE_CHARS
    assert "operation was not executed" in detail["message"]

def test_run_operation_description_names_the_outer_evidence_position():
    registry = build_chain_tool_registry(context_tools=(),
        proposal_tool_schema=OperationRegistry().proposal_tool_schema,
        update_plan=lambda arguments, context: None, run_operation=lambda arguments, context: None,
        plan_analysis=lambda arguments, context: None, inspect_analysis_completion=lambda arguments, context: None)
    description = next(d["description"] for d in registry.descriptors() if d["tool_id"] == "run_operation")
    assert all(field in description for field in ("evidence_refs", "expected_effect", "risks", "changes"))
    assert "top-level" in description and "inspected" in description
    assert "changes must be a JSON object" in description
    assert "expected_artifacts) go on that step in changes.steps, never on changes itself" in description
    assert "never a JSON-encoded string" in description


@pytest.mark.parametrize("text", ["{\"steps\": [", "{\"steps\": [" + " " * 5000],
    ids=["malformed", "oversized-malformed"])
def test_malformed_changes_string_names_the_callers_type_error_without_a_repaired_proposal(text):
    registry, _, calls = _registry()
    arguments = _request()
    arguments["changes"] = text
    original = copy.deepcopy(arguments)

    refused = _execute(registry, arguments)

    assert not refused.ok and refused.error == "invalid_tool_arguments" and not calls
    detail = next(d for d in refused.error_details if d["path"] == "changes")
    assert detail["constraint"] == "type"
    assert detail["expected_type"] == "object" and detail["actual_type"] == "string"
    assert "caller supplied the string" in detail["message"]
    assert "operation was not executed" in detail["message"]
    assert "server did not convert an object to string" in detail["message"]
    assert "arguments.changes" in detail["message"]
    assert "inspect_operation_contract" in detail["message"]
    assert len(detail["message"]) <= MAX_VALIDATION_MESSAGE_CHARS
    assert len(json.dumps(detail)) < MAX_VALIDATION_DETAIL_CHARS
    assert not any("example_arguments" in d or "example_arguments_patch" in d
        for d in refused.error_details)
    assert arguments == original


@pytest.mark.parametrize("tool_id,changes,normalize", [
    ("inspect_x", "{\"steps\": [", None),
    ("run_operation", [], None),
    ("run_operation", {}, lambda arguments: {**arguments, "changes": "{\"steps\": ["}),
], ids=["other-tool", "other-type", "not-supplied-as-string"])
def test_changes_string_attribution_requires_the_callers_string_and_matching_contract(tool_id, changes, normalize):
    registry = ToolRegistry()
    calls = []
    registry.register(ToolDefinition(tool_id=tool_id, version="v1", side_effect="none",
        input_schema={"type": "object", "properties": {"changes": {"type": "object"}}},
        handler=lambda arguments, context: calls.append(arguments), normalize=normalize))
    refused = asyncio.run(registry.execute({"tool_call_id": "replay", "tool_id": tool_id,
        "arguments": {"changes": changes}}, session_id="session"))
    assert not refused.ok and refused.error == "invalid_tool_arguments" and not calls
    assert not any("caller supplied the string" in d["message"] for d in refused.error_details)


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


def test_a_plan_that_claims_an_exclusion_no_step_applies_is_refused(tmp_path):
    """QRData 397: 'excluding Palm Beach county' with no filter fitted all 67 counties."""
    import pandas as pd
    import pytest
    from workbench.agent.orchestration_proposals import OrchestrationProposals
    from workbench.contracts.common.errors import OperationValidationError

    data = tmp_path / "florida.parquet"
    pd.DataFrame({"county": ["Alachua", "PalmBeach", "Lee"], "buchanan00": [1, 2, 3], "perot96": [4, 5, 6]}).to_parquet(data)
    proposals = OrchestrationProposals.__new__(OrchestrationProposals)
    proposals.context_provider = type("Provider", (), {"project_root": tmp_path})()
    proposals.repository = type("Repository", (), {"root": tmp_path / "workbench"})()
    import workbench.data_operations as operations
    original = operations.resolve_data_column_cast_context
    operations.resolve_data_column_cast_context = lambda *a, **k: {"source_artifact_path": "../../florida.parquet"}
    (tmp_path / "runs" / "run").mkdir(parents=True)
    fit = [{"step_id": "fit", "operation_id": "model.genesis", "spec": {"branches": [{"branch_id": "b", "outcome": "buchanan00", "predictors": ["perot96"]}]}}]
    target = {"run_id": "run", "node_ref": "stage:cleaned"}
    try:
        with pytest.raises(OperationValidationError, match="excludes 'PalmBeach' \\(column county\\), but the source still has 1 of 3 rows"):
            proposals._preflight_claimed_exclusions({"changes": {"steps": fit}, "target": target,
                                                     "expected_effect": ["Fit OLS excluding Palm Beach county"]})
        # 3724e8b2 round: the plan no longer said it, but the request did.
        request = "As the Palm Beach county is an outlier, we fit the model without Palm Beach county."
        with pytest.raises(OperationValidationError, match="the request asks to exclude 'PalmBeach' \\(column county\\), but the source still has 1 of 3 rows"):
            proposals._preflight_claimed_exclusions({"changes": {"steps": fit}, "target": target,
                                                     "expected_effect": ["Fit OLS of Buchanan00 on Perot96"]}, request)
        proposals._preflight_claimed_exclusions({"changes": {"steps": [{"step_id": "s", "operation_id": "data.subset", "spec": {}}, *fit]},
                                                 "target": target, "expected_effect": ["Fit OLS"]}, request)
        proposals._preflight_claimed_exclusions({"changes": {"steps": fit}, "target": target,
                                                 "expected_effect": ["Fit OLS"]}, "Fit the model on all counties.")
        for effect, steps in ((["Fit OLS excluding Palm Beach county"], [{"step_id": "s", "operation_id": "data.subset", "spec": {}}, *fit]),
                              (["Fit OLS without the leverage points"], fit),
                              (["Fit OLS on all counties"], fit)):
            proposals._preflight_claimed_exclusions({"changes": {"steps": steps}, "target": target, "expected_effect": effect})
    finally:
        operations.resolve_data_column_cast_context = original


def test_pack_step_frame_checks_run_before_the_person_is_asked(tmp_path):
    """QRData 374 (55ce11c1 round): periods written as ranges became a pending proposal."""
    import pandas as pd
    import pytest
    from workbench.agent.orchestration_proposals import OrchestrationProposals
    from workbench.contracts.common.errors import OperationValidationError

    panel = pd.DataFrame([{"state": state, "year": year, "sales": float(state * 10 + year - 2000)}
                          for state in (1, 2, 3, 4) for year in range(2000, 2008)])
    panel.to_parquet(tmp_path / "panel.parquet")
    proposals = OrchestrationProposals.__new__(OrchestrationProposals)
    proposals.context_provider = type("Provider", (), {"project_root": tmp_path})()
    proposals.repository = type("Repository", (), {"root": tmp_path / "workbench"})()
    import workbench.data_operations as operations
    original = operations.resolve_data_column_cast_context
    operations.resolve_data_column_cast_context = lambda *a, **k: {"source_artifact_path": "../../panel.parquet"}
    (tmp_path / "runs" / "run").mkdir(parents=True)
    target = {"run_id": "run", "node_ref": "stage:cleaned"}
    options = {"unit_column": "state", "time_column": "year", "treated_unit": "1"}

    def plan(pre, post, **spec):
        return {"target": target, "changes": {"steps": [{"step_id": "fit", "operation_id": "synthetic_control.fit", "spec": {
            "input_mode": "typed", "column_bindings": {"outcomes": ["sales"]},
            "options": {**options, "pre_periods": pre, "post_periods": post}, **spec}}]}}
    try:
        with pytest.raises(OperationValidationError, match="workflow step fit: SYNTHETIC_CONTROL_PERIOD_GAPS.*2001, 2002, 2003, 2006"):
            proposals._preflight_pack_steps(plan([2000, 2004], [2005, 2007]))
        proposals._preflight_pack_steps(plan(list(range(2000, 2005)), [2005, 2006, 2007]))
        # A step that reads another step's output is checked at execution, where that frame exists.
        proposals._preflight_pack_steps(plan([2000, 2004], [2005, 2007], source={"from_step": "prep", "output": "produced_dataset"}))
    finally:
        operations.resolve_data_column_cast_context = original



def test_a_test_familys_own_data_checks_run_before_the_person_is_asked(tmp_path):
    """QRData 070 (08cfac50 round): group_order ["1", "2"] for two counted rows was approved, then refused."""
    import pandas as pd
    import pytest
    from workbench.agent.orchestration_proposals import OrchestrationProposals
    from workbench.contracts.common.errors import OperationValidationError

    pd.DataFrame({"events": [139, 154], "trials": [12933, 12938], "arm": ["fish oil", "placebo"]}).to_parquet(tmp_path / "trial.parquet")
    proposals = OrchestrationProposals.__new__(OrchestrationProposals)
    proposals.context_provider = type("Provider", (), {"project_root": tmp_path})()
    proposals.repository = type("Repository", (), {"root": tmp_path / "workbench"})()
    import workbench.data_operations as operations
    original = operations.resolve_data_column_cast_context
    operations.resolve_data_column_cast_context = lambda *a, **k: {"source_artifact_path": "../../trial.parquet"}
    (tmp_path / "runs" / "run").mkdir(parents=True)
    target = {"run_id": "run", "node_ref": "stage:cleaned"}

    def plan(**options):
        return {"target": target, "changes": {"steps": [{"step_id": "prop_test", "operation_id": "test.proportions", "spec": {
            "input_mode": "frame", "column_bindings": {"columns": ["events", "trials"]},
            "options": {"events_column": "events", "trials_column": "trials", **options}}}]}}
    try:
        with pytest.raises(OperationValidationError, match=r"workflow step prop_test: test.proportions: proportions group_order "
                                                           r"must list the two groups \['row 1', 'row 2'\] \(without group_column"):
            proposals._preflight_pack_steps(plan(group_order=["1", "2"]))
        with pytest.raises(OperationValidationError, match=r"group_order must list the two groups \['fish oil', 'placebo'\]"):
            proposals._preflight_pack_steps(plan(group_column="arm", group_order=["fish", "placebo"]))
        proposals._preflight_pack_steps(plan(group_order=["row 2", "row 1"]))
        # QRData 079 (08cfac50 replay): input_mode omitted is filled as compilation fills it, not refused.
        omitted = plan(group_order=["row 2", "row 1"])
        del omitted["changes"]["steps"][0]["spec"]["input_mode"]
        proposals._preflight_pack_steps(omitted)
        proposals._preflight_pack_steps(plan(group_column="arm", group_order=["placebo", "fish oil"]))
        proposals._preflight_pack_steps(plan())
        # A family with no preflight, and a step reading another step's output, are checked when they run.
        proposals._preflight_pack_steps({"target": target, "changes": {"steps": [{"step_id": "t", "operation_id": "test.chi_square",
            "spec": {"input_mode": "frame", "column_bindings": {"columns": ["events", "arm"]}, "options": {}}}]}})
        stepped = plan(group_order=["1", "2"])
        stepped["changes"]["steps"][0]["spec"]["source"] = {"from_step": "prep", "output": "produced_dataset"}
        proposals._preflight_pack_steps(stepped)
    finally:
        operations.resolve_data_column_cast_context = original

def test_period_lists_the_engine_would_refuse_are_refused_before_approval():
    """QRData 374 (6af0a0da round): range objects and a one-period pre list were approved, then failed in the engine."""
    import pytest
    from workbench.agent.workflow_contracts import validate_workflow_steps
    from workbench.contracts.common.errors import OperationValidationError

    def fit(pre, post):
        return [{"step_id": "fit", "operation_id": "synthetic_control.fit", "spec": {
            "input_mode": "typed", "column_bindings": {"outcomes": ["sales"]},
            "options": {"unit_column": "state", "time_column": "year", "treated_unit": "1",
                        "pre_periods": pre, "post_periods": post}}}]

    with pytest.raises(OperationValidationError, match="pre_periods lists each period, not a range object"):
        validate_workflow_steps(fit([{"low": 2000, "high": 2004}], [2005, 2006]))
    with pytest.raises(OperationValidationError, match="SYNTHETIC_CONTROL_INSUFFICIENT_PRE_PERIODS"):
        validate_workflow_steps(fit([2004], [2005, 2006]))
    with pytest.raises(OperationValidationError, match="must be disjoint"):
        validate_workflow_steps(fit([2003, 2004], [2004, 2005]))
    # What the engine accepts stays accepted: unsorted lists and string labels.
    validate_workflow_steps(fit([2004, 2003], [2005]))
    validate_workflow_steps(fit(["2003Q1", "2003Q2"], ["2003Q3"]))


def test_closed_fields_remain_available_from_the_authoritative_contract_tool():
    """The fields whose absence caused refusals ride in the index and match the contract tool."""
    from workbench.agent.context_tools_support.node_tools import _step_vocabulary_view
    from workbench.agent.protocol import step_vocabulary_lines
    from workbench.agent.workflow_contracts import workflow_step_vocabulary
    from workbench.agent.workflow_contract_parts.signature import published_step_signature

    index = step_vocabulary_lines()
    operations = ("test.t_tests", "treatment_effects.estimate", "statistical.derive_numeric", "time_series.granger")
    vocabulary = workflow_step_vocabulary()
    contracts = _step_vocabulary_view(vocabulary, operations)["step_operations"]
    for operation_id in operations:
        line = next(item for item in index.splitlines() if item.startswith(f"  - {operation_id} -> "))
        assert line.endswith(f" Fields: {published_step_signature(operation_id)}.")
        assert contracts[operation_id]["required"] == vocabulary["step_operations"][operation_id]["required"]
        assert contracts[operation_id]["fields"] and published_step_signature(operation_id)
    assert '"ATE"|"ATT"|"ATC"' in published_step_signature("treatment_effects.estimate")
    assert 'operator: "natural_log"|"multiply"' in published_step_signature("statistical.derive_numeric")
    assert "  - model.genesis -> " in index and "Fields:" not in next(
        item for item in index.splitlines() if item.startswith("  - model.genesis -> "))


def test_a_step_field_refusal_carries_the_steps_fields_and_a_semantic_one_does_not():
    import pytest
    from workbench.agent.workflow_contracts import validate_workflow_steps
    from workbench.contracts.common.errors import OperationValidationError

    with pytest.raises(OperationValidationError) as shape:
        validate_workflow_steps([{"step_id": "t", "operation_id": "test.chi_square", "spec": {
            "input_mode": "frame", "column_bindings": {"row": "a", "column": "b"}, "options": {}}}])
    assert "column_bindings.row is not a field here" in str(shape.value)
    assert 'Fields of test.chi_square: input_mode: "frame"; column_bindings: {columns: [string] (2-n)}' in str(shape.value)
    with pytest.raises(OperationValidationError) as semantic:
        validate_workflow_steps([{"step_id": "d", "operation_id": "statistical.derive_numeric", "spec": {
            "recipes": [{"operator": "multiply", "input_columns": ["a"], "output_name": "b"}]}}])
    assert "requires 2 distinct input column(s)" in str(semantic.value) and "Fields of" not in str(semantic.value)


def test_the_mode_notice_matches_the_review_policy():
    from workbench.http.agent_turn_routes import _execution_mode_notice

    assert "read-only analysis included" in _execution_mode_notice("ask", "proposal_only")
    assert "read-only analysis runs at once" in _execution_mode_notice("ask", "auto_read_only")
    assert "Auto within plan" in _execution_mode_notice("auto", "auto_read_only")


def test_a_read_tool_takes_owner_run_id_as_its_missing_run_id_and_says_so():
    """172d65cd round: 6 show_dataset_rows calls sent owner_run_id (the other read tools' name) and no run_id."""
    import asyncio
    from workbench.agent.tools import ToolDefinition, ToolRegistry

    seen = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        tool_id="show_rows", version="v1", side_effect="none",
        input_schema={"type": "object", "required": ["run_id", "node_id"], "additionalProperties": False,
                      "properties": {"run_id": {"type": "string"}, "node_id": {"type": "string"}}},
        handler=lambda arguments, context: seen.append(arguments) or {"shown": True}))
    result = asyncio.run(registry.execute({"tool_call_id": "c1", "tool_id": "show_rows", "arguments": {
        "owner_run_id": "run_a", "active_head_run_id": "run_b", "node_id": "stage:cleaned"}}, session_id="s"))
    assert result.ok and seen == [{"run_id": "run_a", "node_id": "stage:cleaned"}]
    assert any("used owner_run_id run_a" in note for note in result.output["workbench_notes"])
    only_head = asyncio.run(registry.execute({"tool_call_id": "c2", "tool_id": "show_rows", "arguments": {
        "active_head_run_id": "run_b", "node_id": "stage:cleaned"}}, session_id="s"))
    assert not only_head.ok and only_head.error == "invalid_tool_arguments"


def test_an_undeclared_source_refusal_names_the_source_to_write_or_how_to_chain():
    import pytest
    from workbench.agent.workflow_contracts import validate_workflow_steps
    from workbench.contracts.common.errors import OperationValidationError

    subset = {"step_id": "subset_data", "operation_id": "data.subset",
              "spec": {"columns": ["y", "x"], "filters": [{"column": "x", "op": "gt", "value": 0}]}}
    fit = {"step_id": "fit", "operation_id": "model.genesis", "depends_on": ["subset_data"],
           "spec": {"model_family": "ols", "branches": [{"branch_id": "b", "outcome": "y", "predictors": ["x"]}]}}
    # Named directly in depends_on, the one producer is the source (3f281a47 round, 8 of 24 refusals).
    assert validate_workflow_steps([subset, fit])[1]["spec"]["source"]["from_step"] == "subset_data"
    # Reached only through a step that produces no dataset, the producer is not named: the refusal says what to write.
    look = {"step_id": "look", "operation_id": "statistical.explore", "depends_on": ["subset_data"],
            "spec": {"operation": "summarize", "selected_columns": ["x"]}}
    with pytest.raises(OperationValidationError) as one:
        validate_workflow_steps([subset, look, {**fit, "depends_on": ["look"]}])
    assert 'Add "source": {"from_step": "subset_data", "output": "produced_dataset"} to the spec of fit.' in str(one.value)
    with pytest.raises(OperationValidationError) as two:
        validate_workflow_steps([subset, {**subset, "step_id": "other"}, {**fit, "depends_on": ["subset_data", "other"]}])
    assert "are independent: make one of them read the other" in str(two.value)
    fit["spec"]["source"] = {"from_step": "subset_data", "output": "produced_dataset"}
    validate_workflow_steps([subset, fit])


def test_a_required_field_with_one_allowed_value_is_filled_when_omitted_and_checked_when_given():
    """input_mode was omitted 8 times in the 172d65cd and 3724e8b2 rounds; "frame" is its only value."""
    import pytest
    from workbench.agent.workflow_contracts import validate_workflow_steps
    from workbench.contracts.common.errors import OperationValidationError

    spec = {"column_bindings": {"time": "t", "cause": "x", "effect": "y"}, "options": {"time_order": "sort_by_time", "max_lag": 2}}
    [step] = validate_workflow_steps([{"step_id": "g", "operation_id": "time_series.granger", "spec": spec}])
    assert step["spec"]["input_mode"] == "frame"
    with pytest.raises(OperationValidationError, match="input_mode must be one of: frame"):
        validate_workflow_steps([{"step_id": "g", "operation_id": "time_series.granger", "spec": {**spec, "input_mode": "summary"}}])


def test_a_proposal_nested_in_changes_and_a_source_on_changes_say_where_they_belong():
    """3f281a47 round: QRData 033 wrote the proposal inside changes; 368 and 381 put source on changes."""
    registry, _, calls = _registry()
    nested = {"changes": {key: value for key, value in _request().items() if key != "changes"}}
    nested["changes"]["steps"] = _request()["changes"]["steps"]
    refused = _execute(registry, nested)
    assert not refused.ok and not calls
    assert any("beside changes" in detail.get("hint", "") for detail in refused.error_details)
    sourced = _request()
    sourced["changes"]["source"] = {"from_step": "summary", "output": "produced_dataset"}
    refused = _execute(registry, sourced)
    assert not refused.ok and not calls
    assert any("changes.steps[i].spec.source" in detail.get("hint", "") for detail in refused.error_details)


def test_a_step_field_or_an_earlier_proposal_on_changes_says_where_it_belongs():
    """6af0a0da round: QRData 349/352/397 put expected_artifacts on changes; 381 wrote steps_existing."""
    registry, _, calls = _registry()
    request = _request()
    request["changes"]["expected_artifacts"] = ["model"]
    refused = _execute(registry, request)
    assert not refused.ok and not calls
    [hint] = [detail["hint"] for detail in refused.error_details if detail.get("hint")]
    assert hint == "expected_artifacts belongs to one step: set changes.steps[i].expected_artifacts on each step that needs it."
    request = _request()
    request["changes"]["steps_existing"] = list(request["changes"]["steps"])
    refused = _execute(registry, request)
    assert not refused.ok and not calls
    [hint] = [detail["hint"] for detail in refused.error_details if detail.get("hint")]
    assert hint.startswith("changes holds only steps; steps of an earlier operation are not listed again.")
    assert hint.endswith("set target.node_ref to that node.")


def test_recipe_and_range_refusals_say_what_to_write():
    """3f281a47 round: QRData 106/380 named derived_variable operands; 380 wrote an expression; 355 an open range."""
    from workbench.agent.workflow_contracts import validate_workflow_steps
    from workbench.contracts.common.errors import OperationValidationError

    def recipe(recipe_operation, parameters, inputs=("a", "b")):
        return [{"step_id": "make", "operation_id": "data.feature_recipe", "spec": {
            "recipe_id": "r", "recipe_operation_id": recipe_operation, "inputs": list(inputs), "output": "c",
            "parameters": parameters}}]

    with pytest.raises(OperationValidationError, match=r"inputs\[0\] <operator> inputs\[1\]"):
        validate_workflow_steps(recipe("derived_variable", {"left": "a", "right": "b"}))
    with pytest.raises(OperationValidationError, match=r"denominator is 'a \+ b'; it must be one of inputs \['a', 'b'\]"):
        validate_workflow_steps(recipe("ratio", {"numerator": "a", "denominator": "a + b", "zero_policy": "fail_closed"}))
    recode = [{"step_id": "code", "operation_id": "data.recode", "spec": {
        "column": "educ", "output": "hs", "rules": [{"from": {"low": 0, "high": 11}, "to": 0}, {"from": {"low": 12}, "to": 1}]}}]
    with pytest.raises(OperationValidationError, match=r"rules\[1\]\.from\.high is required"):
        validate_workflow_steps(recode)
