"""Durable server request references preserve branch, payload and recovery identity."""
from __future__ import annotations

import asyncio
import copy
import importlib
import importlib.util
import json

import pytest
from jsonschema import Draft202012Validator

from workbench.agent.operations import OperationRegistry
from workbench.agent.session import EntryRef, JsonlSessionRepository
from workbench.agent.toolsets import build_chain_tool_registry


def refs():
    assert importlib.util.find_spec("workbench.agent.operation_request_refs"), "durable request references are missing"
    return importlib.import_module("workbench.agent.operation_request_refs")


def request():
    return {"operation_id": "operation.multi_step", "operation_version": "v1",
        "target": {"run_id": "source", "node_ref": "stage:source", "artifact_id": "data"},
        "preconditions": {"context_version": "node-operation-context/v1", "context_fingerprint": "source-context",
            "active_head_run_id": "source", "owner_resolution": "single_candidate"},
        "changes": {"steps": [{"step_id": "summary", "operation_id": "statistical.explore",
            "spec": {"operation": "tabulate", "selected_columns": ["x"]}}]},
        "evidence_refs": ["source/data"], "expected_effect": ["Summarize the verified source."], "risks": []}


def origin(repository, *, session_id="s", invocation="inspection", step=1):
    call = {"tool_call_id": invocation, "tool_id": "inspect_analysis_completion", "arguments": {}}
    metadata = {"command_id": "command", "provider_step": step, "tool_call_id": invocation,
        "invocation_id": invocation}
    entry = repository.append_once(session_id, "tool_intent", {**metadata, "session_id": session_id,
        "tool_call": call}, key=invocation, stage="tool_intent")
    return metadata, entry


def prepared(tmp_path):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    metadata, entry = origin(repository)
    arguments = request()
    binding = {"chain_id": "c", "active_head_run_id": "source", "plan_sha256": "a" * 64,
        "contract_sha256": "b" * 64, "verified_manifest_sha256": "c" * 64}
    return repository, metadata, entry, arguments, binding


def publish(repository, metadata, arguments, binding):
    return refs().persist(repository, session_id="s", metadata=metadata, binding=binding,
        requests=[{"kind": "sensitivity", "label": "Declared sensitivity", "arguments": arguments}],
        operation_registry=OperationRegistry())


def test_unexpected_validator_runtime_error_is_not_reclassified_as_an_unavailable_request(monkeypatch):
    module = refs()
    fault = RuntimeError("unexpected validator fault")

    def broken_validator(*args):
        raise fault

    monkeypatch.setattr(module, "validate", broken_validator)
    with pytest.raises(RuntimeError, match="unexpected validator fault") as raised:
        module.validate_request(request(), OperationRegistry())
    assert raised.value is fault


@pytest.mark.parametrize("error_name", ["OperationValidationError", "UnknownOperationError"])
def test_known_operation_contract_refusals_remain_unavailable(monkeypatch, error_name):
    from workbench.agent.operation_definitions import UnknownOperationError
    from workbench.contracts.common.errors import OperationValidationError

    module = refs()
    fault = {"OperationValidationError": OperationValidationError,
             "UnknownOperationError": UnknownOperationError}[error_name]("declared contract refusal")

    def refused_contract(*args):
        raise fault

    monkeypatch.setattr(module, "validate", refused_contract)
    with pytest.raises(module.RequestRefError, match="does not satisfy its operation contract") as raised:
        module.validate_request(request(), OperationRegistry())
    assert raised.value.__cause__ is fault


def test_reference_is_private_bounded_append_once_and_readable_after_restart(tmp_path):
    from workbench.agent.context import ContextBuilder

    repository, metadata, _, arguments, binding = prepared(tmp_path)
    original = copy.deepcopy(arguments)
    [offered] = publish(repository, metadata, arguments, binding)
    assert len(offered["request_ref"]) < 100
    assert publish(repository, metadata, arguments, binding) == [offered]
    rebuilt = JsonlSessionRepository(repository.root)
    saved = refs().read(rebuilt, session_id="s", request_ref=offered["request_ref"])
    assert saved["arguments"] == original and saved["binding"] == binding
    assert arguments == original
    entries = [e for e in rebuilt.get_branch("s") if e.entry_type == refs().ENTRY_TYPE]
    assert len(entries) == 1
    assert len(json.dumps(entries[0].payload, ensure_ascii=False, sort_keys=True).encode()) <= refs().MAX_SOURCE_BYTES
    assert not ContextBuilder(rebuilt).build("s").messages


