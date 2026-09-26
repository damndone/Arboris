"""Server-written closing messages: user's language, facts from the proposal."""

from workbench.agent.turn_messages import (
    budget_exhausted_message,
    detect_language,
    matches_language,
    proposal_summary,
)


def test_language_detection() -> None:
    assert detect_language("把 region 作为分类变量加进模型") == "zh"
    assert detect_language("run ols on dataset:demo") == "en"
    assert detect_language("对 wage 做 OLS 回归") == "zh"
    assert detect_language(None) == "en"
    assert not matches_language("I'll submit the proposal now.", "zh")


def test_a_multi_step_proposal_is_summarised_from_its_steps() -> None:
    proposal = {
        "operation_id": "operation.multi_step",
        "changes": {
            "steps": [
                {"operation_id": "data.subset", "spec": {"filters": [{"column": "age", "op": "ge", "value": 25}]}},
                {"operation_id": "model.genesis", "spec": {"model_family": "ols"}},
            ]
        },
    }
    text = proposal_summary(proposal, "zh")
    assert text.startswith("已生成待确认的提案（operation.multi_step），尚未执行")
    # Sentences from the proposal's own content, not raw JSON.
    assert "1. Keep rows where age ≥ 25" in text and "2. Estimate OLS model" in text
    assert "has not run yet" in proposal_summary(proposal, "en")


def test_the_budget_message_says_what_was_tried_and_why_it_stopped() -> None:
    text = budget_exhausted_message(
        "zh", "max_steps_exceeded",
        ["list_project_datasets", "inspect_node_context", "list_project_datasets"],
        "source run does not satisfy the OLS golden-flow contract",
    )
    assert "步数预算已用完" in text
    assert "list_project_datasets、inspect_node_context" in text
    assert "OLS golden-flow" in text
