"""v1.8.10: fitting a tool's output into its budget must not hide what it cut.

Found in the step-1 browser acceptance. `inspect_result_summary` has an 8 KB
budget; a Callaway-Sant'Anna summary on the example dataset is 12 KB. The
projection gave every nested level half of its parent's budget however small
the siblings were, so the 11 KB `result_summary` was squeezed into 4 KB, and it
dropped nested keys without a trace. The Agent received the ATT and no interval,
and nothing told it the interval existed.
"""

from __future__ import annotations

import json

from workbench.agent.tools import _bounded_tool_output, _project_value


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def test_a_nested_section_may_use_the_room_its_small_siblings_leave() -> None:
    payload = {
        "request_id": "r",
        "node": {"id": "model:cs_did_1"},
        "result_summary": {"evidence": "x" * 5_000},
        "large_tail": "y" * 5_000,
    }
    projected = _bounded_tool_output(payload, 8_192)
    assert _size(projected) <= 8_192
    assert projected["result_summary"] == payload["result_summary"]


def test_a_nested_key_that_was_cut_is_named() -> None:
    value = {"first": "a" * 300, "second": "b" * 300, "third": "c" * 300}
    projected = _project_value(value, 500)
    assert _size(projected) <= 500
    assert projected["first"] == value["first"]
    cut = set(projected.get("_omitted_keys", [])) | set(projected.get("_truncated_keys", {}))
    for key in value:
        if projected.get(key) != value[key]:
            assert key in cut, f"{key} was cut and nothing says so"


def test_a_shortened_list_says_how_much_was_kept() -> None:
    value = {"rows": [{"estimate": index, "std_error": 0.1} for index in range(40)]}
    projected = _project_value(value, 400)
    assert _size(projected) <= 400
    kept = len(projected["rows"])
    assert 0 < kept < 40
    assert projected["_truncated_keys"]["rows"] == f"kept {kept} of 40"


def test_small_fields_after_a_large_one_are_kept() -> None:
    value = {"large": "z" * 2_000, "status": "complete", "count": 3}
    projected = _project_value(value, 600)
    assert _size(projected) <= 600
    assert projected["status"] == "complete" and projected["count"] == 3


def test_earlier_sections_keep_priority_over_later_ones() -> None:
    value = {"model_evidence": "m" * 900, "run_level": "r" * 900}
    projected = _project_value(value, 1_200)
    assert projected["model_evidence"] == value["model_evidence"]
    assert "run_level" in projected.get("_omitted_keys", []) or "run_level" in projected.get("_truncated_keys", {})


def test_a_value_within_budget_is_returned_unchanged() -> None:
    value = {"a": [1, 2, 3], "b": {"c": "d"}}
    assert _project_value(value, 1_000) is value
    assert _bounded_tool_output(value, 1_000) is value


def test_list_rows_are_kept_whole() -> None:
    rows = [{"label": index, "estimate": 0.123456789, "ci": [0.1, 0.2]} for index in range(30)]
    projected = _project_value({"rows": rows}, 500)
    assert all(row in rows for row in projected["rows"])