@pytest.mark.parametrize("fault", ["string_changes", "missing_evidence", "oversized", "too_many"])
def test_incomplete_invalid_or_over_limit_requests_never_become_references(tmp_path, fault):
    repository, metadata, _, arguments, binding = prepared(tmp_path)
    items = [{"kind": "sensitivity", "label": "Declared sensitivity", "arguments": arguments}]
    if fault == "string_changes":
        arguments["changes"] = '{"steps": ['
    elif fault == "missing_evidence":
        del arguments["evidence_refs"]
    elif fault == "oversized":
        arguments["expected_effect"] = ["x" * refs().MAX_SOURCE_BYTES]
    else:
        items *= refs().MAX_REQUESTS + 1
    with pytest.raises(refs().RequestRefError):
        refs().persist(repository, session_id="s", metadata=metadata, binding=binding,
            requests=items, operation_registry=OperationRegistry())
    assert not any(e.entry_type == refs().ENTRY_TYPE for e in repository.get_branch("s"))


@pytest.mark.parametrize("fault", ["user_message", "unverified_private_entry", "other_session", "off_branch", "tampered", "duplicate"])
def test_reference_cannot_select_user_json_other_scope_or_unverified_content(tmp_path, fault):
    repository, metadata, anchor, arguments, binding = prepared(tmp_path)
    [offered] = publish(repository, metadata, arguments, binding)
    reference = offered["request_ref"]
    [entry] = [e for e in repository.get_branch("s") if e.entry_type == refs().ENTRY_TYPE]
    session_id = "s"
    if fault in {"user_message", "unverified_private_entry"}:
        fake = repository.append("s", "message" if fault == "user_message" else refs().ENTRY_TYPE, entry.payload)
        reference = reference.replace(entry.entry_id, fake.entry_id)
    elif fault == "other_session":
        repository.create_session("other", chain_id="c", role="chain")
        session_id = "other"
    elif fault == "off_branch":
        repository.rewind("s", EntryRef("s", anchor.entry_id))
    else:
        path = repository._session_path("s")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if fault == "tampered":
            rows[-1]["payload"]["requests"][0]["arguments"]["target"]["run_id"] = "different-source"
        else:
            rows.append(rows[-1])
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(refs().RequestRefError):
        refs().read(repository, session_id=session_id, request_ref=reference)


def test_run_operation_keeps_full_envelope_and_accepts_only_an_exclusive_reference():
    registry = build_chain_tool_registry(context_tools=(), proposal_tool_schema=OperationRegistry().proposal_tool_schema,
        update_plan=lambda a, c: None, run_operation=lambda a, c: None,
        plan_analysis=lambda a, c: None, inspect_analysis_completion=lambda a, c: None)
    schema = next(d["input_schema"] for d in registry.descriptors() if d["tool_id"] == "run_operation")
    validator = Draft202012Validator(schema)
    reference = "opreq:" + "a" * 32 + ":0"
    assert validator.is_valid(request())
    assert validator.is_valid({"request_ref": reference})
    for overrides in [{"changes": {}}, {"target": {}}, {"evidence_refs": []}, {"operation_id": "operation.multi_step"}]:
        assert not validator.is_valid({"request_ref": reference, **overrides})
    for value in ["../source", {}, "opreq:" + "a" * 32 + ":99"]:
        assert not validator.is_valid({"request_ref": value})


@pytest.mark.parametrize("fault", ["string_changes", "missing_target", "misplaced_target", "target_type", "model_patch"])
def test_full_envelope_help_still_selects_its_operation_after_adding_refs(fault):
    from tests.test_agent_tool_feedback_examples import request as model_request

    registry = build_chain_tool_registry(context_tools=(), proposal_tool_schema=OperationRegistry().proposal_tool_schema,
        update_plan=lambda a, c: None, run_operation=lambda a, c: pytest.fail("invalid operation executed"),
        plan_analysis=lambda a, c: None, inspect_analysis_completion=lambda a, c: None)
    arguments = request()
    if fault == "string_changes":
        arguments["changes"] = '{"steps": ['
    elif fault == "missing_target":
        del arguments["target"]
    elif fault == "misplaced_target":
        arguments["changes"]["target"] = arguments.pop("target")
    elif fault == "target_type":
        arguments["target"]["run_id"] = 42
    else:
        arguments = model_request()
        arguments["changes"]["model_type"] = {"old": "linear_mixed_effects", "new": "linear_mixed_effects"}
    result = asyncio.run(registry.execute({"tool_call_id": "full", "tool_id": "run_operation",
        "arguments": arguments}, session_id="s"))
    assert not result.ok and result.error == "invalid_tool_arguments"
    assert not any("request_ref" in str(detail) for detail in result.error_details)
    if fault == "string_changes":
        assert any(d.get("expected_type") == "object" and d.get("actual_type") == "string"
            and "caller supplied the string" in d["message"] for d in result.error_details)
    elif fault == "missing_target":
        assert any(d.get("required_paths") == ["arguments.target"] for d in result.error_details)
    elif fault == "misplaced_target":
        assert any(d.get("example_arguments_patch") == [{"op": "move", "from": "/changes/target", "path": "/target"}]
            for d in result.error_details)
    elif fault == "target_type":
        assert any(d["path"] == "target.run_id" and d.get("expected_type") == "string" for d in result.error_details)
    else:
        assert any(d.get("example_arguments", {}).get("changes", {}).get("model_type") == "linear_mixed_effects"
            for d in result.error_details)


