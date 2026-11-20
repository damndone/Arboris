"""The run_operation declaration the model sees carries only the operations it can call.

2026-11-13: the declaration was 38 KB of every request, and half of it was full branches for typed
operations outside the envelope's operation_id enum (seven data.* ones), which no call could
select. Callable operations keep their whole contract; validation uses the complete declaration.
"""
from __future__ import annotations

import json

from tests.test_read_only_analysis import _Fixture


def _schemas(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    registry = runtime.orchestrator.tool_registry("chain-a")
    definition = registry._definitions["run_operation"]
    sent = next(tool for tool in registry.descriptors() if tool["tool_id"] == "run_operation")["input_schema"]
    return definition, sent


def _branches(schema):
    return {branch["properties"]["operation_id"]["const"]: branch for branch in schema["oneOf"]
            if "const" in branch.get("properties", {}).get("operation_id", {})}


def test_every_callable_operation_keeps_its_whole_contract(tmp_path):
    definition, sent = _schemas(tmp_path)
    full, model = _branches(definition.input_schema), _branches(sent)
    callable_ids = set(definition.input_schema["properties"]["operation_id"]["enum"])
    assert set(model) == callable_ids
    assert all(model[operation] == full[operation] for operation in callable_ids)


def test_only_uncallable_branches_are_left_out(tmp_path):
    definition, sent = _schemas(tmp_path)
    dropped = [branch for branch in definition.input_schema["oneOf"] if branch not in sent["oneOf"]]
    callable_ids = set(definition.input_schema["properties"]["operation_id"]["enum"])
    assert dropped and all(branch["properties"]["operation_id"]["const"] not in callable_ids for branch in dropped)
    assert {key: value for key, value in sent.items() if key != "oneOf"} == \
        {key: value for key, value in definition.input_schema.items() if key != "oneOf"}


def test_the_declaration_sent_is_shorter(tmp_path):
    definition, sent = _schemas(tmp_path)
    assert len(json.dumps(sent)) < 0.7 * len(json.dumps(definition.input_schema))
