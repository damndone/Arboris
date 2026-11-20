"""v1.8.11 step 2: the Agent path clusters panel and DID fits by entity by default."""

from __future__ import annotations

import asyncio
import copy
import json
import struct

import numpy as np
import pandas as pd
import pytest

from workbench.agent.context_tools import _bounded_inference
from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
from workbench.services.draft_materialization import normalize_ols_genesis_model_params


@pytest.mark.parametrize("family", ["panel_ols", "did"])
def test_panel_families_default_to_clustered_and_forward_a_cluster_column(family) -> None:
    contract = MODEL_FAMILY_CONTRACTS[family]
    assert contract.default_covariance == "clustered"
    spec = {"model_family": family, "entity_col": "county", "time_col": "year", "did_mode": "cohort",
            "did_cohort_col": "first_treat", "model_options": {"cluster": "state"}}
    params = contract.build_model_params(spec, {"outcome": "y"}, ["x"], "clustered")
    assert params["model_options"] == {"covariance": "clustered", "cluster": "state"}
    normalized = normalize_ols_genesis_model_params(params)
    assert normalized["model_options"]["cluster"] == "state"


def test_other_families_keep_the_conventional_default() -> None:
    assert MODEL_FAMILY_CONTRACTS["ols"].default_covariance == "unadjusted"


def test_the_agent_is_told_an_old_panel_result_is_not_clustered() -> None:
    legacy = {"entity_col": "firm", "covariance_evidence": {"covariance": "robust", "cluster_entity": False}}
    inference = _bounded_inference(legacy)
    assert inference["not_clustered_by_entity"] is True
    assert "predates v1.8.11" in inference["inference_note"]
    current = {"entity_col": "firm", "covariance_evidence": {
        "covariance": "clustered", "cluster_entity": True, "cluster_variable": "firm", "cluster_count": 50,
        "inference_version": "workbench.inference.v2", "inference_distribution": "t", "effective_df": 49}}
    inference = _bounded_inference(current)
    assert "not_clustered_by_entity" not in inference
    assert inference["cluster_variable"] == "firm"


