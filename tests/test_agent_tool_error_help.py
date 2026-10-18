"""Refusals of the Agent's own input say what to write instead (v1.9.1 smoke findings)."""

from __future__ import annotations

import asyncio

from workbench.agent.contract_help import help_for
from workbench.agent.orchestrator import _UPDATE_PLAN_SCHEMA
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
