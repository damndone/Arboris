"""A protected column's values stay home when a result names the column beside them.

2026-11-06 risk review, finding 2 (rechecked at 9e09502e): a real tabulate result's
frequency entries {variable: "name", value: "<person>", count} reached the provider, and the
audit said name was redacted because only the neighbouring column description was. Grouped
results ({group_by: "name", groups: [{value}]}), filters ({column, operator, value}) and
by-group tests ({by_group: {column, groups: [{key}]}, results: [{group}]}) leaked the same way.
Asserted on the HTTP body the provider receives, from results the real computations produce.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_egress import REMOTE, _send
from workbench.agent.context_tools_support.summaries_public import _public_operation_artifact_result
from workbench.agent.workflow_runtime import _named_test_by_group
from workbench.egress import EgressPolicy, egress_project, read_audit, save_policy
from workbench.statistical_exploration_compute import execute_exploration
from workbench.statistical_exploration_spec import ExplorationSpec, FilterSpec
from workbench.statistical_tests import run_named_statistical_test

PEOPLE = ["PERSON_ALPHA", "PERSON_BETA", "PERSON_ALPHA", "PERSON_GAMMA"]


def _frame(repeat: int = 1) -> pd.DataFrame:
    rows = len(PEOPLE) * repeat
    return pd.DataFrame({"name": PEOPLE * repeat, "region": ["east", "west"] * (rows // 2),
                         "x": [float(i % 7) for i in range(rows)], "y": [float((i * 3) % 11) for i in range(rows)]})


def _exploration(spec: ExplorationSpec) -> dict:
    public, _ = _public_operation_artifact_result("statistical_exploration", {"result": execute_exploration(_frame(), spec)})
    return public


def _grouped_test(column: str) -> dict:
    result = _named_test_by_group(_frame(30), column, "test.correlations", lambda rows: run_named_statistical_test(
        rows, family="correlations", analysis_columns=["x", "y"], dataset_sha256="0" * 64,
        lineage_parent="cleaned_dataset"))
    public, _ = _public_operation_artifact_result("statistical_test", {"result": result})
    return public


def _wire(monkeypatch, root: Path, public: dict) -> str:
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "inspect_operation_artifact", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c",
         "content": json.dumps({"ok": True, "output": {"artifact_evidence": {"result": public}}})},
    ]
    with egress_project(root):
        return json.dumps(_send(monkeypatch, messages, REMOTE), ensure_ascii=False)


RESULTS = {
    "frequency_table": lambda: _exploration(ExplorationSpec(operation="tabulate", selected_columns=("name",))),
    "filter": lambda: _exploration(ExplorationSpec(operation="summarize", selected_columns=("x",),
                                                   filters=(FilterSpec("name", "neq", "PERSON_GAMMA"),))),
    "grouped_summary": lambda: _exploration(ExplorationSpec(operation="summarize", selected_columns=("x",),
                                                            options={"group_by": "name"})),
    "grouped_frequency": lambda: _exploration(ExplorationSpec(operation="tabulate", selected_columns=("x",),
                                                              options={"group_by": "name"})),
    "by_group_test": lambda: _grouped_test("name"),
}


@pytest.mark.parametrize("label", sorted(RESULTS))
def test_restricted_values_named_by_their_column_never_reach_the_provider(monkeypatch, tmp_path, label):
    save_policy(tmp_path, EgressPolicy(columns={"name": "restricted"}))
    public = RESULTS[label]()
    assert any(person in json.dumps(public) for person in PEOPLE)  # the computation does carry them
    wire = _wire(monkeypatch, tmp_path, public)
    assert not [person for person in PEOPLE if person in wire]
    assert "name" in read_audit(tmp_path)[-1]["redacted_columns"]


def test_the_counts_beside_a_withheld_value_still_reach_the_provider(monkeypatch, tmp_path):
    save_policy(tmp_path, EgressPolicy(columns={"name": "restricted"}))
    wire = json.loads(_wire(monkeypatch, tmp_path, RESULTS["frequency_table"]()))
    output = json.loads(next(m for m in wire["messages"] if m["role"] == "tool")["content"])
    frequencies = output["output"]["artifact_evidence"]["result"]["frequencies"]
    assert sorted(entry["count"] for entry in frequencies) == [1, 1, 2]


def test_an_unprotected_grouping_column_keeps_its_levels(monkeypatch, tmp_path):
    save_policy(tmp_path, EgressPolicy(columns={"name": "restricted"}))
    wire = _wire(monkeypatch, tmp_path, _grouped_test("region"))
    assert "east" in wire and "west" in wire
