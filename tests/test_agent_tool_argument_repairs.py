"""Arguments with one possible meaning are corrected with a note; anything else stays refused."""
import pytest

from workbench.agent import tools as tools_module
from workbench.agent.operations import OperationRegistry, normalize_operation_target
from workbench.agent.toolsets import _question_scope_has_no_playbooks


@pytest.mark.parametrize("text,expected", [
    ('{"steps": [{"a": [1, 2]', {"steps": [{"a": [1, 2]}]}),
    ('{"note": "a } in text", "b": {"c": 1}', {"note": "a } in text", "b": {"c": 1}}),
])
def test_text_missing_only_its_closing_brackets_has_one_meaning(text, expected):
    assert tools_module._strict_json(tools_module._close_open_brackets(text)) == expected


@pytest.mark.parametrize("text", [
    '{"a": [1}',          # a bracket closes the wrong thing: where the missing one goes is a guess
    '{"a": 1}}',          # one too many
    '{"a": "cut off',     # stopped inside a value
    '{"a": 1,',           # stopped before the next field
    '{"a":',
    '{"steps": [',        # cut after an opening bracket: closing it would invent an empty plan
    '{"steps": [{',
])
def test_text_with_more_than_one_reading_is_not_repaired(text):
    assert tools_module._close_open_brackets(text) is None


def test_a_refusal_reaches_the_model_with_where_the_text_breaks():
    from tests.test_agent_tool_contract_recovery import _execute, _registry, _request

    registry, _, calls = _registry()
    refused = _execute(registry, {**_request(), "changes": '{"steps": [{"a": 1}}]}'})
    detail = next(item for item in refused.error_details if item.get("path") == "changes")
    assert detail["text_breaks_at"] == 19 and detail["text_before_break"].endswith("}}") and not calls


def test_a_refusal_says_where_the_text_breaks():
    problem = tools_module._json_text_problem('{"steps": [{"a": 1}}]}')
    assert problem == {"text_breaks_at": 19, "text_before_break": '{"steps": [{"a": 1}}',
                       "text_expected_close": "]", "text_found": "}"}


@pytest.mark.parametrize("scope,given,expected", [
    ("question", {"scope": "question", "source": {}}, []),
    ("analysis", {"scope": "analysis", "source": {}}, None),
])
def test_only_a_question_scope_plan_gets_its_empty_playbook_list(scope, given, expected):
    assert _question_scope_has_no_playbooks({"completion": given})["completion"].get("playbooks") == expected


def test_playbooks_the_model_chose_are_left_for_validation():
    plan = {"completion": {"scope": "question", "playbooks": ["cross-sectional-analysis"]}}
    assert _question_scope_has_no_playbooks(plan) is plan


def _normalize(**arguments):
    return normalize_operation_target(OperationRegistry(), arguments)


def test_a_step_named_as_the_operation_runs_as_a_workflow_of_that_step():
    result = _normalize(operation_id="statistical.explore", target={}, changes={"operation": "summarize", "selected_columns": ["a"]})
    assert result["operation_id"] == "operation.multi_step"
    step = result["changes"]["steps"][0]
    assert step["operation_id"] == "statistical.explore" and step["spec"]["selected_columns"] == ["a"] and step["depends_on"] == []


def test_an_operation_that_stands_alone_is_not_wrapped():
    registry = OperationRegistry()
    named = sorted(registry.natural_language_operation_ids())[0]
    assert normalize_operation_target(registry, {"operation_id": named, "target": {}, "changes": {}})["operation_id"] == named


def test_a_source_beside_the_spec_moves_inside_it_and_a_contradiction_stays():
    source = {"from_step": "a", "output": "produced_dataset"}
    moved = _normalize(operation_id="operation.multi_step", target={}, changes={"steps": [
        {"step_id": "b", "operation_id": "statistical.explore", "source": source, "spec": {"operation": "summarize"}}]})
    step = moved["changes"]["steps"][0]
    assert "source" not in step and step["spec"]["source"] == source
    both = _normalize(operation_id="operation.multi_step", target={}, changes={"steps": [
        {"step_id": "b", "operation_id": "statistical.explore", "source": source, "spec": {"source": {"from_step": "c"}}}]})
    assert "source" in both["changes"]["steps"][0]


def test_workflow_identity_and_dependencies_beside_the_steps_are_dropped():
    result = _normalize(operation_id="operation.multi_step", target={}, changes={"workflow_id": "x", "depends_on": [], "steps": []})
    assert result["changes"] == {"steps": []}
