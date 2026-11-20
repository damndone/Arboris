"""Figures are drawn when first read, byte for byte as the run would have drawn them."""
import hashlib
import json
import shutil

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.figure_plans import FIGURE_PLAN, ensure_figures
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path, **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"x1": rng.normal(size=300), "x2": rng.integers(0, 3, 300), "g": rng.integers(0, 2, 300)})
    frame["y"] = 1 + frame.x1 - .5 * frame.g + rng.normal(size=300)
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path / "project", "figures")
    outcome = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2", "g"], **kwargs)
    return project.root / "runs" / outcome["run_id"]


def _digests(run_root):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (run_root / "figures").glob("*.png")}


def test_a_run_records_a_plan_and_the_first_reader_draws_the_same_bytes(tmp_path, monkeypatch):
    run_root = _run(tmp_path / "lazy")
    assert (run_root / FIGURE_PLAN).is_file() and not _digests(run_root)
    index = json.loads((run_root / "artifacts_index.json").read_text())
    assert not [record for record in index["artifacts"] if record["artifact_type"] == "figure"]

    client, params = TestClient(app), {"project_root": str(run_root.parent.parent)}
    assert client.get(f"/runs/{run_root.name}/artifacts", params=params).status_code == 200
    assert not _digests(run_root)  # GET stays read-only
    drawn = client.post(f"/runs/{run_root.name}/figures", params=params)
    assert drawn.status_code == 200 and drawn.json()["figures"] > 0
    lazy = _digests(run_root)
    assert "residuals_fitted.png" in lazy and "histograms.png" in lazy

    from workbench.engine.stages import diagnostics
    monkeypatch.setattr(diagnostics, "defer_figures", lambda *args, **kwargs: False)
    eager = _digests(_run(tmp_path / "eager"))
    assert lazy == eager


def test_drawing_happens_once_and_a_failure_leaves_the_run_readable(tmp_path):
    run_root = _run(tmp_path)
    ensure_figures(run_root)
    before = (run_root / "artifacts_index.json").read_bytes()
    ensure_figures(run_root)
    assert (run_root / "artifacts_index.json").read_bytes() == before

    broken = tmp_path / "broken"
    shutil.copytree(run_root, broken)
    shutil.rmtree(broken / "figures")
    (broken / "figures").mkdir()
    (broken / FIGURE_PLAN).write_text(json.dumps({"schema": "workbench.figures.plan/v1", "model_result_ids": ["missing"],
                                                  "options": {}}))
    ensure_figures(broken)
    assert json.loads((broken / "figures" / "rendered.json").read_text())["error"] == "KeyError"
