from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.config import WorkbenchConfig
from workbench.ingestion import ingest_files
from workbench.metadata import infer_schema
from workbench.projects import create_project, create_run


def test_ingest_csv_copies_raw_snapshot_and_registers_schema(tmp_path: Path):
    source = tmp_path / "source.csv"
    pd.DataFrame(
        {"firm_id": [1, 2], "year": [2020, 2021], "sales": [10.0, 12.5]}
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    frames = ingest_files([source], run.root, WorkbenchConfig())
    assert list(frames.keys()) == ["source.csv"]
    assert (run.root / "raw_snapshot" / "source.csv").exists()

    schema = infer_schema("dataset_1", frames, run.root)
    assert "year" in schema.time_candidates
    assert "firm_id" in schema.id_candidates
    roles = {column.name: column.semantic_role for column in schema.columns}
    assert roles["sales"] == "numeric_measure"


def test_unsupported_file_is_not_copied_or_registered(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("not,data", encoding="utf-8")
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    with pytest.raises(ValueError, match="unsupported file type"):
        ingest_files([source], run.root, WorkbenchConfig())
    assert not (run.root / "raw_snapshot" / "source.txt").exists()
    assert read_json(run.root / "artifacts_index.json") == {"schema_version": 1, "artifacts": []}


def test_duplicate_basenames_are_rejected_before_copy(tmp_path: Path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    left = left_dir / "source.csv"
    right = right_dir / "source.csv"
    pd.DataFrame({"x": [1]}).to_csv(left, index=False)
    pd.DataFrame({"x": [2]}).to_csv(right, index=False)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    with pytest.raises(ValueError, match="duplicate input filenames"):
        ingest_files([left, right], run.root, WorkbenchConfig())
    assert not (run.root / "raw_snapshot" / "source.csv").exists()


def test_row_limit_is_checked_before_registration(tmp_path: Path):
    source = tmp_path / "source.csv"
    pd.DataFrame({"x": [1, 2]}).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    with pytest.raises(ValueError, match="row count exceeds limit"):
        ingest_files([source], run.root, WorkbenchConfig(max_rows=1))
    assert not (run.root / "raw_snapshot" / "source.csv").exists()
    assert read_json(run.root / "artifacts_index.json") == {"schema_version": 1, "artifacts": []}


def test_excel_sheet_limit_is_checked_before_registration(tmp_path: Path):
    source = tmp_path / "source.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="one", index=False)
        pd.DataFrame({"x": [2]}).to_excel(writer, sheet_name="two", index=False)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    with pytest.raises(ValueError, match="excel sheet count exceeds limit"):
        ingest_files([source], run.root, WorkbenchConfig(max_excel_sheets=1))
    assert not (run.root / "raw_snapshot" / "source.xlsx").exists()
    assert read_json(run.root / "artifacts_index.json") == {"schema_version": 1, "artifacts": []}


def test_metadata_candidates_are_deduplicated_across_files(tmp_path: Path):
    frames = {
        "left.csv": pd.DataFrame({"firm_id": [1, 2], "year": [2020, 2021]}),
        "right.csv": pd.DataFrame({"firm_id": [3, 4], "year": [2020, 2021]}),
    }
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    schema = infer_schema("dataset_1", frames, run.root)
    assert schema.id_candidates == ("firm_id",)
    assert schema.time_candidates == ("year",)


def test_metadata_role_precedence_is_explicit(tmp_path: Path):
    frames = {
        "source.csv": pd.DataFrame(
            {
                "year": [2020, 2021],
                "firm_id": [1, 2],
                "year_id": [202001, 202102],
            }
        )
    }
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    schema = infer_schema("dataset_1", frames, run.root)
    roles = {column.name: column.semantic_role for column in schema.columns}
    assert roles == {"year": "time", "firm_id": "entity_id", "year_id": "entity_id"}
