"""Target conflicts reject the original request and keep correction in the shared loop."""
import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from tests.test_agent_analysis_loop_lifecycle import _adapter_kwargs, _orchestrator
from tests.test_agent_analysis_loop_resolver import _write_source
from workbench.agent.chains import ensure_chain_root
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.analysis_loop.lifecycle import AnalysisLoopProposalError, create_analysis_loop_proposal
from workbench.app import app
from workbench.http import agent_analysis_routes


@pytest.mark.parametrize("requested, has_primary, code", [
    ("coef:control", True, "ANALYSIS_TARGET_CONFLICT"),
    ("coef:missing", True, "ANALYSIS_TARGET_UNKNOWN"),
    ("coef:missing", False, "ANALYSIS_TARGET_UNKNOWN"),
])
def test_shared_admission_rejects_selection_with_a_bounded_correction_plan(tmp_path, requested, has_primary, code):
    orchestrator = _orchestrator(tmp_path)
    arguments = _adapter_kwargs(tmp_path)
    if not has_primary:
        arguments["source"] = replace(arguments["source"], primary_estimand=None)
    with pytest.raises(AnalysisLoopProposalError) as failure:
        create_analysis_loop_proposal(orchestrator=orchestrator, chain_id="chain-a",
                                     requested_result_id=requested, **arguments)
    assert failure.value.code == code
    recovery = failure.value.details["recovery"]
    assert recovery["schema"] == "workbench.analysis-target-recovery.v1"
    assert recovery["status"] == "needs_target_decision"
    assert recovery["requested_result_id"] == requested
    assert recovery["primary_result_id"] == ("coef:treatment" if has_primary else None)
    assert recovery["safe_next_call"]["tool_id"] == "inspect_node_context"
    assert recovery["safe_next_call"]["arguments"]["owner_run_id"] == "run-source"
    assert recovery["requires_target_decision"] is True
    assert recovery["resume_policy"] == "independent_steps_only"
    assert len(recovery["steps"]) == 3
    assert recovery["options"][0]["id"] == "preserve_requested_target"
    assert len(recovery["options"]) == (2 if has_primary else 1)
    assert "do not execute" in recovery["options"][-1]["prompt"].lower()
    assert orchestrator.proposal_store.latest_revisions_for_session("chain-session") == []
    assert orchestrator.operation_store.list_records() == []
    assert not list((tmp_path / "workbench" / "analysis-packets").rglob("*.json"))


class RecoveryProvider(NodeOperationContextProvider):
    def inspect_node_context(self, request):
        return {"node_hash": "node-source", "forest_node_key": "node-source",
                "context_version": "node-operation-context/v1", "context_fingerprint": "context-source",
                "active_head_run_id": request.active_head_run_id, "owner_resolution": "active_head_contains_node"}


def _setup(tmp_path, role="chain"):
    project = tmp_path / "project"
    project.mkdir()
    _write_source(project)
    path = project / "runs/run-source/model_results/ols_1.json"
    result = json.loads(path.read_text())
    primary, requested = result["stable_result_ids"][0], result["stable_result_ids"][-1]
    assert primary != requested
    result["primary_estimand"] = {"result_id": primary, "role": "primary"}
    path.write_text(json.dumps(result))
    repository = JsonlSessionRepository(project / "workbench")
    repository.create_session("main", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    ensure_chain_root(repository.root, runs_root=project / "runs", chain_id="chain-a",
                      active_head_run_id="run-source", agent_session_id="chain-session")
    events = AgentEventStream(repository.root)
    session = "main" if role == "main" else "chain-session"
    core = AgentCore(repository, events, object(), session_id=session)
    orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="main", context_provider=RecoveryProvider(project))
    if role == "main":
        orchestrator.register_main(session, core)
    else:
        orchestrator.register_chain("chain-a", session, core)
    request = {"operation_id": "model.rerun", "target": {"run_id": "run-source", "node_ref": "model:ols_1",
        "node_hash": "guess", "forest_node_key": "guess", "result_id": requested},
        "preconditions": {"context_version": "node-operation-context/v1", "context_fingerprint": "guess",
            "active_head_run_id": "run-source", "owner_resolution": "guess"},
        "changes": {"covariance": {"old": "unadjusted", "new": "clustered"},
            "entity_col": {"old": None, "new": "company_id"}}, "evidence_refs": [],
        "expected_effect": ["Review clustered inference."], "risks": ["Cluster count matters."]}
    registry = orchestrator.tool_registry("project" if role == "main" else "chain-a")
    core.tools, core.tool_runtime = registry.descriptors(), registry
    return project, primary, requested, repository, core, orchestrator, registry, request


