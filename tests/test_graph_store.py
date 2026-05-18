"""Unit tests for backend/workbench/graph_store.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.graph_model import (
    AutoChosenReason,
    BranchRef,
    Contestability,
    DecisionPoint,
    Edge,
    Graph,
    Node,
    NodeKind,
    Trust,
)
from workbench.graph_store import (
    GraphSerializationError,
    GraphStore,
    graph_from_json,
    graph_to_json,
)


def _sample_graph() -> Graph:
    dp = DecisionPoint(
        decision_id="model_type_auto_select",
        selected="logit",
        candidates=("ols", "logit", "poisson"),
        source="data_driven_default",
        contestability=Contestability(
            assumption_checks_needed=("variable_role_inference",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation="y is binary",
            chosen_params={"y_unique": 2, "y_dtype": "int64"},
        ),
    )
    node_raw = Node(
        id="stage:raw",
        kind=NodeKind.DATASET_STAGE,
        display_label="Raw data",
        created_at="2026-05-13T10:23:00+00:00",
        parent_stage_id=None,
        branch_id="main",
    )
    node_model = Node(
        id="model:primary",
        kind=NodeKind.MODEL,
        display_label="logit primary",
        created_at="2026-05-13T10:25:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        trust=Trust.CAUTION,
        trust_reason="auto-selected model type",
        decision_point=dp,
    )
    edge = Edge(
        id="e1",
        source_id="stage:raw",
        target_id="model:primary",
        op="logit.fit",
        params={},
    )
    return Graph(
        schema_version=1,
        run_id="run_test",
        nodes={node_raw.id: node_raw, node_model.id: node_model},
        edges={edge.id: edge},
        branches={
            "main": BranchRef(id="main", forked_from_node_id=None, head_node_ids=(node_model.id,)),
        },
    )


def test_roundtrip_preserves_full_graph():
    g = _sample_graph()
    data = graph_to_json(g)
    rebuilt = graph_from_json(data)
    assert rebuilt == g


def test_to_json_produces_serializable_dict():
    g = _sample_graph()
    data = graph_to_json(g)
    # Must be JSON-encodable as-is
    encoded = json.dumps(data)
    assert "model_type_auto_select" in encoded
    assert "logit" in encoded


def test_to_json_rejects_non_json_safe_payload():
    """A non-serializable chosen_params value must surface as GraphSerializationError."""
    class _NotJsonSafe:
        pass

    bad_dp = DecisionPoint(
        decision_id="bad",
        reason=AutoChosenReason(
            reason_type="system_default",
            chosen_params={"obj": _NotJsonSafe()},
        ),
    )
    node = Node(
        id="x",
        kind=NodeKind.VARIABLE,
        display_label="x",
        created_at="2026-05-13T10:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        decision_point=bad_dp,
    )
    g = Graph(
        schema_version=1, run_id="run_bad",
        nodes={node.id: node}, edges={}, branches={},
    )
    with pytest.raises(GraphSerializationError, match="not JSON-serializable"):
        graph_to_json(g)


def test_store_write_then_read(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    g = _sample_graph()
    run_dir = tmp_path / "run_test"
    run_dir.mkdir()
    store.write(g)
    loaded = store.read("run_test")
    assert loaded == g


def test_store_read_missing_returns_legacy_empty(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_old"
    run_dir.mkdir()
    loaded = store.read("run_old")
    assert loaded.legacy is True
    assert loaded.nodes == {}
    assert loaded.edges == {}


def test_store_atomic_write_no_partial_on_crash(tmp_path: Path, monkeypatch):
    """Simulate a crash mid-write: original file must remain untouched."""
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_crash"
    run_dir.mkdir()

    g1 = _sample_graph()
    object.__setattr__(g1, "run_id", "run_crash")
    store.write(g1)
    assert store.read("run_crash").run_id == "run_crash"

    # Now write a second graph but intercept os.replace to raise mid-write
    import os
    real_replace = os.replace

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)

    g2 = _sample_graph()
    object.__setattr__(g2, "run_id", "run_crash")
    # Tweak something visible so we can detect partial write
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.write(g2)

    # Original file must be intact (we still read the first write's content)
    loaded = store.read("run_crash")
    assert loaded.run_id == "run_crash"
    assert "stage:raw" in loaded.nodes


def test_store_mutate_returns_post_mutation_graph(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_mut"
    run_dir.mkdir()

    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_mut")
    store.write(g)

    def archive_main_branch(graph: Graph) -> Graph:
        new_branches = dict(graph.branches)
        old = new_branches["main"]
        new_branches["main"] = BranchRef(
            id=old.id,
            forked_from_node_id=old.forked_from_node_id,
            head_node_ids=old.head_node_ids,
            archived=True,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes=graph.nodes,
            edges=graph.edges,
            branches=new_branches,
            legacy=graph.legacy,
        )

    result = store.mutate("run_mut", archive_main_branch)
    assert result.branches["main"].archived is True
    assert store.read("run_mut").branches["main"].archived is True
