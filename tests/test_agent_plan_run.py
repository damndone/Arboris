"""A real plan stop is terminal before explicit approval and continuation."""
import asyncio

from fastapi.testclient import TestClient

from tests.test_agent_routes import _config
from tests.test_read_only_analysis import _Fixture
from workbench.agent.model import ModelStreamEvent
from workbench.agent.runtime_adapter import headless_runtime_scope
from workbench.agent.turn_store import TurnStore
from workbench.app import app


def test_normal_auto_plan_stop_leaves_no_active_turn_and_can_continue_after_approval(tmp_path):
    fixture = _Fixture(tmp_path)
    requests = []
    class PlanThenStop:
        async def stream(self, request):
            requests.append(request)
            if len(requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "plan", "tool_id": "update_plan", "arguments": {
                        "question": "Describe the source sample.", "criteria": ["Use recorded counts."],
                        "steps": [{"step_id": "describe", "title": "Describe the source sample",
                                   "operation_ids": ["statistical.explore"]}]}})
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "The approved plan is available.")
                yield ModelStreamEvent.done(request.request_id)
    with headless_runtime_scope(adapter_factory=lambda config: PlanThenStop(), config=_config()):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            params = {"project_root": str(fixture.project_root)}
            path = "/agent/sessions/chain-session"
            response = client.post(path + "/turns", params=params, json={
                "question": "Describe the source sample.", "execution_mode": "auto"})
            assert response.status_code == 200, response.text
            assert response.json()["assistant"]["stop_reason"] == "proposal_ready"
            assert len(requests) == 1
            assert TurnStore(fixture.project_root).list_active() == []
            plan = client.get(path + "/plan", params=params).json()["plan"]
            assert plan["status"] == "draft"
            approved = client.post(path + "/plan/approve", params=params, json={"version": plan["version"]})
            assert approved.status_code == 200, approved.text
            assert len(requests) == 1  # Approval alone never constructs another provider step.
            continued = client.post(path + "/continue", params=params, json={"execution_mode": "auto"})
            assert continued.status_code == 200, continued.text
            assert len(requests) == 2
            assert TurnStore(fixture.project_root).list_active() == []
