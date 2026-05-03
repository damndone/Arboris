import json
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_run_workflow_creates_traceable_outputs(tmp_path: Path):
    source = tmp_path / "cross_section.csv"
    pd.DataFrame(
        {
            "y": [1 + 2 * i for i in range(35)],
            "x": list(range(35)),
            "firm_id": list(range(100, 135)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "run_manifest.json").exists()
    assert (run_root / "reports" / "report.html").exists()
    assert (run_root / "reports" / "report.pdf").exists()
    assert (run_root / "exports" / "tables.xlsx").exists()
    assert (run_root / "artifacts_index.json").exists()
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"
    artifact_index = read_json(run_root / "artifacts_index.json")
    artifact_ids = {
        artifact["artifact_id"] for artifact in artifact_index["artifacts"]
    }
    assert {
        "cleaning_actions",
        "cleaned_dataset",
        "data_profile",
        "analysis_router",
        "regression_1",
        "report_html",
        "report_pdf",
        "tables_xlsx",
    }.issubset(artifact_ids)
    assert all(
        not artifact["path"].startswith("/")
        for artifact in artifact_index["artifacts"]
    )
    model_result = read_json(run_root / "model_results" / "regression_1.json")
    assert model_result["model_id"] == "regression_1"
    assert "x" in model_result["coefficients"]


def test_run_workflow_blocks_missing_model_columns(tmp_path: Path):
    source = tmp_path / "cross_section.csv"
    pd.DataFrame(
        {
            "y": [1 + 2 * i for i in range(35)],
            "x": list(range(35)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["missing"])

    assert result["status"] == "blocked"
    run_root = project.root / "runs" / result["run_id"]
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")
    assert manifest["status"] == "blocked"
    assert errors["issues"][0]["code"] == "MODEL_COLUMNS_NOT_FOUND"
    assert not (run_root / "model_results" / "regression_1.json").exists()


def test_manifest_contains_started_at_y_and_x(tmp_path: Path):
    project_root = tmp_path / "proj"
    create_project(tmp_path, "proj")
    data = project_root / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"])

    manifest_path = project_root / "runs" / result["run_id"] / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "started_at" in manifest
    assert manifest["started_at"].endswith("+00:00") or manifest["started_at"].endswith("Z")
    assert manifest["y"] == "y"
    assert manifest["x"] == ["x"]
    assert manifest["status"] == "completed"


def test_new_run_artifacts_index_has_schema_version(tmp_path: Path):
    project_root = tmp_path / "proj"
    create_project(tmp_path, "proj")
    data = project_root / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"])

    index_path = project_root / "runs" / result["run_id"] / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index.get("schema_version") == 1
