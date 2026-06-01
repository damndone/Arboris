from pathlib import Path

import pytest

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
    assert config.max_panel_missing_cells == 0.5
    assert config.min_variable_role_confidence == 0.65
    assert config.random_seed == 20260429
    assert config.imputation_method == ""
    assert config.imputation_m == 5
    assert config.imputation_max_iter == 10
    assert config.prediction_enabled is False
    assert config.prediction_model_type == ""
    assert config.prediction_cv_folds == 5
    assert config.prediction_sampling_method == ""


def test_load_config_allows_project_override(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        "max_rows: 100\n"
        "min_join_overlap: 0.8\n"
        "imputation_method: mice\n"
        "prediction_enabled: true\n"
        "prediction_model_type: prediction_ridge\n"
        "prediction_cv_folds: 3\n"
        "prediction_sampling_method: oversample\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.max_rows == 100
    assert config.min_join_overlap == 0.8
    assert config.imputation_method == "mice"
    assert config.prediction_enabled is True
    assert config.prediction_model_type == "prediction_ridge"
    assert config.prediction_cv_folds == 3
    assert config.prediction_sampling_method == "oversample"
    assert config.max_upload_files == 20


def test_load_config_none_returns_defaults():
    assert load_config(None) == WorkbenchConfig()


def test_load_config_missing_path_returns_defaults(tmp_path: Path):
    assert load_config(tmp_path / "missing.yml") == WorkbenchConfig()


def test_load_config_empty_file_returns_defaults(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("", encoding="utf-8")
    assert load_config(path) == WorkbenchConfig()


def test_load_config_ignores_unknown_keys(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        "max_rows: 100\nunknown_threshold: 0.25\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.max_rows == 100
    assert not hasattr(config, "unknown_threshold")


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("- max_rows\n", encoding="utf-8")
    with pytest.raises(ValueError, match="config.yml.*mapping"):
        load_config(path)


def test_domain_records_are_serializable():
    record = ArtifactRecord(
        artifact_id="raw_file",
        path="data/raw/source.csv",
        artifact_type="raw_data",
        step="ingestion",
        sha256="abc123",
        inputs=[],
    )
    assert record.to_dict() == {
        "artifact_id": "raw_file",
        "path": "data/raw/source.csv",
        "artifact_type": "raw_data",
        "step": "ingestion",
        "sha256": "abc123",
        "inputs": [],
        "config_hash": "",
        "code_version": "0.1.0",
    }
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
        "issue_id": "",
        "affected_stage": "",
        "variables": [],
        "metric": "",
        "value": None,
        "threshold": None,
        "template_key": "",
        "template_params": {},
        "recommended_action_key": "",
        "is_user_action_required": False,
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
    assert record.to_dict() == {
        "step": "merge",
        "suggestion": "Use inner join on firm_id.",
        "confidence": 0.82,
        "evidence": ["firm_id overlap is high"],
        "user_action": "accepted",
        "final_decision": "inner_join",
    }


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
    assert column.to_dict() == {
        "name": "firm_id",
        "dtype": "int64",
        "semantic_role": "entity_id",
        "confidence": 0.91,
        "source_file": "panel.csv",
        "evidence": ["unique within firm-year"],
    }
    assert data == {
        "dataset_id": "panel_dataset",
        "source_files": ["panel.csv"],
        "columns": [
            {
                "name": "firm_id",
                "dtype": "int64",
                "semantic_role": "entity_id",
                "confidence": 0.91,
                "source_file": "panel.csv",
                "evidence": ["unique within firm-year"],
            }
        ],
        "primary_key_candidates": ["firm_id", "year"],
        "time_candidates": ["year"],
        "id_candidates": ["firm_id"],
        "transformations": [{"operation": "normalize_columns"}],
    }


def test_domain_list_fields_are_not_mutable_through_records():
    record = ArtifactRecord(
        artifact_id="raw_file",
        path="data/raw/source.csv",
        artifact_type="raw_data",
        step="ingestion",
        sha256="abc123",
        inputs=["source.csv"],
    )
    with pytest.raises(AttributeError):
        record.inputs.append("other.csv")
    assert record.to_dict()["inputs"] == ["source.csv"]


def test_domain_mapping_fields_are_not_mutable_through_records():
    issue = GuardrailIssue(
        severity=Severity.BLOCKER,
        code="invalid",
        message="Invalid input.",
        evidence={"rows": 0},
    )
    with pytest.raises(TypeError):
        issue.evidence["rows"] = 1
    assert issue.to_dict()["evidence"] == {"rows": 0}


def test_cli_module_exports_app():
    from workbench.cli import app

    assert app is not None
