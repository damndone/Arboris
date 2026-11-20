"""Saved native models and new datasets share the normal approval lifecycle."""

from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from tests.test_native_random_forest_adapter import frame
from tests.test_native_prediction_apply import independent_predictions
from workbench import native_ridge
from workbench.artifacts import read_json, register_artifact, sha256_file, write_json
from workbench.graph_store import GraphStore
from workbench.services.operation_catalog import operation_catalog


APPLY = "prediction.native_forest_apply"
TRAIN = "prediction.native_random_forest_regression"
CLASSIFY = "prediction.native_random_forest_classification"


def test_saved_model_application_is_a_declared_dataset_producer():
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operations = workflow_capability_registry()
    assert APPLY in operations.operation_ids(), "saved model application is not registered"
    operation = operations.require(APPLY)
    assert operation.produces_dataset and operation.dataset_kind == "derived_data"


def _compiled_apply(operation=TRAIN, **changes):
    from workbench.agent.workflow import compile_workflow

    return compile_workflow(workflow_id="saved-forest-contract",
        target={"run_id": "new", "node_ref": "stage:source", "artifact_id": "source_data"},
        preconditions={"context_fingerprint": "sha256:fixture"}, available_columns=["x", "z"],
        steps=[{"step_id": "apply", "operation_id": APPLY, "spec": {
            "input_mode": "frame", "column_bindings": {}, "options": {
                "model_run_id": "train", "model_artifact_id": "workflow_capability_" + operation.replace(".", "_") + "_a_b",
                "model_sha256": "a" * 64, **changes}}}])


def test_regression_default_request_and_step_fingerprint_stay_unchanged():
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    step = _compiled_apply().steps[0]
    assert step.spec["options"] == {
        "model_run_id": "train", "model_artifact_id": "workflow_capability_prediction_native_random_forest_regression_a_b",
        "model_sha256": "a" * 64,
    }
    normalized = workflow_capability_registry().require(APPLY).validate({
        "operation_id": APPLY, **{key: step.spec[key] for key in ("input_mode", "column_bindings", "options")}})
    assert normalized["options"] == {"prediction_column": "prediction", **step.spec["options"]}
    # Captured through compile_workflow before classifier application was added.
    assert step.fingerprint == "sha256:9ee59b4c290abb903cdfc874655d41646ea4d10e042723e439a5f4d0a04e7cdc"


@pytest.mark.parametrize("override,expected", [({}, "probability"), ({"probability_column": "class_one"}, "class_one")])
def test_classifier_default_and_explicit_probability_columns_are_normalized(override, expected):
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    step = _compiled_apply(CLASSIFY, **override).steps[0]
    normalized = workflow_capability_registry().require(APPLY).validate({
        "operation_id": APPLY, **{key: step.spec[key] for key in ("input_mode", "column_bindings", "options")}})
    assert normalized["options"]["probability_column"] == expected


def test_regression_rejects_classification_only_parameter_after_model_switch():
    from workbench.contracts.common.errors import OperationValidationError

    with pytest.raises(OperationValidationError, match="FOREST_APPLY_PROBABILITY_CLASSIFICATION_ONLY"):
        _compiled_apply(probability_column="probability")


def _request(run_id, request_id, operation, options, bindings=None):
    return {"mode": "preview", "request_id": request_id,
            "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": "source_data"},
            "steps": [{"step_id": "apply", "operation_id": operation,
                       "spec": {"input_mode": "frame", "column_bindings": bindings or {}, "options": options}}]}


