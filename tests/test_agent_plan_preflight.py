"""Parameter checks use real registered data and run before plan authority is granted."""
from __future__ import annotations

import asyncio
import hashlib
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _register_source_node_identity
from tests.test_read_only_analysis import _Fixture
from workbench import analysis_ledger
from workbench.agent.context_tools import InspectNodeContextRequest
from workbench.app import app


SESSION = "chain-session"
PLAN = f"/agent/sessions/{SESSION}/plan"


def _test_step(group_order):
    return {"step_id": "proportions", "operation_id": "test.proportions", "spec": {
        "input_mode": "frame", "column_bindings": {"columns": ["group", "event"]},
        "options": {"group_column": "group", "outcome_column": "event", "event_value": 1,
                    "group_order": group_order},
    }}


def _exploration_step(step_id, **options):
    return {"step_id": step_id, "operation_id": "statistical.explore", "spec": {
        "operation": "summarize", "selected_columns": ["wage"], "options": options,
    }}


def _source(fixture):
    return {"run_id": fixture.run_id, "node_ref": "stage:source", "artifact_id": fixture.artifact_id}


def _arguments(fixture, steps):
    context = fixture.orchestrator.context_provider.inspect_node_context(InspectNodeContextRequest(
        request_id="plan-preflight-test", owner_run_id=fixture.run_id, op_node_id="stage:source",
        active_head_run_id=fixture.run_id))
    return {"operation_id": "operation.multi_step", "target": _source(fixture),
            "preconditions": {key: context[key] for key in
                              ("context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")},
            "changes": {"steps": steps}, "evidence_refs": ["fixture"], "expected_effect": [], "risks": []}


def _execute_tool(fixture, tool, arguments):
    return asyncio.run(fixture.orchestrator.tool_registry("chain-a").execute({
        "tool_call_id": tool, "tool_id": tool, "arguments": arguments,
    }, session_id=SESSION))


def _prepare(fixture, *steps):
    return _execute_tool(fixture, "run_operation", {**_arguments(fixture, list(steps)), "prepare_only": True})


def _plan(fixture, proposal_ref=None, operations=("test.proportions",)):
    step = {"step_id": "compare", "title": "Compare groups", "operation_ids": list(operations)}
    if proposal_ref is not None:
        step["proposal_ref"] = proposal_ref
    return _execute_tool(fixture, "update_plan", {
        "question": "Compare the groups", "criteria": ["Report the difference"], "steps": [step],
    })


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    from tests import test_read_only_analysis
    from workbench.http import agent_route_runtime

    frame = test_read_only_analysis._frame().assign(
        entity=np.repeat(np.arange(20), 3), period=np.tile([1, 2, 3], 20),
        cohort=np.repeat([2] * 10 + [0] * 10, 3), instrument=np.linspace(1, 5, 60), constant=0,
        boundary_group=np.r_[np.arange(50), np.full(10, np.nan)],
    )
    frame["event"] = (frame["region"] == "north").astype(int)
    monkeypatch.setattr(test_read_only_analysis, "_frame", lambda: frame)
    fixture = _Fixture(tmp_path)
    _register_source_node_identity(fixture.project_root, fixture.run_id)
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", lambda: pytest.fail("preflight needs no provider"))
    return fixture