def test_manual_and_agent_return_the_same_selection_recovery_without_a_provider(tmp_path, monkeypatch):
    project, primary, requested, repository, core, orchestrator, registry, request = _setup(tmp_path)
    agent = asyncio.run(registry.execute({"tool_id": "run_operation", "tool_call_id": "conflict", "arguments": request},
                                        session_id=core.session_id))
    assert not agent.ok
    assert agent.output["code"] == "ANALYSIS_TARGET_CONFLICT"
    assert agent.output["executed"] is False
    monkeypatch.setattr(agent_analysis_routes, "NodeOperationContextProvider", RecoveryProvider)
    with TestClient(app) as client:
        response = client.post(f"/agent/sessions/{core.session_id}/analysis-loop/proposals",
            params={"project_root": str(project)}, json={"source_run_id": "run-source", "source_node_ref": "model:ols_1",
                "active_head_run_id": "run-source", "cluster_variable": "company_id", "result_id": requested})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == agent.output["code"]
    assert error["details"]["recovery"] == agent.output["recovery"]
    assert orchestrator.proposal_store.latest_revisions_for_session(core.session_id) == []
    assert orchestrator.operation_store.list_records() == []


@pytest.mark.parametrize("role", ["chain", "main"])
@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_core_reviews_conflict_and_drafts_a_plan_without_repeating_or_changing_the_target(tmp_path, role, mode):
    project, primary, requested, repository, core, orchestrator, registry, request = _setup(tmp_path, role)
    orchestrator.execution_mode = mode

    class RecordedModel:
        def __init__(self): self.requests = []; self.recovery = None; self.target_chosen = False
        async def stream(self, model_request):
            self.requests.append(model_request)
            index = len(self.requests)
            if self.target_chosen:
                call = {"tool_id": "run_operation", "arguments": {
                    **request, "target": {**request["target"], "result_id": primary}}}
            elif index == 1:
                call = {"tool_id": "run_operation", "arguments": request}
            elif index == 2:
                payload = json.loads([m for m in model_request.messages if m.get("role") == "tool"][-1]["content"])
                assert payload["ok"] is False
                self.recovery = payload["output"]["recovery"]
                assert self.recovery["requested_result_id"] == requested
                assert self.recovery["primary_result_id"] == primary
                call = self.recovery["safe_next_call"]
            elif index == 3:
                call = {"tool_id": "update_plan", "arguments": {
                    "question": "Resolve the target conflict without substituting the requested estimand.",
                    "criteria": ["Keep the requested target unless the user explicitly changes it."],
                    "steps": [{"step_id": "target-decision", "title": "Review the generated target correction options",
                        "operation_ids": ["model.rerun"], "status": "awaiting"}]}}
            else:
                yield ModelStreamEvent.text_delta(model_request.request_id,
                    "The analysis is partly complete. The requested result conflicts with the source primary. "
                    "I reviewed the source and drafted correction options; choose the target before dependent estimation.")
                yield ModelStreamEvent.done(model_request.request_id)
                return
            yield ModelStreamEvent.tool_call_delta(model_request.request_id, {**call, "tool_call_id": f"step-{index}"})
            yield ModelStreamEvent.done(model_request.request_id, "tool_calls")

    model = RecordedModel()
    core.adapter = model
    asyncio.run(core.prompt("Continue the analysis while preserving the requested target.", budget={"max_steps": 6}))
    assert len(model.requests) in {3, 4}
    tool_messages = [entry.payload for entry in repository.get_branch(core.session_id) if entry.payload.get("role") == "tool"]
    assert [m["name"] for m in tool_messages] == ["run_operation", "inspect_node_context", "update_plan"]
    assert len([entry for entry in repository.get_branch(core.session_id) if entry.payload.get("role") == "user"]) == 1
    plan = orchestrator.plan_store.current(core.session_id)
    assert plan.steps[0].status == "awaiting"
    assert orchestrator.operation_store.list_records() == []
    assert orchestrator.proposal_store.latest_revisions_for_session(core.session_id) == []
    assert json.loads((project / "runs/run-source/model_results/ols_1.json").read_text())["primary_estimand"]["result_id"] == primary

    before_choice = len(model.requests)
    model.target_chosen = True
    asyncio.run(core.prompt("I choose the source primary. Draft its operation proposal for confirmation; do not execute it.",
                            budget={"max_steps": 3}))
    assert len(model.requests) == before_choice + 1
    proposals = orchestrator.proposal_store.latest_revisions_for_session(core.session_id)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.status == "pending"
    assert proposal.preconditions["analysis_loop"]["target_hash"]
    from workbench.analysis_loop.storage import PlanDiffStore
    packet = PlanDiffStore(repository.root).get_terminal_packet(proposal.preconditions["plan_logical_key"])
    assert packet.plan_diff.target_identity["result_id"] == primary
    assert orchestrator.operation_store.list_records() == []


