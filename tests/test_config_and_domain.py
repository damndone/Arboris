from pathlib import Path

from workbench.config import WorkbenchConfig, load_config
from workbench.domain import (
    ArtifactRecord,
    ColumnMetadata,
    DatasetKind,
    DatasetSchema,
    DecisionRecord,
    GuardrailIssue,
    Severity,
)


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


def test_load_config_none_returns_defaults():
    assert load_config(None) == WorkbenchConfig()


def test_load_config_missing_path_returns_defaults(tmp_path: Path):
    assert load_config(tmp_path / "missing.yml") == WorkbenchConfig()


def test_load_config_ignores_unknown_keys(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        "max_rows: 100\nunknown_threshold: 0.25\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.max_rows == 100
    assert not hasattr(config, "unknown_threshold")


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


def test_guardrail_issue_serializes_enum_value():
    issue = GuardrailIssue(
        severity=Severity.WARNING,
        code="missing_rate",
        message="Column has many missing values.",
        evidence={"column": "wage", "missing_rate": 0.45},
    )
    assert issue.to_dict() == {
        "severity": "WARNING",
        "code": "missing_rate",
        "message": "Column has many missing values.",
        "evidence": {"column": "wage", "missing_rate": 0.45},
    }


def test_decision_record_is_serializable():
    record = DecisionRecord(
        step="merge",
        suggestion="Use inner join on firm_id.",
        confidence=0.82,
        evidence=["firm_id overlap is high"],
        user_action="accepted",
        final_decision="inner_join",
    )
    assert record.to_dict()["final_decision"] == "inner_join"
    assert record.to_dict()["evidence"] == ["firm_id overlap is high"]


def test_dataset_schema_serializes_nested_column_metadata():
    column = ColumnMetadata(
        name="firm_id",
        dtype="int64",
        semantic_role="entity_id",
        confidence=0.91,
        source_file="panel.csv",
        evidence=["unique within firm-year"],
    )
    schema = DatasetSchema(
        dataset_id="panel_dataset",
        source_files=["panel.csv"],
        columns=[column],
        primary_key_candidates=["firm_id", "year"],
        time_candidates=["year"],
        id_candidates=["firm_id"],
        transformations=[{"operation": "normalize_columns"}],
    )
    data = schema.to_dict()
    assert data["dataset_id"] == "panel_dataset"
    assert data["columns"][0]["name"] == "firm_id"
    assert data["transformations"] == [{"operation": "normalize_columns"}]


def test_cli_module_exports_app():
    from workbench.cli import app

    assert app is not None
