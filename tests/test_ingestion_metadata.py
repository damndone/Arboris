import builtins
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.config import WorkbenchConfig
from workbench.data_interchange import InterchangeUnavailableError
from workbench.ingestion import ingest_files, read_frame_bounded
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


def test_raw_snapshot_symlink_is_rejected_before_any_external_copy(tmp_path: Path):
    source = tmp_path / "source.csv"
    pd.DataFrame({"x": [1]}).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    outside = tmp_path / "outside"
    outside.mkdir()
    raw_snapshot = run.root / "raw_snapshot"
    raw_snapshot.rmdir()
    raw_snapshot.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError) as error:
        ingest_files([source], run.root, WorkbenchConfig())

    assert not (outside / source.name).exists()
    assert read_json(run.root / "artifacts_index.json") == {"schema_version": 1, "artifacts": []}
    assert error.value.reason_code == "raw_snapshot_containment"


def test_raw_snapshot_copy_failure_removes_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench import ingestion as ingestion_api

    source = tmp_path / "source.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    def partial_copy_then_fail(source_handle, target_handle, length=64 * 1024):
        target_handle.write(source_handle.read(1))
        target_handle.flush()
        raise OSError("injected copy failure")

    monkeypatch.setattr(ingestion_api.shutil, "copyfileobj", partial_copy_then_fail)

    with pytest.raises(OSError, match="injected copy failure"):
        ingest_files([source], run.root, WorkbenchConfig())

    assert not (run.root / "raw_snapshot" / source.name).exists()
    assert read_json(run.root / "artifacts_index.json")["artifacts"] == []


def test_raw_snapshot_register_failure_removes_unregistered_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench import ingestion as ingestion_api

    source = tmp_path / "source.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")

    def fail_registration(*args, **kwargs):
        raise RuntimeError("injected registration failure")

    monkeypatch.setattr(ingestion_api, "register_artifact", fail_registration)

    with pytest.raises(RuntimeError, match="injected registration failure"):
        ingest_files([source], run.root, WorkbenchConfig())

    assert not (run.root / "raw_snapshot" / source.name).exists()
    assert read_json(run.root / "artifacts_index.json")["artifacts"] == []


def test_raw_snapshot_register_failure_after_registration_keeps_registered_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench import ingestion as ingestion_api

    source = tmp_path / "source.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    original_register_artifact = ingestion_api.register_artifact

    def register_then_fail(*args, **kwargs):
        original_register_artifact(*args, **kwargs)
        raise RuntimeError("injected post-registration failure")

    monkeypatch.setattr(ingestion_api, "register_artifact", register_then_fail)

    with pytest.raises(RuntimeError, match="injected post-registration failure"):
        ingest_files([source], run.root, WorkbenchConfig())

    assert (run.root / "raw_snapshot" / source.name).exists()
    artifacts = read_json(run.root / "artifacts_index.json")["artifacts"]
    assert [artifact["path"] for artifact in artifacts] == [
        f"raw_snapshot/{source.name}"
    ]


def test_raw_snapshot_source_mutation_during_copy_is_rejected_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench import ingestion as ingestion_api

    source = tmp_path / "source.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    original_copyfileobj = ingestion_api.shutil.copyfileobj

    def copy_then_mutate_source(source_handle, target_handle, length=64 * 1024):
        original_copyfileobj(source_handle, target_handle, length)
        source.write_text("x\n999\n", encoding="utf-8")

    monkeypatch.setattr(
        ingestion_api.shutil, "copyfileobj", copy_then_mutate_source
    )

    with pytest.raises(ValueError) as error:
        ingest_files([source], run.root, WorkbenchConfig())

    assert error.value.reason_code == "source_identity"
    assert not (run.root / "raw_snapshot" / source.name).exists()
    assert read_json(run.root / "artifacts_index.json")["artifacts"] == []


def test_parquet_bounded_ingestion_reports_typed_optional_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    real_import = builtins.__import__

    def missing_pyarrow(name, *args, **kwargs):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ModuleNotFoundError("pyarrow is intentionally unavailable for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_pyarrow)

    with pytest.raises(InterchangeUnavailableError) as error:
        read_frame_bounded(tmp_path / "source.parquet", max_rows=10)

    assert error.value.capability.target_format == "parquet"
    assert error.value.capability.status == "unavailable"
    assert error.value.capability.reason_code == "optional_dependency"


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


def test_coerce_datetime_to_numeric_converts_numeric_hint_columns():
    from workbench.ingestion import _coerce_datetime_to_numeric

    frame = pd.DataFrame({
        "policy_years": pd.to_datetime(["1900-01-01", "1900-01-02", "1900-01-03"]),
        "exposure_months": pd.to_datetime(["1900-01-01", "1900-02-01", "1900-03-01"]),
        "label": pd.to_datetime(["2020-01-01", "2021-06-15", "2022-12-31"]),
    })
    _coerce_datetime_to_numeric(frame)

    # Columns with numeric hints should be coerced to numeric
    assert pd.api.types.is_numeric_dtype(frame["policy_years"])
    assert pd.api.types.is_numeric_dtype(frame["exposure_months"])
    # Column without numeric hint should stay datetime
    assert pd.api.types.is_datetime64_any_dtype(frame["label"])


def test_metadata_registry_owns_nested_metadata_immutably() -> None:
    from workbench.metadata import MetadataRegistryV1

    metadata = {
        "columns": {
            "score": {
                "value_labels": {"1": "one"},
                "user_missing_values": [99],
            }
        }
    }
    registry = MetadataRegistryV1(
        source_run_id="run-1",
        source_node_id="node-1",
        source_artifact_id="artifact-1",
        schema_revision="schema:fixture",
        metadata_revision="metadata:fixture",
        metadata=metadata,
        source_content_sha256="a" * 64,
        schema_artifact_id="schema:fixture",
        schema_artifact_sha256="d" * 64,
        metadata_artifact_id="metadata:fixture-artifact",
        metadata_artifact_path="metadata/registry.json",
        metadata_artifact_sha256="b" * 64,
        metadata_index_entry_sha256="c" * 64,
    )

    metadata["columns"]["score"]["value_labels"]["1"] = "caller-mutated"
    metadata["columns"]["score"]["user_missing_values"].append(100)

    assert registry.metadata["columns"]["score"]["value_labels"]["1"] == "one"
    assert registry.metadata["columns"]["score"]["user_missing_values"] == (99,)
    with pytest.raises(TypeError):
        registry.metadata["columns"]["score"]["value_labels"]["1"] = "blocked"
    with pytest.raises((TypeError, AttributeError)):
        registry.metadata["columns"]["score"]["user_missing_values"].append(101)

    serialized = registry.to_dict()
    serialized["metadata"]["columns"]["score"]["value_labels"]["1"] = "serialized-mutated"
    assert registry.metadata["columns"]["score"]["value_labels"]["1"] == "one"
