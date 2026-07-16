"""P6-1 — a rejected tool call must say what was wrong with it.

`invalid_tool_arguments` on its own is not feedback, it is a shrug. The live
DeepSeek smoke retried `propose_operation` five times, each attempt a guess,
because the reason never came back.
"""

from __future__ import annotations

import asyncio
import json

from workbench.agent.operations import OperationRegistry
from workbench.agent.tools import (
    MAX_VALIDATION_ERRORS,
    MAX_VALIDATION_MESSAGE_CHARS,
    ToolDefinition,
    ToolRegistry,
    validation_details,
)


def _registry(schema: dict) -> ToolRegistry:
    def handler(arguments, context):
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="t",
            version="v1",
            input_schema=schema,
            side_effect="none",
            handler=handler,
        )
    )
    return registry


_PLAIN_SCHEMA = {
    "type": "object",
    "required": ["owner_run_id", "op_node_id"],
    "properties": {
        "owner_run_id": {"type": "string"},
        "op_node_id": {"type": "string"},
    },
    "additionalProperties": False,
}


def test_a_rejected_call_reports_every_independent_problem_at_once() -> None:
    """Plain schemas: don't drip one fix per round trip."""

    details = validation_details(
        _PLAIN_SCHEMA, {"owner_run_id": 5, "typo_field": "x"}
    )

    messages = " ".join(d["message"] for d in details)
    assert "'op_node_id' is a required property" in messages
    assert "typo_field" in messages
    assert any(d["path"] == "owner_run_id" and "not of type 'string'" in d["message"] for d in details)


def test_a_oneOf_union_reports_the_branch_the_caller_meant() -> None:
    """The regression this was built for: the real propose_operation schema.

    A oneOf reports one root error that says the instance "is not valid under
    any of the given schemas" and echoes the entire payload — useless, and
    large. The actionable error lives in its context.
    """

    schema = OperationRegistry().proposal_tool_schema()
    # The exact mistake DeepSeek made: casts sent as a JSON string.
    bad = {
        "operation_id": "data.columns.cast",
        "operation_version": "v1",
        "target": {
            "run_id": "r",
            "node_ref": "stage:cleaned",
            "casts": '[{"column": "wage", "target_dtype": "string"}]',
        },
        "preconditions": {"active_head_run_id": "r"},
        "changes": {"casts": [{"column": "wage", "target_dtype": "string"}]},
        "evidence_refs": ["e"],
        "expected_effect": ["x"],
        "risks": ["r"],
    }

    details = validation_details(schema, bad)

    assert details, "a rejected union call must still explain itself"
    primary = details[0]
    assert primary["path"] == "target.casts"
    assert "is not of type 'array'" in primary["message"]
    assert primary["constraint"] == "type"
    # The unhelpful root message must not be what we hand back.
    assert not any(
        "is not valid under any of the given schemas" in d["message"] for d in details
    )


def test_a_union_never_reports_another_operations_requirements() -> None:
    """Wrong advice is worse than the shrug it replaces.

    `best_match` ranks errors heuristically and knows nothing about the
    `operation_id` discriminator, so it offered model.rerun's "'node_hash' is a
    required property" for a data.columns.cast proposal — a field that does not
    exist on that operation. The caller would have chased it forever.
    """

    schema = OperationRegistry().proposal_tool_schema()
    bad_cast = {
        "operation_id": "data.columns.cast",
        "operation_version": "v1",
        "target": {"run_id": "r", "node_ref": "n", "casts": '[{"c": 1}]'},
        "preconditions": {"active_head_run_id": "r"},
        "changes": {"casts": [{"column": "wage", "target_dtype": "string"}]},
        "evidence_refs": ["e"],
        "expected_effect": ["x"],
        "risks": ["r"],
    }

    details = validation_details(schema, bad_cast)

    blob = json.dumps(details)
    assert "node_hash" not in blob
    assert "forest_node_key" not in blob
    assert any(d["path"] == "target.casts" for d in details)


def test_a_union_reports_the_right_branch_for_each_operation() -> None:
    """The discriminator, not a heuristic, decides which contract applies."""

    schema = OperationRegistry().proposal_tool_schema()
    bad_rerun = {
        "operation_id": "model.rerun",
        "operation_version": "v1",
        "target": {"run_id": "r", "node_ref": "n"},  # missing node_hash
        "preconditions": {
            "context_version": "v",
            "context_fingerprint": "f",
            "active_head_run_id": "r",
            "owner_resolution": "o",
        },
        "changes": {},
        "evidence_refs": ["e"],
        "expected_effect": ["x"],
        "risks": ["r"],
    }

    details = validation_details(schema, bad_rerun)

    blob = json.dumps(details)
    # model.rerun genuinely does require node_hash — here saying so is correct.
    assert "node_hash" in blob
    assert "casts" not in blob


def test_feedback_is_bounded_in_count_and_size() -> None:
    """Messages embed the caller's own value; echo it back, but not unbounded."""

    huge = "x" * 5_000
    details = validation_details(
        {"type": "object", "properties": {"a": {"type": "integer"}}}, {"a": huge}
    )
    assert len(details) == 1
    assert len(details[0]["message"]) <= MAX_VALIDATION_MESSAGE_CHARS + len("… [truncated]")
    assert details[0]["message"].endswith("… [truncated]")

    many = {"type": "object", "required": [f"f{i}" for i in range(12)]}
    assert len(validation_details(many, {})) == MAX_VALIDATION_ERRORS


def test_the_details_reach_the_model_in_the_tool_payload() -> None:
    registry = _registry(_PLAIN_SCHEMA)

    result = asyncio.run(
        registry.execute(
            {"tool_id": "t", "tool_call_id": "c1", "arguments": {"owner_run_id": 5}},
            session_id="s1",
        )
    )

    assert result.ok is False
    # The stable code stays — existing consumers key on it.
    assert result.error == "invalid_tool_arguments"
    payload = result.to_payload()
    assert payload["error_details"] == result.error_details
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "op_node_id" in serialized and "required property" in serialized


def test_a_successful_call_keeps_its_existing_payload_shape() -> None:
    registry = _registry(_PLAIN_SCHEMA)

    result = asyncio.run(
        registry.execute(
            {
                "tool_id": "t",
                "tool_call_id": "c1",
                "arguments": {"owner_run_id": "r", "op_node_id": "n"},
            },
            session_id="s1",
        )
    )

    assert result.ok is True
    assert result.to_payload() == {"ok": True, "output": {"ok": True}, "error": None}


def test_a_handler_failure_carries_no_validation_details() -> None:
    """Only schema rejections have a schema explanation to give."""

    def handler(arguments, context):
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            tool_id="t",
            version="v1",
            input_schema={"type": "object"},
            side_effect="none",
            handler=handler,
        )
    )

    result = asyncio.run(
        registry.execute({"tool_id": "t", "tool_call_id": "c", "arguments": {}}, session_id="s")
    )

    assert result.ok is False
    assert result.error == "RuntimeError"
    assert result.error_details is None
    assert "error_details" not in result.to_payload()
