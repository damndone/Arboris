from pathlib import Path

from workbench.config import WorkbenchConfig, load_config
from workbench.domain import ArtifactRecord, DatasetKind, Severity


def test_default_config_matches_v1_boundaries():
    config = WorkbenchConfig()
    assert config.max_single_file_gb == 2.0
    assert config.max_rows == 5_000_000
    assert config.max_excel_sheets == 20
    assert config.max_upload_files == 20
    assert config.min_join_overlap == 0.7
    assert config.max_missing_rate == 0.4
    assert config.min_model_n == 30


def test_load_config_allows_project_override(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("max_rows: 100\nmin_join_overlap: 0.8\n", encoding="utf-8")
    config = load_config(path)
    assert config.max_rows == 100
    assert config.min_join_overlap == 0.8
    assert config.max_upload_files == 20


def test_domain_records_are_serializable():
    record = ArtifactRecord(
        artifact_id="raw_file",
        path="data/raw/source.csv",
        artifact_type="raw_data",
        step="ingestion",
        sha256="abc123",
        inputs=[],
    )
    assert record.to_dict()["artifact_id"] == "raw_file"
    assert Severity.BLOCKER.value == "BLOCKER"
    assert DatasetKind.PANEL.value == "panel"