@pytest.mark.parametrize("wire_value", ["True", "true", True, False, "false"])
def test_workflow_prepare_only_interprets_true_without_running_operations(fixture, wire_value):
    result = _execute_tool(fixture, "run_operation", {
        **_arguments(fixture, [_test_step(["a", "b"])]), "prepare_only": wire_value,
    })
    if wire_value in (True, "True", "true"):
        assert result.ok and result.output["prepared"] and result.output["proposal_ref"]
        assert not result.output.get("requires_confirmation")
    else:
        assert not result.ok and result.error == "invalid_tool_arguments"
    assert fixture.orchestrator.operation_store.list_records() == []
    assert analysis_ledger.read(fixture.project_root) == []


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_plan_preflight_reads_exact_proposal_and_checks_group_values(fixture, mode):
    fixture.orchestrator.execution_mode = mode
    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok and prepared.output["proposal_ref"], prepared
    assert not prepared.output.get("requires_confirmation")
    assert fixture.orchestrator.operation_store.list_records() == []
    result = _plan(fixture, prepared.output["proposal_ref"])
    assert result.ok and result.output["saved"], result
    assert bool(result.output.get("requires_confirmation")) == (mode == "auto")

    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params=params)
        assert response.status_code == 200, response.text
        preflight = response.json()
        assert preflight["plan_version"] == 1 and preflight["status"] == "ready"
        assert preflight["can_approve"]
        [step] = preflight["steps"]
        assert step["source"]["artifact_id"] == fixture.artifact_id and len(step["source"]["sha256"]) == 64
        assert step["estimated_seconds"] is None
        assert any(check["level"] == "L1" and check["status"] == "passed" and
                   check["operation_id"] == "test.proportions" and "group" in check["columns"]
                   for check in step["checks"])
        assert analysis_ledger.read(fixture.project_root) == []
        if mode == "auto":
            assert client.post(PLAN + "/approve", params=params, json={"version": 1}).status_code == 200
            [event] = analysis_ledger.read(fixture.project_root)
            assert event["plan_snapshot"]["steps"][0]["proposal_ref"] == prepared.output["proposal_ref"]


def test_prepared_empty_report_cannot_reserve_an_analysis_plan_slot(fixture):
    from workbench.agent.plan_control import PlanControl, PlanControlError

    fixture.orchestrator.execution_mode = "auto"
    prepared = _prepare(fixture, {"step_id": "report", "operation_id": "report.compose", "spec": {}})
    assert prepared.ok and prepared.output["prepared"]
    revision = _execute_tool(fixture, "update_plan", {
        "question": "Complete the source-bound analysis",
        "criteria": ["Save a report with results"],
        "completion": {"scope": "analysis", "playbooks": ["ols"], "source": {
            "run_id": fixture.run_id, "artifact_id": fixture.artifact_id}},
        "steps": [{"step_id": "report", "title": "Report", "operation_ids": ["report.compose"],
                   "proposal_ref": prepared.output["proposal_ref"]}],
    })
    assert revision.ok and revision.output["saved"], revision
    assert revision.output["preflight"]["status"] == "blocked", revision.output
    assert not revision.output.get("requires_confirmation")
    control = PlanControl(fixture.project_root, fixture.repository, SESSION)
    with pytest.raises(PlanControlError) as raised:
        control.approve(revision.output["plan"]["version"])
    assert raised.value.code == "AGENT_PLAN_PREFLIGHT_BLOCKED"
    assert fixture.orchestrator.operation_store.list_records() == []


def _timed_workflow(fixture, ref):
    from workbench.agent.workflow import compile_workflow

    proposal = fixture.orchestrator.proposal_store.latest_revision(ref["proposal_id"])
    return compile_workflow(workflow_id="prior-local-workflow", target=proposal.target,
                            preconditions=proposal.preconditions, steps=proposal.changes["steps"])


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_plan_preflight_estimates_a_previously_completed_exact_workload(fixture, mode, monkeypatch):
    from workbench.agent import workflow_timing
    from workbench.agent.workflow import execute_workflow

    fixture.orchestrator.execution_mode = mode
    previous = _prepare(fixture, _test_step(["a", "b"]))
    assert previous.ok, previous
    draft = _timed_workflow(fixture, previous.output["proposal_ref"])
    clock = iter((1_000_000_000, 2_257_000_000))
    monkeypatch.setattr(workflow_timing, "perf_counter_ns", lambda: next(clock))
    assert execute_workflow(fixture.project_root, draft).status == "completed"

    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok and _plan(fixture, prepared.output["proposal_ref"]).ok
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params={"project_root": str(fixture.project_root)})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "ready" and report["can_approve"]
    [step] = report["steps"]
    assert step["estimated_seconds"] == 1.257
    assert analysis_ledger.read(fixture.project_root) == []


