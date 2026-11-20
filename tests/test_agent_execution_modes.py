"""v1.9.1: the orchestrator executes what the person's mode, plan, grants and rules allow.

Uses the real proposal -> confirm -> execute path of the read-only fixture;
only the authority changes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.test_read_only_analysis import FINGERPRINT, _Fixture, _explore, _recode, _t_test
from workbench import analysis_ledger
from workbench.agent import plans
from workbench.agent.permissions import Grants, PermissionClass, Rule, Rules


def _with_authority_runner(fixture: _Fixture) -> list[str]:
    seen: list[str] = []

    async def runner(proposal, actor="read_only_policy"):
        seen.append(actor)
        record = fixture.orchestrator.confirm_proposal(
            proposal.proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
            actor_type=actor, current_context_fingerprint=FINGERPRINT, current_active_head_run_id=fixture.run_id,
        )
        return await fixture.orchestrator.execute_confirmed_operation(
            record.record_id, project_root=fixture.project_root,
            current_context_fingerprint=FINGERPRINT, current_active_head_run_id=fixture.run_id,
        )

    fixture.orchestrator.read_only_runner = runner
    return seen


def test_ask_mode_waits_for_a_data_change(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    receipt = fixture.propose([_recode()])
    assert receipt["requires_confirmation"] is True
    assert receipt["permission_class"] == "derive"


def test_auto_mode_runs_a_planned_derive_step_and_records_the_plan_as_authority(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    fixture.orchestrator.execution_mode = "auto"
    fixture.orchestrator.plan_scope = {"in_plan": True, "allowed_classes": ["analyze", "derive"]}
    receipt = fixture.propose([_recode()])
    assert receipt["executed"] is True, receipt
    assert receipt["authorized_by"] == "approved_plan" and seen == ["approved_plan"]
    [entry] = analysis_ledger.read(fixture.project_root)
    assert entry["authorized_by"] == "approved_plan" and entry["changes_data"] is True


def test_auto_mode_asks_outside_the_plan(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    _with_authority_runner(fixture)
    fixture.orchestrator.execution_mode = "auto"
    fixture.orchestrator.plan_scope = {"in_plan": True, "allowed_classes": ["analyze"]}
    assert fixture.propose([_recode()])["requires_confirmation"] is True
    fixture.orchestrator.plan_scope = None
    assert fixture.propose([_recode()])["requires_confirmation"] is True


def test_auto_plan_stops_when_its_registered_source_changes(tmp_path):
    from workbench.agent.completion import source_receipt
    from workbench.artifacts import sha256_file

    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    fixture.orchestrator.execution_mode = "auto"
    source = source_receipt(fixture.project_root, {"run_id": fixture.run_id, "artifact_id": fixture.artifact_id})
    assert source is not None
    plan = plans.approve(plans.merge(None, question="Recode the wage", criteria=[],
        steps=(plans.PlanStep("recode", "Recode the wage", ("data.recode",)),),
        budget=None, allowed_classes=None, completion={"scope": "question", "playbooks": [], "source": source}))
    fixture.orchestrator.plan_store.save("chain-session", plan)

    run_root = fixture.project_root / "runs" / fixture.run_id
    dataset = run_root / "data.csv"
    rows = dataset.read_text().splitlines()
    dataset.write_text("\n".join([*rows[:1], *reversed(rows[1:])]) + "\n")
    index = run_root / "artifacts_index.json"
    artifacts = json.loads(index.read_text())
    artifacts["artifacts"][0]["sha256"] = sha256_file(dataset)
    index.write_text(json.dumps(artifacts))

    receipt = fixture.propose([_recode()])
    assert receipt["requires_confirmation"] and "approved plan's source" in receipt["confirmation_reason"]
    assert seen == [] and fixture.orchestrator.operation_store.list_records() == []


@pytest.mark.parametrize("extra", [_explore("tab", "region"),
    {**_recode(), "step_id": "another-recode", "spec": {**_recode()["spec"], "output": "also_high"}}])
def test_workflow_envelope_grants_only_its_declared_planned_operations(tmp_path, extra):
    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    fixture.orchestrator.execution_mode = "auto"
    _approved_explore(fixture, allowed_classes=("analyze", "derive"), operation_id="data.recode")

    receipt = fixture.propose([_recode(), extra])
    assert receipt["requires_confirmation"] and "not in the approved plan" in receipt["confirmation_reason"]
    assert seen == [] and fixture.orchestrator.operation_store.list_records() == []


def test_a_conversation_grant_runs_the_granted_class(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    seen = _with_authority_runner(fixture)
    fixture.orchestrator.session_grants = Grants(frozenset({Rule(PermissionClass.DERIVE)}))
    receipt = fixture.propose([_recode()])
    assert receipt["executed"] is True and seen == ["session_grant"]


def test_review_before_running_still_asks_even_with_a_grant(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    _with_authority_runner(fixture)
    fixture.orchestrator.execution_policy = "proposal_only"
    fixture.orchestrator.session_grants = Grants(frozenset({Rule(PermissionClass.ANALYZE)}))
    receipt = fixture.propose([_explore("tab", "region")])
    assert receipt["requires_confirmation"] is True


def test_a_deny_rule_refuses_and_the_floor_cannot_be_loosened(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    _with_authority_runner(fixture)
    fixture.orchestrator.permission_rules = Rules(deny=(Rule(PermissionClass.DERIVE, "operation.multi_step"),))
    denied = fixture.propose([_recode()])
    assert denied["executed"] is False and denied["denied"] is True
    assert analysis_ledger.read(fixture.project_root) == []


def test_read_only_analysis_still_runs_at_once_in_ask_mode(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    receipt = fixture.propose([_explore("tab", "region")])
    assert receipt["executed"] is True and receipt["authorized_by"] == "read_only_policy"


def _approved_explore(fixture, *, failed_dependency=False, allowed_classes=("analyze",), operation_id="statistical.explore", spent=False):
    preceding = (plans.PlanStep("prepare", "Prepare", ("data.recode",), status="failed" if failed_dependency else "done",
                               completed_operation_ids=() if failed_dependency else ("data.recode",)),) if failed_dependency or spent else ()
    step = plans.PlanStep("next", "Next", (operation_id,), depends_on=("prepare",) if preceding else ())
    plan = plans.approve(plans.merge(None, question="Describe the data", criteria=[], steps=(*preceding, step),
                                    budget={"steps": 1} if spent else None, allowed_classes=list(allowed_classes)))
    fixture.orchestrator.plan_store.save("chain-session", plan)


def test_auto_ready_planned_analysis_runs_with_the_canonical_ui_policy(tmp_path):
    fixture = _Fixture(tmp_path)
    _with_authority_runner(fixture)
    fixture.orchestrator.execution_mode = "auto"
    fixture.orchestrator.execution_policy = "auto_read_only"
    _approved_explore(fixture)
    result = fixture.propose([_explore("tab", "region")])
    assert result["executed"] and result["authorized_by"] == "read_only_policy"
    assert fixture.orchestrator.plan_store.current("chain-session").steps[-1].status == "done"


def test_an_explicit_review_still_stops_an_otherwise_planned_auto_analysis(tmp_path):
    fixture = _Fixture(tmp_path)
    fixture.orchestrator.execution_mode = "auto"
    fixture.orchestrator.execution_policy = "proposal_only"
    _approved_explore(fixture)
    result = fixture.propose([_explore("tab", "region")])
    assert result["requires_confirmation"]
    assert result["confirmation_reason"] == "Review before execution was requested for this turn."
    assert analysis_ledger.read(fixture.project_root) == []


def test_a_legacy_request_with_only_the_policy_keeps_its_review_boundary(tmp_path):
    from workbench.http.agent_route_requests import AgentTurnRequest
    request = AgentTurnRequest(question="Inspect the data", execution_policy="proposal_only")
    assert "execution_mode" not in request.model_fields_set
    fixture = _Fixture(tmp_path)
    fixture.orchestrator.execution_mode = request.execution_mode
    fixture.orchestrator.execution_policy = request.execution_policy
    result = fixture.propose([_explore("tab", "region")])
    assert result["requires_confirmation"]
    assert result["confirmation_reason"] == "Review before execution was requested for this turn."
    assert analysis_ledger.read(fixture.project_root) == []


def test_explicit_review_keeps_the_specific_inferential_budget_count(tmp_path, monkeypatch):
    from workbench.agent import read_only_policy
    fixture = _Fixture(tmp_path)
    fixture.orchestrator.execution_mode = "auto"
    fixture.orchestrator.execution_policy = "proposal_only"
    _approved_explore(fixture, operation_id="test.t_tests")
    monkeypatch.setattr(read_only_policy, "SESSION_INFERENTIAL_BUDGET", 0)
    result = fixture.propose([_t_test("tt")])
    assert result["requires_confirmation"]
    assert "already run 0 inferential tests" in result["confirmation_reason"]
    assert analysis_ledger.read(fixture.project_root) == []


@pytest.mark.parametrize("case,reason", [
    ("outside", "not in the approved plan"),
    ("failed_dependency", "not in the approved plan"),
    ("unapproved_derive", "does not allow this kind of step"),
    ("project_ask", "a project rule asks"),
    ("spent_budget", "approved plan's budget is spent"),
])
def test_auto_required_ask_reasons_are_not_replaced_by_the_review_policy(tmp_path, case, reason):
    fixture = _Fixture(tmp_path)
    fixture.orchestrator.execution_mode = "auto"
    fixture.orchestrator.execution_policy = "proposal_only"
    if case != "outside":
        _approved_explore(fixture, failed_dependency=case == "failed_dependency",
                          operation_id="data.recode" if case == "unapproved_derive" else "statistical.explore",
                          spent=case == "spent_budget")
    if case == "project_ask":
        fixture.orchestrator.permission_rules = Rules(ask=(Rule(PermissionClass.ANALYZE),))
    result = fixture.propose([_recode()] if case == "unapproved_derive" else [_explore("tab", "region")])
    assert result["requires_confirmation"]
    assert reason in result["confirmation_reason"]
    assert analysis_ledger.read(fixture.project_root) == []
