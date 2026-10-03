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
    (project.root / "config.yml").write_text(
        "imputation_method: mice\nimputation_m: 1\nimputation_max_iter: 2\n",
        encoding="utf-8",
    )
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
    assert summary["m"] == 1
    assert summary["mode"] == "single_imputation"
    assert summary["persisted_datasets"] == 1
    assert summary["pooled_estimates"] is False
    assert summary["input_artifact"] == "cleaned_dataset"
    assert summary["output_artifact"] == "imputed_dataset"
    assert not (run_root / "processed" / "imputed_dataset_0001.parquet").exists()
    artifact_ids = {
        artifact["artifact_id"]
        for artifact in read_json(run_root / "artifacts_index.json")["artifacts"]
    }
    assert "mice_manifest" not in artifact_ids
    assert not any(artifact_id.startswith("imputed_dataset_") for artifact_id in artifact_ids)


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