@pytest.mark.parametrize("changed,status", [
    ("parameters", "ready"), ("workload", "ready"), ("registered_digest", "ready"),
    ("ambiguous_source", "blocked"), ("sidecar", "deferred"), ("oversized_record", "ready"),
    ("invalid_duration", "ready"), ("policy_denial", "blocked"),
])
def test_plan_preflight_excludes_nonmatching_or_unverified_timings(fixture, changed, status):
    from workbench.agent.workflow import execute_workflow

    steps = [_test_step(["a", "b"])]
    previous = _prepare(fixture, *steps)
    assert previous.ok, previous
    draft = _timed_workflow(fixture, previous.output["proposal_ref"])
    assert execute_workflow(fixture.project_root, draft).status == "completed"

    run = fixture.project_root / "runs" / fixture.run_id
    index_path = run / "artifacts_index.json"
    index = json.loads(index_path.read_text())
    [source] = [row for row in index["artifacts"] if row["artifact_id"] == fixture.artifact_id]
    if changed == "parameters":
        steps = [_test_step(["b", "a"])]
    if changed == "workload":
        steps.append({**steps[0], "step_id": "another-test"})
    if changed == "registered_digest":
        path = run / source["path"]
        content = path.read_bytes()
        new_content = content + content.splitlines()[-1] + b"\n"
        path.write_bytes(new_content)
        source["sha256"] = hashlib.sha256(new_content).hexdigest()
        index_path.write_text(json.dumps(index))

    prepared = _prepare(fixture, *steps)
    assert prepared.ok and _plan(fixture, prepared.output["proposal_ref"]).ok
    if changed == "ambiguous_source":
        index["artifacts"].append(dict(source))
        index_path.write_text(json.dumps(index))
    if changed == "sidecar":
        (run / "data.schema.json").write_text('{"dtypes": {"event": "int64"}}')
    if changed == "policy_denial":
        (fixture.repository.root / "agent-permissions.json").write_text(json.dumps({
            "deny": [{"class": "analyze", "operation_id": "test.proportions"}],
        }))
    if changed in {"oversized_record", "invalid_duration"}:
        [record_path] = list((fixture.repository.root / "workflow-timings").glob("*.json"))
        record = json.loads(record_path.read_text())
        if changed == "invalid_duration":
            record["elapsed_ns"] = True
        record_path.write_text(json.dumps(record) + (" " * 512 if changed == "oversized_record" else ""))

    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params={"project_root": str(fixture.project_root)})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == status, report
    assert report["steps"][0]["estimated_seconds"] is None
    assert analysis_ledger.read(fixture.project_root) == []


def test_plan_preflight_estimate_requires_the_observed_source_generation(fixture, monkeypatch):
    from workbench.agent import plan_preflight
    from workbench.agent.workflow import execute_workflow

    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    assert execute_workflow(fixture.project_root, _timed_workflow(fixture, ref)).status == "completed"
    assert _plan(fixture, ref).ok
    monkeypatch.setattr(plan_preflight, "_SOURCE_BYTES", 1)

    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params=params)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "deferred" and response.json()["can_approve"]
        assert response.json()["steps"][0]["estimated_seconds"] > 0

        with (fixture.project_root / "runs" / fixture.run_id / "data.csv").open("a") as file:
            file.write("\n")
        response = client.get(PLAN + "/preflight", params=params)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "deferred" and response.json()["can_approve"]
        assert response.json()["steps"][0]["estimated_seconds"] is None


def test_resumed_historical_workflow_does_not_invent_a_timing_observation(fixture):
    from workbench.agent.workflow import WorkflowExecutor, execute_workflow
    from workbench.agent.workflow_runtime import build_workflow_step_executor

    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    draft = _timed_workflow(fixture, ref)
    root = fixture.project_root
    assert WorkflowExecutor(root).execute(draft, build_workflow_step_executor(root, draft)).status == "completed"
    assert execute_workflow(root, draft).status == "completed"
    assert _plan(fixture, ref).ok

    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params={"project_root": str(root)})
    assert response.status_code == 200, response.text
    assert response.json()["steps"][0]["estimated_seconds"] is None
    assert not (fixture.repository.root / "workflow-timings").exists()


