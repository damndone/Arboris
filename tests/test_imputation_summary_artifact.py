from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run_mice_workflow(tmp_path: Path) -> Path:
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
    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        imputation={"method": "mice"},
    )
    assert result["status"] == "completed"
    return project.root / "runs" / result["run_id"]


def test_imputation_summary_json_is_written(tmp_path: Path):
    run_root = _run_mice_workflow(tmp_path)

    summary = read_json(run_root / "imputation_summary.json")

    assert summary["schema_version"] == 1
    assert summary["method"] == "mice"
    assert summary["status"] == "completed"
    assert summary["input_artifact"] == "cleaned_dataset"
    assert summary["output_artifact"] == "imputed_dataset"


def test_imputation_summary_is_registered_as_artifact(tmp_path: Path):
    run_root = _run_mice_workflow(tmp_path)

    index = read_json(run_root / "artifacts_index.json")
    record = next(
        artifact
        for artifact in index["artifacts"]
        if artifact["artifact_id"] == "imputation_summary"
    )

    assert record["path"] == "imputation_summary.json"
    assert record["artifact_type"] == "metadata"
    assert record["step"] == "imputation"
    assert record["inputs"] == ["cleaned_dataset"]
