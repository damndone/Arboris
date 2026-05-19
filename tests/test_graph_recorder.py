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
        contestability=Contestability.derive(
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
        decision_points=(dp,),
        trust=Trust.CAUTION,
        trust_reason="auto-selected model type",
    )
    recorder.flush()
    g = store.read("run_test")
    n = g.nodes["model:primary"]
    assert n.kind == NodeKind.MODEL
    assert n.decision_points
    assert n.decision_points[0].selected == "logit"


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


def test_record_edge_rejects_missing_target_id(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    with pytest.raises(ValueError, match="target_id 'missing' not in graph"):
        recorder.record_edge(
            edge_id="e1",
            source_id="stage:raw",
            target_id="missing",
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


# -- DecisionPoint factory tests ----------------------------------------------

from workbench.graph_decision_factory import (
    auto_coerce_to_numeric,
    categorical_auto_dummy,
    handle_missing_values,
    model_type_auto_select,
    ols_default_robust_se,
    variable_silently_dropped,
)


def test_factory_model_type_auto_select_shape():
    dp = model_type_auto_select(selected="logit", y_unique=2, y_dtype="int64")
    assert dp.decision_id == "model_type_auto_select"
    assert dp.candidates == ("ols", "logit", "poisson")
    assert dp.source == "data_driven_default"
    assert dp.reason is not None
    assert dp.reason.chosen_params["y_unique"] == 2


def test_factory_categorical_auto_dummy_shape():
    dp = categorical_auto_dummy(variable="region", n_unique=4, reference_level="north")
    assert dp.decision_id == "categorical_auto_dummy"
    assert dp.reason.chosen_params["reference_level"] == "north"


def test_factory_ols_default_robust_se_shape():
    dp = ols_default_robust_se()
    assert dp.decision_id == "ols_default_robust_se"
    assert dp.candidates == ()  # not enumerated
    assert dp.source == "system_default"
    assert dp.contestability.assumption_checks_needed == ("breusch_pagan", "white_test")


def test_factory_auto_coerce_to_numeric_shape():
    dp = auto_coerce_to_numeric(variable="rating", conversion_rate=1.0)
    assert dp.decision_id == "auto_coerce_to_numeric"
    assert dp.reason.chosen_params["conversion_rate"] == 1.0


def test_factory_handle_missing_values_shape():
    dp = handle_missing_values(variables=["y", "x1", "x2"])
    assert dp.decision_id == "handle_missing_values"
    assert len(dp.candidates) == 18
    assert dp.reason.chosen_params_schema == "MissingValueStrategy.v1"
    assert dp.reason.chosen_params["method"] == "drop_rows_with_missing_required_fields"


def test_factory_variable_silently_dropped_shape():
    dp = variable_silently_dropped(
        variable="edu_level",
        drop_reason="zero_variance",
        n_unique_after_cleaning=1,
    )
    assert dp.decision_id == "variable_silently_dropped"
    assert dp.contestability.assumption_checks_needed == ()
    assert dp.reason.chosen_params["drop_reason"] == "zero_variance"


# -- Edge cases ----------------------------------------------------------------


def test_record_report_adds_report_node(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_report(
        node_id="report:html",
        display_label="HTML report",
        payload_ref="reports/report.html",
        trust=Trust.OK,
    )
    recorder.flush()
    g = store.read("run_test")
    assert "report:html" in g.nodes
    assert g.nodes["report:html"].kind == NodeKind.REPORT
    assert g.nodes["report:html"].payload_ref == "reports/report.html"


def test_duplicate_node_id_raises(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    with pytest.raises(ValueError, match="duplicate node id"):
        recorder.record_stage(node_id="stage:raw", display_label="Raw again")


def test_flush_with_no_model_or_report_uses_leaves_as_head(tmp_path: Path):
    """When there are only stages, head = topological leaves (no outgoing edges)."""
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    recorder.record_stage(node_id="stage:cleaned", display_label="Cleaned")
    recorder.record_edge(edge_id="e1", source_id="stage:raw",
                         target_id="stage:cleaned", op="clean")
    recorder.flush()
    g = store.read("run_test")
    heads = g.branches["main"].head_node_ids
    assert heads == ("stage:cleaned",), heads


def test_flush_head_with_multiple_leaves(tmp_path: Path):
    """Multiple leaves all become heads."""
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    recorder.record_stage(node_id="stage:cleanedA", display_label="A")
    recorder.record_stage(node_id="stage:cleanedB", display_label="B")
    recorder.record_edge(edge_id="eA", source_id="stage:raw",
                         target_id="stage:cleanedA", op="x")
    recorder.record_edge(edge_id="eB", source_id="stage:raw",
                         target_id="stage:cleanedB", op="y")
    recorder.flush()
    g = store.read("run_test")
    heads = set(g.branches["main"].head_node_ids)
    assert heads == {"stage:cleanedA", "stage:cleanedB"}


def test_flush_blocked_path_head_is_lone_leaf(tmp_path: Path):
    """Blocked-path early flush with only stage:raw — head is that node."""
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    recorder.flush()
    g = store.read("run_test")
    assert g.branches["main"].head_node_ids == ("stage:raw",)


def test_record_stage_with_trust_and_decision_point(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    dp = DecisionPoint(decision_id="handle_missing_values",
                       selected="drop_rows_with_missing_required_fields")
    recorder.record_stage(
        node_id="stage:cleaned",
        display_label="Cleaned",
        trust=Trust.CAUTION,
        trust_reason="MCAR assumption not verified",
        decision_points=(dp,),
    )
    recorder.flush()
    g = store.read("run_test")
    n = g.nodes["stage:cleaned"]
    assert n.trust == Trust.CAUTION
    assert n.trust_reason == "MCAR assumption not verified"
    assert n.decision_points
    assert n.decision_points[0].decision_id == "handle_missing_values"


def test_record_edge_with_reversible_and_params(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:raw", display_label="Raw")
    recorder.record_stage(node_id="stage:transformed", display_label="Transformed")
    recorder.record_edge(
        edge_id="e_log",
        source_id="stage:raw",
        target_id="stage:transformed",
        op="np.log1p",
        params={"description": "log(1+x) transform"},
        reversible=True,
        inverse_op="np.expm1",
    )
    recorder.flush()
    g = store.read("run_test")
    e = g.edges["e_log"]
    assert e.op == "np.log1p"
    assert e.params == {"description": "log(1+x) transform"}
    assert e.reversible is True
    assert e.inverse_op == "np.expm1"


def test_record_edge_with_none_params_defaults_to_empty_dict(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="a", display_label="A")
    recorder.record_stage(node_id="b", display_label="B")
    recorder.record_edge(edge_id="e", source_id="a", target_id="b", op="link")
    recorder.flush()
    assert store.read("run_test").edges["e"].params == {}


def test_record_variable_without_decision_point(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    recorder = GraphRecorder(run_id="run_test", store=store)
    recorder.record_stage(node_id="stage:cleaned", display_label="Cleaned")
    recorder.record_variable(
        node_id="var:income:cleaned",
        display_label="income (cleaned)",
        parent_stage_id="stage:cleaned",
    )
    recorder.flush()
    v = store.read("run_test").nodes["var:income:cleaned"]
    assert v.kind == NodeKind.VARIABLE
    assert v.decision_points == ()
