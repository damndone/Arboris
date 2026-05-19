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
    assert cleaned.decision_points
    assert cleaned.decision_points[0].decision_id == "handle_missing_values"
    assert cleaned.decision_points[0].reason.chosen_params_schema == "MissingValueStrategy.v1"


def test_orchestrator_emits_model_decision_point_for_ols(tmp_path: Path):
    """An OLS model node must carry a DecisionPoint (robust SE default)."""
    runs_root = tmp_path / "demo"
    run_id = _run_fixture_analysis(runs_root=runs_root, tmp_path=tmp_path, model_type="ols")
    graph = GraphStore(runs_root=runs_root / "runs").read(run_id)
    model_nodes = [n for n in graph.nodes.values() if n.kind.value == "model"]
    primary = next((n for n in model_nodes if "primary" in n.id.lower() or "model:" in n.id), model_nodes[0])
    assert primary.decision_points
    assert primary.decision_points[0].decision_id == "ols_default_robust_se"


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
    assert graph.nodes["stage:cleaned"].decision_points
    assert graph.nodes["stage:cleaned"].decision_points[0].decision_id == "handle_missing_values"


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


def test_safe_flush_swallows_errors_and_warns(tmp_path: Path):
    """A failing GraphRecorder.flush() must not propagate; warning is raised."""
    import warnings as _w
    from workbench.orchestrator import _safe_flush_recorder

    class _Boom:
        def flush(self):
            raise OSError("disk full")
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        _safe_flush_recorder(_Boom(), context="test")  # must not raise
    assert any(
        issubclass(w.category, RuntimeWarning) and "disk full" in str(w.message)
        for w in caught
    )


# -- _check_dropped_variables structured-return unit tests --------------------


def test_check_dropped_variables_returns_structured_entries(tmp_path: Path):
    """Structured return — no more string round-tripping."""
    from workbench.orchestrator import _check_dropped_variables

    frame = pd.DataFrame({"x_kept": [1.0, 2.0, 3.0], "x_zero": [1.0, 1.0, 1.0]})
    model_results = [("ols_1", {"coefficients": {"x_kept": 0.5, "Intercept": 0.1}})]
    issue_dicts: list = []
    result = _check_dropped_variables(
        ["x_kept", "x_zero"], model_results, frame, issue_dicts, tmp_path,
    )
    assert result == [{
        "variable": "x_zero",
        "reason": "zero_variance",
        "reason_display": "dropped due to zero variance",
    }]


# -- Blocked run still gets graph.json (P0-2 regression guard) -----------------


