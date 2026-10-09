"""Representative offline HTTP composition, with report values pinned to evidence."""
from __future__ import annotations

import hashlib
import json
import math

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pandas as pd
import pytest

from tests.test_iv_gmm_pack import _iv_data
from workbench.api_errors import register_error_handlers
from workbench.lineage.upload_store import store_upload_bytes
from workbench.projects import create_project


def test_http_manual_recode_tests_iv_pca_and_report_without_provider(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The manual journey must not load or call a provider")

    monkeypatch.setattr("workbench.agent.model.OpenAICompatibleModelAdapter.__init__", forbidden)
    monkeypatch.setattr("workbench.llm.config.load_llm_config", forbidden)
    monkeypatch.setattr("workbench.llm.client.chat_completion", forbidden)
    from workbench.http.operation_routes import router as operations
    from workbench.http.manual_report_routes import router as reports
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    from workbench.services.results_service import read_model_results

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(operations)
    app.include_router(reports)
    client = TestClient(app)
    root = create_project(tmp_path, "manual-offline").root
    # Reuse the well-conditioned pack fixture; no independent estimator or
    # tolerance policy is introduced by this surface-composition acceptance.
    y, exog, endog, instruments = _iv_data()
    frame = pd.DataFrame({"y": y, "const": exog[:, 0], "x": exog[:, 1],
                          "endog": endog[:, 0], "z1": instruments[:, 0], "z2": instruments[:, 1]})
    upload = frame.to_csv(index=False).encode()
    sha = store_upload_bytes(root, upload, filename="iv.csv")
    source = {"from_step": "recode", "output": "produced_dataset"}
    steps = [
        {"step_id": "recode", "operation_id": "data.recode", "spec": {
            "column": "x", "output": "group", "rules": [
                {"from": {"low": -100, "high": 0}, "to": 0}, {"from": "else", "to": 1}]}},
        {"step_id": "describe", "operation_id": "statistical.explore", "spec": {
            "operation": "summarize", "selected_columns": ["y", "x"], "source": source}},
        {"step_id": "ttest", "operation_id": "test.t_tests", "spec": {
            "input_mode": "frame", "column_bindings": {"columns": ["y", "group"]}, "options": {}, "source": source}},
        {"step_id": "iv", "operation_id": "model.genesis", "spec": {
            "model_family": "iv_2sls", "iv_endog": ["endog"], "iv_instruments": ["z1", "z2"],
            "branches": [{"branch_id": "iv", "outcome": "y", "predictors": ["x"]}], "source": source}},
        {"step_id": "weak", "operation_id": "iv.weak_instruments", "spec": {
            "input_mode": "typed", "column_bindings": {"outcome": "y", "exog": ["const", "x"],
                "endog": ["endog"], "instruments": ["z1", "z2"]}, "options": {}, "source": source}},
        {"step_id": "pca", "operation_id": "multivariate.pca", "spec": {
            "input_mode": "frame", "column_bindings": {"columns": ["x", "endog", "z1"]},
            "options": {"matrix": "correlation", "component_selection": "all", "include_scores": False,
                        "max_score_rows": 100}, "source": source}},
    ]
    assert all(step["operation_id"] in WORKFLOW_STEP_SPEC_CONTRACTS for step in steps)
    params = {"project_root": str(root)}
    preview_response = client.post("/operations/run", params=params, json={
        "mode": "preview", "request_id": "offline-journey", "target": {
            "kind": "upload", "upload_sha256": sha, "filename": "iv.csv"}, "steps": steps})
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["status"] == "awaiting_confirmation"
    assert not list((root / "runs").iterdir())
    confirmation = {"mode": "confirm", "request_id": preview["request_id"],
                    "preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"]}
    response = client.post("/operations/run", params=params, json=confirmation)
    assert response.status_code == 200, response.text
    executed = response.json()
    assert executed["status"] == "completed", executed
    by_step = {step["step_id"]: step for step in executed["steps"]}
    assert set(by_step) == {step["step_id"] for step in steps}
    assert all(step["status"] == "completed" and step["artifact_refs"] for step in by_step.values())
    assert client.post("/operations/run", params=params, json=confirmation).json() == executed
    source_run = by_step["recode"]["node_refs"][0]["run_id"]
    source_node = by_step["recode"]["node_refs"][0]["node_id"]
    source_root = root / "runs" / source_run
    graph = json.loads((source_root / "graph.json").read_text())
    data_path = source_root / graph["nodes"][source_node]["payload_ref"]
    recoded = pd.read_parquet(data_path) if data_path.suffix == ".parquet" else pd.read_csv(data_path)
    assert recoded["group"].tolist() == (frame["x"] > 0).astype(int).tolist()
    assert len(recoded) == len(frame) == 240

    def artifact(ref):
        run_root = root / "runs" / ref["run_id"]
        records = json.loads((run_root / "artifacts_index.json").read_text())["artifacts"]
        record = next(item for item in records if item["artifact_id"] == ref["artifact_id"])
        path = run_root / record["path"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
        return record, json.loads(content) if path.suffix == ".json" else None

    descriptions = [artifact(ref)[1] for ref in by_step["describe"]["artifact_refs"]]
    summary = next(payload["result"] for payload in descriptions if payload and "variables" in payload.get("result", {}))
    assert summary["filtered_row_count"] == 240
    for column in ("x", "y"):
        assert summary["variables"][column]["mean"] == pytest.approx(recoded[column].mean())

    # The source file and model are read only through returned, owned artifact
    # identities. Report tests below compare against these actual executions.
    model_run = next(ref["run_id"] for ref in by_step["iv"]["artifact_refs"] if ref["run_id"] != source_run)
    model_root = root / "runs" / model_run
    [model] = read_model_results(model_root)
    assert model["nobs"] == 240
    assert "iv" in str(model.get("model_type") or model.get("model"))
    # Post-estimation has a model target and consumes its inference kernel,
    # while the preceding steps consume a dataset. Confirm that branch through
    # a separate public request rather than inventing a frame source for Wald.
    response = client.post("/operations/run", params=params, json={
        "mode": "execute", "request_id": "offline-model-wald", "target": {
            "kind": "model_node", "run_id": model_run, "node_id": f"model:{model['model_id']}"},
        "steps": [{"step_id": "wald", "operation_id": "postestimation.wald", "spec": {
            "constraints": [{"terms": {"endog": 1}, "value": 0}]}}]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.json()
    by_step["wald"] = response.json()["steps"][0]
    inputs = json.loads((model_root / "run_inputs.json").read_text())
    assert inputs["dataset_source"]["source_run_id"] == source_run
    assert inputs["dataset_source"]["op_node_id"] == source_node

    def numeric_fields(value, prefix=""):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from numeric_fields(item, f"{prefix}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from numeric_fields(item, f"{prefix}/{index}")
        elif isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
            yield "post_estimation" + prefix, value

    evidence = {}
    for step_id in ("ttest", "wald", "weak", "pca"):
        records = [(ref, artifact(ref)[1]) for ref in by_step[step_id]["artifact_refs"]]
        ref, payload = next((ref, payload) for ref, payload in records if payload and isinstance(payload.get("result"), dict))
        evidence[step_id] = (ref, payload["result"])
        assert dict(numeric_fields(payload["result"])), step_id
    # Registered workflow evidence is projected at its owning source run. A
    # model-child draft separately exposes the fitted IV coefficient evidence.
    draft_response = client.get(f"/runs/{source_run}/manual-reports/draft", params=params)
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert client.get(f"/runs/{source_run}/manual-reports/draft", params=params).json() == draft
    selected = []
    for step_id in ("ttest", "weak", "pca"):
        ref, result = evidence[step_id]
        facts = [fact for fact in draft["facts"] if ref["artifact_id"] in fact["source"]["artifact_ids"]]
        assert facts, f"Missing {step_id} report evidence"
        assert all(fact["source"]["run_id"] == ref["run_id"] for fact in facts)
        actual_numbers = dict(numeric_fields(result))
        numeric = [fact for fact in facts if isinstance(fact["value"], (float, int)) and not isinstance(fact["value"], bool)]
        assert numeric and all(actual_numbers[fact["field"]] == fact["value"] for fact in numeric)
        selected.extend(facts)
    model_draft = client.get(f"/runs/{model_run}/manual-reports/draft", params=params)
    assert model_draft.status_code == 200, model_draft.text
    wald_ref, wald_result = evidence["wald"]
    wald_facts = [fact for fact in model_draft.json()["facts"] if wald_ref["artifact_id"] in fact["source"]["artifact_ids"]]
    assert wald_facts and all(fact["source"]["run_id"] == model_run for fact in wald_facts)
    wald_numbers = dict(numeric_fields(wald_result))
    assert all(wald_numbers[fact["field"]] == fact["value"] for fact in wald_facts
               if isinstance(fact["value"], (int, float)) and not isinstance(fact["value"], bool))
    coefficients = model["coefficients"]
    for term, coefficient in coefficients.items():
        assert any(fact["field"] == f"coefficient/{term}/estimate" and fact["value"] == coefficient["estimate"]
                   for fact in model_draft.json()["facts"])

    original_model = (model_root / "model_results" / f"{model['model_id']}.json").read_bytes()
    save = {"id": "mrpt_offline_journey", "source_fingerprint": draft["source_fingerprint"],
            "title": "Offline analysis", "text": "User interpretation of the registered test and PCA evidence.",
            "fact_ids": [fact["id"] for fact in selected], "figure_ids": []}
    saved = client.post(f"/runs/{source_run}/manual-reports", params=params, json=save)
    assert saved.status_code == 200, saved.text
    record = saved.json()["record"]
    assert record["author"] == "user" and record["draft_origin"] == "deterministic"
    assert {fact["id"]: fact for fact in record["facts"]} == {fact["id"]: fact for fact in selected}
    history = client.get(f"/runs/{source_run}/manual-reports", params=params)
    assert history.status_code == 200 and history.json()["reports"] == [record]
    exported = client.get(f"/runs/{source_run}/manual-reports/{save['id']}/export", params={**params, "format": "html"})
    assert exported.status_code == 200, exported.text
    assert "User interpretation" in exported.text and "Computed evidence" in exported.text
    assert any(str(fact["value"]) in exported.text for fact in selected if isinstance(fact["value"], float))
    # A second immutable, run-bound report preserves fitted IV and Wald
    # evidence; cross-run report aggregation is not silently invented here.
    model_snapshot = model_draft.json()
    model_facts = [fact for fact in model_snapshot["facts"] if fact["field"].startswith("coefficient/")] + wald_facts
    model_save = {**save, "id": "mrpt_offline_model", "source_fingerprint": model_snapshot["source_fingerprint"],
                  "fact_ids": [fact["id"] for fact in model_facts]}
    model_saved = client.post(f"/runs/{model_run}/manual-reports", params=params, json=model_save)
    assert model_saved.status_code == 200, model_saved.text
    assert {fact["id"]: fact for fact in model_saved.json()["record"]["facts"]} == {fact["id"]: fact for fact in model_facts}
    model_export = client.get(f"/runs/{model_run}/manual-reports/{model_save['id']}/export", params={**params, "format": "html"})
    assert model_export.status_code == 200 and "Computed evidence" in model_export.text
    assert (model_root / "model_results" / f"{model['model_id']}.json").read_bytes() == original_model


def test_http_genesis_accepts_verified_cleaned_parquet_without_public_upload_expansion(tmp_path):
    from tests.test_postestimation_workflow_steps import _run
    from workbench.http.operation_routes import router
    from workbench.ingestion import read_frame_bounded
    from workbench.services.results_service import read_model_results

    root, run_id = _run(tmp_path, "cleaned", model_type="ols", y="y", x=["x1", "x2"])
    graph = json.loads((root / "runs" / run_id / "graph.json").read_text())
    source_path = root / "runs" / run_id / graph["nodes"]["stage:cleaned"]["payload_ref"]
    assert source_path.suffix == ".parquet"
    expected = pd.read_parquet(source_path)
    with pytest.raises(ValueError, match="unsupported file type"):
        read_frame_bounded(source_path, max_rows=10000)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    client = TestClient(app)
    params = {"project_root": str(root)}
    response = client.post("/operations/run", params=params, json={
        "mode": "preview", "request_id": "cleaned-parquet", "target": {
            "kind": "dataset_node", "run_id": run_id, "node_id": "stage:cleaned", "artifact_id": "cleaned_dataset"},
        "steps": [{"step_id": "fit", "operation_id": "model.genesis", "spec": {
            "model_family": "ols", "branches": [{"branch_id": "base", "outcome": "y", "predictors": ["x1", "x2"]}]}}]})
    assert response.status_code == 200, response.text
    preview = response.json()
    response = client.post("/operations/run", params=params, json={
        "mode": "confirm", "request_id": preview["request_id"],
        "preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed", result
    child = next(ref["run_id"] for ref in result["steps"][0]["artifact_refs"] if ref["run_id"] != run_id)
    child_root = root / "runs" / child
    [model] = read_model_results(child_root)
    assert model["nobs"] == len(expected)
    inputs = json.loads((child_root / "run_inputs.json").read_text())
    assert inputs["upload"]["sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert inputs["dataset_source"]["source_artifact_id"] == "cleaned_dataset"
    assert inputs["dataset_source"]["op_node_id"] == "stage:cleaned"
    from workbench.services.script_export import export_analysis_script
    exported = export_analysis_script(root, child, "model:ols_1", "stata", require_native=True)
    assert exported["coverage"]
    # Internal trust is tied to exact artifact ownership and bytes, not the
    # filename or presence of a dataset_source-shaped client value.
    from workbench.config import WorkbenchConfig
    from workbench.ingestion import _read_verified_dataset_parquet
    isolated = root / "runs" / "forged-binding-test"
    isolated.mkdir()
    input_file = isolated / "run_inputs.json"
    input_file.write_text(json.dumps({**inputs, "dataset_source": None}))
    with pytest.raises(ValueError, match="verified dataset source"):
        _read_verified_dataset_parquet(source_path, isolated, WorkbenchConfig())
    input_file.write_text(json.dumps({**inputs, "dataset_source": {
        **inputs["dataset_source"], "source_artifact_id": "raw_input.csv"}}))
    with pytest.raises(ValueError, match="not owned"):
        _read_verified_dataset_parquet(source_path, isolated, WorkbenchConfig())
    input_file.write_text(json.dumps({**inputs, "upload": {**inputs["upload"], "sha256": "0" * 64}}))
    with pytest.raises(ValueError, match="pinned run upload"):
        _read_verified_dataset_parquet(source_path, isolated, WorkbenchConfig())
    input_file.write_text(json.dumps(inputs))
    with pytest.raises(ValueError, match="row count exceeds limit"):
        _read_verified_dataset_parquet(source_path, isolated, WorkbenchConfig(max_rows=1))