def test_plan_preflight_needs_the_source_used_by_the_execution_runtime(fixture, monkeypatch):
    from workbench.agent import workflow_runtime
    from workbench.agent.workflow import execute_workflow

    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    resolve = workflow_runtime.resolve_statistical_source

    def changed_runtime_source(*args, **kwargs):
        context, frame = resolve(*args, **kwargs)
        return {**context, "source_sha256": "0" * 64}, frame

    monkeypatch.setattr(workflow_runtime, "resolve_statistical_source", changed_runtime_source)
    assert execute_workflow(fixture.project_root, _timed_workflow(fixture, ref)).status == "completed"
    assert _plan(fixture, ref).ok
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params={"project_root": str(fixture.project_root)})
    assert response.status_code == 200, response.text
    assert response.json()["steps"][0]["estimated_seconds"] is None
    assert not (fixture.repository.root / "workflow-timings").exists()


def test_bad_group_binding_blocks_before_criteria_and_can_be_replaced(fixture):
    fixture.orchestrator.execution_mode = "auto"
    bad = _prepare(fixture, _test_step(["a", "unknown"]))
    assert bad.ok and bad.output["proposal_ref"], bad
    draft = _plan(fixture, bad.output["proposal_ref"])
    assert draft.ok and draft.output["saved"] and not draft.output.get("requires_confirmation"), draft

    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        blocked = client.post(PLAN + "/approve", params=params, json={"version": 1})
        assert blocked.status_code == 409, blocked.text
        assert "group_order" in blocked.text and "AGENT_PLAN_PREFLIGHT_BLOCKED" in blocked.text
        assert analysis_ledger.read(fixture.project_root) == []

        good = _prepare(fixture, _test_step(["b", "a"]))
        assert good.ok, good
        edit = client.patch(PLAN, params=params, json={"version": 1, "steps": [{
            "step_id": "compare", "title": "Compare groups", "operation_ids": ["test.proportions"],
            "proposal_ref": good.output["proposal_ref"],
        }]})
        assert edit.status_code == 200, edit.text
        assert edit.json()["plan"]["version"] == 2
        approved = client.post(PLAN + "/approve", params=params, json={"version": 2})
        assert approved.status_code == 200, approved.text


@pytest.mark.parametrize("group_column,count", [("instrument", 60), ("boundary_group", 51)])
def test_group_limit_rejects_raw_workflow_before_any_step_runs(fixture, monkeypatch, group_column, count):
    from workbench.agent import plan_preflight
    from workbench.http.agent_operation_routes import _run_read_only_proposal

    monkeypatch.setattr(plan_preflight, "_SOURCE_BYTES", 1)  # Raw proposals already resolve the full source.
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = "auto"
    orchestrator.read_only_runner = lambda proposal, actor=None: _run_read_only_proposal(
        fixture.project_root, orchestrator, proposal, actor)
    assert _plan(fixture, operations=("statistical.explore",)).output["requires_confirmation"]
    with TestClient(app) as client:
        approved = client.post(PLAN + "/approve", params={"project_root": str(fixture.project_root)},
                               json={"version": 1})
    assert approved.status_code == 200, approved.text
    before = analysis_ledger.read(fixture.project_root)
    steps = [_exploration_step("pooled"), _exploration_step("grouped", group_by=group_column)]
    receipt = _execute_tool(fixture, "run_operation", _arguments(fixture, steps))
    assert not receipt.ok and receipt.error == "OperationValidationError", receipt
    [detail] = receipt.error_details
    assert "grouped" in detail["message"] and f"{count} groups" in detail["message"]
    assert "50" in detail["message"] and "options.group_values" in detail["message"]
    assert fixture.orchestrator.operation_store.list_records() == []
    assert not list((fixture.repository.root / "workflows").glob("*.jsonl"))
    assert not list((fixture.repository.root / "exploration").glob("*.jsonl"))
    assert analysis_ledger.read(fixture.project_root) == before
    assert orchestrator.plan_store.current(SESSION).steps[0].status == "pending"
    corrected = _exploration_step("grouped", group_by="group")
    execution = _execute_tool(fixture, "run_operation", _arguments(fixture, [steps[0], corrected]))
    assert execution.output["operation"]["status"] == "completed", execution
    assert orchestrator.plan_store.current(SESSION).steps[0].status == "done"


