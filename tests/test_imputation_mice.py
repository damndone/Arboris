from pathlib import Path

import numpy as np
import pandas as pd

from workbench.artifacts import read_json
from workbench.imputation import run_mice_imputation
from workbench.orchestrator import run_workflow
from workbench.projects import create_project, create_run


def test_mice_imputation_writes_artifacts_without_overwriting_cleaned_dataset(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    processed_dir = run.root / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    cleaned_path = processed_dir / "cleaned_dataset.parquet"
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, np.nan, 4.0, 5.0],
            "x": [2.0, np.nan, 6.0, 8.0, 10.0],
            "mostly_missing": [1.0, np.nan, np.nan, np.nan, np.nan],
            "group": ["a", "b", "a", "b", None],
        }
    )
    frame.to_parquet(cleaned_path, index=False)
    original_cleaned = cleaned_path.read_bytes()

    summary = run_mice_imputation(
        frame,
        run.root,
        columns=["y", "x", "mostly_missing", "group", "missing_column"],
        m=2,
        max_iter=2,
        random_seed=123,
        max_missing_rate=0.4,
    )

    imputed_path = run.root / "processed" / "imputed_dataset.parquet"
    summary_path = run.root / "imputation" / "mice_summary.json"
    decisions_path = run.root / "imputation" / "mice_decisions.json"
    assert imputed_path.exists()
    assert summary_path.exists()
    assert decisions_path.exists()
    assert cleaned_path.read_bytes() == original_cleaned

    imputed = pd.read_parquet(imputed_path)
    assert imputed["y"].isna().sum() == 0
    assert imputed["x"].isna().sum() == 0
    assert imputed["mostly_missing"].isna().sum() == 4
    assert imputed["group"].iloc[:4].tolist() == ["a", "b", "a", "b"]
    assert pd.isna(imputed["group"].iloc[4])

    assert summary["status"] == "completed"
    assert summary["method"] == "mice"
    assert summary["m"] == 2
    assert "group" in summary["skipped_columns"]
    assert "mostly_missing" in summary["skipped_columns"]
    assert summary["selected_columns"] == ["y", "x"]
    persisted_summary = read_json(summary_path)
    decisions = read_json(decisions_path)
    assert persisted_summary["imputed_columns"] == ["y", "x"]
    assert persisted_summary["selected_columns"] == ["y", "x"]
    skipped = {item["column"]: item["reason"] for item in decisions["skipped_columns"]}
    assert skipped["group"] == "non_numeric"
    assert skipped["mostly_missing"] == "missing_rate_above_threshold"
    assert skipped["missing_column"] == "not_found"

    artifact_ids = {
        artifact["artifact_id"]
        for artifact in read_json(run.root / "artifacts_index.json")["artifacts"]
    }
    assert {"imputed_dataset", "mice_summary", "mice_decisions"}.issubset(artifact_ids)


def test_mice_imputation_skips_when_no_numeric_columns(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    frame = pd.DataFrame({"group": ["a", None, "b"]})

    summary = run_mice_imputation(frame, run.root, columns=["group"])

    assert summary["status"] == "skipped"
    assert summary["selected_columns"] == []
    assert summary["warnings"] == ["No supported numeric columns were available for MICE."]
    assert (run.root / "imputation" / "mice_summary.json").exists()
    assert (run.root / "imputation" / "mice_decisions.json").exists()
    assert not (run.root / "processed" / "imputed_dataset.parquet").exists()


def test_workflow_uses_mice_only_when_configured(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    (project.root / "config.yml").write_text(
        "imputation_method: mice\nimputation_m: 2\nimputation_max_iter: 2\n",
        encoding="utf-8",
    )
    y_values = [float(1 + 2 * i) for i in range(40)]
    x_values = [float(i) for i in range(40)]
    for index in (5, 11, 17, 23):
        y_values[index] = np.nan
    for index in (7, 13, 19, 29):
        x_values[index] = np.nan
    source = tmp_path / "data.csv"
    pd.DataFrame({"y": y_values, "x": x_values, "group": ["a", "b"] * 20}).to_csv(
        source,
        index=False,
    )

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x", "group"])

    run_root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed"
    assert (run_root / "processed" / "cleaned_dataset.parquet").exists()
    assert (run_root / "processed" / "imputed_dataset.parquet").exists()
    assert read_json(run_root / "imputation" / "mice_summary.json")["status"] == "completed"
    model_result = read_json(run_root / "model_results" / "ols_1.json")
    assert model_result["nobs"] == 40