def test_reference_failures_share_the_full_requests_two_attempt_scope(tmp_path):
    from workbench.agent.recovery import record_failure
    from workbench.agent.tool_receipts import tool_call_sha256

    repository, metadata, _, arguments, binding = prepared(tmp_path)
    [offered] = publish(repository, metadata, arguments, binding)
    full = {"tool_call_id": "full", "tool_id": "run_operation", "arguments": arguments}
    short = {"tool_call_id": "short", "tool_id": "run_operation", "arguments": {"request_ref": offered["request_ref"]}}
    digest = tool_call_sha256(short)
    first = record_failure(repository, "s", "next-command", 1, full, {"ok": False, "error": "bad fit"})
    second = record_failure(repository, "s", "next-command", 2, short, {"ok": False, "error": "bad fit"})
    assert first["scope_sha256"] == second["scope_sha256"]
    assert first["attempts"] == 1 and second["attempts"] == second["limit"] == 2 and second["exhausted"]
    assert tool_call_sha256(short) == digest and short["arguments"] == {"request_ref": offered["request_ref"]}


@pytest.mark.parametrize("lose_before_receipt", [True, False])
def test_inspection_crash_preserves_exact_receipt_boundary(tmp_path, monkeypatch, lose_before_receipt):
    from tests.test_agent_core_restart import ProcessLost, setup
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.tools import ToolResult
    from workbench.agent.turn_journal import TurnRecoveryRequired

    class Adapter:
        def __init__(self, inspect=False):
            self.inspect, self.calls = inspect, 0

        async def stream(self, model_request):
            self.calls += 1
            if self.inspect:
                self.inspect = False
                yield ModelStreamEvent.tool_call_delta(model_request.request_id,
                    {"tool_call_id": "inspection", "tool_id": "inspect_analysis_completion", "arguments": {}})
                yield ModelStreamEvent.done(model_request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(model_request.request_id, "Inspection recorded.")
                yield ModelStreamEvent.done(model_request.request_id)

    class Runtime:
        calls = 0

        async def execute(self, call, *, session_id, metadata):
            self.calls += 1
            offered = refs().persist(repository, session_id=session_id, metadata=metadata, binding={"head": "source"},
                requests=[{"kind": "sensitivity", "label": "Declared sensitivity", "arguments": request()}],
                operation_registry=OperationRegistry())
            if lose_before_receipt:
                raise ProcessLost()
            return ToolResult(tool_call_id=call["tool_call_id"], tool_id=call["tool_id"], ok=True,
                output={"operation_requests": offered})

    async def scenario():
        runtime = Runtime()
        core, store, repo = setup(tmp_path, Adapter(inspect=True), runtime=runtime)
        nonlocal repository
        repository = repo
        append = repo.append_once

        def lose_public_message(*args, **kwargs):
            if kwargs.get("stage") == "tool_result":
                raise ProcessLost()
            return append(*args, **kwargs)

        if not lose_before_receipt:
            monkeypatch.setattr(repo, "append_once", lose_public_message)
        with pytest.raises(ProcessLost):
            await core.prompt("Inspect delivery.", budget={"max_steps": 3, "timeout_s": 30})
        [turn] = store.list_active()
        adapter = Adapter()
        resumed, _, fresh = setup(tmp_path, adapter, runtime=runtime, create=False)
        if lose_before_receipt:
            with pytest.raises(TurnRecoveryRequired, match="receipt"):
                await resumed.resume(turn.turn_id)
            assert adapter.calls == 0
        else:
            assert await resumed.resume(turn.turn_id) == "Inspection recorded."
            message = next(e for e in fresh.get_branch("session-a") if e.payload.get("role") == "tool")
            reference = json.loads(message.payload["content"])["output"]["operation_requests"][0]["request_ref"]
            assert refs().read(fresh, session_id="session-a", request_ref=reference)["arguments"] == request()
        assert runtime.calls == 1
        assert len([e for e in fresh.get_branch("session-a") if e.entry_type == refs().ENTRY_TYPE]) == 1

    repository = None
    asyncio.run(scenario())
