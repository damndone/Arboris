"""v1.9.1 plans: typed steps, versions, approval, and Auto runs inside the plan only."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.test_agent_execution_modes import _with_authority_runner
from tests.test_read_only_analysis import _Fixture, _recode
from workbench.agent import plans
from workbench.agent.plans import PlanError, PlanStore

KNOWN = {"statistical.explore", "data.recode", "model.genesis", "test.t_tests", "export.dataset"}


def _steps(*items):
    return plans.parse_steps(list(items), KNOWN)


def _step(step_id, ops, deps=()):
    return {"step_id": step_id, "title": step_id, "operation_ids": list(ops), "depends_on": list(deps)}


def test_steps_are_validated() -> None:
    with pytest.raises(PlanError, match="unknown operation"):
        _steps(_step("a", ["nope.op"]))
    with pytest.raises(PlanError, match="cycle"):
        _steps(_step("a", ["data.recode"], ["b"]), _step("b", ["data.recode"], ["a"]))
    with pytest.raises(PlanError, match="unknown steps"):
        _steps(_step("a", ["data.recode"], ["z"]))
    with pytest.raises(PlanError, match="repeated"):
        _steps(_step("a", ["data.recode"]), _step("a", ["model.genesis"]))


def test_allowed_classes_come_from_the_steps_and_never_include_the_floor() -> None:
    plan = plans.merge(None, question="q", criteria=["c"], budget=None, allowed_classes=None,
                       steps=_steps(_step("a", ["statistical.explore"]), _step("b", ["model.genesis"]),
                                    _step("c", ["export.dataset"])))
    assert plan.status == "draft" and plan.allowed_classes == ("analyze", "derive")
    assert plans.merge(None, question="q", criteria=[], budget=None, allowed_classes=["derive", "external"],
                       steps=_steps(_step("a", ["data.recode"]))).allowed_classes == ("derive",)


def test_after_approval_new_steps_are_exploratory_and_widening_needs_approval_again() -> None:
    first = plans.merge(None, question="q", criteria=["c"], budget={"steps": 3}, allowed_classes=None,
                        steps=_steps(_step("a", ["statistical.explore"])))
    approved = plans.approve(first)
    same_kind = plans.merge(approved, question="q", criteria=["c"], budget=None, allowed_classes=None,
                            steps=_steps(_step("a", ["statistical.explore"]), _step("b", ["test.t_tests"])))
    assert same_kind.status == "approved"
    assert [s.added_after_results for s in same_kind.steps] == [False, True]
    wider = plans.merge(same_kind, question="q", criteria=["c"], budget=None, allowed_classes=None,
                        steps=_steps(_step("a", ["statistical.explore"]), _step("m", ["model.genesis"])))
    assert wider.status == "needs_approval"
    changed_criteria = plans.merge(approved, question="q", criteria=["other"], budget=None, allowed_classes=None,
                                   steps=_steps(_step("a", ["statistical.explore"])))
    assert changed_criteria.status == "needs_approval"


def test_scope_covers_only_open_planned_operations() -> None:
    plan = plans.approve(plans.merge(None, question="q", criteria=[], budget={"steps": 1}, allowed_classes=None,
                                     steps=_steps(_step("a", ["data.recode"]), _step("b", ["model.genesis"]))))
    assert plans.scope_for(plan, ["data.recode"])["in_plan"] is True
    assert plans.scope_for(plan, ["data.recode", "test.t_tests"])["in_plan"] is False
    assert plans.scope_for(plan, ["data.recode"], executed_steps=1)["within_budget"] is False
    assert plans.scope_for(plans.merge(None, question="q", criteria=[], budget=None, allowed_classes=None,
                                       steps=_steps(_step("a", ["data.recode"]))), ["data.recode"])["in_plan"] is False


def test_editing_one_budget_cannot_silently_remove_other_approved_limits():
    approved = plans.approve(plans.merge(None, question="q", criteria=[],
        budget={"steps": 1, "wall_s": 120, "inferential": 2}, allowed_classes=None,
        steps=_steps(_step("a", ["data.recode"]))))
    revised = plans.merge(approved, question="q", criteria=[], budget={"wall_s": 60},
        allowed_classes=None, steps=approved.steps)
    assert revised.budget == {"steps": 1, "wall_s": 60, "inferential": 2}
    assert revised.status == "approved"
    assert plans.scope_for(revised, ["data.recode"], executed_steps=1)["within_budget"] is False
    wider = plans.merge(revised, question="q", criteria=[], budget={"steps": 2},
        allowed_classes=None, steps=revised.steps)
    assert wider.status == "needs_approval"
    assert wider.budget == {"steps": 2, "wall_s": 60, "inferential": 2}
    assert plans.scope_for(wider, ["data.recode"])["in_plan"] is False


def test_explicit_class_restrictions_take_effect_and_cannot_be_silently_reopened():
    approved = plans.approve(plans.merge(None, question="q", criteria=[], budget=None,
        allowed_classes=None, steps=_steps(_step("a", ["statistical.explore"]), _step("b", ["model.genesis"]))))
    restricted = plans.merge(approved, question="q", criteria=[], budget=None,
        allowed_classes=["analyze"], steps=approved.steps)
    assert restricted.allowed_classes == ("analyze",)
    assert restricted.status == "approved"
    revoked = plans.merge(restricted, question="q", criteria=[], budget=None,
        allowed_classes=[], steps=restricted.steps)
    assert revoked.allowed_classes == ()
    assert plans.scope_for(revoked, ["statistical.explore"])["allowed_classes"] == []
    progress = plans.merge(revoked, question="q", criteria=[], budget=None,
        allowed_classes=None, steps=revoked.steps)
    assert progress.status == "approved" and progress.allowed_classes == ()
    widened = plans.merge(revoked, question="q", criteria=[], budget=None,
        allowed_classes=["analyze"], steps=revoked.steps)
    assert widened.status == "needs_approval"


def test_store_keeps_every_version(tmp_path: Path) -> None:
    store = PlanStore(tmp_path)
    plan = plans.merge(None, question="q", criteria=[], budget=None, allowed_classes=None,
                       steps=_steps(_step("a", ["data.recode"])))
    store.save("s", plan)
    store.save("s", plans.approve(plan))
    assert [p.status for p in store.history("s")] == ["draft", "approved"]
    assert store.current("s").approved_version == 1


def test_auto_mode_runs_an_approved_plan_step_and_marks_it_done(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = "auto"
    registry = orchestrator.tool_registry("chain-a")
    draft = asyncio.run(registry.execute({"tool_call_id": "p1", "tool_id": "update_plan", "arguments": {
        "question": "Does group predict wage?", "criteria": ["report the recoded share"],
        "steps": [{"step_id": "recode", "title": "Recode wage", "operation_ids": ["data.recode"]}]}},
        session_id="chain-session"))
    assert draft.ok and draft.output["requires_confirmation"] is True
    # Before approval the step waits for a card.
    assert fixture.propose([_recode()])["requires_confirmation"] is True
    store = orchestrator.plan_store
    store.save("chain-session", plans.approve(store.current("chain-session")))
    receipt = fixture.propose([_recode()])
    assert receipt["executed"] is True and seen == ["approved_plan"]
    assert store.current("chain-session").steps[0].status == "done"
    assert store.current("chain-session").status == "completed"


def test_a_status_update_without_question_or_criteria_keeps_them_and_the_approval(tmp_path: Path) -> None:
    """Paid fix2 round (panel, Auto): an update that left out criteria read as clearing them,
    and every progress update reopened the approved plan."""
    fixture = _Fixture(tmp_path)
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = "auto"
    registry = orchestrator.tool_registry("chain-a")
    step = {"step_id": "recode", "title": "Recode wage", "operation_ids": ["data.recode"]}

    def update(arguments):
        return asyncio.run(registry.execute({"tool_call_id": "p", "tool_id": "update_plan", "arguments": arguments},
                                            session_id="chain-session"))

    update({"question": "Does group predict wage?", "criteria": ["report the recoded share"], "steps": [step]})
    store = orchestrator.plan_store
    store.save("chain-session", plans.approve(store.current("chain-session")))

    progress = update({"steps": [{**step, "status": "running"}]})
    plan = store.current("chain-session")
    assert progress.ok and plan.status == "approved"
    assert plan.question == "Does group predict wage?" and plan.criteria == ("report the recoded share",)
    assert "approval_reopened" not in progress.output

    loosened = update({"criteria": ["report any share"], "steps": [step]})
    assert store.current("chain-session").status == "needs_approval"
    assert "send update_plan without them" in loosened.output["approval_reopened"]


@pytest.mark.parametrize("restriction", ["budget", "allowed_classes", "unlimited_steps"])
def test_real_plan_updates_keep_auto_inside_the_restricted_authority(tmp_path, restriction):
    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = "auto"
    registry = orchestrator.tool_registry("chain-a")
    steps = [{"step_id": f"recode-{i}", "title": f"Recode {i}", "operation_ids": ["data.recode"]}
             for i in range(2)]

    def update(patch):
        result = asyncio.run(registry.execute({"tool_call_id": "plan", "tool_id": "update_plan",
            "arguments": {"steps": steps, **patch}}, session_id="chain-session"))
        assert result.ok and result.output["saved"], result
        return orchestrator.plan_store.current("chain-session")

    initial = update({"question": "Describe the wage recodes", "criteria": ["Report both recodes"],
        "budget": {"steps": 1, "wall_s": 60}})
    orchestrator.plan_store.save("chain-session", plans.approve(initial))
    if restriction == "budget":
        revised = update({"budget": {"wall_s": 30}})
        assert revised.budget == {"steps": 1, "wall_s": 30}
        assert fixture.propose([_recode()])["executed"] is True
        assert seen == ["approved_plan"]
    elif restriction == "allowed_classes":
        revised = update({"allowed_classes": []})
        assert revised.allowed_classes == ()
    else:
        revised = update({"budget": {"steps": 0}})
        assert revised.status == "needs_approval"
        assert revised.budget == {"steps": 0, "wall_s": 60}
    receipt = fixture.propose([_recode()])
    assert receipt["requires_confirmation"] is True
    assert len(seen) == (1 if restriction == "budget" else 0)
