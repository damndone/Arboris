"""V1.4.0 end-to-end: assert orchestrator emits expected graph for a known fixture run."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from workbench.config import load_config
from workbench.graph_store import GraphStore
from workbench.orchestrator import _lineage, _run_workflow, _write_manifest
from workbench.projects import create_project, create_run


def _run_fixture_analysis(runs_root: Path, tmp_path: Path, model_type: str = "auto") -> str:
    """Run a full _run_workflow on synthetic data and return the run_id.

    Parameters match the pattern from test_on_step_callback_all_steps.
    """
    proot = runs_root
    create_project(tmp_path, proot.name)
    run = create_run(proot, mode="auto")
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    config = load_config(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([data]),
        started_at=started_at, y="y", x=["x"],
    )

    _run_workflow(
        run.root, run.run_id, [data],
        "auto", "y", ["x"], config, started_at,
        model_type=model_type,
    )
    return run.run_id


def test_orchestrator_emits_graph_with_expected_structure(tmp_path: Path):
    """Run a fixture pipeline end-to-end and verify the graph it produces."""
    runs_root = tmp_path / "demo"
    run_id = _run_fixture_analysis(runs_root=runs_root, tmp_path=tmp_path)

    store = GraphStore(runs_root=runs_root / "runs")
    graph = store.read(run_id)

    # Structural assertions
    assert not graph.legacy
    assert "main" in graph.branches
    assert "stage:raw" in graph.nodes
    assert "stage:cleaned" in graph.nodes
    # At least one model node
    model_nodes = [n for n in graph.nodes.values() if n.kind.value == "model"]
    assert len(model_nodes) >= 1
    # Edge from cleaned to model
    cleaned_to_model = [
        e for e in graph.edges.values()
        if e.source_id == "stage:cleaned" and e.target_id in graph.nodes
        and graph.nodes[e.target_id].kind.value == "model"
    ]
    assert len(cleaned_to_model) >= 1


def test_orchestrator_emits_handle_missing_values_decision_point(tmp_path: Path):
    """Cleaning stage must carry the handle_missing_values DecisionPoint."""
    runs_root = tmp_path / "demo"
    run_id = _run_fixture_analysis(runs_root=runs_root, tmp_path=tmp_path)
    graph = GraphStore(runs_root=runs_root / "runs").read(run_id)
    cleaned = graph.nodes["stage:cleaned"]
    assert cleaned.decision_point is not None
    assert cleaned.decision_point.decision_id == "handle_missing_values"
    assert cleaned.decision_point.reason.chosen_params_schema == "MissingValueStrategy.v1"


def test_orchestrator_emits_model_decision_point_for_ols(tmp_path: Path):
    """An OLS model node must carry a DecisionPoint (robust SE default)."""
    runs_root = tmp_path / "demo"
    run_id = _run_fixture_analysis(runs_root=runs_root, tmp_path=tmp_path, model_type="ols")
    graph = GraphStore(runs_root=runs_root / "runs").read(run_id)
    model_nodes = [n for n in graph.nodes.values() if n.kind.value == "model"]
    primary = next((n for n in model_nodes if "primary" in n.id.lower() or "model:" in n.id), model_nodes[0])
    assert primary.decision_point is not None
    assert primary.decision_point.decision_id == "ols_default_robust_se"


def test_existing_artifacts_still_present_with_graph(tmp_path: Path):
    """Adding the graph must not change other artifacts."""
    runs_root = tmp_path / "demo"
    run_id = _run_fixture_analysis(runs_root=runs_root, tmp_path=tmp_path)
    run_dir = runs_root / "runs" / run_id
    # Spot-check: the existing files we expect still exist
    assert (run_dir / "errors.json").is_file()
    # graph.json is the new artifact
    assert (run_dir / "graph.json").is_file()


def test_orchestrator_graph_complete_after_multi_x_run(tmp_path: Path):
    """Graph is produced correctly with multiple X variables (string + numeric)."""
    runs_root = tmp_path / "demo"
    proot = runs_root
    from workbench.projects import create_project as cp, create_run as cr
    from workbench.config import load_config as lc
    from workbench.orchestrator import _run_workflow as rw, _lineage as li, _write_manifest as wm

    cp(tmp_path, "demo")
    run = cr(proot, mode="auto")
    data = tmp_path / "data.csv"
    rows = []
    for i in range(35):
        rows.append({"y": 1 + 2 * i, "x1": i, "score": str(10 + i) if i != 17 else "N/A"})
    df = pd.DataFrame(rows)
    df["score"] = df["score"].astype("object")
    df.to_csv(data, index=False)

    config = lc(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    wm(run.root, run.run_id, "auto", "running", li([data]),
       started_at=started_at, y="y", x=["x1", "score"])

    rw(run.root, run.run_id, [data], "auto", "y", ["x1", "score"], config, started_at)

    store = GraphStore(runs_root=runs_root / "runs")
    graph = store.read(run.run_id)
    assert not graph.legacy
    assert "stage:cleaned" in graph.nodes
    assert "model:ols_1" in graph.nodes
    assert graph.nodes["stage:cleaned"].decision_point is not None
    assert graph.nodes["stage:cleaned"].decision_point.decision_id == "handle_missing_values"


def test_orchestrator_graph_has_variable_nodes_for_all_x(tmp_path: Path):
    """Every x variable gets a variable node; graph is complete with multi-x fixture."""
    runs_root = tmp_path / "demo"
    proot = runs_root
    from workbench.projects import create_project as cp, create_run as cr
    from workbench.config import load_config as lc
    from workbench.orchestrator import _run_workflow as rw, _lineage as li, _write_manifest as wm

    cp(tmp_path, "demo")
    run = cr(proot, mode="auto")
    data = tmp_path / "data.csv"
    pd.DataFrame({
        "y": [1 + 2 * i for i in range(35)],
        "x1": list(range(35)),
        "x2": [float(i * 3 + 1) for i in range(35)],
    }).to_csv(data, index=False)

    config = lc(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    wm(run.root, run.run_id, "auto", "running", li([data]),
       started_at=started_at, y="y", x=["x1", "x2"])

    rw(run.root, run.run_id, [data], "auto", "y", ["x1", "x2"], config, started_at)

    store = GraphStore(runs_root=runs_root / "runs")
    graph = store.read(run.run_id)
    # All x variables get variable nodes
    var_node_ids = {n.id for n in graph.nodes.values() if n.kind.value == "variable"}
    assert "var:y:cleaned" in var_node_ids
    assert "var:x1:cleaned" in var_node_ids
    assert "var:x2:cleaned" in var_node_ids
    # Model graph is complete
    assert "model:ols_1" in graph.nodes
    assert "report:html" in graph.nodes


# -- _parse_dropped_var_entry unit tests ---------------------------------------

from workbench.orchestrator import _parse_dropped_var_entry


def test_parse_dropped_var_basic():
    assert _parse_dropped_var_entry("x4 (dropped due to zero variance)") == {
        "variable": "x4", "reason": "dropped_due_to_zero_variance",
    }


def test_parse_dropped_var_nested_parens_in_reason():
    """Reason may contain parens (e.g. collinearity → categories may overlap)."""
    entry = "x1 (dropped due to perfect collinearity (categories may overlap with other predictors))"
    result = _parse_dropped_var_entry(entry)
    assert result["variable"] == "x1"
    assert "perfect_collinearity" in result["reason"]
    assert "categories_may_overlap" in result["reason"]


def test_parse_dropped_var_empty_and_no_parens():
    assert _parse_dropped_var_entry("") == {"variable": "", "reason": "unknown"}
    assert _parse_dropped_var_entry("my_var") == {"variable": "my_var", "reason": "unknown"}
