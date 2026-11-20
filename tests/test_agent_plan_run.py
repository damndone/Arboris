"""A real plan stop is terminal before explicit approval and continuation."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_plan_preflight import _arguments
from tests.test_agent_routes import _config
from tests.test_data_column_cast import _register_source_node_identity
from tests.test_read_only_analysis import _Fixture, _explore, _recode
from workbench import analysis_ledger
from workbench.agent.model import ModelStreamEvent
from workbench.agent.protocol import ensure_standing_message
from workbench.agent.runtime_adapter import headless_runtime_scope
from workbench.agent.turn_store import TurnStore
from workbench.app import app
from workbench.cli_agent import continue_headless, run_headless


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


@pytest.mark.parametrize(("step", "permission_class", "authority"), [
    (_explore("distribution", "region"), "analyze", "read_only_policy"),
    (_recode(), "derive", "approved_plan"),
])
def test_auto_redirects_a_premature_workflow_to_one_plan_approval(tmp_path, step, permission_class, authority):
    fixture = _Fixture(tmp_path)
    _register_source_node_identity(fixture.project_root, fixture.run_id)
    session_id = "chain-session"
    mode = {"mode": "auto", "execution_policy": "auto_read_only"}
    question = "Describe the distribution by region and explain how to check it."
    operation = _arguments(fixture, [step])
    fixture.repository.update_metadata(session_id, execution_mode="auto", execution_policy="auto_read_only")
    ensure_standing_message(fixture.repository, session_id, name="workbench_agent_protocol",
                            content="Old Auto instructions.", message_type="agent_protocol")

    requests = []

    class RecoverToPlan:
        async def stream(self, request):
            requests.append(request)
            if len(requests) in {1, 3}:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": f"workflow-{len(requests)}", "tool_id": "run_operation", "arguments": operation,
                })
            elif len(requests) == 2:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "plan", "tool_id": "update_plan", "arguments": {
                        "question": question, "criteria": ["Use the registered data."],
                        "steps": [{"step_id": "analysis", "title": "Analyze the data",
                                   "operation_ids": [step["operation_id"]]}],
                        "allowed_classes": ["analyze"],
                    },
                })
            else:
                assert len(requests) == 4
                executed = json.loads(request.messages[-1]["content"])["output"]
                assert executed["executed"] and executed["operation"]["status"] == "completed"
                yield ModelStreamEvent.text_delta(request.request_id, "The regional tabulation is complete.")
                yield ModelStreamEvent.done(request.request_id)
                return
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    with headless_runtime_scope(adapter_factory=lambda _: RecoverToPlan(), config=_config()):
        first = asyncio.run(run_headless(fixture.project_root, question, session_id=session_id,
                                         on_event=lambda _: None, **mode))
        assert first["status"] == "awaiting_plan_approval", first
        assert len(requests) == 2 and first["plan"]["status"] == "draft"
        assert first["plan"]["allowed_classes"] == [permission_class]
        assert first["pending_proposals"] == []
        assert fixture.orchestrator.operation_store.list_records() == []
        assert analysis_ledger.read(fixture.project_root) == []
        assert TurnStore(fixture.project_root).list_active() == []

        [protocol] = [message["content"] for message in requests[0].messages
                      if message.get("name") == "workbench_agent_protocol"]
        assert "Old Auto instructions." not in protocol
        assert "before submitting a workflow for execution" in protocol
        feedback = json.loads(requests[1].messages[-1]["content"])["output"]
        assert feedback["plan_required"] and not feedback["executed"]
        assert "update_plan" in feedback["guidance"] and "prepare_only" in feedback["guidance"]

        params = {"project_root": str(fixture.project_root)}
        with TestClient(app, base_url="http://127.0.0.1") as client:
            approval = client.post(f"/agent/sessions/{session_id}/plan/approve", params=params,
                                   json={"version": first["plan"]["version"]})
        assert approval.status_code == 200, approval.text
        assert len(requests) == 2

        continued = asyncio.run(continue_headless(fixture.project_root, session_id,
                                                   on_event=lambda _: None, **mode))
        assert continued["pending_proposals"] == []
        assert continued["plan"]["steps"][0]["status"] == "done"
        records = fixture.orchestrator.operation_store.list_records()
        assert len(records) == 2
        assert {(record.operation_id, record.status) for record in records} == {
            ("operation.multi_step", "completed"), (step["operation_id"], "completed"),
        }
        [parent] = [record for record in records if record.workflow_step_id is None]
        assert parent.actor_type == authority
        criteria = [event for event in analysis_ledger.read(fixture.project_root)
                    if event.get("event_type") == "criteria_fixed"]
        assert len(criteria) == 1


def test_ordinary_workflow_dispatch_refuses_a_newly_registered_source(tmp_path):
    from workbench.agent import plans
    from workbench.artifacts import sha256_file
    from workbench.http.agent_operation_routes import _run_read_only_proposal

    fixture = _Fixture(tmp_path)
    _register_source_node_identity(fixture.project_root, fixture.run_id)
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = 'auto'
    draft = plans.merge(None, question='Tabulate regions.', criteria=[],
                        steps=(plans.PlanStep('describe', 'Tabulate regions', ('statistical.explore',)),),
                        budget=None, allowed_classes=None)
    orchestrator.plan_store.save('chain-session', plans.approve(draft))
    run = fixture.project_root / 'runs' / fixture.run_id

    async def change_registered_source(proposal, actor=None):
        dataset = run / 'data.csv'
        dataset.write_text(dataset.read_text().replace('north', 'east'))
        index_path = run / 'artifacts_index.json'
        index = json.loads(index_path.read_text())
        index['artifacts'][0]['sha256'] = sha256_file(dataset)
        index_path.write_text(json.dumps(index))
        return await _run_read_only_proposal(fixture.project_root, orchestrator, proposal, actor)

    orchestrator.read_only_runner = change_registered_source
    result = asyncio.run(orchestrator.tool_registry('chain-a').execute({
        'tool_id': 'run_operation', 'tool_call_id': 'work',
        'arguments': _arguments(fixture, [_explore('regions', 'region')]),
    }, session_id='chain-session'))
    assert result.ok and result.output['executed'] is False, result
    assert 'registered dataset digest changed' in result.output['error']
    assert not list((fixture.repository.root / 'exploration').glob('*.jsonl'))


@pytest.mark.parametrize("operation_id,message", [
    ("model.genesis", "project rules deny"),
    ("operation.multi_step", "actual workflow step operation IDs"),
])
def test_auto_declines_an_unapprovable_plan_without_an_approval_card(tmp_path, operation_id, message):
    fixture = _Fixture(tmp_path)
    rules = fixture.repository.root / "agent-permissions.json"
    rules.write_text(json.dumps({"deny": [{"class": "external"}, {"class": "high"}]}))
    question = "Estimate a panel effect and report robustness."
    requests = []

    class DeniedPlan:
        async def stream(self, request):
            requests.append(request)
            if len(requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "plan", "tool_id": "update_plan", "arguments": {
                        "question": question, "criteria": ["Use fixed effects and report robustness."],
                        "steps": [{"step_id": "fit", "title": "Fit panel fixed effects",
                                   "operation_ids": [operation_id]}],
                        "allowed_classes": ["analyze"],
                    },
                })
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "The proposed plan needs revision.")
                yield ModelStreamEvent.done(request.request_id)

    with headless_runtime_scope(adapter_factory=lambda _: DeniedPlan(), config=_config()):
        turn = asyncio.run(run_headless(fixture.project_root, question, session_id="chain-session",
                                         mode="auto", execution_policy="auto_read_only", on_event=lambda _: None))
    assert turn["status"] == "idle", turn
    assert turn["plan"] is None and turn["pending_proposals"] == []
    assert len(requests) == 2
    feedback = json.loads(requests[1].messages[-1]["content"])["output"]
    assert feedback["saved"] is False and not feedback.get("requires_confirmation")
    assert operation_id in feedback["error"] and message in feedback["error"]
    assert fixture.orchestrator.operation_store.list_records() == []
    assert analysis_ledger.read(fixture.project_root) == []


@pytest.mark.parametrize(("mode", "question", "focus_run", "plan_first"), [
    ("auto", "Estimate the training effect and report robustness.", None, True),
    ("ask", "Estimate the training effect and report robustness.", None, False),
    ("auto", "What does the existing training result say?", None, False),
    ("auto", "What does a full analysis require?", None, False),
    ("auto", "Compare the diagnostics in the current fitted model.", None, False),
    ("auto", "Estimate the training effect and report robustness.", "other-run", False),
])
def test_selected_auto_analysis_gets_facts_and_a_bounded_first_plan(
    tmp_path, monkeypatch, mode, question, focus_run, plan_first,
):
    from workbench.agent import initial_plan_facts

    fixture = _Fixture(tmp_path)
    if focus_run is not None:
        fixture.repository.append("chain-session", "custom_message", {
            "message_type": "agent_focus", "name": "workbench_agent_focus", "audience": "model",
            "content": "The person selected a historical run.",
            "metadata": {"focus": {"run_id": focus_run, "kind": "node", "id": "model:historical"}},
        })
    facts_reads = []

    def facts(provider, *, owner_run_id, active_head_run_id):
        facts_reads.append((owner_run_id, active_head_run_id))
        return {"schema": "workbench.initial_plan_facts.v1", "content_role": "untrusted_data",
                "source": {"run_id": owner_run_id, "artifact_id": "fixture"},
                "dataset": {"columns": [{"name": "training", "unique_count": 2}]}}

    monkeypatch.setattr(initial_plan_facts, "initial_plan_facts", facts)
    requests = []

    class FirstPlan:
        def supports_named_tool_choice(self):
            return True

        async def stream(self, request):
            requests.append(request)
            if not plan_first or len(requests) > 2:
                yield ModelStreamEvent.text_delta(request.request_id, "The requested analysis is ready to inspect.")
                yield ModelStreamEvent.done(request.request_id)
                return
            if len(requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "unoffered", "tool_id": "calculate",
                    "arguments": {"calculations": [{"expression": "2+2"}]},
                })
            operations = ["operation.multi_step"] if len(requests) == 1 else ["statistical.explore"]
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id": f"plan-{len(requests)}", "tool_id": "update_plan",
                "arguments": {"question": question, "criteria": ["Use the selected data."],
                              "steps": [{"step_id": "estimate", "title": "Estimate effect",
                                         "operation_ids": operations}]},
            })
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    settings = {"mode": mode, "execution_policy": "auto_read_only", "on_event": lambda _: None}
    with headless_runtime_scope(adapter_factory=lambda _: FirstPlan(), config=_config()):
        first = asyncio.run(run_headless(fixture.project_root, question, session_id="chain-session", **settings))
        if not plan_first:
            assert not facts_reads and first["plan"] is None
            assert all("run_operation" in {tool["tool_id"] for tool in request.tools} for request in requests)
            return
        assert first["status"] == "awaiting_plan_approval", first
        assert len(requests) == 2 and first["plan"]["version"] == 1
        assert facts_reads == [(fixture.run_id, fixture.run_id)]
        withheld = next(message for message in requests[1].messages if message.get("tool_call_id") == "unoffered")
        assert json.loads(withheld["content"])["error"] == "initial_plan_tool_not_offered"
        for request in requests:
            assert [tool["tool_id"] for tool in request.tools] == ["update_plan"]
            assert request.model_config["tool_choice"]["function"]["name"] == "update_plan"
            [note] = [message for message in request.messages if message.get("name") == "workbench_initial_plan"]
            assert "training" in note["content"] and "untrusted_data" in note["content"]
        assert analysis_ledger.read(fixture.project_root) == []
        with TestClient(app) as client:
            approved = client.post("/agent/sessions/chain-session/plan/approve",
                params={"project_root": str(fixture.project_root)}, json={"version": 1})
        assert approved.status_code == 200, approved.text
        asyncio.run(continue_headless(fixture.project_root, "chain-session", **settings))
        assert len(requests) == 3 and "run_operation" in {tool["tool_id"] for tool in requests[-1].tools}
        assert not requests[-1].model_config.get("tool_choice")
        assert len([message for message in requests[-1].messages if message.get("name") == "workbench_initial_plan"]) == 1
