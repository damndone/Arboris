"""A step row says what the call was about, and never breaks the transcript."""
import pytest

from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tool_activity import describe_tool_call
from workbench.http.agent_route_projection import _messages


@pytest.mark.parametrize(("tool", "arguments", "expected"), [
    ("run_operation", {"operation_id": "operation.multi_step", "changes": {"steps": [
        {"operation_id": "statistical.explore", "spec": {"operation": "tabulate", "selected_columns": ["a", "b"]}}]}},
     "Frequency table of a, b"),
    ("run_operation", {"operation_id": "operation.multi_step", "changes": '{"steps": ['
                       '{"operation_id": "statistical.explore", "spec": {"operation": "tabulate", "selected_columns": ["a"]}},'
                       '{"operation_id": "statistical.explore", "spec": {"operation": "corr", "selected_columns": ["a", "b"]}}]}'},
     "Frequency table of a +1 more"),
    ("inspect_operation_contract", {"operation_id": "matching.att", "owner_run_id": "r1"}, "matching.att"),
    ("show_dataset_rows", {"columns": ["wage", "age"], "run_id": "r1"}, "wage, age"),
    ("inspect_data_schema", {"owner_run_id": "r1", "op_node_id": "stage:cleaned"}, None),
    ("update_plan", {"title": "x"}, None),
    ("run_operation", {"operation_id": "x", "changes": "{not json"}, None),
    ("run_operation", {"operation_id": "x", "changes": "{not json", "expected_effect": ["Paired t-test of  a and b"]}, "Paired t-test of a and b"),
    ("run_operation", "not a mapping", None),
])
def test_described(tool, arguments, expected):
    assert describe_tool_call(tool, arguments) == expected


def test_a_long_target_is_bounded():
    assert len(describe_tool_call("show_dataset_rows", {"columns": ["c" * 50] * 20})) == 140


def test_tool_messages_carry_target_and_duration(tmp_path):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    call = {"tool_call_id": "c1", "tool_id": "show_dataset_rows", "arguments": {"columns": ["wage"]}}
    repository.append("s", "message", {"role": "assistant", "content": "", "tool_calls": [call], "stop_reason": "tool_calls"})
    repository.append("s", "tool_intent", {"tool_call": call})
    repository.append("s", "message", {"role": "tool", "content": '{"ok": true}', "name": "show_dataset_rows", "tool_call_id": "c1"})
    tool = [message for message in _messages(repository, "s") if message["role"] == "tool"][0]
    assert tool["activity"]["target"] == "wage"
    assert tool["activity"]["seconds"] >= 0


def test_a_starting_step_announces_its_target():
    from types import SimpleNamespace
    from workbench.agent.tool_batches import _start

    emitted = []
    core = SimpleNamespace(session_id="s", _active_command_id="c", events=SimpleNamespace(
        emit=lambda session, kind, payload, command_id: emitted.append((kind, payload))))
    _start(core, {"tool_call_id": "t", "tool_id": "run_operation", "arguments": {"expected_effect": "Paired t-test of a, b"}})
    assert emitted == [("tool_execution_start", {"tool_call_id": "t", "tool_id": "run_operation", "target": "Paired t-test of a, b"})]
