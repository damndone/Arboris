"""V1.4.1 §4 — summary field generation per orchestrator-emitted node."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.config import load_config
from workbench.graph_store import GraphStore
from workbench.orchestrator import _lineage, _run_workflow, _write_manifest
from workbench.projects import create_project, create_run


def _run_graph(
    tmp_path: Path,
    frame: pd.DataFrame,
    *,
    y: str = "y",
    x: list[str] | None = None,
    model_type: str = "auto",
):
    proot = tmp_path / "demo"
    create_project(tmp_path, "demo")
    run = create_run(proot, mode="auto")
    data = tmp_path / "data.csv"
    frame.to_csv(data, index=False)
    config = load_config(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    x_vars = x if x is not None else [c for c in frame.columns if c != y]
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([data]), started_at=started_at, y=y, x=x_vars,
    )
    _run_workflow(
        run.root, run.run_id, [data], "auto", y, x_vars,
        config, started_at, model_type=model_type,
    )
    store = GraphStore(runs_root=proot / "runs")
    return store.read(run.run_id)


def test_raw_stage_summary_exact(tmp_path: Path):
    frame = pd.DataFrame({"y": range(35), "x": range(35)})
    graph = _run_graph(tmp_path, frame)
    assert graph.nodes["stage:raw"].summary == "Raw: 35 rows × 2 cols"


def test_cleaned_stage_summary_with_no_drops(tmp_path: Path):
    frame = pd.DataFrame({"y": range(35), "x": range(35)})
    graph = _run_graph(tmp_path, frame)
    assert graph.nodes["stage:cleaned"].summary == "Cleaned: 35 rows"


def test_cleaned_stage_summary_with_drops(tmp_path: Path):
    rows = [{"y": i, "x": i} for i in range(33)]
    frame = pd.DataFrame([*rows, rows[0], rows[1]])
    graph = _run_graph(tmp_path, frame)
    assert graph.nodes["stage:cleaned"].summary == "Cleaned: 33 rows (2 dropped)"


def test_variable_kept_numeric_summary(tmp_path: Path):
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": range(35)})
    graph = _run_graph(tmp_path, frame)
    assert graph.nodes["var:x:cleaned"].summary == "Kept as numeric"


def test_variable_categorical_dummy_summary(tmp_path: Path):
    frame = pd.DataFrame({
        "y": [1 + i for i in range(40)],
        "group_code": ["a", "b"] * 20,
    })
    graph = _run_graph(tmp_path, frame, x=["group_code"])
    assert graph.nodes["var:group_code:cleaned"].summary == \
        "Dummy-encoded (2 levels, ref='a')"


def test_variable_coerced_summary(tmp_path: Path):
    frame = pd.DataFrame({
        "y": [1 + 2 * i for i in range(35)],
        "score": [*[str(10 + i) for i in range(34)], "bad"],
    })
    graph = _run_graph(tmp_path, frame, x=["score"])
    assert graph.nodes["var:score:cleaned"].summary == \
        "Coerced to numeric (97% convertible)"


def test_variable_dropped_summary_uses_reason_display(tmp_path: Path, monkeypatch):
    import workbench.orchestrator as orch

    def fake_dropped(*args, **kwargs):
        return [{
            "variable": "x_zero",
            "reason": "zero_variance",
            "reason_display": "dropped due to zero variance",
        }]

    monkeypatch.setattr(orch, "_check_dropped_variables", fake_dropped)
    frame = pd.DataFrame({
        "y": [1 + 2 * i for i in range(35)],
        "x": range(35),
        "x_zero": [1] * 35,
    })
    graph = _run_graph(tmp_path, frame, x=["x", "x_zero"])
    assert graph.nodes["var:x_zero:dropped"].summary == \
        "Dropped: dropped due to zero variance"


def test_model_ols_summary_has_se_and_n(tmp_path: Path):
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": range(35)})
    graph = _run_graph(tmp_path, frame, model_type="ols")
    assert graph.nodes["model:ols_1"].summary == "OLS (HC1, n=35)"


def test_model_logit_summary_has_n(tmp_path: Path):
    frame = pd.DataFrame({"y": [0, 1] * 20, "x": range(40)})
    graph = _run_graph(tmp_path, frame)
    assert graph.nodes["model:logit_1"].summary == "Logit (n=40)"


def test_model_poisson_summary_has_n(tmp_path: Path):
    frame = pd.DataFrame({
        "event_count": [1, 2, 3, 4, 5] * 8,
        "x": range(40),
    })
    graph = _run_graph(tmp_path, frame, y="event_count", x=["x"])
    assert graph.nodes["model:poisson_1"].summary == "Poisson (n=40)"


def test_model_poisson_rate_summary_has_exposure_and_n(tmp_path: Path):
    rng = np.random.default_rng(42)
    exposure = np.full(40, 12.0)
    x = np.arange(40)
    event_count = rng.poisson(exposure * np.exp(-3.0 + 0.03 * x)).astype(int)
    frame = pd.DataFrame({
        "event_count": event_count,
        "x": x,
        "x2_exposure": exposure,
    })
    graph = _run_graph(tmp_path, frame, y="event_count", x=["x", "x2_exposure"])
    assert graph.nodes["model:poisson_1"].summary == \
        "Poisson rate (exposure=x2_exposure, n=40)"


def test_report_summary(tmp_path: Path):
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": range(35)})
    graph = _run_graph(tmp_path, frame)
    assert graph.nodes["report:html"].summary == "HTML report"