def test_group_limit_blocks_an_exact_plan_before_approval(fixture):
    fixture.orchestrator.execution_mode = "auto"
    prepared = _prepare(fixture, _exploration_step("by_instrument", group_by="instrument"))
    assert prepared.ok and prepared.output["prepared"], prepared
    ref = prepared.output["proposal_ref"]
    draft = _plan(fixture, ref, ("statistical.explore",))
    assert draft.ok and draft.output["saved"] and not draft.output.get("requires_confirmation"), draft
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params=params)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["status"] == "blocked" and not report["can_approve"], report
        [reason] = [check for check in report["steps"][0]["checks"] if check["status"] == "blocked"]
        assert reason["workflow_step_id"] == "by_instrument" and "60 groups" in reason["message"]
        assert client.post(PLAN + "/approve", params=params, json={"version": 1}).status_code == 409
    receipt = _execute_tool(fixture, "run_operation", {"proposal_ref": ref})
    assert not receipt.ok and "60 groups" in receipt.error_details[0]["message"], receipt
    assert analysis_ledger.read(fixture.project_root) == []
    assert fixture.orchestrator.operation_store.list_records() == []
    assert fixture.orchestrator.proposal_store.latest_status(ref["proposal_id"]) == "plan_prepared"


@pytest.mark.parametrize("options,expected", [
    ({"group_by": "entity"}, "ready"),
    ({"group_by": "instrument", "group_values": list(range(51))}, "deferred"),
])
def test_group_limit_does_not_block_allowed_groupings(fixture, options, expected):
    prepared = _prepare(fixture, _exploration_step("grouped", **options))
    draft = _plan(fixture, prepared.output["proposal_ref"], ("statistical.explore",))
    assert draft.output["preflight"]["status"] == expected, draft


def test_group_limit_defers_unread_exact_source(fixture, monkeypatch):
    from workbench.agent import plan_preflight

    monkeypatch.setattr(plan_preflight, "_SOURCE_BYTES", 1)
    prepared = _prepare(fixture, _exploration_step("grouped", group_by="instrument"))
    assert _plan(fixture, prepared.output["proposal_ref"], ("statistical.explore",)).output["preflight"]["status"] == "deferred"


def test_source_bytes_changed_between_review_and_approval(fixture):
    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    assert _plan(fixture, prepared.output["proposal_ref"]).ok
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        assert client.get(PLAN + "/preflight", params=params).json()["status"] == "ready"
        path = fixture.project_root / "runs" / fixture.run_id / "data.csv"
        with path.open("a") as file:
            file.write("1,b,south\n")
        response = client.post(PLAN + "/approve", params=params, json={"version": 1})
        assert response.status_code == 409, response.text
        assert analysis_ledger.read(fixture.project_root) == []


def test_unpinned_dtype_sidecar_cannot_pass_exact_source_checks(fixture):
    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    assert _plan(fixture, prepared.output["proposal_ref"]).ok
    sidecar = fixture.project_root / "runs" / fixture.run_id / "data.schema.json"
    sidecar.write_text('{"dtypes": {"event": "int64"}}', encoding="utf-8")
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params={"project_root": str(fixture.project_root)})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deferred", response.text


def test_future_workflow_input_is_deferred_not_checked_against_the_root(fixture):
    fixture.orchestrator.execution_mode = "auto"
    subset = {"step_id": "subset", "operation_id": "data.subset", "spec": {
        "columns": ["group", "event"],
        "filters": [{"column": "group", "op": "eq", "value": "a"}],
    }}
    downstream = {**_test_step(["a", "unknown"]), "depends_on": ["subset"]}
    prepared = _prepare(fixture, subset, downstream)
    assert prepared.ok, prepared
    draft = _plan(fixture, prepared.output["proposal_ref"], ("data.subset", "test.proportions"))
    assert draft.ok and draft.output["saved"], draft
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params=params)
        assert client.post(PLAN + "/approve", params=params, json={"version": 1}).status_code == 200
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "deferred" and report["can_approve"]
    [step] = report["steps"]
    assert any(check.get("operation_id") == "test.proportions" and check["status"] == "deferred"
               and check["code"] == "UPSTREAM_SOURCE_PENDING" for check in step["checks"])
    receipt = _execute_tool(fixture, "run_operation", {"proposal_ref": prepared.output["proposal_ref"]})
    assert receipt.ok and receipt.output["requires_confirmation"], receipt
    assert fixture.orchestrator.operation_store.list_records() == []


