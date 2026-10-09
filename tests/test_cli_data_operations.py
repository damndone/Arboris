"""Generated data CLI uses the same confirmed workflow as the manual API."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd
import pytest
from typer.testing import CliRunner

from tests.test_data_column_cast import _source_project
from workbench.cli import app
from workbench.projects import create_project

REPO = Path(__file__).resolve().parents[1]
WIDE = {"COLUMNS": "400"}


def invoke(*args):
    return CliRunner().invoke(app, list(map(str, args)), env=WIDE)


def source(tmp_path, frame=None):
    frame = frame if frame is not None else pd.DataFrame({"x": [1, 2, 3, 4], "g": [0, 0, 1, 1]})
    root, run_id, artifact_id = _source_project(tmp_path, frame)
    create_project(tmp_path, "project")
    return root, run_id, "stage:source", artifact_id


def args_for(operation, target, spec):
    root, run_id, node, artifact = target
    args = ["data", operation, str(root), run_id, "--source-node", node, "--source-artifact", artifact]
    for name, value in spec.items():
        args.extend(["--" + name.replace("_", "-"), json.dumps(value) if isinstance(value, (list, dict, bool)) else str(value)])
    return args


def confirm(root, preview):
    return invoke("data", "confirm", root, "--request-id", preview["request_id"],
                  "--preview-id", preview["preview_id"], "--fingerprint", preview["fingerprint"])


def test_data_subcommands_and_options_come_from_every_live_declaration():
    from workbench.data_operation_registry import data_operation_declarations
    result = invoke("data", "--help")
    assert result.exit_code == 0, result.output
    for declaration in data_operation_declarations():
        assert declaration.operation in result.output
        detail = invoke("data", declaration.operation, "--help")
        assert detail.exit_code == 0, detail.output
        for field in declaration.fields:
            assert "--" + field.replace("_", "-") in detail.output, (declaration.operation, field)


def test_new_registered_declaration_automatically_reaches_cli_help(monkeypatch):
    from dataclasses import replace
    from workbench import data_operation_registry as registry
    declaration = registry.get_data_operation("subset")
    monkeypatch.setitem(registry._REGISTRY, "future_data", replace(declaration, operation="future_data"))
    assert "future_data" in invoke("data", "--help").output
    assert "--columns" in invoke("data", "future_data", "--help").output


def test_subset_preview_confirm_replay_and_true_cli_provenance(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CLI data operation cannot contact a provider")
    monkeypatch.setattr("workbench.llm.client.chat_completion", forbidden)
    target = source(tmp_path)
    spec = {"columns": ["x", "g"], "filters": [{"column": "x", "op": "gt", "value": 2}]}
    preview = invoke(*args_for("subset", target, spec))
    assert preview.exit_code == 0, preview.output
    document = json.loads(preview.stdout)
    assert document["status"] == "awaiting_confirmation"
    assert not (target[0] / "workbench/workflows").exists()
    assert json.loads(invoke(*args_for("subset", target, spec)).stdout) == document
    completed = confirm(target[0], document)
    assert completed.exit_code == 0, completed.output
    result = json.loads(completed.stdout)
    assert result["status"] == "completed" and result["operation_record_id"]
    assert result["steps"][0]["row_counts"]["output"] == 2
    assert result["steps"][0]["node_refs"]
    assert json.loads(confirm(target[0], document).stdout) == result
    ledger = [json.loads(line) for line in (target[0] / "workbench/analysis_ledger.jsonl").read_text().splitlines()]
    assert len(ledger) == 1
    assert ledger[0]["actor"] == "user" and ledger[0]["source"] == "workbench data (CLI)"
    record = target[0] / "workbench/operation-records" / (result["operation_record_id"] + ".jsonl")
    assert "human_cli" in record.read_text()


@pytest.mark.parametrize("operation,spec,needle", [
    ("subset", {"columns": ["absent"]}, "absent"),
    ("merge", {"secondary_run_id": "run_source", "secondary_node_id": "stage:source",
               "secondary_artifact_id": "source_data", "keys": ["absent"]}, "absent"),
    ("reshape", {"direction": "long_to_wide", "index": ["g"], "columns": "g", "values": "x"}, "reshape"),
])
def test_invalid_columns_keys_and_reshape_return_nonzero(tmp_path, operation, spec, needle):
    target = source(tmp_path)
    result = invoke(*args_for(operation, target, spec))
    if result.exit_code == 0:
        result = confirm(target[0], json.loads(result.stdout))
    assert result.exit_code in {1, 2}, result.output
    assert needle in result.output.lower()


def test_bad_json_missing_required_fields_and_changed_confirmation(tmp_path):
    target = source(tmp_path)
    invalid = invoke(*args_for("subset", target, {"columns": "not-json"}))
    assert invalid.exit_code == 2 and "JSON" in invalid.output
    missing = invoke(*args_for("recode", target, {}))
    assert missing.exit_code == 2 and "--column" in missing.output
    preview = json.loads(invoke(*args_for("subset", target, {"columns": ["x"]})).stdout)
    wrong = confirm(target[0], {**preview, "fingerprint": "wrong"})
    assert wrong.exit_code == 2 and "CONFIRMATION_CONFLICT" in wrong.output


@pytest.mark.parametrize("operation", ["recode", "reshape", "merge"])
def test_declared_data_examples_execute_with_registered_output(tmp_path, operation):
    from workbench.data_operation_registry import get_data_operation
    declaration = get_data_operation(operation)
    frame = declaration.example_frame()
    spec = dict(declaration.example)
    target = source(tmp_path, frame)
    if operation == "merge":
        # A self-join uses the same explicitly owned source on both sides.
        spec.update(secondary_run_id=target[1], secondary_node_id=target[2], secondary_artifact_id=target[3])
        spec["keys"] = list(frame.columns)
    preview = invoke(*args_for(operation, target, spec))
    assert preview.exit_code == 0, preview.output
    executed = confirm(target[0], json.loads(preview.stdout))
    assert executed.exit_code == 0, executed.output
    result = json.loads(executed.stdout)
    assert result["status"] == "completed" and result["steps"][0]["artifact_refs"]


def test_startup_and_warm_declaration_help_budget():
    probe = "import sys,time; t=time.perf_counter(); import workbench.cli; print(time.perf_counter()-t); print([m for m in ('pandas','numpy','scipy','fastapi') if m in sys.modules])"
    result = subprocess.run([sys.executable, "-c", probe], cwd=REPO,
                            env={**os.environ, "PYTHONPATH": str(REPO / "backend")}, capture_output=True, text=True, check=True)
    elapsed, loaded = result.stdout.strip().splitlines()
    assert float(elapsed) < .5 and loaded == "[]", result.stdout
    # Match the existing cold CLI-import budget; measure command construction
    # separately with the declaration registry already loaded.
    from workbench.data_operation_registry import data_operation_declarations
    data_operation_declarations()
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    start = time.perf_counter()
    assert invoke("data", "--help").exit_code == 0
    assert time.perf_counter() - start < .5


def test_real_cli_data_fit_postestimate_export_preserves_lineage(tmp_path):
    import numpy as np
    i = np.arange(80)
    frame = pd.DataFrame({"x": i / 10, "z": i % 7,
                          "y": 2 + .3 * i / 10 + .7 * (i % 7) + np.sin(i)})
    project = create_project(tmp_path, "project").root
    data_file = tmp_path / "input.csv"
    frame.to_csv(data_file, index=False)
    env = {**os.environ, "PYTHONPATH": str(REPO / "backend"), "WORKBENCH_UI_ORIGIN": "http://localhost:5193"}
    def real(args):
        result = subprocess.run([sys.executable, "-m", "workbench.cli", *map(str, args)],
                                cwd=REPO, env=env, text=True, capture_output=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    # Use the existing public CLI to create complete source provenance rather
    # than fabricating run_inputs for a minimal unit-test dataset fixture.
    initialized = subprocess.run([sys.executable, "-m", "workbench.cli", "run", str(project), str(data_file),
                                  "y", "--x", "x", "--x", "z", "--model-type", "ols"],
                                 cwd=REPO, env=env, text=True, capture_output=True, timeout=90)
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    target = (project, initialized.stdout.strip(), "stage:cleaned", "cleaned_dataset")
    def real_confirm(preview):
        return real(["data", "confirm", target[0], "--request-id", preview["request_id"],
                     "--preview-id", preview["preview_id"], "--fingerprint", preview["fingerprint"]])
    subset = real_confirm(real(args_for("subset", target, {"columns": ["x", "z", "y"],
                    "filters": [{"column": "x", "op": "gt", "value": 1}]})))
    step = subset["steps"][0]
    node = step["node_refs"][0]
    source_root = target[0] / "runs" / node["run_id"]
    graph = json.loads((source_root / "graph.json").read_text())
    registry = json.loads((source_root / "artifacts_index.json").read_text())["artifacts"]
    source_path = graph["nodes"][node["node_id"]]["payload_ref"]
    artifact_id = next(item["artifact_id"] for item in registry if item["path"] == source_path)
    child = (target[0], node["run_id"], node["node_id"], artifact_id)
    fitted = real_confirm(real(args_for("fit", child, {"model_family": "ols",
                             "branches": [{"branch_id": "base", "outcome": "y", "predictors": ["x", "z"]}]})))
    model_run = next(item["run_id"] for item in fitted["steps"][0]["artifact_refs"] if item["run_id"] != target[1])
    from workbench.services.results_service import read_model_results
    model_result = read_model_results(target[0] / "runs" / model_run)[0]
    assert model_result["nobs"] == 69, "The selected subset must replace the original 80-row upload"
    inputs = json.loads((target[0] / "runs" / model_run / "run_inputs.json").read_text())
    assert inputs["dataset_source"]["source_artifact_id"] == child[3]
    assert inputs["dataset_source"]["source_run_id"] == child[1]
    assert inputs["dataset_source"]["op_node_id"] == child[2]
    # The HTTP adapter submits the same declaration and selected immutable
    # source through the shared workflow, with independently confirmed intent.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from workbench.api_errors import register_error_handlers
    from workbench.http.operation_routes import router
    http = FastAPI()
    register_error_handlers(http)
    http.include_router(router)
    client = TestClient(http)
    params = {"project_root": str(project)}
    prepared = client.post("/operations/run", params=params, json={
        "mode": "preview", "request_id": "http-selected-model", "target": {
            "kind": "dataset_node", "run_id": child[1], "node_id": child[2], "artifact_id": child[3]},
        "steps": [{"step_id": "operation", "operation_id": "model.genesis", "spec": {
            "model_family": "ols", "branches": [{"branch_id": "base", "outcome": "y", "predictors": ["x", "z"]}]}}]})
    assert prepared.status_code == 200, prepared.text
    preview = prepared.json()
    response = client.post("/operations/run", params=params, json={
        "mode": "confirm", "request_id": preview["request_id"],
        "preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"]})
    assert response.status_code == 200, response.text
    api_result = response.json()
    assert api_result["status"] == "completed", api_result
    api_run = next(item["run_id"] for item in api_result["steps"][0]["artifact_refs"] if item["run_id"] != child[1])
    api_model = read_model_results(project / "runs" / api_run)[0]
    assert api_model["nobs"] == model_result["nobs"] == 69
    assert api_model["coefficients"] == model_result["coefficients"]
    api_inputs = json.loads((project / "runs" / api_run / "run_inputs.json").read_text())
    assert api_inputs["dataset_source"] == inputs["dataset_source"]
    wald = real(["postestimation", "wald", target[0], model_run, "--model-ref", "model:ols_1",
                 "--constraints", '[{"terms":{"x":1},"value":0}]'])
    assert wald["status"] == "completed"
    exported = real(["export-script", target[0], model_run, "--target", "artifact:" + wald["artifact_ids"][0],
                     "--language", "stata"])
    assert Path(exported["bundle_path"]).is_file()
    assert [item["operation"] for item in exported["coverage"]][-1] == "postestimation.wald"


def test_cli_and_api_same_input_produce_the_same_data_and_isolate_origin(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from workbench.api_errors import WorkbenchAPIError, register_error_handlers
    from workbench.http.operation_routes import router
    from workbench.services.manual_operations import run_manual_operation

    target = source(tmp_path)
    spec = {"columns": ["x", "g"], "filters": [{"column": "x", "op": "gt", "value": 2}]}
    preview = json.loads(invoke(*args_for("subset", target, spec)).stdout)
    cli = json.loads(confirm(target[0], preview).stdout)
    with pytest.raises(WorkbenchAPIError, match="another adapter origin"):
        run_manual_operation(target[0], {"mode": "confirm", "request_id": preview["request_id"],
                                       "preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"]})
    http = FastAPI()
    register_error_handlers(http)
    http.include_router(router)
    client = TestClient(http)
    params = {"project_root": str(target[0])}
    body = {"request_id": "http-same-input", "mode": "preview", "target": {
        "kind": "dataset_node", "run_id": target[1], "node_id": target[2], "artifact_id": target[3]},
        "steps": [{"step_id": "operation", "operation_id": "data.subset", "spec": spec}]}
    prepared = client.post("/operations/run", params=params, json=body)
    assert prepared.status_code == 200, prepared.text
    p = prepared.json()
    executed = client.post("/operations/run", params=params, json={"mode": "confirm", "request_id": p["request_id"],
        "preview_id": p["preview_id"], "fingerprint": p["fingerprint"]})
    assert executed.status_code == 200, executed.text
    api = executed.json()
    assert api["status"] == cli["status"] == "completed"
    assert api["steps"][0]["row_counts"] == cli["steps"][0]["row_counts"]
    def output_frame(result):
        node_ref = result["steps"][0]["node_refs"][0]
        root = target[0] / "runs" / node_ref["run_id"]
        graph = json.loads((root / "graph.json").read_text())
        path = root / graph["nodes"][node_ref["node_id"]]["payload_ref"]
        return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    pd.testing.assert_frame_equal(output_frame(cli), output_frame(api))
