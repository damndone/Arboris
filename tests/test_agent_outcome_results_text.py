"""An executed workflow's results reach the Agent as whole steps, never cut mid-JSON."""
from __future__ import annotations

import json

from workbench.agent.operation_outcome import results_text

READ_WITH = {"owner_run_id": "run-a", "op_node_id": "stage:cleaned", "active_head_run_id": "run-a",
             "operation_record_id": "oprec_1"}


def _step(step_id: str, size: int) -> dict:
    return {"step_id": step_id, "operation_id": "statistical.explore", "status": "completed", "read_with": READ_WITH,
            "artifacts": [{"artifact_id": f"exploration_{step_id}", "result": {"values": "v" * size}}]}


def _shown(text: str) -> list[dict]:
    head = text.split("\n", 1)[0]
    return json.loads(head[head.index(": [") + 2:])


def test_steps_that_fit_are_whole_and_share_one_read_scope():
    text = results_text([_step("a", 100), _step("b", 100), _step("c", 100)], budget=2_000)
    assert [step["step_id"] for step in _shown(text)] == ["a", "b", "c"]
    assert "read_with" not in json.dumps(_shown(text))
    assert text.count('"owner_run_id": "run-a"') == 1
    assert "Not shown" not in text


def test_steps_past_the_budget_are_named_with_their_artifact_ids():
    # Round 7, QRData 033: the third step was cut off and read back with an extra call.
    text = results_text([_step("a", 1_000), _step("b", 1_000), _step("c", 1_000)], budget=2_500)
    assert [step["step_id"] for step in _shown(text)] == ["a", "b"]
    stubs = json.loads(text.split("Not shown for room", 1)[1].split(": ", 1)[1])
    assert stubs == [{"step_id": "c", "operation_id": "statistical.explore", "status": "completed",
                      "artifact_ids": ["exploration_c"]}]


def test_one_step_larger_than_the_room_is_bounded_not_dropped():
    text = results_text([_step("a", 50_000)], budget=4_000)
    assert len(text) < 8_000
    assert "exploration_a" in text


def test_steps_with_different_read_scopes_keep_their_own():
    other = {**_step("b", 10), "read_with": {**READ_WITH, "operation_record_id": "oprec_2"}}
    shown = _shown(results_text([_step("a", 10), other]))
    assert [step["read_with"]["operation_record_id"] for step in shown] == ["oprec_1", "oprec_2"]
