"""v1.9.1: the orchestrator executes what the person's mode, plan, grants and rules allow.

Uses the real proposal -> confirm -> execute path of the read-only fixture;
only the authority changes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.test_read_only_analysis import FINGERPRINT, _Fixture, _explore, _recode
from workbench import analysis_ledger
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
