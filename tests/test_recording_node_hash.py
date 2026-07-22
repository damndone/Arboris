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


def test_node_index_always_written(tmp_path):
    # v1.6.1: the lineage index is now ALWAYS written (the graph view is the forest,
    # which needs node identity regardless of the incremental-cache flag). graph.json
    # itself still stays decorate-free (node_hash lives only in node_index.json).
    project = create_project(tmp_path, "demo")
    run_root = _run(project.root, FIX / "forest_min.csv")
    assert (run_root / "node_index.json").exists()
    graph = json.loads((run_root / "graph.json").read_text())
    for node in graph["nodes"].values():
        assert "node_hash" not in node  # graph.json unchanged (decorate-only)


def test_node_index_includes_stage_raw_with_upload_hash(tmp_path):
    # v1.6.11: stage:raw carries the Merkle chain root (the upload's content
    # hash). Without it the raw dataset node had no identity, which left Ask AI
    # permanently disabled on raw nodes (missing_node_hash).
    project = create_project(tmp_path, "demo")
    run_root = _run(project.root, FIX / "forest_min.csv")
    idx = json.loads((run_root / "node_index.json").read_text())
    assert "stage:raw" in idx
    entry = idx["stage:raw"]
    assert len(entry["node_hash"]) == 64  # sha256 of the uploaded bytes
    assert entry["producing_stage"] == "ingestion"
    assert entry["cas_ref"]["artifact"].startswith("_uploads")
    # raw identity = chain root; cleaned is a distinct downstream hash
    assert idx["stage:cleaned"]["node_hash"] != entry["node_hash"]


def test_build_node_index_without_upload_hash_omits_stage_raw():
    # Legacy callers (no upload hash) keep the old shape — no phantom raw entry.
    from workbench.lineage.node_index import build_node_index

    idx = build_node_index(
        {"cleaning": "c" * 64}, normalized_y="y", normalized_x=["x1"],
        model_results=[], upload_hash="",
    )
    assert "stage:raw" not in idx
    assert "stage:cleaned" in idx


def test_build_node_index_includes_pack_owned_stage_entries():
    from workbench.lineage.node_index import build_node_index

    extra = {
        "stage:ts-analysis-view": {
            "node_hash": "a" * 64,
            "producing_stage": "arma_garch:analysis-view",
            "cas_ref": {
                "node_hash": "a" * 64,
                "artifact": "artifacts/time_series/ts.analysis_view_manifest.json",
            },
        }
    }
    idx = build_node_index(
        {"cleaning": "c" * 64},
        normalized_y="y",
        normalized_x=[],
        model_results=[],
        extra_entries=extra,
    )

    assert idx["stage:ts-analysis-view"] == extra["stage:ts-analysis-view"]