def test_unbound_plan_remains_approvable_and_has_unknown_timing(fixture):
    assert _plan(fixture).ok
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params=params)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["status"] == "deferred" and report["can_approve"]
        assert report["steps"][0]["estimated_seconds"] is None
        assert client.post(PLAN + "/approve", params=params, json={"version": 1}).status_code == 200


@pytest.mark.parametrize("family, declaration, expected", [
    ("iv_2sls", {"iv_endog": ["event"], "iv_instruments": ["instrument"]}, "ready"),
    ("iv_2sls", {"iv_endog": ["event"], "iv_instruments": ["constant"]}, "blocked"),
    ("did", {"entity_col": "entity", "time_col": "period", "did_mode": "cohort", "did_cohort_col": "cohort"}, "ready"),
    ("did", {"entity_col": "entity", "time_col": "period", "did_mode": "cohort", "did_cohort_col": "constant"}, "blocked"),
])
def test_model_preflight_checks_real_iv_design_or_did_cohorts_without_fitting(fixture, family, declaration, expected):
    step = {"step_id": "model", "operation_id": "model.genesis", "spec": {
        "model_family": family, **declaration,
        "branches": [{"branch_id": "fit", "outcome": "wage", "predictors": []}],
    }}
    prepared = _prepare(fixture, step)
    assert prepared.ok, prepared
    draft = _plan(fixture, prepared.output["proposal_ref"], ("model.genesis",))
    assert draft.ok, draft
    with TestClient(app) as client:
        response = client.get(PLAN + "/preflight", params={"project_root": str(fixture.project_root)})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected, response.text
    assert fixture.orchestrator.operation_store.list_records() == []
    assert not (fixture.project_root / "runs" / fixture.run_id / "model_results").exists()


def test_approved_step_runs_only_the_checked_revision_through_ordinary_operation_lifecycle(fixture):
    from workbench.agent.proposals import ProposalConfirmationError
    from workbench.http.agent_operation_routes import _run_read_only_proposal
    from workbench.http.agent_route_projection import _public_proposals

    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = "auto"
    orchestrator.read_only_runner = lambda proposal, actor=None: _run_read_only_proposal(
        fixture.project_root, orchestrator, proposal, actor)
    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    assert _public_proposals(orchestrator.proposal_store, SESSION) == []
    with pytest.raises(ProposalConfirmationError, match="plan_prepared"):
        orchestrator.proposal_store.confirm(**ref, actor_type="user", current_context_fingerprint=None,
                                           current_active_head_run_id=None)
    assert _plan(fixture, ref).ok

    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        assert client.post(PLAN + "/approve", params=params, json={"version": 1}).status_code == 200
    different = _execute_tool(fixture, "run_operation", _arguments(fixture, [_test_step(["b", "a"])]))
    assert different.ok and different.output["requires_confirmation"], different
    assert orchestrator.operation_store.list_records() == []

    executed = _execute_tool(fixture, "run_operation", {"proposal_ref": ref})
    assert executed.ok and executed.output["operation"]["status"] == "completed", executed
    assert executed.output["proposal_id"] == ref["proposal_id"]
    assert orchestrator.plan_store.current(SESSION).steps[0].status == "done"
    [criteria] = [event for event in analysis_ledger.read(fixture.project_root) if event.get("event_type") == "criteria_fixed"]
    assert criteria["plan_snapshot"]["steps"][0]["proposal_ref"] == ref


def test_exact_iv_plan_keeps_the_high_risk_confirmation_floor(fixture):
    fixture.orchestrator.execution_mode = "auto"
    operation = {"step_id": "iv", "operation_id": "model.genesis", "spec": {
        "model_family": "iv_2sls", "iv_endog": ["event"], "iv_instruments": ["instrument"],
        "branches": [{"branch_id": "fit", "outcome": "wage", "predictors": []}],
    }}
    prepared = _prepare(fixture, operation)
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    assert _plan(fixture, ref, ("model.genesis",)).output["preflight"]["status"] == "ready"
    with TestClient(app) as client:
        approved = client.post(PLAN + "/approve", json={"version": 1},
                               params={"project_root": str(fixture.project_root)})
    assert approved.status_code == 200, approved.text

    receipt = _execute_tool(fixture, "run_operation", {"proposal_ref": ref})
    assert receipt.ok and receipt.output["requires_confirmation"], receipt
    assert "high risk" in receipt.output["confirmation_reason"]
    assert fixture.orchestrator.operation_store.list_records() == []


