"""The manual API executes declared workflows through the shared lifecycle."""

import json

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.api_errors import register_error_handlers


@pytest.fixture
def client():
    from workbench.http.operation_routes import router

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def source(tmp_path):
    root, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"x": [1, 2, 3, 4], "g": [0, 0, 1, 1]}))
    return root, {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": artifact_id}


def _explore():
    return {"step_id": "summary", "operation_id": "statistical.explore", "spec": {"operation": "summarize", "selected_columns": ["x"]}}


def _post(client, root, body):
    return client.post("/operations/run", params={"project_root": str(root)}, json=body)


def _confirm(client, root, preview):
    return _post(client, root, {"mode": "confirm", "request_id": preview["request_id"],
                               "preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"]})


def test_readonly_execute_replays_one_persisted_ui_operation(client, source, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("manual operations must not construct a model provider")

    monkeypatch.setattr("workbench.agent.model.OpenAICompatibleModelAdapter.__init__", forbidden)
    monkeypatch.setattr("workbench.llm.config.load_llm_config", forbidden)
    root, target = source
    body = {"mode": "execute", "request_id": "summary-1", "target": target, "steps": [_explore()]}
    response = _post(client, root, body)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["status"] == "completed", first
    assert first["steps"][0]["artifact_refs"]
    assert _post(client, root, body).json() == first
    records = [json.loads(line) for line in (root / "workbench" / "analysis_ledger.jsonl").read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["actor"] == "user"
    assert records[0]["source"] == "POST /operations/run"
    conflict = _post(client, root, {**body, "steps": [{**_explore(), "spec": {"operation": "misstable"}}]})
    assert conflict.status_code == 409


def test_mutation_preview_confirm_and_dependency_use_child_dataset(client, source):
    root, target = source
    steps = [
        {"step_id": "keep", "operation_id": "data.subset", "spec": {"columns": ["x", "g"], "filters": [{"column": "x", "op": "gt", "value": 2}]}},
        {**_explore(), "spec": {**_explore()["spec"], "source": {"from_step": "keep", "output": "produced_dataset"}}},
    ]
    body = {"mode": "execute", "request_id": "subset-1", "target": target, "steps": steps}
    response = _post(client, root, body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "awaiting_confirmation"
    assert not (root / "workbench" / "workflows").exists()
    response = _confirm(client, root, preview)
    assert response.status_code == 200, response.text
    completed = response.json()
    assert completed["status"] == "completed", completed
    assert [step["status"] for step in completed["steps"]] == ["completed", "completed"]
    assert completed["steps"][0]["node_refs"]
    assert completed["steps"][0]["row_counts"]["output"] == 2
    assert _confirm(client, root, preview).json() == completed


def test_confirm_rejects_stale_source_and_changed_confirmation(client, source):
    root, target = source
    preview = _post(client, root, {"mode": "preview", "request_id": "stale", "target": target, "steps": [_explore()]}).json()
    wrong = _confirm(client, root, {**preview, "fingerprint": "incorrect"})
    assert wrong.status_code == 409
    (root / "runs" / target["run_id"] / "data.csv").write_text("x,g\n99,0\n")
    response = _confirm(client, root, preview)
    assert response.status_code == 409, response.text
    assert not (root / "workbench" / "workflows").exists()


@pytest.mark.parametrize("steps", [
    [{"step_id": "bad", "operation_id": "not.registered", "spec": {}}],
    [{**_explore(), "spec": {"operation": "summarize", "selected_columns": ["absent"]}}],
    [{"step_id": "a", "operation_id": "statistical.explore", "spec": {"operation": "summarize"}, "depends_on": ["a"]}],
])
def test_invalid_plan_is_rejected_before_business_records(client, source, steps):
    root, target = source
    response = _post(client, root, {"mode": "execute", "request_id": "invalid", "target": target, "steps": steps})
    assert response.status_code == 422, response.text
    assert not (root / "workbench" / "proposals").exists()


def test_partial_failure_reports_completed_artifacts_and_blocked_dependencies(client, source):
    root, target = source
    steps = [_explore(), {"step_id": "bad", "operation_id": "statistical.explore", "spec": {
        "operation": "summarize_detail", "selected_columns": ["x"], "options": {"quantile_method": "invalid"}}},
        {**_explore(), "step_id": "blocked", "depends_on": ["bad"]}]
    result = _post(client, root, {"mode": "execute", "request_id": "partial", "target": target, "steps": steps})
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["steps"][0]["status"] == "completed"
    assert payload["steps"][0]["artifact_refs"]
    assert payload["status"] == "failed"
    assert [step["status"] for step in payload["steps"]] == ["completed", "failed", "blocked"]
    assert "quantile" in payload["steps"][1]["error"]


def test_concurrent_same_request_has_one_effect_and_ledger_entry(client, source):
    from concurrent.futures import ThreadPoolExecutor

    root, target = source
    body = {"mode": "execute", "request_id": "concurrent", "target": target, "steps": [_explore()]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: _post(client, root, body), range(2)))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "completed"
    assert len((root / "workbench" / "analysis_ledger.jsonl").read_text().splitlines()) == 1


def test_upload_is_verified_then_materialized_only_after_confirmation(client, tmp_path):
    from workbench.projects import create_project
    from workbench.lineage.upload_store import store_upload_bytes

    root = create_project(tmp_path, "upload").root
    sha = store_upload_bytes(root, b"x,g\n1,0\n2,1\n3,1\n", filename="data.csv")
    body = {"mode": "preview", "request_id": "upload", "target": {
        "kind": "upload", "upload_sha256": sha, "filename": "data.csv"}, "steps": [_explore()]}
    response = _post(client, root, body)
    assert response.status_code == 200, response.text
    assert not list((root / "runs").iterdir())
    response = _confirm(client, root, response.json())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.json()
    assert response.json()["target"]["node_ref"] == "stage:raw"


def test_model_target_uses_the_completed_kernel_and_owned_dataset(client, tmp_path):
    from tests.test_postestimation_workflow_steps import _run

    root, run_id = _run(tmp_path, "model", model_type="logit", y="yb", x=["x1", "x2", "x3"])
    response = _post(client, root, {"mode": "execute", "request_id": "wald", "target": {
        "kind": "model_node", "run_id": run_id, "node_id": "model:logit_1"}, "steps": [{
            "step_id": "wald", "operation_id": "postestimation.wald", "spec": {
                "constraints": [{"terms": {"x1": 1}, "value": 0}]}}]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.json()
    assert response.json()["steps"][0]["artifact_refs"]


def test_declared_genesis_authorization_uses_real_confirmation_and_model_runtime(client, tmp_path):
    from workbench.projects import create_project
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    from workbench.lineage.upload_store import store_upload_bytes

    frame = pd.DataFrame({"x": list(range(40)), "y": [2 * i + i % 3 for i in range(40)]})
    root = create_project(tmp_path, "project").root
    sha = store_upload_bytes(root, frame.to_csv(index=False).encode(), filename="models.csv")
    contract = WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"]
    assert contract.risk_level == "high"
    assert contract.confirmation_policy == "proposal_authorization"
    response = _post(client, root, {"mode": "execute", "request_id": "genesis", "target": {
        "kind": "upload", "upload_sha256": sha, "filename": "models.csv"},
        "steps": [{"step_id": "fit", "operation_id": "model.genesis", "spec": {
            "model_family": "ols", "branches": [{"branch_id": "base", "outcome": "y", "predictors": ["x"]}]}}]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_confirmation"
    result = _confirm(client, root, response.json())
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed", result.json()
    assert result.json()["steps"][0]["artifact_refs"]


def test_generated_dispatcher_obeys_declared_high_risk_confirmation_without_id_allowlist(client, tmp_path, monkeypatch):
    from dataclasses import replace
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    # The current generated selector is low risk. Raising its declared risk
    # verifies extension behavior without inventing a shipped high-risk recipe.
    declaration = WORKFLOW_STEP_SPEC_CONTRACTS["model.auto"]
    monkeypatch.setitem(WORKFLOW_STEP_SPEC_CONTRACTS, "model.auto", replace(
        declaration, risk_level="high", confirmation_policy="proposal_authorization"))
    root, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({
        "x": list(range(40)), "y": [2 * i + (i % 3) * 0.125 + 0.17 for i in range(40)]}))
    target = {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": artifact_id}
    response = _post(client, root, {"mode": "execute", "request_id": "selector", "target": target, "steps": [{
        "step_id": "select", "operation_id": "model.auto", "spec": {
            "input_mode": "frame", "column_bindings": {"outcome": "y", "features": ["x"]}, "options": {}}}]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_confirmation"
    result = _confirm(client, root, response.json())
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed", result.json()


def test_custom_dispatcher_still_requires_server_bound_gateway(client, source):
    root, target = source
    response = _post(client, root, {"mode": "preview", "request_id": "custom", "target": target, "steps": [{
        "step_id": "custom", "operation_id": "model.custom", "spec": {
            "capability_ref": "client-claim", "binding_ref": "client-claim", "operation": "fit"}}]})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "AUTHORIZED_GATEWAY_REQUIRED"
    assert not (root / "workbench" / "operation-records").exists()
