"""Proposal audit records repeat only what the model has not already seen for that proposal."""
import json

from workbench.agent.context import ContextBuilder
from workbench.agent.session import JsonlSessionRepository

CHANGES = {"steps": [{"operation_id": "statistical.explore", "spec": {"operation": "corr", "selected_columns": ["rent", "density"]}}]}


def _proposal(**overrides):
    record = {"record_type": "revision", "proposal_id": "p1", "operation_id": "operation.multi_step", "revision": 1,
              "target": {"run_id": "r1"}, "preconditions": {"active_head_run_id": "r1"}, "changes": CHANGES,
              "expected_effect": ["correlation"], "risks": ["none"], "fingerprint": "f1", "status": "pending"}
    return {**record, **overrides}


def _confirmation(**overrides):
    record = {"record_type": "confirmation", "proposal_id": "p1", "operation_id": "operation.multi_step", "revision": 1,
              "fingerprint": "f1", "target": {"run_id": "r1"}, "preconditions": {"active_head_run_id": "r1"},
              "changes": CHANGES, "actor_type": "user", "confirmed_at": "2026-10-22T00:00:00+00:00", "status": "confirmed"}
    return {**record, **overrides}


def _record(repository, message_type, field, record):
    repository.append("s", "custom_message", {"message_type": message_type, "audience": "model",
        "content": json.dumps(record, ensure_ascii=False, sort_keys=True), field: record})


def _session(tmp_path, *, confirmation):
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="s", role="chain")
    repository.append("s", "message", {"role": "user", "content": "Check the correlation."})
    repository.append("s", "message", {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "run_operation", "arguments": "{}"}}]})
    repository.append("s", "message", {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
        {"error": None, "ok": True, "output": {"proposal": _proposal(), "requires_confirmation": True}})})
    _record(repository, "operation_proposal", "proposal", _proposal())
    _record(repository, "operation_confirmation", "confirmation", confirmation)
    return repository


def test_records_already_shown_in_the_tool_result_keep_only_new_fields(tmp_path):
    repository = _session(tmp_path, confirmation=_confirmation())
    messages = ContextBuilder(repository).build("s").messages
    proposal, confirmation = (json.loads(m["content"]) for m in messages[-2:])
    assert {k: proposal[k] for k in ("record_type", "proposal_id", "revision", "fingerprint", "status")} == {
        "record_type": "revision", "proposal_id": "p1", "revision": 1, "fingerprint": "f1", "status": "pending"}
    assert "changes" not in proposal and "changes" in proposal["repeated_fields"]
    assert "changes" not in confirmation and "preconditions" not in confirmation
    assert confirmation["record_type"] == "confirmation" and confirmation["status"] == "confirmed"
    assert confirmation["actor_type"] == "user" and confirmation["confirmed_at"] == "2026-10-22T00:00:00+00:00"
    # The stored audit record is untouched.
    stored = [e for e in repository.get_branch("s") if e.entry_type == "custom_message"]
    assert stored[-1].payload["confirmation"]["changes"] == CHANGES
    assert json.loads(stored[-1].payload["content"])["changes"] == CHANGES


def test_a_confirmation_of_an_edited_revision_is_shown_in_full(tmp_path):
    edited = {"steps": [{"operation_id": "statistical.explore", "spec": {"operation": "corr", "selected_columns": ["rent"]}}]}
    confirmation = _confirmation(revision=2, fingerprint="f2", changes=edited)
    repository = _session(tmp_path, confirmation=confirmation)
    shown = json.loads(ContextBuilder(repository).build("s").messages[-1]["content"])
    assert shown == confirmation


def test_bounded_summaries_are_left_as_written(tmp_path):
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="s", role="chain")
    repository.append("s", "message", {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
        {"output": {"proposal": _proposal()}})})
    summary = json.dumps({"proposal_id": "p1", "details_omitted": "too long"})
    repository.append("s", "custom_message", {"message_type": "operation_proposal", "audience": "model",
                                              "content": summary, "proposal": _proposal()})
    assert ContextBuilder(repository).build("s").messages[-1]["content"] == summary


def test_a_record_stored_before_its_tool_result_is_still_shortened(tmp_path):
    """The real order (2026-10-23 tapes): the audit record is written while the tool runs,
    before the run_operation result that carries the same proposal."""
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="s", role="chain")
    repository.append("s", "message", {"role": "user", "content": "Check the correlation."})
    repository.append("s", "message", {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "run_operation", "arguments": "{}"}}]})
    _record(repository, "operation_proposal", "proposal", _proposal())
    repository.append("s", "message", {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
        {"error": None, "ok": True, "output": {"proposal": _proposal(), "requires_confirmation": True}})})
    messages = ContextBuilder(repository).build("s").messages
    record = next(json.loads(m["content"]) for m in messages if m["role"] == "system" and '"proposal_id"' in m["content"])
    assert "changes" not in record and "changes" in record["repeated_fields"]
