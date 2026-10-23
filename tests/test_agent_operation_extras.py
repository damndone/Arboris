"""An Ask-mode confirmation tells the Agent what Auto mode's tool result already does (v1.9.1).

Free-route DeepSeek rounds: per task about three artifact reads, two plan updates
and two completion checks were the Agent asking for what the Workbench knew.
"""
from workbench.agent import plans as plan_module
from workbench.agent.delivery import delivery_digest, delivery_lines
from workbench.agent.operation_outcome import outcome_text


def _plan(*steps):
    return plan_module.merge(None, question="q", criteria=["c"], steps=plan_module.parse_steps(
        list(steps), {"model.genesis", "iv.ar_confidence", "report.compose", "statistical.explore"}),
        budget=None, allowed_classes=None)


def test_a_confirmed_operation_marks_only_the_steps_it_fully_covers():
    plan = _plan({"step_id": "explore", "title": "Explore", "operation_ids": ["statistical.explore"]},
                 {"step_id": "fit", "title": "Fit and test", "operation_ids": ["model.genesis", "iv.ar_confidence"],
                  "depends_on": ["explore"]})
    after = plan_module.mark_covered(plan, ["statistical.explore"], "completed")
    assert [step.status for step in after.steps] == ["done", "pending"]
    # Part of a step's work leaves it open, with the plan's authority over the rest.
    partial = plan_module.mark_covered(after, ["model.genesis"], "completed")
    assert [step.status for step in partial.steps] == ["done", "pending"]
    full = plan_module.mark_covered(after, ["model.genesis", "iv.ar_confidence"], "completed")
    assert [step.status for step in full.steps] == ["done", "done"]
    # A step whose dependency is not done is not marked.
    blocked = plan_module.mark_covered(plan, ["model.genesis", "iv.ar_confidence"], "completed")
    assert [step.status for step in blocked.steps] == ["pending", "pending"]


def test_the_digest_carries_what_to_do_and_nothing_without_a_contract():
    assert delivery_digest({"status": "partial", "missing": ["completion_contract:select_playbooks_and_source"]}) is None
    digest = delivery_digest({"status": "partial", "missing": ["report:registered_nonempty"], "evidence_catalog": {"x": 1},
                              "next_step": "Propose compose_report exactly as given.", "compose_report": {"spec": {}}})
    assert set(digest) == {"status", "missing", "next_step", "compose_report"}
    text = "\n".join(delivery_lines(digest))
    assert "Delivery check after this operation: partial; missing: report:registered_nonempty." in text
    assert "compose_report" in text and "call it only for its evidence catalog" in text


def test_the_result_message_carries_results_marked_steps_and_the_check():
    facts = {"proposal_id": "p1", "operation_id": "operation.multi_step", "status": "completed", "produced_run_id": None,
             "results": [{"step_id": "fit", "estimate": 0.516}], "plan_steps_marked": {"steps": ["fit"], "status": "done"},
             "delivery": {"status": "requirements_met", "next_step": "Delivery requirements are met: report it."}}
    text = outcome_text(facts)
    assert '"estimate": 0.516' in text and "no need to read them again" in text
    assert "Plan step(s) fit marked done by the Workbench." in text
    assert "Delivery check after this operation: requirements_met." in text
