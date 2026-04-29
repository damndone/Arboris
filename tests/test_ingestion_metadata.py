from pathlib import Path

import pandas as pd

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
