"""Unit tests for the GraphRecorder helper used by orchestrator.

These tests exercise the recorder in isolation — they do NOT run the
real orchestrator. Task 5 covers the end-to-end orchestrator path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workbench.graph_model import (
    AutoChosenReason,
    Contestability,
    DecisionPoint,
    NodeKind,
    Trust,
)
from workbench.graph_recorder import GraphRecorder
from workbench.graph_store import GraphStore


def test_recorder_creates_main_branch_on_init(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.flush()
    g = store.read("run_test")
    assert "main" in g.branches
    assert g.branches["main"].forked_from_node_id is None


def test_record_stage_adds_node(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(
        node_id="stage:raw",
        display_label="Raw data",
        payload_ref=None,
    )
    recorder.flush()
    g = store.read("run_test")
    assert "stage:raw" in g.nodes
    assert g.nodes["stage:raw"].kind == NodeKind.DATASET_STAGE


def test_record_model_with_decision_point(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
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
            chosen_params={"y_unique": 2},
        ),
    )
    recorder.record_model(
        node_id="model:primary",
        display_label="logit primary",
        payload_ref="model_results/primary.json",
        decision_point=dp,
        trust=Trust.CAUTION,
        trust_reason="auto-selected model type",
    )
    recorder.flush()
    g = store.read("run_test")
    n = g.nodes["model:primary"]
    assert n.kind == NodeKind.MODEL
    assert n.decision_point is not None
    assert n.decision_point.selected == "logit"


def test_record_edge_connects_nodes(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    recorder.record_stage(node_id="stage:cleaned", display_label="Cleaned")
    recorder.record_edge(
        edge_id="e1",
        source_id="stage:raw",
        target_id="stage:cleaned",
        op="drop_na",
    )
    recorder.flush()
    g = store.read("run_test")
    assert "e1" in g.edges
    assert g.edges["e1"].source_id == "stage:raw"


def test_record_edge_validates_endpoints_exist(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    with pytest.raises(ValueError, match="source_id 'missing' not in graph"):
        recorder.record_edge(
            edge_id="e1",
            source_id="missing",
            target_id="stage:raw",
            op="drop_na",
        )


def test_record_variable_includes_parent_stage(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:cleaned", display_label="Cleaned")
    recorder.record_variable(
        node_id="var:income:cleaned",
        display_label="income (cleaned)",
        parent_stage_id="stage:cleaned",
    )
    recorder.flush()
    g = store.read("run_test")
    v = g.nodes["var:income:cleaned"]
    assert v.kind == NodeKind.VARIABLE
    assert v.parent_stage_id == "stage:cleaned"


def test_flush_updates_main_branch_head(tmp_path: Path):
    """The most-recently-added MODEL or REPORT node is the branch head."""
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    recorder.record_model(node_id="model:primary", display_label="logit")
    recorder.flush()
    g = store.read("run_test")
    assert "model:primary" in g.branches["main"].head_node_ids