def _panel_frame():
    unit = np.repeat(np.arange(20), 6)
    period = np.tile(np.arange(6), 20)
    predictor = ((unit * 7 + period * 11) % 19) / 7.0 + np.sin((unit + 1) * (period + 1))
    return pd.DataFrame({"outcome": 0.3 * unit + 0.6 * period + 1.25 * predictor + 0.1 * np.cos(unit + 3 * period),
                         "predictor": predictor, "unit": unit, "period": period, "cluster": unit // 2})


def _panel_step(cluster=None, *, step_id="fit", covariance=None):
    spec = {"model_family": "panel_ols", "entity_col": "unit", "time_col": "period",
            "model_options": {} if cluster is None else {"cluster": cluster},
            "branches": [{"branch_id": "main", "outcome": "outcome", "predictors": ["predictor"]}]}
    if covariance is not None:
        spec["covariance"] = covariance
    return {"step_id": step_id, "operation_id": "model.genesis", "spec": spec}


def _admit_panel(step):
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.tools import ToolDefinition, ToolRegistry
    from workbench.agent.workflow import compile_workflow

    operations, compiled = OperationRegistry(), []

    def admit(arguments, context):
        operation = operations.require(arguments["operation_id"], arguments["operation_version"])
        operation.validator(arguments["target"], arguments["preconditions"], arguments["changes"])
        draft = compile_workflow(workflow_id="panel-contract", target=arguments["target"],
            preconditions=arguments["preconditions"], steps=arguments["changes"]["steps"],
            available_columns=list(_panel_frame().columns))
        compiled.append(draft)
        return {"admitted": True}

    tools = ToolRegistry()
    tools.register(ToolDefinition(tool_id="run_operation", version="v1", side_effect="proposal",
        input_schema=operations.proposal_tool_schema(), handler=admit))
    arguments = {
        "operation_id": "operation.multi_step", "operation_version": "v1",
        "target": {"run_id": "source", "node_ref": "stage:cleaned", "artifact_id": "cleaned_dataset"},
        "preconditions": {"context_version": "node-operation-context/v1", "context_fingerprint": "source-hash",
                          "active_head_run_id": "source", "owner_resolution": "single_candidate"},
        "changes": {"steps": [step]}, "evidence_refs": ["profile:source"],
        "expected_effect": ["Fit the declared panel model"], "risks": [],
    }
    original = copy.deepcopy(arguments)
    result = asyncio.run(tools.execute({"tool_call_id": "panel", "tool_id": "run_operation", "arguments": arguments},
                                      session_id="panel-contract"))
    assert arguments == original
    return result, compiled


def _panel_params(draft):
    spec = draft.steps[0].spec
    contract = MODEL_FAMILY_CONTRACTS[spec["model_family"]]
    branch = spec["branches"][0]
    params = contract.build_model_params(spec, branch, list(branch["predictors"]),
        branch.get("covariance") or spec.get("covariance") or contract.default_covariance)
    return normalize_ols_genesis_model_params(params)


def _exact(value):
    if isinstance(value, dict):
        return {key: _exact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_exact(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return struct.pack(">d", float(value))
    return value


def test_custom_cluster_passes_the_public_workflow_schema_and_column_admission():
    result, compiled = _admit_panel(_panel_step("cluster"))
    assert result.ok, result.to_payload()
    assert len(compiled) == 1
    assert _panel_params(compiled[0])["model_options"] == {"covariance": "clustered", "cluster": "cluster"}


@pytest.mark.parametrize("cluster,covariance,message", [
    ("missing_cluster", None, "missing column(s): missing_cluster"),
    (["cluster"], None, "model_options.cluster must name a column"),
    ("cluster", "robust", "model_options.cluster applies only to clustered standard errors"),
    ("cluster", "unadjusted", "model_options.cluster applies only to clustered standard errors"),
])
def test_custom_cluster_refusals_reach_existing_column_and_option_validators(cluster, covariance, message):
    result, compiled = _admit_panel(_panel_step(cluster, covariance=covariance))
    assert not result.ok and not compiled
    assert message in result.error_details[0]["message"]


@pytest.mark.parametrize("cluster", [None, "cluster"], ids=["entity-default", "custom-cluster"])
def test_public_panel_params_match_manual_same_kernel_results_bit_for_bit(cluster):
    from workbench.econometrics.panel_iv import run_panel_ols

    result, compiled = _admit_panel(_panel_step(cluster))
    assert result.ok, result.to_payload()
    params = _panel_params(compiled[0])
    options = params["model_options"]
    manual, manual_fit = run_panel_ols(_panel_frame(), y="outcome", x=["predictor"], entity="unit", time="period",
        model_id="panel_ols_1", covariance="clustered", cluster_col=cluster, time_effects=True)
    admitted, admitted_fit = run_panel_ols(_panel_frame(), y=params["y"], x=params["x"], entity=params["entity_col"],
        time=params["time_col"], model_id="panel_ols_1", covariance=options["covariance"],
        cluster_col=options.get("cluster"), time_effects=params.get("time_col") is not None)
    assert _exact(admitted) == _exact(manual)
    for name in ("params", "std_errors", "tstats", "pvalues", "cov"):
        expected, actual = np.asarray(getattr(manual_fit, name)), np.asarray(getattr(admitted_fit, name))
        assert expected.shape == actual.shape and expected.dtype == actual.dtype
        assert expected.tobytes() == actual.tobytes()
    assert admitted["covariance_evidence"]["cluster_variable"] == (cluster or "unit")
    assert admitted["covariance_evidence"]["cluster_count"] == (10 if cluster else 20)


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_real_panel_workflow_keeps_the_high_floor_then_executes_after_human_confirmation(tmp_path, monkeypatch, mode):
    from tests import test_read_only_analysis as source_fixture
    from workbench.agent import plans
    from workbench.econometrics.panel_iv import run_panel_ols

    # Replace source data only; the proposal, permissions, execution and estimator are real.
    monkeypatch.setattr(source_fixture, "_frame", _panel_frame)
    fixture = source_fixture._Fixture(tmp_path)
    orchestrator = fixture.orchestrator
    orchestrator.execution_mode = mode
    orchestrator.execution_policy = "auto_read_only"
    plan = plans.approve(plans.merge(None, question="Fit the declared panel specifications", criteria=[],
        steps=(plans.PlanStep("models", "Panel models", ("model.genesis",)),),
        budget=None, allowed_classes=["derive", "high"]))
    orchestrator.plan_store.save("chain-session", plan)
    steps = [_panel_step("cluster", step_id="custom_cluster"), _panel_step(step_id="entity_cluster")]
    receipt = fixture.propose(steps)

    assert receipt["requires_confirmation"] and not receipt.get("executed", False), receipt
    assert receipt["permission_class"] == "high"
    assert orchestrator.operation_store.list_records() == []
    assert len(list((fixture.project_root / "runs").iterdir())) == 1
    proposal = orchestrator.proposal_store.latest_revision(receipt["proposal"]["proposal_id"])
    assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "pending"
    record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type="user", current_context_fingerprint=source_fixture.FINGERPRINT,
        current_active_head_run_id=fixture.run_id)
    assert record.actor_type == "user"
    completed = asyncio.run(orchestrator.execute_confirmed_operation(record.record_id, project_root=fixture.project_root,
        current_context_fingerprint=source_fixture.FINGERPRINT, current_active_head_run_id=fixture.run_id))
    assert completed.status == "completed", completed.to_dict()
    state = completed.outputs["workflow_state"]
    assert state["status"] == "completed"
    for step_id, cluster in (("custom_cluster", "cluster"), ("entity_cluster", None)):
        artifact_ids = state["steps"][step_id]["artifact_ids"]
        [qualified] = [item for item in artifact_ids if item.endswith(":panel_ols_1")]
        run_id = qualified.split(":", 1)[0]
        run_root = fixture.project_root / "runs" / run_id
        produced = json.loads((run_root / "model_results/panel_ols_1.json").read_text())
        inputs = json.loads((run_root / "run_inputs.json").read_text())["form"]
        options = inputs["model_options"]
        options = json.loads(options) if isinstance(options, str) else options
        assert options == {"covariance": "clustered", **({"cluster": cluster} if cluster else {})}
        evidence = produced["covariance_evidence"]
        assert evidence["cluster_variable"] == (cluster or "unit")
        assert evidence["cluster_count"] == (10 if cluster else 20)
        actual_frame = pd.read_parquet(run_root / "processed/cleaned_dataset.parquet")
        manual, _ = run_panel_ols(actual_frame, y="outcome", x=["predictor"], entity="unit", time="period",
            model_id="panel_ols_1", covariance="clustered", cluster_col=cluster, time_effects=True)
        assert _exact(produced["coefficients"]) == _exact(manual["coefficients"])
        assert _exact(evidence) == _exact(manual["covariance_evidence"])
