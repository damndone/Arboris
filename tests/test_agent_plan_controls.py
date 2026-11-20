"""Human plan edits use the same versioned plan and audited authority seam."""
from workbench.http import agent_route_runtime
import pytest
from fastapi.testclient import TestClient

from workbench import analysis_ledger
from workbench.app import app
from workbench.agent.plans import PlanStore, merge, parse_steps
from workbench.agent.session import JsonlSessionRepository


def fixture(tmp_path):
    root = tmp_path / "project"
    repo = JsonlSessionRepository(root / "workbench")
    repo.create_session("session-a", role="chain", chain_id="chain-a")
    plan = merge(None, question="Compare wages.", criteria=["Report uncertainty."],
                 steps=parse_steps([{"step_id": "test", "title": "Compare groups",
                                     "operation_ids": ["test.t_tests"]}], {"test.t_tests"}),
                 budget={"steps": 5}, allowed_classes=None)
    store = PlanStore(repo.root)
    store.save("session-a", plan)
    return root, repo, store, plan


def test_person_revises_a_draft_without_a_model_call(tmp_path, monkeypatch):
    from workbench.http import agent_routes
    root, repo, store, plan = fixture(tmp_path)
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", lambda: pytest.fail("plan edit must not load a model"))
    with TestClient(app) as client:
        response = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                                json={"version": plan.version, "question": "Compare log wages.",
                                      "criteria": ["Report the effect and uncertainty."]})
    assert response.status_code == 200, response.text
    revised = response.json()["plan"]
    assert revised["version"] == 2 and revised["status"] == "draft"
    assert revised["question"] == "Compare log wages."
    assert store.current("session-a").to_dict() == revised
    notices = [e for e in repo.get_branch("session-a") if e.payload.get("message_type") == "agent_plan_revised"]
    assert len(notices) == 1 and "Compare log wages." in notices[0].payload["content"]


def test_approved_question_edit_needs_new_approval_and_records_the_real_actor(tmp_path):
    root, repo, store, plan = fixture(tmp_path)
    with TestClient(app) as client:
        approved = client.post("/agent/sessions/session-a/plan/approve", params={"project_root": str(root)},
                               json={"version": plan.version})
        assert approved.status_code == 200
        edited = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                              json={"version": plan.version, "question": "Compare log wages."})
    assert edited.status_code == 200, edited.text
    assert edited.json()["plan"]["status"] == "needs_approval"
    events = analysis_ledger.read(root)
    changed = [e for e in events if e.get("event_type") == "question_change"]
    assert len(changed) == 1 and changed[0]["actor"] == "user"
    assert changed[0]["plan_snapshot"]["question"] == "Compare log wages."


def test_edit_retry_repairs_a_lost_notice_without_another_plan_revision(tmp_path, monkeypatch):
    root, repo, store, plan = fixture(tmp_path)
    original = JsonlSessionRepository.append_once
    def fail_notice(self, *args, **kwargs):
        if kwargs.get("stage") == "plan_revised":
            raise OSError("lost notice")
        return original(self, *args, **kwargs)
    with TestClient(app, raise_server_exceptions=False) as client:
        with monkeypatch.context() as scoped:
            scoped.setattr(JsonlSessionRepository, "append_once", fail_notice)
            failed = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                                  json={"version": 1, "question": "Compare log wages."})
        assert failed.status_code == 500
        [before, revised] = store.history("session-a")
        repaired = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                                json={"version": 1, "question": "Compare log wages."})
    assert repaired.status_code == 200, repaired.text
    assert store.current("session-a") == revised and len(store.history("session-a")) == 2
    assert len([e for e in repo.get_branch("session-a") if e.payload.get("message_type") == "agent_plan_revised"]) == 1


def test_stale_or_status_forging_edit_cannot_change_the_plan(tmp_path):
    root, repo, store, plan = fixture(tmp_path)
    with TestClient(app) as client:
        stale = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                             json={"version": 8, "question": "Other question"})
        forged = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                              json={"version": 1, "steps": [{"step_id": "test", "title": "Pretend done",
                                    "operation_ids": ["test.t_tests"], "status": "done"}]})
    assert stale.status_code == 409
    assert forged.status_code == 422
    assert store.current("session-a") == plan


def test_reassigning_a_pending_step_requires_a_new_exact_version_approval(tmp_path):
    root, repo, store, plan = fixture(tmp_path)
    with TestClient(app) as client:
        assert client.post("/agent/sessions/session-a/plan/approve", params={"project_root": str(root)},
                           json={"version": 1}).status_code == 200
        response = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
            json={"version": 1, "steps": [{"step_id": "test", "title": "Describe instead",
                                          "operation_ids": ["model.genesis"]}]})
    assert response.status_code == 200, response.text
    assert response.json()["plan"]["status"] == "needs_approval"
    from workbench.agent.plans import scope_for
    assert scope_for(store.current("session-a"), ["model.genesis"])["in_plan"] is False


def test_model_notice_is_bounded_and_overlarge_edits_fail_before_commit(tmp_path):
    root, repo, store, plan = fixture(tmp_path)
    steps = [{"step_id": f"s{i}", "title": "A" * 200,
              "operation_ids": ["test.t_tests"], "expected_outputs": ["B" * 200] * 40}
             for i in range(40)]
    with TestClient(app) as client:
        response = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                                json={"version": 1, "steps": steps})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AGENT_PLAN_EDIT_TOO_LARGE"
    assert store.current("session-a") == plan
    assert repo.get_branch("session-a") == []


def test_plan_write_failure_retries_the_original_prepared_revision(tmp_path, monkeypatch):
    root, repo, store, plan = fixture(tmp_path)
    original = PlanStore._append
    def fail(*args):
        raise OSError("lost plan append")
    with TestClient(app, raise_server_exceptions=False) as client:
        with monkeypatch.context() as scoped:
            scoped.setattr(PlanStore, "_append", fail)
            assert client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                                json={"version": 1, "question": "Other question"}).status_code == 500
        assert store.current("session-a") == plan
        intent = next(e.payload for e in repo.get_branch("session-a") if e.entry_type == "plan_edit_intent")
        response = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
                                json={"version": 1, "question": "Other question"})
    assert response.status_code == 200, response.text
    assert response.json()["plan"] == intent["snapshot"]
    assert len(store.history("session-a")) == 2


def test_completed_step_cannot_be_reassigned_and_mode_survives_session_reload(tmp_path, monkeypatch):
    from dataclasses import replace
    from tests.test_agent_routes import _config
    from workbench.http import agent_routes
    root, repo, store, plan = fixture(tmp_path)
    store.update("session-a", lambda previous: replace(previous, steps=(replace(previous.steps[0], status="done"),)))
    repo.update_metadata("session-a", execution_mode="auto")
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", _config)
    with TestClient(app) as client:
        assert client.get("/agent/sessions/session-a", params={"project_root": str(root)}).json()["execution_mode"] == "auto"
        response = client.patch("/agent/sessions/session-a/plan", params={"project_root": str(root)},
            json={"version": 1, "steps": [{"step_id": "test", "title": "Another model",
                                          "operation_ids": ["model.genesis"]}]})
    assert response.status_code == 409
    assert store.current("session-a").steps[0].status == "done"
