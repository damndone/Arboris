"""v1.8.10 step 7: the Agent cites the group-difference test before comparing groups.

Enforced by the numeric check (agent/numeric_grounding.py): when a by-group
result is in the conversation and a reply names two of its groups with
comparative language, the reply must cite one of the group-difference test's
statistics or p-values; otherwise it is withdrawn once and then flagged.
"""

from __future__ import annotations

import json

from workbench.agent.numeric_grounding import check, correction_message, unverified_note

TOOL_RESULT = {
    "persisted_models": [
        {"model_id": "ols_1_g01", "by_group": {
            "column": "sex", "group": "female", "group_index": 1, "n_groups": 2,
            "comparing_groups": "cite the group-difference test",
            "difference_tests": {"status": "estimated", "tests": [
                {"label": "all coefficients equal across groups", "statistic": 4.2187, "df_num": 2,
                 "df_den": 496.0, "p_value": 0.015229},
                {"label": "effect of educ equal across groups", "statistic": 6.0412, "df_num": 1,
                 "df_den": 496.0, "p_value": 0.014327},
            ]}},
         "coefficients": [{"term": "educ", "estimate": 0.0812}]},
        {"model_id": "ols_1_g02", "by_group": {"column": "sex", "group": "male", "group_index": 2,
                                               "comparing_groups": "cite"},
         "coefficients": [{"term": "educ", "estimate": 0.0634}]},
    ]
}
MESSAGES = [{"role": "tool", "name": "inspect_result_summary", "content": json.dumps(TOOL_RESULT)}]


def _comparisons(reply: str):
    return [finding for finding in check(reply, MESSAGES) if finding.kind == "group_comparison"]


def test_comparing_groups_without_the_test_is_a_finding() -> None:
    findings = _comparisons("female 的教育回报 0.0812 比 male 的 0.0634 更高。")
    assert len(findings) == 1 and findings[0].text == "female, male"
    assert "0.0143" in findings[0].closest
    assert "group-difference test" in correction_message(findings)
    assert "组间差异检验" in unverified_note(findings, "zh")


def test_citing_the_test_passes() -> None:
    assert not _comparisons(
        "female 的回报 0.0812 高于 male 的 0.0634，教育回报的组间差异检验 F = 6.041，p = 0.0143。"
    )


def test_describing_groups_without_comparing_passes() -> None:
    assert not _comparisons("female 组教育系数 0.0812；male 组为 0.0634。")


def test_without_a_by_group_result_nothing_is_required() -> None:
    plain = [{"role": "tool", "name": "x", "content": json.dumps({"coefficients": [{"estimate": 0.0812}]})}]
    assert not [f for f in check("female 比 male 更高：0.0812", plain) if f.kind == "group_comparison"]


def test_groups_of_a_by_group_test_without_a_difference_test_must_not_be_compared() -> None:
    from workbench.agent.context_tools import _public_test_by_group

    result = {"test_type": "welch_t_test", "results": [
        {"test_id": "t:y:d", "group": "east", "statistic": 2.81, "p_value": 0.0052},
        {"test_id": "t:y:d", "group": "west", "statistic": 0.42, "p_value": 0.6741},
    ], "by_group": {"column": "region", "groups": [{"key": "east"}, {"key": "west"}], "estimated_groups": 2,
                    "comparing_groups": "not a test of a difference"}}
    messages = [{"role": "tool", "name": "x", "content": json.dumps(_public_test_by_group(result))}]
    findings = [f for f in check("east 的效果显著（p = 0.0052），比 west 更强。", messages) if f.kind == "group_comparison"]
    assert findings and findings[0].closest == ()
    assert "No group-difference test was run" in correction_message(findings)