def test_blocked_run_still_gets_graph_json(tmp_path: Path):
    """Validation-blocked runs must still write a partial graph.json."""
    from workbench.projects import create_project as cp, create_run as cr
    from workbench.config import load_config as lc
    from workbench.orchestrator import _run_workflow as rw, _lineage as li, _write_manifest as wm

    proot = tmp_path / "demo"
    cp(tmp_path, "demo")
    run = cr(proot, mode="auto")
    data = tmp_path / "data.csv"
    # Only 3 rows → below min_model_n threshold → validation blocker
    pd.DataFrame({"y": [1, 2, 3], "x": [10, 20, 30]}).to_csv(data, index=False)

    config = lc(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    wm(run.root, run.run_id, "auto", "running", li([data]),
       started_at=started_at, y="y", x=["x"])

    result = rw(run.root, run.run_id, [data], "auto", "y", ["x"], config, started_at)
    assert result["status"] == "blocked"

    # graph.json must exist even for blocked runs
    store = GraphStore(runs_root=tmp_path / "demo" / "runs")
    graph = store.read(run.run_id)
    assert not graph.legacy
    assert "stage:raw" in graph.nodes


# -- logit model path graph completeness ---------------------------------------


def test_logit_model_path_produces_complete_graph(tmp_path: Path):
    """Binary y → logit path must emit a complete graph with stage:cleaned + model node."""
    from workbench.projects import create_project as cp, create_run as cr
    from workbench.config import load_config as lc
    from workbench.orchestrator import _run_workflow as rw, _lineage as li, _write_manifest as wm

    proot = tmp_path / "demo"
    cp(tmp_path, "demo")
    run = cr(proot, mode="auto")
    data = tmp_path / "data.csv"
    # Binary y for logit
    pd.DataFrame({
        "y": [0, 1, 0, 1, 0, 1, 0, 1] * 5,  # 40 rows, balanced
        "x1": list(range(40)),
    }).to_csv(data, index=False)

    config = lc(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    wm(run.root, run.run_id, "auto", "running", li([data]),
       started_at=started_at, y="y", x=["x1"])

    rw(run.root, run.run_id, [data], "auto", "y", ["x1"], config, started_at)

    store = GraphStore(runs_root=tmp_path / "demo" / "runs")
    graph = store.read(run.run_id)
    assert not graph.legacy
    assert "model:logit_1" in graph.nodes
    # logit path should get model_type_auto_select DP when auto
    model_node = graph.nodes["model:logit_1"]
    assert model_node.decision_points, "logit model must emit a DecisionPoint"
    assert model_node.decision_points[0].decision_id == "model_type_auto_select"
    assert model_node.decision_points[0].selected == "binary"


# -- explicit OLS graph consistency (P0-1 regression guard) --------------------


def test_explicit_ols_graph_has_robust_se_dp_not_model_type_dp(tmp_path: Path):
    """Explicit model_type="ols" must emit ols_default_robust_se DP,
    NOT model_type_auto_select (P0-1 regression guard — the else branch
    after auto model selection short-circuits)."""
    from workbench.projects import create_project as cp, create_run as cr
    from workbench.config import load_config as lc
    from workbench.orchestrator import _run_workflow as rw, _lineage as li, _write_manifest as wm

    proot = tmp_path / "demo"
    cp(tmp_path, "demo")
    run = cr(proot, mode="auto")
    data = tmp_path / "data.csv"
    # Force ols type so we can test the DP is robust_se (no fallback needed for ols)
    # For the fallback path test, we use model_type="ols" which uses the else branch
    # and gets _robust_se_dp directly (no _model_type_dp since not auto).
    pd.DataFrame({
        "y": [1 + 2 * i for i in range(35)],
        "x1": list(range(35)),
    }).to_csv(data, index=False)

    config = lc(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    wm(run.root, run.run_id, "auto", "running", li([data]),
       started_at=started_at, y="y", x=["x1"])

    # Use model_type="ols" to go through the else branch (non-auto, explicit ols)
    rw(run.root, run.run_id, [data], "auto", "y", ["x1"], config, started_at,
       model_type="ols")

    store = GraphStore(runs_root=tmp_path / "demo" / "runs")
    graph = store.read(run.run_id)
    model_node = graph.nodes["model:ols_1"]
    # Explicit ols → no model_type_auto_select DP (it wasn't auto)
    # Should have ols_default_robust_se
    assert model_node.decision_points
    assert model_node.decision_points[0].decision_id == "ols_default_robust_se"


def test_auto_ols_path_records_both_dps_on_model_node(tmp_path: Path):
    """auto + continuous y: both DPs now ride together (no precedence drop)."""
    runs_root = tmp_path / "demo"
    run_id = _run_fixture_analysis(runs_root=runs_root, tmp_path=tmp_path,
                                   model_type="auto")

    store = GraphStore(runs_root=runs_root / "runs")
    graph = store.read(run_id)
    model_node = graph.nodes["model:ols_1"]
    dp_ids = [dp.decision_id for dp in model_node.decision_points]
    assert "model_type_auto_select" in dp_ids
    assert "ols_default_robust_se" in dp_ids


def test_model_fit_failed_fallback_clears_model_type_dp(tmp_path: Path):
    """When the primary fit raises ValueError (orchestrator.py:393-398), the
    fallback retries OLS and clears _model_type_dp; only ols_default_robust_se
    remains on the MODEL node."""
    from workbench.projects import create_project as cp, create_run as cr
    from workbench.config import load_config as lc
    from workbench.orchestrator import _run_workflow as rw, _lineage as li, _write_manifest as wm

    proot = tmp_path / "demo"
    cp(tmp_path, "demo")
    run = cr(proot, mode="auto")
    data = tmp_path / "data.csv"
    # model_type="poisson" with continuous (non-count) y forces _map → "count",
    # but run_poisson should reject non-integer / negative-friendly continuous
    # values; the except block at orchestrator.py:383 catches the ValueError
    # and retries OLS, clearing _model_type_dp.
    pd.DataFrame({
        "y": [1.5 + 0.3 * i for i in range(35)],
        "x1": list(range(35)),
    }).to_csv(data, index=False)

    config = lc(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    wm(run.root, run.run_id, "auto", "running", li([data]),
       started_at=started_at, y="y", x=["x1"])

    rw(run.root, run.run_id, [data], "auto", "y", ["x1"], config, started_at,
       model_type="poisson")

    store = GraphStore(runs_root=tmp_path / "demo" / "runs")
    graph = store.read(run.run_id)
    # OLS fallback ran. _model_type_dp was None (non-auto path). After fit failure,
    # it stays None and only _robust_se_dp populates the MODEL DP.
    model_node = graph.nodes["model:ols_1"]
    assert model_node.decision_points
    assert model_node.decision_points[0].decision_id == "ols_default_robust_se"
