"""Completion requests use the existing approval, execution and completion path."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_agent_completion_sensitivity import _fit, _leverage_frame
from tests.test_agent_operation_request_refs import origin, refs
from tests.test_agent_workflow_integration import IdleAdapter
from workbench.agent.chains import ChainStore
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.plans import Plan, PlanStep
from workbench.agent.session import JsonlSessionRepository


@pytest.fixture
def analysis(tmp_path):
    project, run_id, contract = _fit(tmp_path, _leverage_frame())
    repository = JsonlSessionRepository(project / "workbench")
    repository.create_session("main", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    repository.append("chain-session", "message", {"role": "user",
        "content": "Complete the full analysis of the declared relation and its sensitivity."})
    events = AgentEventStream(repository.root)
    orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="main",
        context_provider=NodeOperationContextProvider(project))
    orchestrator.register_chain("chain-a", "chain-session",
        AgentCore(repository, events, IdleAdapter(), session_id="chain-session"))
    ChainStore(repository.root).create_root(chain_id="chain-a", run_family_id="family",
        active_head_run_id=run_id, agent_session_id="chain-session")
    orchestrator.plan_store.save("chain-session", Plan(plan_id="analysis", version=1, status="approved",
        question="Assess the fitted relation and its sensitivity.", criteria=("Retain the declared model and source.",),
        steps=(PlanStep("sensitivity", "Sensitivity fit", ("data.subset", "model.genesis")),
               PlanStep("report", "Report", ("report.compose",), depends_on=("sensitivity",))),
        allowed_classes=("analyze", "derive"), approved_version=1, completion=contract))

    async def runner(proposal, actor="read_only_policy"):
        fingerprint = proposal.preconditions["context_fingerprint"]
        head = proposal.preconditions["active_head_run_id"]
        record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
            fingerprint=proposal.fingerprint, actor_type=actor,
            current_context_fingerprint=fingerprint, current_active_head_run_id=head)
        return await orchestrator.execute_confirmed_operation(record.record_id, project_root=project,
            current_context_fingerprint=fingerprint, current_active_head_run_id=head)

    orchestrator.read_only_runner = runner
    return SimpleNamespace(project=project, run_id=run_id, contract=contract, repository=repository,
        orchestrator=orchestrator, runner=runner)


def inspect(case, *, invocation="inspect", arguments=None):
    metadata, _ = origin(case.repository, session_id="chain-session", invocation=invocation)
    result = asyncio.run(case.orchestrator.tool_registry("chain-a").execute({"tool_call_id": invocation,
        "tool_id": "inspect_analysis_completion", "arguments": arguments or {}},
        session_id="chain-session", metadata=metadata))
    assert result.ok, (result.error, result.error_details)
    return result.output


def run_ref(case, reference, *, call_id="run-ref", overrides=None):
    return asyncio.run(case.orchestrator.tool_registry("chain-a").execute({"tool_call_id": call_id,
        "tool_id": "run_operation", "arguments": {"request_ref": reference, **(overrides or {})}},
        session_id="chain-session", metadata={"command_id": "operation-command", "provider_step": 2,
            "tool_call_id": call_id, "invocation_id": call_id}))


def test_internal_request_validator_fault_uses_the_existing_tool_error_trace(analysis, monkeypatch, caplog):
    case = analysis
    module = refs()

    def broken_validator(*args):
        raise RuntimeError("unexpected validator fault")

    monkeypatch.setattr(module, "validate", broken_validator)
    metadata, _ = origin(case.repository, session_id="chain-session")
    result = asyncio.run(case.orchestrator.tool_registry("chain-a").execute({"tool_call_id": "inspection",
        "tool_id": "inspect_analysis_completion", "arguments": {}}, session_id="chain-session", metadata=metadata))
    assert not result.ok and result.error == "RuntimeError" and result.error_id
    assert result.output is None and result.error_details is None
    assert "unexpected validator fault" in caplog.text
    assert "unexpected validator fault" not in json.dumps(result.to_payload())
    assert not any(entry.entry_type == module.ENTRY_TYPE for entry in case.repository.get_branch("chain-session"))


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_sensitivity_then_report_use_real_mode_approval_execution_and_completion(analysis, mode):
    case = analysis
    case.orchestrator.execution_mode = mode
    output = inspect(case)
    [offered] = [item for item in output["operation_requests"] if item["kind"] == "sensitivity"]
    saved = refs().read(case.repository, session_id="chain-session", request_ref=offered["request_ref"])
    assert saved["arguments"]["changes"]["steps"] == output["sensitivity_options"][0]["workflow"]["steps"]
    assert saved["arguments"]["target"]["run_id"] == case.run_id
    assert case.orchestrator.operation_store.list_records() == []
    result = run_ref(case, offered["request_ref"])
    assert result.ok, (result.error, result.error_details)
    # The existing model.genesis risk floor applies in both modes, even with an approved plan.
    assert result.output["requires_confirmation"] is True and result.output["permission_class"] == "high"
    assert not case.orchestrator.operation_store.list_records()
    proposal = case.orchestrator.proposal_store.latest_revision(result.output["proposal"]["proposal_id"])
    assert asyncio.run(case.runner(proposal, "user")).status == "completed"
    after_fit = inspect(case, invocation="inspect-report")
    assert after_fit["missing"] == ["report:registered_nonempty", "plan:approved_criteria_unverified"]
    [report] = [item for item in after_fit["operation_requests"] if item["kind"] == "report"]
    registered = refs().read(case.repository, session_id="chain-session", request_ref=report["request_ref"])
    assert registered["arguments"]["changes"]["steps"][0]["spec"] == after_fit["compose_report"]["spec"]
    rendered = run_ref(case, report["request_ref"], call_id="report-ref")
    assert rendered.ok, rendered
    if rendered.output.get("requires_confirmation"):
        proposal = case.orchestrator.proposal_store.latest_revision(rendered.output["proposal"]["proposal_id"])
        assert asyncio.run(case.runner(proposal, "user")).status == "completed"
    else:
        assert rendered.output["executed"] and rendered.output["operation"]["status"] == "completed", rendered
    checked = case.orchestrator._completion_check("chain-session")
    assert checked["status"] == "partial"
    assert checked["playbook_status"] == "requirements_met"
    assert checked["missing"] == ["plan:approved_criteria_unverified"]
    assert checked["criteria_verification"]["unbound_slots"] == [{"criterion_index": 0}]
    assert len([r for r in case.orchestrator.operation_store.list_records() if r.workflow_step_id is None]) == 2


@pytest.mark.parametrize("change", ["head", "plan", "contract", "source", "context", "user_scope"])
def test_reference_refuses_changed_bindings_before_creating_a_proposal(analysis, monkeypatch, change):
    case = analysis
    [offered] = inspect(case)["operation_requests"]
    if change == "head":
        monkeypatch.setattr(case.orchestrator, "_resolve_chain_head", lambda chain, requested: "another-head")
    elif change == "plan":
        case.orchestrator.plan_store.update("chain-session", lambda p: replace(p, criteria=("Changed criterion.",)))
    elif change == "contract":
        case.orchestrator.operation_registry.require("operation.multi_step").proposal_schema["description"] = "Changed contract"
    elif change == "source":
        data = case.project / "runs" / case.run_id / "processed/cleaned_dataset.parquet"
        data.write_bytes(data.read_bytes() + b"changed")
    elif change == "user_scope":
        case.repository.append("chain-session", "message", {"role": "user",
            "content": "Stop this analysis. Only show already saved results."})
    else:
        original = case.orchestrator.context_provider.inspect_node_context
        monkeypatch.setattr(case.orchestrator.context_provider, "inspect_node_context",
            lambda request: {**original(request), "context_fingerprint": "changed-context"})
    rejected = run_ref(case, offered["request_ref"])
    assert not rejected.ok and "inspect_analysis_completion" in str(rejected.error_details), rejected
    assert case.orchestrator.operation_store.list_records() == []
    assert not (case.repository.root / "proposals").exists() or not list((case.repository.root / "proposals").glob("*.jsonl"))


def test_reference_is_resolved_by_a_fresh_orchestrator_after_restart(analysis):
    case = analysis
    [offered] = inspect(case)["operation_requests"]
    repository = JsonlSessionRepository(case.repository.root)
    events = AgentEventStream(repository.root)
    fresh = WorkbenchOrchestrator(repository, events, main_session_id="main",
        context_provider=NodeOperationContextProvider(case.project))
    fresh.register_chain("chain-a", "chain-session", AgentCore(repository, events, IdleAdapter(), session_id="chain-session"))
    resumed = run_ref(SimpleNamespace(orchestrator=fresh), offered["request_ref"])
    assert resumed.ok, (resumed.error, resumed.error_details)
    assert resumed.output["requires_confirmation"] and resumed.output["permission_class"] == "high"
    assert resumed.output["proposal"]["target"]["run_id"] == case.run_id
    assert fresh.operation_store.list_records() == []


def test_reference_rejects_overrides_and_preserves_existing_permission_denial(analysis):
    from workbench.agent.permissions import PermissionClass, Rule, Rules

    case = analysis
    [offered] = inspect(case)["operation_requests"]
    overwritten = run_ref(case, offered["request_ref"], overrides={"changes": {}})
    assert not overwritten.ok and overwritten.error == "invalid_tool_arguments"
    case.orchestrator.permission_rules = Rules(deny=(Rule(PermissionClass.HIGH, "operation.multi_step"),))
    denied = run_ref(case, offered["request_ref"], call_id="denied-ref")
    assert denied.ok and denied.output.get("denied") and denied.output.get("executed") is False, denied.output
    assert case.orchestrator.operation_store.list_records() == []


def test_public_projection_keeps_readable_reference_and_optional_source_cannot_retarget_it(analysis, monkeypatch):
    case = analysis
    check = case.orchestrator._completion_check

    def large_check(session_id, *, suggest=False):
        result = check(session_id, suggest=suggest)
        result["evidence_catalog"] = [{"large_explanation": "x" * 30_000}]
        return result

    monkeypatch.setattr(case.orchestrator, "_completion_check", large_check)
    output = inspect(case, arguments={"source": {"run_id": "unrelated", "artifact_id": "user-selected"}})
    [offered] = output["operation_requests"]
    assert offered["label"] and offered["source"]["run_id"] == case.run_id
    assert "…" not in offered["request_ref"] and len(json.dumps(output)) <= 12_000
    saved = refs().read(case.repository, session_id="chain-session", request_ref=offered["request_ref"])
    assert saved["arguments"]["target"]["run_id"] == case.run_id
    assert saved["arguments"]["changes"]["steps"]
    assert output["source"] is None


def test_report_reference_requires_a_unique_verified_dataset_target(analysis, monkeypatch):
    from workbench.graph_store import GraphStore

    case = analysis
    check = case.orchestrator._completion_check

    def report_check(session_id, *, suggest=False):
        result = check(session_id, suggest=suggest)
        result.pop("sensitivity_options", None)
        result["compose_report"] = {"operation_id": "report.compose", "spec": {"result_refs": [
            {"run_id": case.run_id, "artifact_id": "ols_1", "role": "primary"}]}}
        return result

    monkeypatch.setattr(case.orchestrator, "_completion_check", report_check)
    graph_store = GraphStore(case.project / "runs")
    graph = graph_store.read(case.run_id)
    node = graph.nodes["stage:cleaned"]
    graph.nodes["stage:ambiguous"] = replace(node, id="stage:ambiguous")
    graph_store.write(graph)
    output = inspect(case)
    assert not output.get("operation_requests")
    assert "ambiguous" in str(output["operation_request_refs_unavailable"])
    assert output["compose_report"]["spec"]["result_refs"][0]["artifact_id"] == "ols_1"