def test_selection_error_recovery_respects_the_tool_output_budget():
    from workbench.agent.tools import ToolDefinition, ToolRegistry
    from workbench.analysis_loop.lifecycle import AnalysisLoopSelectionError

    def refuse(arguments, context):
        raise AnalysisLoopSelectionError("Nothing was submitted or executed.", code="ANALYSIS_TARGET_CONFLICT",
            details={"recovery": {"schema": "workbench.analysis-target-recovery.v1", "requested_result_id": "coef:" + "x" * 20000,
                                  "steps": ["review source"], "options": []}})
    registry = ToolRegistry()
    registry.register(ToolDefinition("bounded-recovery", "v1", {"type": "object"}, "proposal", refuse, max_output_budget=2048))
    result = asyncio.run(registry.execute({"tool_id": "bounded-recovery", "tool_call_id": "bounded", "arguments": {}}, session_id="s"))
    assert result.ok is False
    assert result.output["code"] == "ANALYSIS_TARGET_CONFLICT"
    assert len(json.dumps(result.output, ensure_ascii=False, sort_keys=True)) <= 2048
    assert len(json.dumps(result.to_payload(), ensure_ascii=False)) < 3000


@pytest.mark.parametrize("omit_selector", [False, True])
def test_target_decision_is_required_after_restart_even_when_the_model_drops_the_selector(tmp_path, omit_selector):
    from workbench.agent import permissions
    project, primary, requested, repository, core, orchestrator, registry, request = _setup(tmp_path)
    rejected = asyncio.run(registry.execute({"tool_id": "run_operation", "tool_call_id": "conflict", "arguments": request},
                                            session_id=core.session_id))
    assert rejected.ok is False
    repeated_rejection = asyncio.run(registry.execute({"tool_id": "run_operation", "tool_call_id": "conflict-repeat", "arguments": request},
                                                     session_id=core.session_id))
    assert repeated_rejection.output == rejected.output
    assert sum(entry.payload.get("message_type") == "analysis_target_conflict"
               for entry in repository.get_branch(core.session_id)) == 1
    # Restart with a rule that ordinarily allows derivation. The unresolved
    # scientific target decision must still use the common human approval.
    restarted = WorkbenchOrchestrator(JsonlSessionRepository(repository.root), AgentEventStream(repository.root),
        main_session_id="main", context_provider=RecoveryProvider(project))
    restarted.register_chain("chain-a", core.session_id,
        AgentCore(restarted.repository, restarted.events, object(), session_id=core.session_id))
    restarted.execution_mode = "auto"
    restarted.permission_rules = permissions.Rules(allow=(permissions.Rule(permissions.PermissionClass.DERIVE),))
    restarted.plan_scope = {"in_plan": True, "named": True, "allowed_classes": ["derive"]}
    dispatched = []

    async def must_wait(proposal, actor):
        dispatched.append(proposal)
        raise AssertionError("A changed target requires a human decision")

    restarted.read_only_runner = must_wait
    target = {**request["target"], "result_id": primary}
    if omit_selector:
        target.pop("result_id")
    corrected = asyncio.run(restarted.tool_registry("chain-a").execute({"tool_id": "run_operation", "tool_call_id": "corrected",
        "arguments": {**request, "target": target}}, session_id=core.session_id))
    assert corrected.ok
    assert corrected.output.get("requires_confirmation") is True
    assert dispatched == []
    proposal = restarted.proposal_store.latest_revision(corrected.output["proposal"]["proposal_id"])
    assert proposal.preconditions["target_correction"]["requested_result_id"] == requested
    assert any("target" in effect.lower() and requested in effect and primary in effect for effect in proposal.expected_effect)
    with pytest.raises(PermissionError, match="target"):
        restarted.confirm_proposal(proposal.proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
            actor_type="approved_plan", current_context_fingerprint="context-source", current_active_head_run_id="run-source")
    assert restarted.operation_store.list_records() == []
    record = restarted.confirm_proposal(proposal.proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
        actor_type="user", current_context_fingerprint="context-source", current_active_head_run_id="run-source")
    assert record.status == "pending"
    from workbench.analysis_loop.lifecycle import latest_target_correction
    decision = latest_target_correction(JsonlSessionRepository(repository.root), core.session_id, "run-source", "model:ols_1")
    assert decision["confirmed"] is True
    repeated = asyncio.run(restarted.tool_registry("chain-a").execute({"tool_id": "run_operation", "tool_call_id": "repeat",
        "arguments": {**request, "target": target}}, session_id=core.session_id))
    assert repeated.output.get("proposal_id", (repeated.output.get("proposal") or {}).get("proposal_id")) == proposal.proposal_id
    assert len(restarted.proposal_store.latest_revisions_for_session(core.session_id)) == 1


@pytest.mark.parametrize("authority", ["project_rule", "session_grant", "approved_plan"])
def test_target_decision_uses_the_common_permission_floor(authority):
    from workbench.agent import permissions
    rule = permissions.Rule(permissions.PermissionClass.DERIVE)
    request = permissions.Request("model.rerun", permissions.PermissionClass.DERIVE,
        in_plan=True, named_in_plan=True, class_allowed_by_plan=True, target_decision_required=True)
    rules = permissions.Rules(allow=(rule,)) if authority == "project_rule" else permissions.Rules()
    grants = permissions.Grants(frozenset({rule})) if authority == "session_grant" else permissions.Grants()
    decision = permissions.decide(permissions.Mode.AUTO, request, rules, grants)
    assert decision.outcome == permissions.Outcome.ASK
    assert decision.floor is True
    assert "target" in decision.reason
