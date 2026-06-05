from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _write_missing_data(tmp_path: Path) -> Path:
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) for i in range(40)]
    for index in (5, 11, 17, 23):
        ys[index] = None
    for index in (7, 13, 19, 29):
        xs[index] = None
    source = tmp_path / "data.csv"
    pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))}).to_csv(
        source,
        index=False,
    )
    return source


def test_run_workflow_imputation_kwarg_triggers_mice(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    source = _write_missing_data(tmp_path)

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        imputation={"method": "mice"},
    )

    run_root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed"
    assert (run_root / "processed" / "imputed_dataset.parquet").exists()
    assert read_json(run_root / "imputation" / "mice_summary.json")["status"] == "completed"


def test_run_workflow_imputation_none_preserves_default_config_path(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    source = _write_missing_data(tmp_path)

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        imputation=None,
    )

    run_root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed"
    assert not (run_root / "processed" / "imputed_dataset.parquet").exists()
    assert not (run_root / "imputation").exists()
