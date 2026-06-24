"""Loop 2A.7 — RecordingStage writes node_index.json (graph node_id -> node_hash).

The bridge that lets 2B dedup shared-prefix graph nodes by node_hash. Decorate-only:
graph.json is byte-untouched (golden 0-drift), node_index.json is a NEW artifact
written only when the incremental cache is active. RecordingStage is never itself
a cached stage."""
import json
from pathlib import Path

from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIX = Path(__file__).parent / "fixtures"


def _run(project_root, src):
    r = run_workflow(project_root, [src], mode="auto", y="wage",
                     x=["education", "experience"], model_type="ols")
    return project_root / "runs" / r["run_id"]


def test_node_index_stamps_graph_nodes(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    run_root = _run(project.root, FIX / "forest_min.csv")

    index = json.loads((run_root / "node_index.json").read_text())
    trace = {t["stage"]: t["node_hash"]
             for t in json.loads((run_root / "incremental_trace.json").read_text())}

    # stage:cleaned carries the cleaning stage-output hash.
    assert index["stage:cleaned"]["node_hash"] == trace["cleaning"]
    assert index["stage:cleaned"]["producing_stage"] == "cleaning"
    assert index["stage:cleaned"]["cas_ref"]["node_hash"] == trace["cleaning"]

    # var:* nodes map to their cleaning stage-output.
    assert index["var:wage:cleaned"]["node_hash"] == trace["cleaning"]

    # model:* carries the estimation hash; report:html the report hash.
    model_keys = [k for k in index if k.startswith("model:")]
    assert model_keys, "no model node in index"
    assert index[model_keys[0]]["node_hash"] == trace["estimation"]
    assert index[model_keys[0]]["producing_stage"] == "estimation"
    assert index["report:html"]["node_hash"] == trace["report"]

    # RecordingStage is NEVER a cached stage.
    assert "recording" not in trace

    # Decorate-only: graph.json nodes are untouched (no node_hash field on them).
    graph = json.loads((run_root / "graph.json").read_text())
    for node in graph["nodes"].values():
        assert "node_hash" not in node


def test_flag_off_writes_no_node_index(tmp_path):
    project = create_project(tmp_path, "demo")
    run_root = _run(project.root, FIX / "forest_min.csv")
    assert not (run_root / "node_index.json").exists()