def test_policy_denial_leaves_bound_workflow_unpublished_after_policy_change(fixture):
    from workbench.agent.permissions import PermissionClass, Rule, Rules

    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    fixture.orchestrator.execution_mode = "auto"
    assert _plan(fixture, ref).output["requires_confirmation"]
    with TestClient(app) as client:
        approved = client.post(PLAN + "/approve", json={"version": 1},
                               params={"project_root": str(fixture.project_root)})
    assert approved.status_code == 200, approved.text
    fixture.orchestrator.permission_rules = Rules(deny=(Rule(PermissionClass.ANALYZE, "test.proportions"),))

    receipt = _execute_tool(fixture, "run_operation", {"proposal_ref": ref})
    assert receipt.ok and receipt.output["denied"] is True
    assert receipt.output["blocked_operations"] == ["test.proportions"]
    assert fixture.orchestrator.proposal_store.latest_status(ref["proposal_id"]) == "plan_prepared"
    assert fixture.orchestrator.operation_store.list_records() == []


def test_exact_reference_edits_reopen_approval_but_titles_preserve_binding(fixture):
    first = _prepare(fixture, _test_step(["a", "b"]))
    second = _prepare(fixture, _test_step(["b", "a"]))
    assert first.ok and second.ok
    first_ref, second_ref = first.output["proposal_ref"], second.output["proposal_ref"]
    assert _plan(fixture, first_ref).ok
    params = {"project_root": str(fixture.project_root)}
    step = {"step_id": "compare", "title": "Compare arms", "operation_ids": ["test.proportions"]}
    with TestClient(app) as client:
        assert client.post(PLAN + "/approve", params=params, json={"version": 1}).status_code == 200
        renamed = client.patch(PLAN, params=params, json={"version": 1, "steps": [step]})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["plan"]["status"] == "approved"
        assert renamed.json()["plan"]["steps"][0]["proposal_ref"] == first_ref
        changed = client.patch(PLAN, params=params, json={"version": 2, "steps": [{**step, "proposal_ref": second_ref}]})
        assert changed.status_code == 200, changed.text
        assert changed.json()["plan"]["status"] == "needs_approval"
        assert changed.json()["plan"]["steps"][0]["proposal_ref"] == second_ref
        assert len(analysis_ledger.read(fixture.project_root)) == 1


def test_normal_proposal_revision_stales_the_bound_plan_before_approval(fixture):
    fixture.orchestrator.execution_policy = "proposal_only"
    prepared = _prepare(fixture, _test_step(["a", "b"]))
    assert prepared.ok, prepared
    ref = prepared.output["proposal_ref"]
    assert _plan(fixture, ref).ok
    pending = _execute_tool(fixture, "run_operation", {"proposal_ref": ref})
    assert pending.ok and pending.output["requires_confirmation"], pending

    revised = fixture.orchestrator.revise_proposal(ref["proposal_id"], base_revision=ref["revision"],
                                                  changes={"steps": [_test_step(["b", "a"])]})
    assert revised.fingerprint != ref["fingerprint"]
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        approval = client.post(PLAN + "/approve", params=params, json={"version": 1})
    assert approval.status_code == 409 and "proposal revision or fingerprint has changed" in approval.text
    assert analysis_ledger.read(fixture.project_root) == []


