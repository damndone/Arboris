"""A composed operation retains every child's permission restrictions."""
import pytest

from workbench.agent.permissions import (
    Grants, Mode, Outcome, PermissionClass as C, Rule, Rules, decide, request_for_operation,
)


def _request():
    return request_for_operation("operation.multi_step", {"steps": [
        {"operation_id": "statistical.explore"}, {"operation_id": "report.compose"},
    ]})


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("restriction", ["deny", "ask"])
def test_child_restriction_wins_over_parent_allow_and_grants(mode, qualified, restriction):
    rule = Rule(C.ANALYZE, "statistical.explore" if qualified else None)
    rules = Rules(allow=(Rule(C.DERIVE),), **{restriction: (rule,)})
    grants = Grants(frozenset({Rule(C.DERIVE)}))
    decision = decide(mode, _request(), rules, grants)
    assert decision.outcome == (Outcome.DENY if restriction == "deny" else Outcome.ASK)


def test_allow_for_one_child_does_not_authorize_its_sibling():
    rules = Rules(allow=(Rule(C.ANALYZE, "statistical.explore"),))
    assert decide(Mode.ASK, _request(), rules).outcome == Outcome.ASK


def test_separate_child_rules_can_authorize_the_composed_operation():
    rules = Rules(allow=(Rule(C.ANALYZE, "statistical.explore"), Rule(C.DERIVE, "report.compose")))
    assert decide(Mode.ASK, _request(), rules).outcome == Outcome.ALLOW


@pytest.mark.parametrize("entry", ["agent", "confirmation"])
def test_actual_proposal_cannot_execute_a_denied_child(tmp_path, entry):
    import json
    from tests.test_read_only_analysis import _Fixture, _explore, FINGERPRINT

    fixture = _Fixture(tmp_path)
    orchestrator = fixture.orchestrator
    rules = {"allow": [{"class": "derive"}],
             "deny": [{"class": "analyze", "operation_id": "statistical.explore"}]}
    (fixture.repository.root / "agent-permissions.json").write_text(json.dumps(rules))
    from workbench.agent.permissions import rules_from_payload
    orchestrator.permission_rules = rules_from_payload(rules)
    receipt = fixture.propose([_explore("tab", "region"), {
        "step_id": "report", "operation_id": "report.compose", "depends_on": ["tab"],
        "spec": {"sections": ["descriptives"]},
    }])
    if entry == "agent":
        assert receipt.get("denied") is True
    else:
        proposal = orchestrator.proposal_store.latest_revision(receipt["proposal_id"])
        with pytest.raises(PermissionError, match="denies"):
            orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
                fingerprint=proposal.fingerprint, actor_type="user",
                current_context_fingerprint=FINGERPRINT, current_active_head_run_id=fixture.run_id)
    assert orchestrator.operation_store.list_records() == []
