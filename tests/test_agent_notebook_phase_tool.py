"""Planning and execution tools stay on the current scoped Core command."""
import asyncio
import importlib
import pytest

from tests.test_read_only_analysis import _Fixture, _recode, FINGERPRINT
from workbench.agent.model import ModelStreamEvent
from workbench.agent.phases import PhaseRequest, PhaseStep


@pytest.mark.parametrize("approval", [False, True])
def test_notebook_planning_tool_uses_the_current_core_model_and_budget(tmp_path, monkeypatch, approval):
    module = importlib.import_module("workbench.agent.planning.agent_phase")
    fixture = _Fixture(tmp_path)
    core = fixture.orchestrator._chain("chain-a")[1]
    entered = []

    class Phase:
        episode_id = "shared-episode"
        def request(self, transcript):
            return PhaseRequest([{"role":"user", "content":"Plan from the bound source."}], [])
        async def consume(self, events, *, error=None):
            assert error is None
            return PhaseStep("completed", result="planned", public_result=({"requires_confirmation":True, "proposal":{"operation_id":"operation.multi_step", "changes":{"steps":[]}}} if approval else {"planned":True}))
        def checkpoint(self):
            return {"episode_id":self.episode_id}
        def failure(self, reason, error=None):
            return RuntimeError(reason)

    def factory(**kwargs):
        entered.append(kwargs)
        return Phase()
    monkeypatch.setattr(module, "create_phase", factory)

    class Model:
        def __init__(self): self.requests = []; self.steps = []
        async def stream(self, request):
            self.requests.append(request)
            self.steps.append(core._steps_used)
            if len(self.requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id":"plan", "tool_id":"plan_analysis",
                    "arguments":{"notebook_id":"source-notebook", "question":"Plan the analysis."}})
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "Planned.")
                yield ModelStreamEvent.done(request.request_id)

    model = Model()
    core.adapter = model
    result = asyncio.run(core.prompt("Plan the analysis.", budget={"max_steps":3}))
    assert result
    assert len(model.requests) == (2 if approval else 3)
    assert model.steps == ([1, 2] if approval else [1, 2, 3])
    assert entered[0]["core"] is core
    assert entered[0]["orchestrator"] is fixture.orchestrator
    assert {m["session_id"] for m in fixture.repository.list_metadata()} == {"main-session", "chain-session"}


def test_run_operation_is_the_single_operation_tool_entry(tmp_path):
    fixture = _Fixture(tmp_path)
    from tests.test_data_column_cast import _register_source_node_identity
    _register_source_node_identity(fixture.project_root, fixture.run_id)
    registry = fixture.orchestrator.tool_registry("chain-a")
    descriptors = {tool["tool_id"]:tool for tool in registry.descriptors()}
    assert "run_operation" in descriptors
    assert {"propose_operation", "propose_analysis_loop"}.isdisjoint(descriptors)
    assert not any(hasattr(fixture.orchestrator, name) for name in (
        "create_proposal", "execute_confirmed_proposal", "execute_confirmed_fork", "reconcile_confirmed_proposal"))
    request = {"operation_id":"operation.multi_step", "target":{
        "run_id":fixture.run_id, "node_ref":"stage:source", "artifact_id":fixture.artifact_id},
        "preconditions":{"context_version":"node-operation-context/v1", "context_fingerprint":FINGERPRINT,
                         "active_head_run_id":fixture.run_id, "owner_resolution":"single_candidate"},
        "changes":{"steps":[_recode()]}, "evidence_refs":[], "expected_effect":["Derive a column."], "risks":[]}
    result = asyncio.run(registry.execute({"tool_id":"run_operation", "tool_call_id":"run", "arguments":request}, session_id="chain-session"))
    assert result.ok and result.output["requires_confirmation"] is True
    proposal = fixture.orchestrator.proposal_store.latest_revision(result.output["proposal"]["proposal_id"])
    assert proposal.session_id == "chain-session"
    assert fixture.orchestrator.operation_store.list_records() == []


@pytest.mark.parametrize("scenario", ["complete", "changed_source", "preparation_failure",
    "restart_provider", "restart_correction", "restart_source_change", "restart_after_publish", "restart_provider_error"])
