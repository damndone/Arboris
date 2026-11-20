"""A plan update that leaves out steps keeps them, as it keeps the question and criteria.

2026-11-08 NVIDIA position binary_logit.specific.r1: the Agent sent update_plan with only a
completion contract; the schema refused it ("'steps' is a required property") and it resent the
whole plan, one model request for nothing. A first plan still needs its steps.
"""
from __future__ import annotations

import asyncio
import copy

from jsonschema import Draft202012Validator

from tests.test_read_only_analysis import _Fixture
from workbench.agent.toolsets import _UPDATE_PLAN_SCHEMA

QUESTION = "How does income relate to the probability of owning a home?"
STEPS = [{"step_id": "explore", "title": "Explore", "operation_ids": ["statistical.explore"]}]


def _update(runtime, arguments):
    result = asyncio.run(runtime.orchestrator.tool_registry("chain-a").execute(
        {"tool_call_id": "plan", "tool_id": "update_plan", "arguments": arguments}, session_id="chain-session"))
    return result


def test_the_schema_no_longer_requires_steps():
    assert Draft202012Validator(_UPDATE_PLAN_SCHEMA).is_valid({"question": QUESTION})


def test_an_update_without_steps_keeps_the_current_steps(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message", {"role": "user", "content": QUESTION})
    first = _update(runtime, {"question": QUESTION, "criteria": ["Fixed before results"], "steps": STEPS})
    assert first.ok and first.output.get("saved") is not False, first.output
    later = _update(runtime, {"criteria": ["Fixed before results", "Report the marginal effect"]})
    assert later.ok and later.output.get("saved") is not False, later.output
    plan = runtime.orchestrator.plan_store.current("chain-session")
    assert [step.step_id for step in plan.steps] == ["explore"] and plan.question == QUESTION
    assert list(plan.criteria) == ["Fixed before results", "Report the marginal effect"]


def test_a_first_plan_without_steps_is_refused(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message", {"role": "user", "content": QUESTION})
    result = _update(runtime, {"question": QUESTION})
    assert result.output.get("saved") is False and "steps" in result.output["error"]


def test_returned_steps_can_be_updated_without_copying_server_audit_fields(tmp_path):
    """The NVIDIA open.r3 trace copied the returned steps and spent a request on their audit keys."""
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message", {"role": "user", "content": QUESTION})
    first = _update(runtime, {"question": QUESTION, "criteria": ["Fixed before results"], "steps": STEPS})
    returned = first.output["plan"]
    saved = runtime.orchestrator.plan_store.current("chain-session").to_dict()
    allowed = _UPDATE_PLAN_SCHEMA["properties"]["steps"]["items"]["properties"]

    assert all(set(step) <= set(allowed) for step in returned["steps"])
    restored = {key: value for key, value in returned.items() if key != "step_state"}
    restored["steps"] = [{**step, **returned["step_state"][step["step_id"]]} for step in returned["steps"]]
    assert restored == saved
    assert returned["step_state"]["explore"]["permission_class"] == "analyze"
    assert returned["step_state"]["explore"]["added_after_results"] is False

    writable = copy.deepcopy(returned["steps"])
    writable[0]["status"] = "running"
    later = _update(runtime, {"steps": writable})
    assert later.ok and later.output["saved"] is True, later
    current = runtime.orchestrator.plan_store.current("chain-session")
    assert current.steps[0].status == "running"
    assert current.steps[0].added_after_results is False
    assert current.steps[0].completed_operation_ids == ()


def test_returned_audit_evidence_still_cannot_be_submitted_as_plan_input(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message", {"role": "user", "content": QUESTION})
    first = _update(runtime, {"question": QUESTION, "steps": STEPS})
    saved = runtime.orchestrator.plan_store.current("chain-session").to_dict()
    returned = first.output["plan"]
    invalid = [{**step, **returned["step_state"][step["step_id"]]} for step in returned["steps"]]

    refused = _update(runtime, {"steps": invalid})

    assert not refused.ok and refused.error == "invalid_tool_arguments"
    assert runtime.orchestrator.plan_store.current("chain-session").to_dict() == saved