def _confirm(client, root, body):
    response = client.post("/operations/run", params={"project_root": str(root)}, json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "awaiting_confirmation" and preview["confirmation_required"]
    response = client.post("/operations/run", params={"project_root": str(root)}, json={
        "mode": "confirm", **{key: preview[key] for key in ("request_id", "preview_id", "fingerprint")},
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.text
    return response.json()


@pytest.fixture
def project(tmp_path, monkeypatch, request):
    from workbench.app import app

    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py")
    monkeypatch.setattr("workbench.agent.model.OpenAICompatibleModelAdapter.__init__",
                        lambda *a, **k: pytest.fail("manual operation contacted a model"))
    training = getattr(request, "param", TRAIN)
    if training == CLASSIFY:
        from tests.test_native_random_forest_classification_adapter import frame as classification_frame

        data = classification_frame()
    else:
        data = frame()
    root, run_id, _ = _source_project(tmp_path, data)
    client = TestClient(app, base_url="http://127.0.0.1")
    _confirm(client, root, _request(run_id, "train", training, {
        "n_trees": 5, "max_depth": 3, "min_samples_leaf": 2, "max_features": 1,
        "seed": 731, "holdout_fraction": .2,
    }, {"predictors": ["x", "z"], "outcome": "y", "time_col": "t"}))
    index = read_json(root / "runs" / run_id / "artifacts_index.json")
    artifact = next(item for item in index["artifacts"] if item["step"] == training)
    options = {"model_run_id": run_id, "model_artifact_id": artifact["artifact_id"],
               "model_sha256": artifact["sha256"], "prediction_column": "forecast"}
    new_run = "run_new"
    new_dir = root / "runs" / new_run
    new_dir.mkdir()
    new_data = data.iloc[[9, 8, 2]][["z", "x"]].reset_index(drop=True).assign(label=["last", "first", "old"])
    new_data.to_csv(new_dir / "data.csv", index=False)
    write_json(new_dir / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    register_artifact(new_dir, "source_data", new_dir / "data.csv", "raw_data", "fixture", [])
    graph = GraphStore(root / "runs").read(run_id)
    GraphStore(root / "runs").write(replace(graph, run_id=new_run,
        nodes={"stage:source": graph.nodes["stage:source"]}, edges={}))
    return client, root, new_run, options, new_data, artifact


@pytest.mark.parametrize("project", [CLASSIFY], indirect=True)
@pytest.mark.parametrize("probability_column", [None, "class_one"])
def test_classification_apply_catalog_exports_labels_probabilities_and_binds_dependencies(project, probability_column):
    from workbench.services.native_prediction_apply import load_saved_forest
    from workbench.native_prediction_apply import score_saved_forest

    client, root, run_id, options, new_data, model_artifact = project
    options = {**options, **({"probability_column": probability_column} if probability_column else {})}
    probability_name = probability_column or "probability"
    catalog = operation_catalog(project_root=str(root))
    item = next(item for item in catalog["operations"] if item["id"] == APPLY)
    [saved] = item["saved_models"]
    assert saved["model_type"] == "native_random_forest_classification"
    assert saved["artifact_id"] == options["model_artifact_id"]
    body = _request(run_id, "classification-apply", APPLY, options)
    body["steps"].append({"step_id": "summary", "operation_id": "statistical.explore", "depends_on": ["apply"],
        "spec": {"operation": "summarize", "selected_columns": ["forecast", probability_name],
                 "source": {"from_step": "apply", "output": "produced_dataset"}}})
    outcome = _confirm(client, root, body)
    assert [step["status"] for step in outcome["steps"]] == ["completed", "completed"]
    assert outcome["steps"][0]["spec"]["options"].get("probability_column") == probability_column
    run = root / "runs" / run_id
    index = read_json(run / "artifacts_index.json")["artifacts"]
    [dataset] = [item for item in index if item["artifact_type"] == "derived_data"]
    [metadata] = [item for item in index if item["artifact_type"] == "workflow_capability_metadata"]
    path = run / dataset["path"]
    output = pd.read_csv(path, float_precision="round_trip")
    assert output.columns.tolist() == [*new_data.columns, "forecast", probability_name]
    pd.testing.assert_frame_equal(output[new_data.columns], new_data)
    _, forest, _ = load_saved_forest(root, options)
    expected, _ = score_saved_forest(new_data, forest=forest, classification=True)
    assert output[probability_name].to_numpy().tobytes() == expected.tobytes()
    np.testing.assert_array_equal(output.forecast, (expected >= .5).astype(np.int64))
    result = read_json(run / metadata["path"])["result"]
    assert result["classification_threshold"] == .5 and result["probability_column"] == probability_name
    assert result["policy"]["evaluation_metrics"] is False and "metrics" not in result
    assert result["policy"]["refit"] is False
    assert result["model_source"]["sha256"] == options["model_sha256"]
    assert dataset["inputs"] == ["source_data", f"{options['model_run_id']}:{model_artifact['artifact_id']}"]
    node_id = outcome["steps"][0]["node_refs"][0]["node_id"]
    [annotation] = [item for item in GraphStore(root / "runs").read(run_id).nodes[node_id].annotations
                    if item.get("type") == "prediction_model_source"]
    assert annotation["sha256"] == options["model_sha256"]
    download = client.get(f"/runs/{run_id}/artifacts/{dataset['artifact_id']}", params={"project_root": str(root)})
    assert download.status_code == 200 and download.content == path.read_bytes()
    assert "prediction_basis" not in json.dumps(outcome) and "trees" not in json.dumps(outcome)


@pytest.mark.parametrize("project", [CLASSIFY], indirect=True)
def test_classifier_label_threshold_is_inclusive_and_does_not_modify_new_inputs(project, monkeypatch):
    from workbench.services import native_prediction_apply as service

    _, root, _, options, new_data, _ = project
    before = new_data.copy(deep=True)
    monkeypatch.setattr(service, "score_saved_forest", lambda *a, **k: (np.array([.49, .5, .51]), {}))
    execution = service.execute_saved_forest(root, new_data, {"options": options})
    assert execution.output_frame.forecast.tolist() == [0, 1, 1]
    assert execution.output_frame.probability.tolist() == [.49, .5, .51]
    pd.testing.assert_frame_equal(new_data, before)


@pytest.mark.parametrize("project", [CLASSIFY], indirect=True)
@pytest.mark.parametrize("name", ["forecast", "x"])
def test_classifier_rejects_probability_column_collision_before_confirmation(project, name):
    client, root, run_id, options, _, _ = project
    options = {**options, "probability_column": name}
    before = set((root / "workbench" / "proposals").iterdir())
    response = client.post("/operations/run", params={"project_root": str(root)},
                           json=_request(run_id, "probability-collision", APPLY, options))
    assert response.status_code == 422 and "FOREST_APPLY_INVALID_OUTPUT" in response.text
    assert set((root / "workbench" / "proposals").iterdir()) == before
    assert not (root / "runs" / run_id / "derived").exists()


def test_manual_train_save_apply_reopen_and_csv_export(project):
    from workbench.statistical_exploration import resolve_statistical_source

    client, root, run_id, options, new_data, model_artifact = project
    catalog = operation_catalog(project_root=str(root))
    item = next(item for item in catalog["operations"] if item["id"] == APPLY)
    assert len(item["saved_models"]) == 1
    saved = item["saved_models"][0]
    assert saved["artifact_id"] == options["model_artifact_id"]
    assert saved["sha256"] == options["model_sha256"] and saved["predictors"] == ["x", "z"]
    outcome = _confirm(client, root, _request(run_id, "apply", APPLY, options))
    refs = outcome["steps"][0]["artifact_refs"]
    run = root / "runs" / run_id
    index = read_json(run / "artifacts_index.json")["artifacts"]
    dataset = next(item for item in index if item["artifact_type"] == "derived_data")
    assert {"run_id": run_id, "artifact_id": dataset["artifact_id"]} in refs
    node_id = outcome["steps"][0]["node_refs"][0]["node_id"]
    _, reopened = resolve_statistical_source(root, source_run_id=run_id, source_node_id=node_id,
                                             source_artifact_id=dataset["artifact_id"])
    pd.testing.assert_frame_equal(reopened.drop(columns="forecast"), new_data)
    metadata = next(item for item in index if item["artifact_type"] == "workflow_capability_metadata")
    result = read_json(run / metadata["path"])["result"]
    assert result["model_source"]["sha256"] == options["model_sha256"]
    assert result["model_source"]["artifact_id"] == model_artifact["artifact_id"]
    assert result["policy"]["refit"] is False and result["output_rows"] == 3
    trained = read_json(root / "runs" / options["model_run_id"] / model_artifact["path"])
    np.testing.assert_allclose(reopened.forecast, independent_predictions(new_data, trained["local_detail"]["prediction_basis"]),
                               rtol=1e-15, atol=0)
    assert f"{options['model_run_id']}:{options['model_artifact_id']}" in dataset["inputs"]
    annotation = GraphStore(root / "runs").read(run_id).nodes[node_id].annotations[-1]
    assert annotation["type"] == "prediction_model_source" and annotation["sha256"] == options["model_sha256"]
    assert "trees" not in json.dumps(outcome) and "prediction_basis" not in json.dumps(outcome)
    assert dataset["sha256"] == sha256_file(run / dataset["path"])
    download = client.get(f"/runs/{run_id}/artifacts/{dataset['artifact_id']}", params={"project_root": str(root)})
    assert download.status_code == 200 and download.content == (run / dataset["path"]).read_bytes()
    assert "attachment" in download.headers["content-disposition"]


@pytest.mark.parametrize("entries", [None, {"bad": "index"}, [None]])
def test_catalog_ignores_malformed_legacy_runs_but_selected_bad_model_fails_explicitly(project, entries):
    from workbench.services.native_prediction_apply import load_saved_forest, saved_forest_choices

    _, root, _, options, _, _ = project
    legacy = root / "runs" / "legacy"
    legacy.mkdir()
    write_json(legacy / "artifacts_index.json", {"schema_version": 1, "artifacts": entries})
    choices = saved_forest_choices(root)
    assert len(choices) == 1 and choices[0]["sha256"] == options["model_sha256"]
    with pytest.raises(ValueError, match="FOREST_APPLY_MODEL_INVALID"):
        load_saved_forest(root, {**options, "model_run_id": "legacy"})


@pytest.mark.parametrize("change", ["digest", "wrong_run", "raw_tree", "column_collision", "missing_column"])
def test_preview_rejects_invalid_saved_model_or_new_data_before_mutation(project, change):
    client, root, run_id, options, _, _ = project
    options = deepcopy(options)
    if change == "digest":
        options["model_sha256"] = "0" * 64
    elif change == "wrong_run":
        options["model_run_id"] = run_id
    elif change == "raw_tree":
        options["prediction_basis"] = {"trees": []}
    elif change == "column_collision":
        options["prediction_column"] = "x"
    else:
        path = root / "runs" / run_id / "data.csv"
        data = pd.read_csv(path).drop(columns="x")
        data.to_csv(path, index=False)
    before = set((root / "workbench" / "proposals").iterdir())
    response = client.post("/operations/run", params={"project_root": str(root)},
                           json=_request(run_id, "invalid", APPLY, options))
    assert response.status_code == 422, response.text
    assert set((root / "workbench" / "proposals").iterdir()) == before
    assert not (root / "runs" / run_id / "derived").exists()


@pytest.mark.parametrize("change", ["bytes", "graph", "node_index", "duplicate"])
@pytest.mark.parametrize("project", [TRAIN, CLASSIFY], indirect=True)
def test_confirmation_rechecks_saved_model_identity(project, change):
    client, root, run_id, options, _, artifact = project
    params = {"project_root": str(root)}
    preview = client.post("/operations/run", params=params,
                          json=_request(run_id, "stale-model", APPLY, options)).json()
    assert preview["status"] == "awaiting_confirmation"
    model_run = root / "runs" / options["model_run_id"]
    node_id = "native-result:" + artifact["artifact_id"]
    if change == "bytes":
        path = model_run / artifact["path"]
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "graph":
        path = model_run / "graph.json"
        graph = read_json(path)
        graph["nodes"][node_id]["payload_ref"] = "data.csv"
        write_json(path, graph)
    elif change == "node_index":
        path = model_run / "node_index.json"
        index = read_json(path)
        index[node_id]["node_hash"] = "0" * 64
        write_json(path, index)
    else:
        path = model_run / "artifacts_index.json"
        index = read_json(path)
        index["artifacts"].append(artifact)
        write_json(path, index)
    confirmation = client.post("/operations/run", params=params, json={
        "mode": "confirm", **{key: preview[key] for key in ("request_id", "preview_id", "fingerprint")},
    })
    assert confirmation.status_code == 409, confirmation.text
    assert "FOREST_APPLY_MODEL_INVALID" in confirmation.text
    assert not (root / "runs" / run_id / "derived").exists()


def test_same_run_prediction_lineage_connects_model_and_data(project):
    client, root, _, options, _, artifact = project
    run_id = options["model_run_id"]
    outcome = _confirm(client, root, _request(run_id, "same-run", APPLY, options))
    node_id = outcome["steps"][0]["node_refs"][0]["node_id"]
    graph = GraphStore(root / "runs").read(run_id)
    assert {edge.source_id for edge in graph.edges.values() if edge.target_id == node_id} == {
        "stage:source", "native-result:" + artifact["artifact_id"],
    }


def test_scored_dataset_is_available_to_the_next_workflow_step(project):
    client, root, run_id, options, _, _ = project
    body = _request(run_id, "apply-and-summarize", APPLY, options)
    body["steps"].append({"step_id": "summary", "operation_id": "statistical.explore", "depends_on": ["apply"],
                          "spec": {"operation": "summarize", "selected_columns": ["forecast"],
                                   "source": {"from_step": "apply", "output": "produced_dataset"}}})
    outcome = _confirm(client, root, body)
    assert [step["status"] for step in outcome["steps"]] == ["completed", "completed"]


@pytest.mark.parametrize("project", [TRAIN, CLASSIFY], indirect=True)
def test_each_execution_parses_the_model_and_converts_each_batch_only_once(project, monkeypatch):
    from workbench import native_prediction_apply as kernel
    from workbench.services import native_prediction_apply as service

    _, root, _, options, new_data, _ = project
    packed, converted = [], []
    original_pack, original_numeric = service.forest_buffer, kernel._numeric

    def pack(*args):
        packed.append(True)
        return original_pack(*args)

    def numeric(series):
        converted.append((series.name, len(series)))
        return original_numeric(series)

    monkeypatch.setattr(service, "forest_buffer", pack)
    monkeypatch.setattr(kernel, "forest_buffer", pack)
    monkeypatch.setattr(kernel, "_numeric", numeric)
    # More than one C++ batch, but each value is converted only once per boundary.
    data = pd.concat([new_data] * 3000, ignore_index=True)
    service.preview_saved_forest(root, data, options)
    assert len(packed) == 1 and sum(size for _, size in converted) == len(data) * 2
    packed.clear()
    converted.clear()
    execution = service.execute_saved_forest(root, data, {"options": options})
    assert len(execution.output_frame) == len(data)
    assert len(packed) == 1 and sum(size for _, size in converted) == len(data) * 2
    assert max(size for _, size in converted) <= 4096


@pytest.mark.parametrize("mode", ["ask", "auto"])
@pytest.mark.parametrize("project", [TRAIN, CLASSIFY], indirect=True)
def test_offline_agent_uses_the_same_saved_model_and_shared_permission_path(project, monkeypatch, mode):
    import socket

    from tests.test_agent_routes import _config
    from tests.test_data_column_cast import _register_source_node_identity
    from workbench.agent.context_tools import InspectNodeContextRequest, NodeOperationContextProvider
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.operations import OperationRecordStore
    from workbench.agent.runtime_adapter import headless_runtime_scope
    from workbench.app import app

    _, root, run_id, options, _, model_artifact = project
    _register_source_node_identity(root, run_id)
    context = NodeOperationContextProvider(root).inspect_node_context(InspectNodeContextRequest(
        request_id="score-source", owner_run_id=run_id, op_node_id="stage:source", active_head_run_id=run_id,
    ))
    requests = []
    spec = _request(run_id, "unused", APPLY, options)["steps"][0]["spec"]

    class ScriptedModel:
        async def stream(self, request):
            requests.append(request)
            if mode == "auto" and len(requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "plan", "tool_id": "update_plan", "arguments": {
                        "question": "Score new data with the saved forest.", "criteria": ["Save predictions."],
                        "steps": [{"step_id": "score", "title": "Apply saved forest", "operation_ids": [APPLY]}],
                    },
                })
            elif len(requests) == (2 if mode == "auto" else 1):
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "score", "tool_id": "run_operation", "arguments": {
                        "operation_id": "operation.multi_step", "operation_version": "v1",
                        "target": {"run_id": run_id, "node_ref": "stage:source", "artifact_id": "source_data"},
                        "preconditions": {key: context[key] for key in (
                            "context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")},
                        "changes": {"steps": [{"step_id": "score", "operation_id": APPLY, "spec": spec}]},
                        "evidence_refs": ["registered model and source"], "expected_effect": ["Save new predictions."], "risks": [],
                    },
                })
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "The scored dataset is saved.")
                yield ModelStreamEvent.done(request.request_id)
                return
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("offline replay connected to network"))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a, **k: pytest.fail("offline replay connected to network"))
    with headless_runtime_scope(adapter_factory=lambda config: ScriptedModel(), config=_config()):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            params = {"project_root": str(root)}
            created = client.post("/agent/sessions", params=params, json={
                "role": "chain", "chain_id": f"run:{run_id}", "run_id": run_id, "context_packet": {},
                "focus": {"kind": "node", "id": "stage:source", "run_id": run_id, "label": "New data"},
            })
            assert created.status_code == 200, created.text
            path = "/agent/sessions/" + created.json()["session_id"]
            response = client.post(path + "/turns", params=params, json={
                "question": "Score new data with the saved forest.", "execution_policy": "proposal_only", "execution_mode": mode,
            })
            assert response.status_code == 200, response.text
            assert not (root / "runs" / run_id / "derived").exists()
            if mode == "auto":
                plan = client.get(path + "/plan", params=params).json()["plan"]
                approved = client.post(path + "/plan/approve", params=params, json={"version": plan["version"]})
                assert approved.status_code == 200, approved.text
            else:
                proposals = client.get(path + "/proposals", params=params).json()["proposals"]
                [proposal] = [item for item in proposals if item["status"] == "pending"]
                confirmed = client.post(path + f"/proposals/{proposal['proposal_id']}/confirm", params=params, json={
                    "revision": proposal["revision"], "fingerprint": proposal["fingerprint"], "active_head_run_id": run_id,
                })
                assert confirmed.status_code == 200, confirmed.text
                assert confirmed.json()["operation"]["status"] == "completed", confirmed.text
            continued = client.post(path + "/continue", params=params, json={"execution_mode": mode})
            assert continued.status_code == 200, continued.text
    records = [record for record in OperationRecordStore(root / "workbench", create=False).list_records()
               if record.actor_type == ("user" if mode == "ask" else "approved_plan")]
    assert len(records) == 1 and records[0].status == "completed"
    assert "prediction_basis" not in json.dumps(records[0].outputs)
    assert "trees" not in json.dumps(records[0].outputs)
    assert all("prediction_basis" not in json.dumps(request.messages) for request in requests)
    index = read_json(root / "runs" / run_id / "artifacts_index.json")["artifacts"]
    [data] = [item for item in index if item["artifact_type"] == "derived_data"]
    expected = ["z", "x", "label", "forecast"]
    if model_artifact["step"] == CLASSIFY:
        expected.append("probability")
    assert pd.read_csv(root / "runs" / run_id / data["path"]).columns.tolist() == expected
