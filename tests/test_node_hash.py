from pathlib import Path
import json

from workbench.graph_recorder import GraphRecorder
from workbench.graph_store import GraphStore
from workbench.lineage.hashing import node_hash, PIPELINE_VERSION


def test_parent_order_irrelevant():
    a = node_hash(["h1", "h2"], {"k": 1}, PIPELINE_VERSION)
    b = node_hash(["h2", "h1"], {"k": 1}, PIPELINE_VERSION)
    assert a == b


def test_op_spec_change_changes_hash():
    a = node_hash(["h1"], {"model_type": "ols"}, PIPELINE_VERSION)
    b = node_hash(["h1"], {"model_type": "iv_2sls"}, PIPELINE_VERSION)
    assert a != b


def test_seed_change_changes_hash():
    a = node_hash(["h1"], {"random_seed": 1}, PIPELINE_VERSION)
    b = node_hash(["h1"], {"random_seed": 2}, PIPELINE_VERSION)
    assert a != b


def test_pipeline_version_change_changes_hash():
    a = node_hash(["h1"], {"k": 1}, "v1.6.0-pipeline-1")
    b = node_hash(["h1"], {"k": 1}, "v9.9.9-pipeline-9")
    assert a != b


def test_runid_time_not_in_op_spec_path():
    a = node_hash(["h1"], {"model_type": "ols"}, PIPELINE_VERSION)
    b = node_hash(["h1"], {"model_type": "ols"}, PIPELINE_VERSION)
    assert a == b


def test_graph_node_hash_survives_recorder_and_store_roundtrip(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="identity-run", store=store)
    recorder.record_stage(
        node_id="stage:dataset",
        display_label="Dataset",
        node_hash="sha256:dataset-identity",
    )
    recorder.flush()

    graph = store.read("identity-run")
    assert graph.nodes["stage:dataset"].node_hash == "sha256:dataset-identity"


def test_legacy_graph_without_node_hash_remains_readable(tmp_path: Path):
    run_root = tmp_path / "legacy-run"
    run_root.mkdir()
    (run_root / "graph.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "run_id": "legacy-run",
                "nodes": {
                    "stage:raw": {
                        "id": "stage:raw",
                        "kind": "dataset_stage",
                        "display_label": "Raw",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "parent_stage_id": None,
                        "branch_id": "main",
                    }
                },
                "edges": {},
                "branches": {},
            }
        ),
        encoding="utf-8",
    )

    graph = GraphStore(runs_root=tmp_path).read("legacy-run")
    assert graph.nodes["stage:raw"].node_hash is None
