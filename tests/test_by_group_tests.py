"""v1.8.10 step 7: named tests and descriptives by group.

The same invariance as for models: each group's test equals running the test
on that group's rows alone. Each test's p-values are also adjusted across the
groups (Holm, Benjamini-Hochberg), the ledger counts one test per group, and
the result reaches the Agent with its groups.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from workbench.agent.context_tools import _public_operation_artifact_result
from workbench.agent.workflow_runtime import _named_test_by_group
from workbench.analysis_ledger import LedgerEntry, LedgerStep
from workbench.combinators.by_group import BY_GROUP_OPEN, MISSING_GROUP, adjust_p_values
from workbench.statistical_exploration import ExplorationSpec, execute_exploration
from workbench.statistical_tests import run_named_statistical_test

# capability -> analysis columns
TEST_CASES = {
    "test.t_tests": ["y", "treated"],
    "test.chi_square": ["treated", "answer"],
    "test.correlations": ["y", "x"],
}


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    n = 600
    frame = pd.DataFrame({
        "region": rng.choice(["east", "north", "south"], n),
        "treated": rng.choice(["no", "yes"], n),
        "answer": rng.choice(["agree", "disagree"], n),
        "x": rng.normal(size=n),
    })
    frame["y"] = 0.4 * frame["x"] + (frame["treated"] == "yes") * 0.3 + rng.normal(size=n)
    frame.loc[frame.index[:40], "region"] = np.nan
    return frame


def _run(frame: pd.DataFrame, capability: str, columns: list[str]) -> dict:
    return run_named_statistical_test(
        frame, family=capability.removeprefix("test."), analysis_columns=columns,
        dataset_sha256="0" * 64, lineage_parent="cleaned_dataset",
    )


def test_every_open_test_is_covered_here() -> None:
    open_tests = {name for name in BY_GROUP_OPEN if name.startswith("test.")}
    assert open_tests <= set(TEST_CASES)


@pytest.mark.parametrize("capability", sorted(TEST_CASES))
def test_each_group_equals_running_the_test_on_its_rows(capability: str) -> None:
    frame = _frame()
    columns = TEST_CASES[capability]
    result = _named_test_by_group(frame, "region", capability, lambda rows: _run(rows, capability, columns))
    groups = result["by_group"]["groups"]
    assert [group["key"] for group in groups] == ["east", "north", "south", MISSING_GROUP]
    assert result["by_group"]["estimated_groups"] == 4
    for group in groups:
        rows = frame[frame["region"].isna()] if group["key"] == MISSING_GROUP else frame[frame["region"] == group["key"]]
        alone = _run(rows, capability, columns)["results"]
        mine = [row for row in result["results"] if row["group"] == group["key"]]
        assert len(mine) == len(alone)
        for ours, reference in zip(mine, alone):
            assert ours["test_id"] == reference["test_id"]
            assert ours["statistic"] == pytest.approx(reference["statistic"], rel=1e-12)
            assert ours["p_value"] == pytest.approx(reference["p_value"], rel=1e-12)
    for test_id in {row["test_id"] for row in result["results"]}:
        rows = [row for row in result["results"] if row["test_id"] == test_id]
        p_values = [row["p_value"] for row in rows]
        assert [row["p_value_holm_across_groups"] for row in rows] == pytest.approx(adjust_p_values(p_values, "holm"))
        assert [row["p_value_bh_across_groups"] for row in rows] == pytest.approx(adjust_p_values(p_values, "bh"))


@pytest.mark.parametrize("capability", sorted(TEST_CASES))
def test_the_grouped_result_reaches_the_agent_with_its_groups(capability: str) -> None:
    result = _named_test_by_group(_frame(), "region", capability,
                                  lambda rows: _run(rows, capability, TEST_CASES[capability]))
    public, _ = _public_operation_artifact_result("statistical_test", {"result": result})
    text = json.dumps(public, ensure_ascii=False, default=str)
    assert len(text) <= 6000, len(text)  # executed_workflow_results' per-artifact limit
    assert "comparing_groups" in text and "p_value_holm_across_groups" in text
    assert {row["group"] for row in public["results"]} == {"east", "north", "south", MISSING_GROUP}


def test_descriptives_by_group_list_the_missing_group() -> None:
    frame = _frame()
    result = execute_exploration(frame, ExplorationSpec(
        operation="summarize", selected_columns=("y",), filters=(), options={"group_by": "region"},
    ))
    values = [group["value"] for group in result["groups"]]
    assert values == ["east", "north", "south", MISSING_GROUP]
    missing = result["groups"][-1]
    assert missing["missing_group"] is True
    alone = execute_exploration(frame[frame["region"].isna()], ExplorationSpec(
        operation="summarize", selected_columns=("y",), filters=(), options={},
    ))
    assert json.dumps(missing["variables"], sort_keys=True, default=str) == json.dumps(
        alone["variables"], sort_keys=True, default=str)


def test_the_ledger_counts_one_test_per_group() -> None:
    entry = LedgerEntry(actor="agent", authorized_by="read_only_policy", source="operation.multi_step",
                        status="completed",
                        steps=(LedgerStep.of("test.t_tests", "s1", tests=4), LedgerStep.of("test.chi_square", "s2")))
    assert entry.to_dict()["inferential_steps"] == 5
