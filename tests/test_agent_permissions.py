"""The permission engine, checked over every combination of its inputs."""

from __future__ import annotations

import itertools

from workbench.agent.permissions import (
    GRANTABLE,
    Grants,
    Mode,
    Outcome,
    PermissionClass,
    Request,
    Rule,
    Rules,
    decide,
    on_floor,
    permission_class,
    strictest,
)
from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

C = PermissionClass
BOOLS = (False, True)


def _requests():
    for cls, source, in_plan, allowed, named, budget in itertools.product(C, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS):
        yield Request("op.x", cls, touches_source=source, in_plan=in_plan, class_allowed_by_plan=allowed,
                      named_in_plan=named, within_budget=budget)


def _rule_sets(cls):
    none = Rules()
    yield "none", none
    yield "allow", Rules(allow=(Rule(cls),))
    yield "allow-op", Rules(allow=(Rule(cls, "op.x"),))
    yield "ask", Rules(ask=(Rule(cls),))
    yield "deny", Rules(deny=(Rule(cls),))
    yield "allow+deny", Rules(allow=(Rule(cls),), deny=(Rule(cls),))


def _grant_sets(cls):
    yield "none", Grants()
    yield "grant", Grants(frozenset({Rule(cls)}))


CASES = [
    (mode, request, rules_name, rules, grants_name, grants)
    for mode in Mode
    for request in _requests()
    for rules_name, rules in _rule_sets(request.permission_class)
    for grants_name, grants in _grant_sets(request.permission_class)
]


def test_the_combination_space_is_covered() -> None:
    # 2 modes x 6 classes x 2^5 request flags x 6 rule sets x 2 grant sets
    assert len(CASES) == 2 * 6 * 32 * 6 * 2


def test_every_combination_has_one_deterministic_decision_with_a_reason() -> None:
    for mode, request, _r, rules, _g, grants in CASES:
        first = decide(mode, request, rules, grants)
        assert first == decide(mode, request, rules, grants)
        assert first.outcome in set(Outcome) and first.reason


def test_deny_rules_always_win() -> None:
    for mode, request, rules_name, rules, _g, grants in CASES:
        if "deny" in rules_name:
            assert decide(mode, request, rules, grants).outcome == Outcome.DENY


def test_the_safety_floor_is_never_allowed() -> None:
    for mode, request, rules_name, rules, _g, grants in CASES:
        if on_floor(request):
            decision = decide(mode, request, rules, grants)
            assert decision.outcome != Outcome.ALLOW, (mode, request, rules_name)
            if "deny" not in rules_name:
                assert decision.outcome == Outcome.ASK and decision.floor


def test_floor_covers_external_high_and_source_changes() -> None:
    for request in _requests():
        expected = request.permission_class in {C.EXTERNAL, C.HIGH} or request.touches_source
        assert on_floor(request) == expected


def test_ask_rules_tighten_everything_except_deny() -> None:
    for mode, request, rules_name, rules, _g, grants in CASES:
        if rules_name == "ask":
            assert decide(mode, request, rules, grants).outcome == Outcome.ASK


def test_reading_is_always_allowed_unless_denied_or_on_the_floor() -> None:
    for mode, request, rules_name, rules, _g, grants in CASES:
        if request.permission_class == C.READ and not on_floor(request) and rules_name in {"none", "allow", "allow-op"}:
            assert decide(mode, request, rules, grants).outcome == Outcome.ALLOW


def test_ask_mode_confirms_every_change_without_a_rule_or_grant() -> None:
    for mode, request, rules_name, rules, grants_name, grants in CASES:
        if mode == Mode.ASK and rules_name == "none" and grants_name == "none" and request.permission_class in {C.DERIVE, C.MODIFY}:
            assert decide(mode, request, rules, grants).outcome == Outcome.ASK


def test_ask_mode_runs_read_only_analysis_within_budget() -> None:
    request = Request("test.t_tests", C.ANALYZE)
    assert decide(Mode.ASK, request).outcome == Outcome.ALLOW
    assert decide(Mode.ASK, Request("test.t_tests", C.ANALYZE, within_budget=False)).outcome == Outcome.ASK


def test_auto_mode_runs_planned_steps_and_stops_outside_the_plan() -> None:
    planned = Request("model.genesis", C.DERIVE, in_plan=True, class_allowed_by_plan=True)
    assert decide(Mode.AUTO, planned).outcome == Outcome.ALLOW
    for change in ({"in_plan": False}, {"class_allowed_by_plan": False}, {"within_budget": False}):
        request = Request("model.genesis", C.DERIVE, **{**dict(in_plan=True, class_allowed_by_plan=True), **change})
        assert decide(Mode.AUTO, request).outcome == Outcome.ASK, change


def test_auto_mode_modifies_only_objects_the_plan_names() -> None:
    base = dict(in_plan=True, class_allowed_by_plan=True)
    assert decide(Mode.AUTO, Request("metadata.edit", C.MODIFY, **base)).outcome == Outcome.ASK
    assert decide(Mode.AUTO, Request("metadata.edit", C.MODIFY, named_in_plan=True, **base)).outcome == Outcome.ALLOW
    assert decide(Mode.AUTO, Request("metadata.edit", C.MODIFY, named_in_plan=True, touches_source=True,
                                     **base)).outcome == Outcome.ASK


def test_grants_cover_only_grantable_classes_off_the_floor() -> None:
    for mode, request, rules_name, rules, grants_name, grants in CASES:
        if rules_name != "none" or grants_name != "grant":
            continue
        decision = decide(mode, request, rules, grants)
        if request.permission_class in GRANTABLE and not request.touches_source:
            assert decision.outcome == Outcome.ALLOW
        elif on_floor(request):
            assert decision.outcome == Outcome.ASK


def test_every_workflow_step_has_a_permission_class() -> None:
    classes = {operation_id: permission_class(operation_id) for operation_id in WORKFLOW_STEP_SPEC_CONTRACTS}
    assert len(classes) >= 100
    # Every registered step is classified by declaration, none by the fail-closed default.
    from workbench.analysis_ledger import step_category

    assert [op for op in classes if step_category(op) == "unclassified"] == []
    assert classes["statistical.explore"] == C.ANALYZE
    assert classes["model.genesis"] == C.DERIVE
    assert classes["postestimation.wald"] == C.ANALYZE


def test_operation_classes_for_registered_operations() -> None:
    assert permission_class("code.execute") == C.EXTERNAL
    assert permission_class("metadata.edit") == C.MODIFY
    assert permission_class("graph.fork") == C.DERIVE
    assert permission_class("run.delete") == C.HIGH
    assert permission_class("export.dataset") == C.EXTERNAL
    assert permission_class("model.rerun") == C.DERIVE
    assert permission_class("anything.new") == C.MODIFY  # fail closed
    assert permission_class("model.genesis", risk_level="high") == C.HIGH


def test_a_multi_step_request_takes_its_strictest_step() -> None:
    assert strictest([C.ANALYZE, C.DERIVE, C.READ]) == C.DERIVE
    assert strictest([C.ANALYZE, C.EXTERNAL]) == C.EXTERNAL
    assert strictest([]) == C.READ
