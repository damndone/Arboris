"""v1.8.9 trust round — proposals read as sentences, with the data's labels."""

from __future__ import annotations

from workbench.agent.proposal_text import proposal_lines, step_sentence
from workbench.agent.turn_messages import proposal_summary

LABELS = {"age": "年龄", "wage": "小时工资", "region": "地区"}


def _workflow(*steps: dict) -> dict:
    return {"operation_id": "operation.multi_step", "changes": {"steps": list(steps)}}


def test_a_workflow_reads_step_by_step_with_labels() -> None:
    lines = proposal_lines(
        _workflow(
            {"step_id": "keep", "operation_id": "data.subset",
             "spec": {"columns": ["wage", "age"], "filters": [{"column": "age", "op": "between", "value": [25, 55]}]}},
            {"step_id": "freq", "operation_id": "statistical.explore",
             "spec": {"operation": "tabulate", "selected_columns": ["region"], "options": {}}},
            {"step_id": "tt", "operation_id": "test.t_tests",
             "spec": {"input_mode": "frame", "column_bindings": {"columns": ["wage", "female"]}, "options": {}}},
            {"step_id": "m", "operation_id": "model.genesis",
             "spec": {"model_family": "ols", "covariance": "robust",
                      "branches": [{"branch_id": "m1", "outcome": "wage", "predictors": ["age"], "categorical": ["region"]}]}},
        ),
        LABELS,
    )
    assert lines == [
        "Keep rows where age (年龄) is between 25 and 55; columns wage (小时工资), age (年龄)",
        "Frequency table of region (地区)",
        "Welch two-sample t-test of a numeric outcome across a binary group: female, wage (小时工资)",
        "Estimate OLS: wage (小时工资) on age (年龄), C(region) (robust standard errors)",
    ]


def test_every_legacy_data_operation_has_its_own_sentence() -> None:
    assert step_sentence("data.recode", {
        "column": "age", "output": "age_group",
        "rules": [{"from": {"low": 18, "high": 39}, "to": 1}, {"from": "missing", "to": None}],
    }, LABELS) == "Recode age (年龄) into new variable age_group: 18–39 → 1, missing → missing"
    assert step_sentence("data.fill_missing", {"strategies": [{"column": "wage", "strategy": "median"}]}, LABELS) == (
        "Missing values: fill wage (小时工资) with its median"
    )
    assert step_sentence("data.merge", {
        "secondary_run_id": "r2", "secondary_node_id": "stage:raw", "secondary_artifact_id": "a", "keys": ["id"],
    }, {}) == "Merge with stage:raw of run r2 on id (left join)"


def test_metadata_edits_say_what_changes() -> None:
    lines = proposal_lines(
        {"operation_id": "metadata.edit", "changes": {"labels": {
            "variable_labels": {"age": "受访者年龄"}, "user_missing_values": {"wage": [-99]}, "value_labels": {"region": None},
        }}},
        LABELS,
    )
    assert lines == [
        "Set the label of age (年龄) to 受访者年龄",
        "Remove the value labels of region (地区)",
        "Set the missing-value codes of wage (小时工资) to [-99]",
    ]


def test_the_closing_reply_uses_the_same_sentences() -> None:
    text = proposal_summary(
        _workflow({"step_id": "d", "operation_id": "data.dedupe", "spec": {"columns": ["id"], "keep": "first"}}), "zh"
    )
    assert "1. Drop rows that repeat id, keeping the first one" in text
    assert "{" not in text
