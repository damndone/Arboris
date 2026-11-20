"""Lossless same-request schema reuse; no Provider or execution kernel is used."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json

import pytest

from tests.test_agent_context_tools import _load_provider_type, _write_project_run
from workbench.agent import context as context_module
from workbench.agent.context import ContextBuilder
from workbench.agent.context_tools import InspectOperationContractRequest, InspectResultSummaryRequest
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.operation_request_refs import wire_schema
from workbench.agent.operations import OperationRegistry
from workbench.agent.protocol import chain_agent_protocol, step_reference
from workbench.agent.session import JsonlSessionRepository
from workbench.agent import tool_receipts
from workbench.agent.tools import ToolDefinition


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _published_protocol(registry):
    return chain_agent_protocol(registry) + "\n" + "\n".join(
        "      " + name + ": " + json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
        for name, spec in step_reference().items())


def _fixture(tmp_path, operations, mutate=None, *, published=False):
    project = tmp_path / "project"
    _write_project_run(project)
    provider = _load_provider_type()(project)
    registry = OperationRegistry()
    arguments = {"request_id": "contract", "owner_run_id": "run-a", "op_node_id": "model:ols_1",
                 "active_head_run_id": "run-a", "operation_id": "operation.multi_step",
                 "step_operation_ids": list(operations)}
    output = provider.inspect_operation_contract(InspectOperationContractRequest(
        **{**arguments, "step_operation_ids": tuple(operations)}), operation_registry=registry)
    # Match TurnJournal.result_message's public JSON boundary before the WAL.
    result = json.loads(json.dumps({"ok": True, "error": None, "output": output},
                                   ensure_ascii=False, sort_keys=True, allow_nan=False))
    if mutate is not None:
        mutate(result)
    repo = JsonlSessionRepository(tmp_path / "workbench")
    repo.create_session("s", chain_id="chain-a", role="chain")
    protocol = _published_protocol(registry) if published else chain_agent_protocol(registry)
    repo.append("s", "custom_message", {"message_type": "agent_protocol", "audience": "model",
        "name": "workbench_agent_protocol", "content": protocol})
    call = {"tool_call_id": "inspect-contract", "tool_id": "inspect_operation_contract", "arguments": arguments}
    repo.append("s", "message", {"role": "assistant", "content": "", "tool_calls": [call]})
    identity = {"session_id": "s", "command_id": "command", "provider_step": 1,
                "tool_call_id": call["tool_call_id"], "invocation_id": "inspection", "tool_call": call}
    tool_receipts.persist(repo, **identity, payload=result)
    tool_receipts.repair_message(repo, **identity)
    summary = provider.inspect_result_summary(InspectResultSummaryRequest(
        request_id="summary", owner_run_id="run-a", op_node_id="model:ols_1", active_head_run_id="run-a"))
    repo.append("s", "message", {"role": "assistant", "content": "", "tool_calls": [
        {"tool_call_id": "inspect-summary", "tool_id": "inspect_result_summary", "arguments": {}}]})
    repo.append("s", "message", {"role": "tool", "tool_call_id": "inspect-summary", "name": "inspect_result_summary",
        "content": json.dumps({"ok": True, "error": None, "output": summary}, ensure_ascii=False, sort_keys=True)})
    tools = [ToolDefinition(tool_id="run_operation", version="v1", side_effect="proposal",
        input_schema=wire_schema(registry.proposal_tool_schema()), handler=lambda args, ctx: None).descriptor()]
    return repo, tools, result


def _request(repo, tools):
    class Capture:
        def __init__(self):
            self.requests = []

        async def stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent.text_delta(request.request_id, "Read-only inspection retained.")
            yield ModelStreamEvent.done(request.request_id)

    adapter = Capture()
    core = AgentCore(repo, AgentEventStream(repo.root), adapter, session_id="s", tools=tools)
    asyncio.run(core.prompt("Continue from the inspected contract."))
    assert len(adapter.requests) == 1
    return adapter.requests[0]


def _contract_message(messages):
    return next(message for message in messages if message.get("role") == "tool"
                and message.get("tool_call_id") == "inspect-contract")


def _restore(result, tools):
    restored = copy.deepcopy(result)
    contract = restored["output"]["contract"]
    branch = next(branch for branch in tools[0]["input_schema"]["oneOf"]
                  if branch.get("properties", {}).get("operation_id", {}).get("const") == "operation.multi_step")
    editable = branch["properties"]["changes"]
    assert contract["editable_schema"]["schema_sha256"] == hashlib.sha256(_canonical(editable)).hexdigest()
    contract["editable_schema"] = editable
    published = step_reference()
    for name, spec in contract["step_vocabulary"]["step_operations"].items():
        if "same_as_published" not in spec:
            continue
        ref = spec.pop("same_as_published")
        assert ref["name"] == "workbench_agent_protocol:" + name
        assert ref["schema_sha256"] == hashlib.sha256(_canonical(published[name])).hexdigest()
        spec.update({field: published[name][field] for field in ref["unchanged_fields"]})
    return restored


@pytest.mark.parametrize("operation_id", ["model.genesis", "report.compose"])
def test_legacy_published_request_reconstructs_both_schema_consumers_without_rewriting_the_wal(tmp_path, operation_id):
    repo, tools, original = _fixture(tmp_path, (operation_id, "iv.ar_confidence"), published=True)
    baseline = ContextBuilder(repo).build("s")
    before = repo._session_path("s").read_bytes()

    request = _request(repo, tools)
    projected = json.loads(_contract_message(request.messages)["content"])

    assert "same_as_published" in projected["output"]["contract"]["step_vocabulary"]["step_operations"][operation_id]
    assert _canonical(_restore(projected, tools)) == _canonical(original)
    assert projected["output"]["contract"]["step_vocabulary"]["step_operations"]["iv.ar_confidence"] == original["output"]["contract"]["step_vocabulary"]["step_operations"]["iv.ar_confidence"]
    assert len(_canonical(projected)) < len(_canonical(original))
    assert repo._session_path("s").read_bytes().startswith(before)
    assert json.loads(_contract_message(ContextBuilder(repo).build("s").messages)["content"]) == original
    old_summary = next(message for message in baseline.messages if message.get("tool_call_id") == "inspect-summary" and message.get("role") == "tool")
    assert old_summary in request.messages


@pytest.mark.parametrize("case", ["missing_protocol", "changed_protocol", "changed_tool_schema", "unknown_schema_field", "error"])
def test_unavailable_or_changed_declarations_and_unknown_or_error_payloads_stay_full(tmp_path, case):
    def mutate(result):
        if case == "unknown_schema_field":
            result["output"]["contract"]["step_vocabulary"]["step_operations"]["model.genesis"]["future_scientific_field"] = {"required": True}
        elif case == "error":
            result.update(ok=False, error="OperationContractUnavailableError", output=None)

    repo, tools, original = _fixture(tmp_path, ("model.genesis",), mutate, published=True)
    if case in {"missing_protocol", "changed_protocol"}:
        protocol = "No generated schema declarations."
        if case == "changed_protocol":
            protocol = _published_protocol(OperationRegistry())
            declared = step_reference()["model.genesis"]
            changed = {**declared, "summary": "Changed schema declaration"}
            protocol = protocol.replace(json.dumps(declared, ensure_ascii=False, separators=(",", ":")),
                                        json.dumps(changed, ensure_ascii=False, separators=(",", ":")))
        repo.append("s", "custom_message", {"message_type": "agent_protocol", "audience": "model",
            "name": "workbench_agent_protocol", "content": protocol})
    if case == "changed_tool_schema":
        branch = next(branch for branch in tools[0]["input_schema"]["oneOf"]
                      if branch.get("properties", {}).get("operation_id", {}).get("const") == "operation.multi_step")
        branch["properties"]["changes"] = {**branch["properties"]["changes"], "description": "Changed declaration"}
    before = _contract_message(ContextBuilder(repo).build("s").messages)

    request = _request(repo, tools)

    assert _contract_message(request.messages) == before
    assert json.loads(before["content"]) == original


def test_fresh_reader_projection_is_deterministic_and_keeps_original_entries(tmp_path):
    repo, tools, original = _fixture(tmp_path, ("model.genesis", "report.compose"), published=True)
    source = ContextBuilder(repo).build("s")
    source_leaf = source.source_entry_ids[-1]
    request = _request(repo, tools)
    assert "same_as_published" in _contract_message(request.messages)["content"]
    before = repo._session_path("s").read_bytes()
    fresh = JsonlSessionRepository(repo.root)
    rebuilt = ContextBuilder(fresh).build("s", leaf_entry_id=source_leaf)

    first = context_module.project_published_contracts(source, tools)
    second = context_module.project_published_contracts(rebuilt, tools)

    assert first == second and first.source_entry_ids == source.source_entry_ids
    assert first.fingerprint == hashlib.sha256(_canonical(first.messages)).hexdigest()
    assert repo._session_path("s").read_bytes() == before
    assert json.loads(_contract_message(rebuilt.messages)["content"]) == original


def test_on_demand_protocol_keeps_all_four_requested_contracts_in_the_actual_request(tmp_path):
    operations = ("statistical.explore", "model.genesis", "postestimation.margins", "report.compose")
    repo, tools, original = _fixture(tmp_path, operations)
    before = repo._session_path("s").read_bytes()

    request = _request(repo, tools)

    returned = json.loads(_contract_message(request.messages)["content"])
    assert returned == original
    assert set(returned["output"]["contract"]["step_vocabulary"]["step_operations"]) == set(operations)
    assert "same_as_published" not in _contract_message(request.messages)["content"]
    assert repo._session_path("s").read_bytes().startswith(before)
