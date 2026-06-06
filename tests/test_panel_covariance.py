import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("linearmodels")


def _panel_frame() -> pd.DataFrame:
    import random
    rng = random.Random(42)
    rows = []
    for firm in ("A", "B", "C", "D", "E", "F", "G", "H"):
        base = {"A": 10, "B": 20, "C": 30, "D": 40,
                "E": 15, "F": 25, "G": 35, "H": 45}[firm]
        for year in (2018, 2019, 2020, 2021, 2022):
            rows.append({
                "firm": firm, "yr": year,
                "profit": base + (year - 2018) * 2.0 + rng.uniform(-1, 1),
                "rnd": base / 2 + (year - 2018) + rng.uniform(-0.5, 0.5),
            })
    return pd.DataFrame(rows)


def _run(tmp_path, **kwargs):
    source = tmp_path / "data.csv"
    _panel_frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], **kwargs)
    return project.root / "runs" / result["run_id"], result


def test_clustered_covariance_runs(tmp_path):
    run_root, result = _run(
        tmp_path, mode="auto", y="profit", x=["rnd"],
        model_type="panel_ols", entity_col="firm", time_col="yr",
        covariance="clustered",
    )
    assert result["status"] == "completed"
    model = read_json(run_root / "model_results" / "panel_ols_1.json")
    assert model["model_type"] == "panel_ols"


def test_default_covariance_runs(tmp_path):
    run_root, result = _run(
        tmp_path, mode="auto", y="profit", x=["rnd"],
        model_type="panel_ols", entity_col="firm", time_col="yr",
    )
    assert result["status"] == "completed"