@pytest.mark.parametrize("binding,operation_id,denied_rule", [
    ("unbound", "model.genesis", {"class": "high"}),
    ("exact_child", "test.proportions", {"class": "analyze", "operation_id": "test.proportions"}),
    ("exact_wrapper", "operation.multi_step", {"class": "analyze", "operation_id": "operation.multi_step"}),
])
def test_plan_approval_rechecks_current_project_denial(fixture, binding, operation_id, denied_rule):
    fixture.orchestrator.execution_mode = "auto"
    if binding == "unbound":
        proposed = _plan(fixture, operations=("model.genesis",))
    else:
        prepared = _prepare(fixture, _test_step(["a", "b"]))
        assert prepared.ok, prepared
        proposed = _plan(fixture, prepared.output["proposal_ref"])
    assert proposed.ok and proposed.output["requires_confirmation"], proposed

    rules = fixture.repository.root / "agent-permissions.json"
    rules.write_text(json.dumps({"deny": [denied_rule]}))
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        inspected = client.get(PLAN + "/preflight", params=params)
        assert inspected.status_code == 200, inspected.text
        report = inspected.json()
        assert not report["can_approve"] and report["status"] == "blocked", report
        [reason] = [check for step in report["steps"] for check in step["checks"]
                    if check["status"] == "blocked"]
        assert reason["operation_id"] == operation_id
        refused = client.post(PLAN + "/approve", params=params, json={"version": 1})
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "AGENT_PLAN_PREFLIGHT_BLOCKED"
        assert analysis_ledger.read(fixture.project_root) == []
        assert fixture.orchestrator.plan_store.current(SESSION).status == "draft"

        allowed_operation = "data.recode" if binding == "exact_wrapper" else "statistical.explore"
        draft = client.patch(PLAN, params=params, json={"version": 1, "steps": [{
            "step_id": "allowed", "title": "Revise to allowed work", "operation_ids": [allowed_operation],
        }]})
        assert draft.status_code == 200, draft.text
        revised_version = draft.json()["plan"]["version"]
        approved = client.post(PLAN + "/approve", params=params, json={"version": revised_version})
        assert approved.status_code == 200, approved.text
    [criteria] = analysis_ledger.read(fixture.project_root)
    assert criteria["event_type"] == "criteria_fixed" and criteria["plan_version"] == revised_version


@pytest.mark.parametrize("operations", [("operation.multi_step",), ("operation.multi_step", "statistical.explore")])
def test_bare_workflow_draft_stays_editable_but_cannot_be_approved(fixture, operations):
    fixture.orchestrator.execution_mode = "ask"
    result = _plan(fixture, operations=operations)
    assert result.ok and result.output["saved"], result
    params = {"project_root": str(fixture.project_root)}
    with TestClient(app) as client:
        inspected = client.get(PLAN + "/preflight", params=params)
        assert inspected.status_code == 200, inspected.text
        assert not inspected.json()["can_approve"], inspected.text
        [reason] = [check for step in inspected.json()["steps"] for check in step["checks"]
                    if check["status"] == "blocked"]
        assert reason["code"] == "WORKFLOW_STEP_OPERATIONS_REQUIRED"
        assert "Ask the Agent to revise this plan" in reason["message"]

        refused = client.post(PLAN + "/approve", params=params, json={"version": 1})
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "AGENT_PLAN_PREFLIGHT_BLOCKED"
        assert analysis_ledger.read(fixture.project_root) == []
        assert fixture.orchestrator.plan_store.current(SESSION).status == "draft"

        draft = client.patch(PLAN, params=params, json={"version": 1, "steps": [{
            "step_id": "compare", "title": "Describe the groups", "operation_ids": ["statistical.explore"],
        }]})
        assert draft.status_code == 200, draft.text
        revised_version = draft.json()["plan"]["version"]
        approved = client.post(PLAN + "/approve", params=params, json={"version": revised_version})
        assert approved.status_code == 200, approved.text
    [criteria] = analysis_ledger.read(fixture.project_root)
    assert criteria["event_type"] == "criteria_fixed" and criteria["plan_version"] == revised_version


def test_closed_legacy_workflow_step_does_not_block_new_operations(fixture):
    fixture.orchestrator.execution_mode = "ask"
    draft = _execute_tool(fixture, "update_plan", {
        "question": "Describe groups after a failed workflow",
        "steps": [
            {"step_id": "old", "title": "Previous fit", "operation_ids": ["operation.multi_step"], "status": "failed"},
            {"step_id": "new", "title": "Describe groups", "operation_ids": ["statistical.explore"]},
        ],
    })
    assert draft.ok and draft.output["saved"], draft
    with TestClient(app) as client:
        approved = client.post(PLAN + "/approve", params={"project_root": str(fixture.project_root)}, json={"version": 1})
    assert approved.status_code == 200, approved.text
    assert approved.json()["plan"]["steps"][0]["status"] == "failed"
