"""Independent adversarial review of the frozen public script-export foundation."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import threading
import zipfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from evidence_retention import run_dir
from test_script_export_lineage_builder import data_path, model_path, wald_path, finished
from workbench.app import app
from workbench.artifacts import read_json
from workbench.script_export.builder import build_script_plan
from workbench.script_export.plan import ScriptExportRefusal
from workbench.services.script_export import export_analysis_script


def evidence():
    """Created on first record, never at import; bounded by tests/evidence_retention.py."""
    override = os.environ.get("WB_SCRIPT_PUBLIC_REVIEW_EVIDENCE")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return run_dir("script-public-integrity")


def record(name, payload):
    path = evidence() / (name+".json")
    assert not path.exists()
    path.write_text(json.dumps(payload, indent=2, default=str)+"\n")


def clone(model, tmp_path):
    project, run_id, data = model
    destination = tmp_path / "isolated-project"
    shutil.copytree(project, destination)
    result = destination, run_id, (destination, *data[1:])
    assert build_script_plan(destination, run_id, "model:ols_1").plan.steps[-1].operation == "model.ols"
    return result


def reindex_json(root, relative, mutate):
    path = root / relative
    payload = read_json(path)
    mutate(payload)
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    index = read_json(root / "artifacts_index.json")
    matches = [item for item in index["artifacts"] if item["path"] == relative]
    assert len(matches) == 1
    matches[0]["sha256"] = hashlib.sha256(raw).hexdigest()
    (root / "artifacts_index.json").write_text(json.dumps(index))
    return payload


def require_refusal(name, project, run_id, target):
    try:
        result = build_script_plan(project, run_id, target)
    except ScriptExportRefusal as exc:
        record(name, {"refused": True, "code": exc.code, "reason": str(exc)})
        return
    record(name, {"refused": False, "plan": result.plan.to_dict(), "retained_project": project})
    pytest.fail("Altered completed-owner evidence was accepted: "+name)


@pytest.mark.parametrize("delta", [.75, 1e-7])
def test_reindexed_kernel_cannot_replace_completed_model_numbers(model_path, tmp_path, delta):
    project, run_id, _ = clone(model_path, tmp_path)
    root = project / "runs" / run_id
    reindex_json(root, "model_results/inference_kernels/ols_1.json",
                 lambda payload: payload["params"].__setitem__(0, payload["params"][0]+delta))
    require_refusal("kernel_reindexed_"+str(delta), project, run_id, "model:ols_1")


def test_reindexed_feature_and_graph_cannot_change_executed_arithmetic(model_path, tmp_path):
    project, run_id, data = clone(model_path, tmp_path)
    root = project / "runs" / data[1]
    derived = data[3]
    reindex_json(root, derived.recipe_path, lambda payload: payload["parameters"].__setitem__("operator", "add"))
    path = root / "graph.json"
    graph = read_json(path)
    nodes = graph["nodes"]
    node = nodes[derived.child_node_id] if isinstance(nodes, dict) else next(item for item in nodes if item["node_id"] == derived.child_node_id)
    annotation = next(item for item in node["annotations"] if item.get("type") == "data_operation")
    annotation["typed_payload"]["parameters"]["operator"] = "add"
    path.write_text(json.dumps(graph))
    require_refusal("recipe_graph_reindexed", project, run_id, "model:ols_1")


def test_renamed_kernel_parameter_requires_an_actual_result_row(model_path,tmp_path):
    project,run_id,_ = clone(model_path,tmp_path)
    def rename(payload):
        payload['param_names'][0] = 'injected_parameter'
        payload['vcov_param_names'][0] = 'injected_parameter'
        payload['params'][0] += .75
    reindex_json(project/'runs'/run_id,'model_results/inference_kernels/ols_1.json',rename)
    require_refusal('kernel_renamed_parameter',project,run_id,'model:ols_1')


def test_reindexed_wald_cannot_change_hypothesis_behind_durable_fingerprint(wald_path, tmp_path):
    from workbench.postestimation.registry import run_operation
    model, artifact_id = wald_path
    project, run_id, _ = clone(model, tmp_path)
    root = project / "runs" / run_id
    index = read_json(root / "artifacts_index.json")
    relative = next(item["path"] for item in index["artifacts"] if item["artifact_id"] == artifact_id)
    kernel = read_json(root / "model_results/inference_kernels/ols_1.json")
    def change(payload):
        constraints = payload["result"]["constraints"]
        constraints[0]["value"] = 1
        payload["result"].update(run_operation("wald", [kernel], {"constraints": constraints}, {}))
    reindex_json(root, relative, change)
    require_refusal("durable_hypothesis_reindexed", project, run_id, "artifact:"+artifact_id)


def test_same_owner_concurrent_requests_are_idempotent(model_path, tmp_path, monkeypatch):
    import workbench.services.script_export as service
    project, run_id, _ = clone(model_path, tmp_path)
    barrier = threading.Barrier(2)
    original = service.read_server_owned_run_artifacts
    def synchronized_read(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return result
    monkeypatch.setattr(service, "read_server_owned_run_artifacts", synchronized_read)
    def request(_):
        try:
            return export_analysis_script(project, run_id, "model:ols_1", "python")
        except Exception as exc:
            return {"exception": type(exc).__name__, "message": str(exc)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, range(2)))
    record("concurrent_same_owner", {"results": results, "retained_project": project})
    assert all("artifact_id" in result for result in results), results
    assert results[0]["artifact_id"] == results[1]["artifact_id"]


def test_directory_swap_cannot_write_bundle_outside_owner(model_path, tmp_path, monkeypatch):
    import workbench.script_export.storage as service
    project, run_id, _ = clone(model_path, tmp_path)
    outside = tmp_path / "outside-owner"
    outside.mkdir()
    original_open = service.os.open
    swapped = False
    def swap_then_open(path, *args, **kwargs):
        nonlocal swapped
        path = Path(path)
        if not swapped and path.name.startswith("script_export_") and path.suffix == ".zip":
            swapped = True
            path.parent.rename(path.parent.with_name("scripts-before-swap"))
            path.parent.symlink_to(outside, target_is_directory=True)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(service.os, "open", swap_then_open)
    outcome = None
    try:
        outcome = export_analysis_script(project, run_id, "model:ols_1", "python")
    except Exception as exc:
        outcome = {"exception": type(exc).__name__, "message": str(exc)}
    escaped = list(outside.glob("*.zip"))
    record("fd_directory_swap", {"outcome": outcome, "escaped_files": escaped,
                                 "escaped_bytes": [item.stat().st_size for item in escaped], "retained_project": project})
    assert not escaped, "Bundle was written outside the owner before registration refused it"


def test_raw_workbook_extra_sheet_obeys_restricted_column_policy(tmp_path):
    from workbench.egress import policy_path
    from workbench.projects import create_project
    project = create_project(tmp_path, "workbook-policy").root
    source = tmp_path / "public-two-sheet.xlsx"
    rng = np.random.default_rng(810114)
    x = rng.normal(size=80)
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame({"x": x, "y": .3+.5*x+rng.normal(size=80)}).to_excel(writer, sheet_name="analysis", index=False)
        pd.DataFrame({"restricted_marker": ["PUBLIC_SYNTHETIC_RESTRICTED_MARKER"]}).to_excel(writer, sheet_name="unused", index=False)
    with TestClient(app) as client:
        submitted = client.post("/runs", data={"project_root": str(project), "mode": "auto", "model_type": "ols",
            "y": "y", "x": "x", "covariance": "unadjusted", "sheet_name": "analysis"},
            files={"file": (source.name, source.read_bytes(), "application/octet-stream")})
        assert submitted.status_code == 200, submitted.text
        run_id = submitted.json()["run_id"]
        finished(client, project, run_id)
        path = policy_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "providers": {}, "columns": {"restricted_marker": "restricted"}}))
        response = client.post(f"/runs/{run_id}/script-export", params={"project_root": str(project)},
                               json={"target": "model:ols_1", "language": "python"})
        detail = {"http_status": response.status_code, "response": response.json(), "retained_project": project}
        if response.status_code == 200:
            downloaded = client.get(response.json()["download_url"])
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                source_name = next(name for name in archive.namelist() if name.endswith(".xlsx"))
                extra = pd.read_excel(io.BytesIO(archive.read(source_name)), sheet_name="unused")
                detail["restricted_marker_exported"] = extra.iloc[0, 0] == "PUBLIC_SYNTHETIC_RESTRICTED_MARKER"
        record("egress_workbook_extra_sheet", detail)
        assert response.status_code == 403, response.text


@pytest.mark.parametrize("extra", ["expected", "projector", "source_path", "snapshots"])
def test_http_does_not_accept_client_export_provenance(model_path, extra):
    project, run_id, _ = model_path
    with TestClient(app) as client:
        response = client.post(f"/runs/{run_id}/script-export", params={"project_root": str(project)},
            json={"target": "model:ols_1", "language": "python", extra: {"injected": "synthetic"}})
    assert response.status_code == 422


def test_agent_rejects_cross_session_and_returns_only_bounded_metadata(model_path):
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.tools import ToolContext
    project, run_id, _ = model_path
    definition = next(item for item in NodeOperationContextProvider(project).tool_definitions(chain_id="review-chain", session_id="review-session")
                      if item.tool_id == "export_analysis_script")
    request = {"run_id": run_id, "target": "model:ols_1", "language": "python"}
    with pytest.raises(ValueError, match="session"):
        definition.handler(request, ToolContext(session_id="other-session", metadata={"project": str(project), "chain": "review-chain"}))
    result = definition.handler(request, ToolContext(session_id="review-session", metadata={"project": str(project), "chain": "review-chain"}))
    assert not {"text", "expected", "coefficients", "project_root", "parameters", "files"} & set(result)


def test_bound_directory_fd_survives_a_real_ancestor_swap(model_path,tmp_path,monkeypatch):
    from workbench.script_export import storage
    project,run_id,_=clone(model_path,tmp_path)
    outside=tmp_path/'outside-fd';outside.mkdir()
    folder=project/'runs'/run_id/'exports/scripts'
    previous={path.name:path.read_bytes() for path in folder.glob('*.zip')}
    original=storage._directory
    swapped=False
    def open_then_swap(parent,name,**kwargs):
        nonlocal swapped
        fd=original(parent,name,**kwargs)
        if name == 'scripts' and not swapped:
            swapped=True
            folder.rename(folder.with_name('scripts-retained'))
            folder.symlink_to(outside,target_is_directory=True)
        return fd
    monkeypatch.setattr(storage,'_directory',open_then_swap)
    with pytest.raises(ScriptExportRefusal):
        export_analysis_script(project,run_id,'model:ols_1','python')
    assert swapped
    assert list(outside.iterdir()) == []
    retained={path.name:path.read_bytes() for path in folder.with_name('scripts-retained').glob('*.zip')}
    assert len(retained) == len(previous)+1
    assert all(retained[name] == raw for name,raw in previous.items())


def test_concurrent_languages_preserve_both_registered_artifacts(model_path,tmp_path):
    project,run_id,_=clone(model_path,tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs=list(pool.map(lambda language:export_analysis_script(project,run_id,'model:ols_1',language),['python','r']))
    records=read_json(project/'runs'/run_id/'artifacts_index.json')['artifacts']
    ids=[item['artifact_id'] for item in records]
    assert all(ids.count(result['artifact_id']) == 1 for result in outputs)
