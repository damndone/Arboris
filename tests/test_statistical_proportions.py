"""test.proportions: two independent proportions against statsmodels, from raw rows or counted rows.

QRData 070 (55ce11c1 round) had only a counted 2x2 table; with no proportion test the model computed by
hand and reported the risk-ratio interval for a rate-difference question.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.contingency_tables import Table2x2
from statsmodels.stats.proportion import confint_proportions_2indep, proportions_ztest

from workbench.statistical_test_values import StatisticalTestContractError
from workbench.statistical_tests import TEST_FAMILIES, run_named_statistical_test


def _raw(x1, n1, x2, n2):
    return pd.DataFrame({"arm": ["a"] * n1 + ["b"] * n2,
                         "y": [1] * x1 + [0] * (n1 - x1) + [1] * x2 + [0] * (n2 - x2)})


def _run(frame, columns, **options):
    return run_named_statistical_test(frame, family="proportions", analysis_columns=columns, **options)["results"][0]


@pytest.mark.parametrize("x1,n1,x2,n2,level", [(145, 12883, 200, 12988, 0.95), (12, 40, 5, 38, 0.90), (3, 25, 9, 31, 0.99)])
def test_matches_statsmodels_and_counted_rows_equal_raw_rows(x1, n1, x2, n2, level):
    raw = _run(_raw(x1, n1, x2, n2), ["arm", "y"], group_column="arm", outcome_column="y", confidence_level=level)
    counted = _run(pd.DataFrame({"arm": ["a", "b"], "e": [x1, x2], "n": [n1, n2]}), ["arm", "e", "n"],
                   group_column="arm", events_column="e", trials_column="n", confidence_level=level)
    assert raw["effect"] == counted["effect"] and raw["statistic"] == counted["statistic"]
    z, p = proportions_ztest([x1, x2], [n1, n2])
    difference = confint_proportions_2indep(x1, n1, x2, n2, method="wald", compare="diff", alpha=1 - level)
    ratio = confint_proportions_2indep(x1, n1, x2, n2, method="log", compare="ratio", alpha=1 - level)
    table = Table2x2(np.array([[x1, n1 - x1], [x2, n2 - x2]]))
    odds = table.oddsratio_confint(alpha=1 - level, method="normal")
    effect = raw["effect"]
    assert raw["statistic"] == pytest.approx(z, rel=1e-12) and raw["p_value"] == pytest.approx(p, rel=1e-12)
    assert (effect["rate_difference"]["ci_lower"], effect["rate_difference"]["ci_upper"]) == pytest.approx(difference, rel=1e-12)
    assert (effect["risk_ratio"]["ci_lower"], effect["risk_ratio"]["ci_upper"]) == pytest.approx(ratio, rel=1e-12)
    assert effect["odds_ratio"]["estimate"] == pytest.approx(table.oddsratio, rel=1e-12)
    assert (effect["odds_ratio"]["ci_lower"], effect["odds_ratio"]["ci_upper"]) == pytest.approx(odds, rel=1e-12)


def test_qrdata_070_counted_table_with_non_events():
    frame = pd.DataFrame({"group": ["fish_oil", "placebo"], "mi": [145, 200], "mi_none": [12738, 12788]})
    row = _run(frame, ["group", "mi", "mi_none"], group_column="group", events_column="mi", non_events_column="mi_none")
    difference = row["effect"]["rate_difference"]
    assert row["groups"] == ["fish_oil", "placebo"] and row["nobs"] == 25871
    assert round(difference["ci_upper"] - difference["ci_lower"], 3) == 0.006


def test_group_order_flips_the_comparison_and_text_outcomes_need_an_event_value():
    frame = _raw(12, 40, 5, 38)
    frame["y"] = frame["y"].map({1: "yes", 0: "no"})
    with pytest.raises(StatisticalTestContractError, match="set event_value"):
        _run(frame, ["arm", "y"], group_column="arm", outcome_column="y")
    forward = _run(frame, ["arm", "y"], group_column="arm", outcome_column="y", event_value="yes")
    backward = _run(frame, ["arm", "y"], group_column="arm", outcome_column="y", event_value="yes", group_order=["b", "a"])
    assert backward["groups"] == ["b", "a"]
    assert backward["effect"]["rate_difference"]["estimate"] == pytest.approx(-forward["effect"]["rate_difference"]["estimate"])
    assert backward["effect"]["risk_ratio"]["estimate"] == pytest.approx(1 / forward["effect"]["risk_ratio"]["estimate"])


def test_refusals_name_what_is_wrong():
    three = pd.DataFrame({"arm": ["a", "b", "c", "a"], "y": [1, 0, 1, 0]})
    with pytest.raises(StatisticalTestContractError, match="exactly two groups; group_column has 3"):
        _run(three, ["arm", "y"], group_column="arm", outcome_column="y")
    counted = pd.DataFrame({"arm": ["a", "b"], "e": [5, 9], "n": [4, 20]})
    with pytest.raises(StatisticalTestContractError, match="events 5 exceed trials 4"):
        _run(counted, ["arm", "e", "n"], group_column="arm", events_column="e", trials_column="n")
    with pytest.raises(StatisticalTestContractError, match="either outcome_column"):
        _run(counted, ["arm", "e", "n"], group_column="arm", events_column="e")
    with pytest.raises(StatisticalTestContractError, match="exactly the role columns"):
        _run(counted, ["arm", "e"], group_column="arm", events_column="e", trials_column="n")
    with pytest.raises(StatisticalTestContractError, match="group_order must list the two groups"):
        _run(counted.assign(e=[2, 9]), ["arm", "e", "n"], group_column="arm", events_column="e", trials_column="n",
             group_order=["a", "z"])


def test_a_zero_cell_leaves_the_ratios_unavailable_but_keeps_the_difference():
    row = _run(pd.DataFrame({"arm": ["a", "b"], "e": [0, 4], "n": [30, 30]}), ["arm", "e", "n"],
               group_column="arm", events_column="e", trials_column="n")
    assert row["effect"]["risk_ratio"]["estimate"] is None and "zero" in row["effect"]["risk_ratio"]["unavailable"]
    assert row["effect"]["odds_ratio"]["estimate"] is None
    assert row["effect"]["rate_difference"]["estimate"] == pytest.approx(-4 / 30)


def test_the_automatic_matrix_does_not_run_a_family_that_needs_declared_roles():
    from workbench.statistical_tests import run_statistical_tests

    assert TEST_FAMILIES["proportions"].automatic is False
    results = run_statistical_tests(_raw(12, 40, 5, 38).assign(score=range(78)), analysis_columns=["arm", "y", "score"])
    assert "proportions" not in results


def test_the_agent_capability_runs_proportions_through_the_named_path():
    from workbench.agent.workflow_capability_adapters import get_workflow_capability_adapter

    adapter = get_workflow_capability_adapter("statistical_test")
    frame = pd.DataFrame({"group": ["fish_oil", "placebo"], "mi": [145, 200], "mi_none": [12738, 12788]})
    request = adapter.validate_request("test.proportions", {
        "operation_id": "test.proportions", "input_mode": "frame",
        "column_bindings": {"columns": ["group", "mi", "mi_none"]},
        "options": {"group_column": "group", "events_column": "mi", "non_events_column": "mi_none"}})
    payload = adapter.execute(frame, request).payload
    row = payload["result"]["results"][0]
    assert payload["family"] == "proportions" and row["test_type"] == "two_proportions"
    # A role naming a column the data lacks, or two total columns at once, is still refused.
    conflicting = adapter.validate_request("test.proportions", {**request, "options": {**request["options"], "trials_column": "other"},
                                                                "column_bindings": {"columns": ["group", "mi", "mi_none"]}})
    with pytest.raises(Exception, match="other|either outcome_column"):
        adapter.execute(frame, conflicting)


def test_the_agent_contract_distinguishes_totals_from_complement_counts():
    from workbench.agent.workflow_capability_adapters import workflow_capability_request_schema

    schema = workflow_capability_request_schema("statistical_test", operation_id="test.proportions")
    options = schema["properties"]["options"]["properties"]
    assert "including events" in options["trials_column"]["description"]
    assert "events and non-events" in options["non_events_column"]["description"]


def test_role_columns_count_as_declared_columns():
    """3724e8b2 round (QRData 070): group_column named only as a role was refused as undeclared."""
    from workbench.agent.workflow_capability_adapters import get_workflow_capability_adapter

    adapter = get_workflow_capability_adapter("statistical_test")
    request = adapter.validate_request("test.proportions", {
        "operation_id": "test.proportions", "input_mode": "frame",
        "column_bindings": {"columns": ["mi", "mi_none"]},
        "options": {"group_column": "group", "events_column": "mi", "non_events_column": "mi_none"}})
    assert request["column_bindings"]["columns"] == ["mi", "mi_none", "group"]
    frame = pd.DataFrame({"group": ["fish_oil", "placebo"], "mi": [145, 200], "mi_none": [12738, 12788]})
    assert adapter.execute(frame, request).payload["result"]["results"][0]["groups"] == ["fish_oil", "placebo"]


def test_two_counted_rows_are_the_groups_and_a_one_valued_group_column_says_so():
    """QRData 070 (3724e8b2 round): no label column, a hand recode gave both rows 'treatment', and the
    refusal read "unsupported semantic type"."""
    counted = pd.DataFrame({"mi": [145, 200], "mi_none": [12738, 12788]})
    row = _run(counted, ["mi", "mi_none"], events_column="mi", non_events_column="mi_none")
    assert row["groups"] == ["row 1", "row 2"] and row["group"] == "row order"
    assert round(row["effect"]["rate_difference"]["ci_upper"] - row["effect"]["rate_difference"]["ci_lower"], 3) == 0.006
    with pytest.raises(StatisticalTestContractError, match="needs exactly two counted rows"):
        _run(pd.concat([counted, counted]), ["mi", "mi_none"], events_column="mi", non_events_column="mi_none")
    with pytest.raises(StatisticalTestContractError, match="exactly two groups; group_column has 1: treatment"):
        _run(counted.assign(group="treatment"), ["group", "mi", "mi_none"], group_column="group",
             events_column="mi", non_events_column="mi_none")
