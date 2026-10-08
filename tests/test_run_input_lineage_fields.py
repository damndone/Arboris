"""run_inputs keeps two lineage records apart (v1.8.12).

``rerun_from`` is node provenance: the node a rerun was requested from, with
the context it was validated against (RunRerunFrom). ``dataset_source`` is the
dataset bridge of a model started from a data-operation node: which run,
node and artifact its input data was materialized from. Before v1.8.12 both
were written under ``rerun_from``, so script export read a rerun's provenance
as a dataset bridge (KeyError 'source_run_id') and the forest served bridges
as rerun provenance.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_rerun_endpoint import _context_fingerprint, _write_node_index
from tests.test_script_export_lineage_builder import data_path, finished, model_path  # noqa: F401 (fixtures)
from workbench.app import app
from workbench.artifacts import read_json
from workbench.script_export.builder import build_script_plan


def _inputs(project: Path, run_id: str) -> dict:
    return read_json(project / "runs" / run_id / "run_inputs.json")


def _head(project: Path, run_id: str) -> dict:
    with TestClient(app) as client:
        body = client.get("/graph", params={"project_root": str(project)}).json()
    return next(head for head in body["heads"] if head["run_id"] == run_id)


def test_a_data_operation_model_run_records_its_dataset_source_not_rerun_provenance(model_path) -> None:
    project, model_run, data = model_path
    inputs = _inputs(project, model_run)

    assert "rerun_from" not in inputs
    assert inputs["dataset_source"]["source_artifact_id"] == data[3].artifact_id
    assert _head(project, model_run)["rerun_from"] is None
    assert [step.operation for step in build_script_plan(project, model_run, "model:ols_1").plan.steps][-1] == "model.ols"


def test_a_run_that_stored_its_dataset_bridge_under_rerun_from_still_exports(model_path, tmp_path) -> None:
    project, model_run, _ = model_path
    copy = tmp_path / "legacy"
    shutil.copytree(project, copy)
    path = copy / "runs" / model_run / "run_inputs.json"
    inputs = json.loads(path.read_text(encoding="utf-8"))
    inputs["rerun_from"] = inputs.pop("dataset_source")
    path.write_text(json.dumps(inputs), encoding="utf-8")

    legacy = build_script_plan(copy, model_run, "model:ols_1").plan.to_dict()

    assert legacy["steps"] == build_script_plan(project, model_run, "model:ols_1").plan.to_dict()["steps"]
    # A dataset bridge is not rerun provenance and is not served as one.
    assert _head(copy, model_run)["rerun_from"] is None


def test_a_context_rerun_child_exports_its_own_executed_path(data_path, tmp_path) -> None:
    project, run_id, _, _ = data_path
    copy = tmp_path / "rerun"
    shutil.copytree(project, copy)
    _write_node_index(copy, run_id, "model:ols_1", "hash_parent_model")
    fingerprint = _context_fingerprint(
        copy,
        owner_run_id=run_id,
        op_node_id="model:ols_1",
        node_hash="hash_parent_model",
        forest_node_key="hash_parent_model",
        owner_resolution="active_head_contains_node",
        active_head_run_id=run_id,
    )
    with TestClient(app) as client:
        response = client.post(
            f"/runs/{run_id}/rerun",
            params={"project_root": str(copy)},
            json={
                "request_id": "req_export",
                "operation": "rerun",
                "context_version": "node-operation-context/v1",
                "context_fingerprint": fingerprint,
                "owner_run_id": run_id,
                "op_node_id": "model:ols_1",
                "node_hash": "hash_parent_model",
                "forest_node_key": "hash_parent_model",
                "owner_resolution": "active_head_contains_node",
                "active_head_run_id": run_id,
                "op_overrides": {"covariance": "unadjusted"},
            },
        )
        assert response.status_code == 200, response.text
        child = response.json()["run_id"]
        finished(client, copy, child)
        targets = client.get(
            f"/runs/{child}/script-export/targets",
            params={"project_root": str(copy), "model_target": "model:ols_1"},
        )

    assert targets.status_code == 200, targets.text
    built = build_script_plan(copy, child, "model:ols_1")
    assert [source.format for source in built.plan.sources] == ["dta"]
    assert built.plan.steps[-1].parameters["covariance"] == "unadjusted"
    assert _head(copy, child)["rerun_from"]["rerun_request_id"] == "req_export"


def test_partial_rerun_records_are_not_served_as_provenance(model_path, tmp_path) -> None:
    project, model_run, _ = model_path
    copy = tmp_path / "partial"
    shutil.copytree(project, copy)
    path = copy / "runs" / model_run / "run_inputs.json"
    inputs = json.loads(path.read_text(encoding="utf-8"))
    # The shape Agent-confirmed reruns wrote before v1.8.12: no context
    # fingerprint and no request id, so Compare with source cannot revalidate it.
    inputs["rerun_from"] = {"owner_run_id": "run-x", "op_node_id": "model:ols_1", "node_hash": "h", "forest_node_key": "h"}
    path.write_text(json.dumps(inputs), encoding="utf-8")

    assert _head(copy, model_run)["rerun_from"] is None