def test_uploaded_source_plans_on_main_turn_and_executes_one_common_receipt(tmp_path, monkeypatch, scenario):
    from fastapi.testclient import TestClient
    from tests.test_notebook_routes import make_project, store_upload_bytes
    from tests.test_agent_workflow_integration import IdleAdapter
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.notebook import NotebookService
    from workbench.agent.notebook.planning_agent import NotebookPlanningAgent
    from workbench.app import app

    project = make_project(tmp_path)
    csv = "y,x\n" + "\n".join(f"{3+i*2+(i%3)*.2},{i}" for i in range(30))
    upload = store_upload_bytes(project, csv.encode(), filename="data.csv")
    service = NotebookService(project)
    notebook = service.ensure_default_projection(dataset={"kind":"dataset", "upload_sha256":upload,
        "filename":"data.csv", "sheet_names":[]}, created_by="test", available_capabilities=["ols"])
    from workbench.agent.planning.factory import _baseline_planning_evidence
    from tests.test_notebook_routes import _trace
    pack = _baseline_planning_evidence(service, notebook.notebook_id,
        service.compile_context(notebook.notebook_id), _trace(project, notebook.notebook_id, notebook.run_family_id))
    evidence = pack.records[0]
    pin = NotebookPlanningAgent._execution_pins(service.compile_context(notebook.notebook_id))["workflow_source"]
    repository = JsonlSessionRepository(project / "workbench")
    repository.create_session("main", chain_id="project", role="main")
    events = AgentEventStream(repository.root)
    requests = []

    class Model:
        async def stream(self, request):
            requests.append(request)
            if scenario == "restart_provider_error" and len(requests) == 2:
                raise OSError("offline provider stream interrupted")
            if scenario == "restart_correction" and len(requests) == 2:
                yield ModelStreamEvent.text_delta(request.request_id, "An untyped answer needs correction.")
                yield ModelStreamEvent.done(request.request_id)
                return
            if scenario in {"restart_provider", "restart_correction", "restart_source_change"} and len(requests) == (3 if scenario == "restart_correction" else 2):
                from tests.test_agent_core_restart import ProcessLost
                raise ProcessLost()
            if len(requests) == 1:
                arguments = {"notebook_id":notebook.notebook_id, "question":"Fit y on x and report the result."}
                tool = "plan_analysis"
            else:
                arguments = {"options":[{"rank":1, "rationale":"Estimate the requested model.",
                    "assumptions":[], "capability_id":"ols", "option_id":"ols",
                    "proposal":{"proposal_id":"ols", "proposal_revision":1,
                        "operation_id":"operation.multi_step", "operation_version":"v1",
                        "target":pin["target"], "preconditions":pin["preconditions"],
                        "changes":{"steps":[{"step_id":"estimate", "operation_id":"model.genesis",
                            "spec":{"model_family":"ols", "covariance":"unadjusted",
                                "branches":[{"branch_id":"main", "outcome":"y", "predictors":["x"]}]}}]}},
                    "expected_artifacts":[{"artifact_id":"ols_1", "artifact_type":"model_result", "required":True,
                                           "count":1, "step":None}], "evidence_refs":[{"evidence_id":evidence.evidence_id,
                        "result_hash":evidence.result_hash, "source_refs":list(evidence.source_refs)}], "comparative_claims":[]}]}
                tool = "submit_notebook_option_batch"
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id":f"call-{len(requests)}", "tool_id":tool, "arguments":arguments})
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    from workbench.agent.turn_journal import TurnJournal, TurnRecoveryRequired
    from workbench.agent.turn_store import TurnStore
    from tests.test_agent_core_restart import ProcessLost
    turns = TurnStore(project)
    core = AgentCore(repository, events, Model(), session_id="main", model_name="offline-model",
        turn_journal=TurnJournal(turns, repository, session_id="main"))
    orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="main",
        context_provider=NodeOperationContextProvider(project))
    orchestrator.register_main("main", core)
    if scenario.startswith("restart_"):
        if scenario == "restart_provider_error":
            original_save = core.turn_journal.save
            def lose_after_error_receipt(*args, **kwargs):
                saved = original_save(*args, **kwargs)
                if args[1] == "phase_received":
                    raise ProcessLost()
                return saved
            monkeypatch.setattr(core.turn_journal, "save", lose_after_error_receipt)
        if scenario == "restart_after_publish":
            original_append = repository.append_once
            def lose_before_summary(session_id, entry_type, payload, **kwargs):
                if entry_type == "message" and payload.get("stop_reason") == "proposal_ready":
                    raise ProcessLost()
                return original_append(session_id, entry_type, payload, **kwargs)
            monkeypatch.setattr(repository, "append_once", lose_before_summary)
        with pytest.raises(ProcessLost):
            asyncio.run(core.prompt("Fit the uploaded dataset.", budget={"max_steps":2 if scenario == "restart_after_publish" else 5, "timeout_s":60}))
        [turn] = turns.list_active()
        saved_request = requests[-1]
        if scenario == "restart_source_change":
            service.set_focus(notebook.notebook_id, user_focus={"goal":"A different research question."})
        repository = JsonlSessionRepository(project / "workbench")
        events = AgentEventStream(repository.root)
        core = AgentCore(repository, events, Model(), session_id="main", model_name="offline-model",
            turn_journal=TurnJournal(TurnStore(project), repository, session_id="main"))
        orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="main",
            context_provider=NodeOperationContextProvider(project))
        orchestrator.register_main("main", core)
        if scenario == "restart_provider_error":
            from workbench.agent.notebook.planning_agent import NotebookPlanningUnavailable
            with pytest.raises(NotebookPlanningUnavailable, match="model provider failed: OSError"):
                asyncio.run(core.resume(turn.turn_id))
            assert requests[-1] is saved_request
            return
        if scenario == "restart_source_change":
            with pytest.raises(TurnRecoveryRequired, match="source"):
                asyncio.run(core.resume(turn.turn_id))
            assert requests[-1] is saved_request
            return
        result = asyncio.run(core.resume(turn.turn_id))
        assert requests[-1].messages == saved_request.messages
        assert turns.get(turn.turn_id).steps_used == len(requests)
        assert turns.get(turn.turn_id).status == "completed"
    else:
        result = asyncio.run(core.prompt("Fit the uploaded dataset.", budget={"max_steps":3, "timeout_s":60}))
    assert result and core._ready_proposal is not None, result
    assert len(requests) == (4 if scenario == "restart_correction" else 3 if scenario in {"restart_provider", "restart_source_change"} else 2)
    assert not (project / "runs" / pin["target"]["run_id"]).exists()
    proposal = core._ready_proposal
    if scenario == "changed_source":
        from workbench.lineage.upload_store import verify_upload
        verify_upload(project, upload).write_bytes(b"y,x\n999,1\n")
    if scenario == "preparation_failure":
        from workbench.agent.notebook import service_workflow
        def broken_source(*args, **kwargs):
            raise OSError("source unavailable at compilation")
        monkeypatch.setattr(service_workflow, "resolve_data_column_cast_context", broken_source)
    with TestClient(app) as client:
        response = client.post(f"/agent/sessions/main/proposals/{proposal['proposal_id']}/confirm",
            params={"project_root":str(project)}, json={"revision":proposal["revision"],
                "fingerprint":proposal["fingerprint"], "active_head_run_id":pin["target"]["run_id"]})
    if scenario == "changed_source":
        assert response.status_code == 409, response.text
        assert not orchestrator.operation_store.list_records()
        return
    assert response.status_code == 200, response.text
    record = response.json()["operation"]
    if scenario == "preparation_failure":
        assert record["status"] == "failed", record
        assert record["error"]["code"] == "WORKFLOW_EXECUTION_FAILED"
        return
    assert record["status"] == "completed", record
    parents = [r for r in orchestrator.operation_store.list_records() if r.operation_id == "operation.multi_step"]
    assert len(parents) == 1 and parents[0].record_id == record["record_id"]
    assert parents[0].agent_session_id == "main"
    assert service.store.read_option(notebook.notebook_id, "ols").lifecycle_status == "executed"
    assert {m["session_id"] for m in repository.list_metadata()} == {"main"}
    with TestClient(app) as client:
        repeat = client.post(f"/agent/sessions/main/proposals/{proposal['proposal_id']}/confirm",
            params={"project_root":str(project)}, json={"revision":proposal["revision"],
                "fingerprint":proposal["fingerprint"], "active_head_run_id":pin["target"]["run_id"]})
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["operation"]["record_id"] == record["record_id"]
    assert len([r for r in orchestrator.operation_store.list_records() if r.operation_id == "operation.multi_step"]) == 1
