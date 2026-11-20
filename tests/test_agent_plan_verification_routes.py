"""On-demand deliverable verification reuses the Agent check without model calls."""
import pytest
from fastapi.testclient import TestClient

from tests.test_agent_plan_controls import fixture
from workbench.agent import delivery
from workbench.app import app
from workbench.http import agent_route_runtime


def test_verification_projects_the_shared_check_without_changing_execution(tmp_path, monkeypatch):
    root, repo, store, plan = fixture(tmp_path)
    checks = []
    criteria = {"plan_id": plan.plan_id, "plan_version": plan.version,
        "basis_sha256": "a" * 64, "status": "partial", "requirements": [],
        "unbound_slots": [{"criterion_index": 0}]}

    def check(project_root, current):
        checks.append((project_root, current))
        return {"status": "partial", "playbook_status": "requirements_met",
            "criteria_verification": criteria, "internal_evidence": "not a response field"}

    monkeypatch.setattr(delivery, "delivery_check", check)
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", lambda: pytest.fail("no Provider"))
    with TestClient(app) as client:
        response = client.get("/agent/sessions/session-a/plan/verification",
            params={"project_root": str(root)})
    assert response.status_code == 200, response.text
    assert response.json() == {"plan_id": plan.plan_id, "plan_version": plan.version,
        "status": "partial", "playbook_status": "requirements_met", "criteria_verification": criteria}
    assert checks == [(root.resolve(), plan)]
    assert store.history("session-a") == [plan]
    assert repo.get_branch("session-a") == []


def test_plan_reads_remain_lightweight_and_verification_errors_are_explicit(tmp_path, monkeypatch):
    root, _, store, plan = fixture(tmp_path)

    def fail(*args):
        raise OSError("evidence unavailable")

    monkeypatch.setattr(delivery, "delivery_check", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        params = {"project_root": str(root)}
        assert client.get("/agent/sessions/session-a/plan", params=params).status_code == 200
        assert client.get("/agent/sessions/session-a/plan/verification", params=params).status_code == 500
    assert store.current("session-a") == plan


def test_verification_without_a_plan_is_an_explicit_not_found(tmp_path):
    root, _, _, _ = fixture(tmp_path)
    # A second real session has no plan; the first session's history remains intact.
    from workbench.agent.session import JsonlSessionRepository
    JsonlSessionRepository(root / "workbench").create_session("no-plan", role="chain", chain_id="chain-b")
    with TestClient(app) as client:
        response = client.get("/agent/sessions/no-plan/plan/verification", params={"project_root": str(root)})
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "AGENT_PLAN_NOT_FOUND"


def test_actual_registered_playbook_pass_does_not_hide_unbound_plan_criteria(tmp_path, monkeypatch):
    from dataclasses import replace
    from tests.test_agent_completion import fixture as completion_fixture
    from workbench.agent.task_requirements import RequirementBinder
    root, repo, store, plan = fixture(tmp_path)
    contract, evidence = completion_fixture(root)
    repo.append("session-a", "message", {"role": "user", "content": "Please complete the full analysis."})
    plan = replace(plan, completion=contract, completion_evidence=evidence,
        task_requirements=RequirementBinder(repo).bind("session-a", None))
    store.save("session-a", plan)
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", lambda: pytest.fail("no Provider"))
    with TestClient(app) as client:
        response = client.get("/agent/sessions/session-a/plan/verification", params={"project_root": str(root)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["playbook_status"] == "requirements_met"
    assert result["status"] == "requirements_met" and result["criteria_not_machine_checked"] is True
    assert result["criteria_verification"]["unbound_slots"] == [{"criterion_index": 0}]
    assert store.current("session-a") == plan
