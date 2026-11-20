"""Export reuses its validated frame, preserving the original wire and writer inputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import pytest

from tests.test_data_column_cast import _source_project
from workbench import egress
from workbench.artifacts import read_json, sha256_file, write_json
from workbench.data_operations import DataColumnCastValidationError, resolve_data_column_cast_context
from workbench.data_operations import frames
from workbench.services import data_export
from workbench.tabular_io import StatisticalFileError, prepare_export, write_prepared


LABELS = {
    "variable_labels": {"educ": "受教育年限", "region": "地区", "observed_at": "日期"},
    "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部", "1.5": "fractional"}},
    "measurement_level": {"region": "nominal"},
    "user_missing_values": {"educ": [-99, {"low": 900, "high": 999}]},
}


@pytest.fixture
def source(tmp_path):
    frame = pd.DataFrame({
        "educ": [12.0, -99.0, 950.0, np.nan, 16.0, 9.0],
        "region": pd.Series([1, 2, 3, 2, 1, 3], dtype="Int64"),
        "city": pd.Series(["北京", "a,b", 'a"b', "line\nbreak", None, "é"], dtype="string"),
        "observed_at": pd.to_datetime(["2020-02-29", None, "1960-01-01", "2024-05-01", "2021-12-31", "2022-01-01"]),
        "source_code": pd.Series(["001", "002X", "", None, "汉字", "006"], dtype="string"),
    })
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    run = project / "runs" / run_id
    path = run / "data.csv"
    write_json(frames._schema_sidecar_path(path), {"dtypes": {column: str(frame[column].dtype) for column in frame.columns}})
    write_json(run / "run_inputs.json", {"form": {"labels": LABELS}})
    return project, run_id, artifact_id, run, path


def count_decodes(monkeypatch, source_path):
    original = pd.read_csv
    calls = []

    def counted(path, *args, **kwargs):
        location = Path(path.name if hasattr(path, "read") else path)
        if location == source_path:
            calls.append(location)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", counted)
    return calls


@pytest.mark.parametrize("action", ["preview", "export"])
@pytest.mark.parametrize("fmt", ["csv", "dta"])
def test_real_export_and_preview_decode_source_once(monkeypatch, source, action, fmt):
    project, run_id, _, _, path = source
    calls = count_decodes(monkeypatch, path)
    function = data_export.preview_export if action == "preview" else data_export.export_dataset
    function(project, run_id, "stage:source", {"format": fmt})
    assert len(calls) == 1


@pytest.mark.parametrize("fmt", ["csv", "dta"])
def test_export_writer_reuses_its_private_selection(monkeypatch, source, fmt):
    project, run_id, _, _, _ = source
    select = data_export._selected
    write = data_export.write_prepared
    frames = []

    def selection(frame, options):
        chosen = select(frame, options)
        frames.append((frame, frame.copy(), chosen))
        return chosen

    def writer(prepared, path):
        frame, before, chosen = frames[0]
        assert prepared.data is chosen
        pd.testing.assert_frame_equal(frame, before)
        return write(prepared, path)

    monkeypatch.setattr(data_export, "_selected", selection)
    monkeypatch.setattr(data_export, "write_prepared", writer)
    data_export.export_dataset(project, run_id, "stage:source", options_for(fmt, "strings", "as_missing", True))
    assert len(frames) == 1


@pytest.mark.parametrize("fmt", ["csv", "dta"])
def test_export_hash_does_not_materialize_staged_file(monkeypatch, source, fmt):
    project, run_id, _, run, _ = source
    read_bytes = Path.read_bytes

    def bounded(path):
        if path.parent == run / "exports" / "data":
            pytest.fail("export hash materialized the staged file")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", bounded)
    result = data_export.export_dataset(project, run_id, "stage:source", {"format": fmt, "filename": "数据"})
    output = exported_file(run, result)
    expected = hashlib.sha256(output.read_bytes() + "数据".encode()).hexdigest()
    assert result["artifact_id"] == f"data_export_{fmt}_{expected[:16]}"


def test_public_resolver_retains_exact_JSON_protocol_and_sidecar_dtypes(source):
    project, run_id, artifact_id, _, path = source
    result = resolve_data_column_cast_context(project, source_run_id=run_id, source_node_id="stage:source")
    assert result == {
        "operation_id": "data.column.cast", "operation_version": "v1", "source_run_id": run_id,
        "source_node_id": "stage:source", "source_artifact_id": artifact_id, "source_artifact_path": "data.csv",
        "source_sha256": sha256_file(path), "row_count": 6,
        "columns": [{"name": "educ", "dtype": "float64"}, {"name": "region", "dtype": "Int64"},
                    {"name": "city", "dtype": "string"}, {"name": "observed_at", "dtype": "datetime64[us]"},
                    {"name": "source_code", "dtype": "string"}],
        "downstream_invalidation": [],
    }
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result


def old_prepare(project, run_id, options):
    """The prior two-read preparation, using the unchanged public resolver contract."""
    options = data_export.ExportOptions.of(options)
    options.validate()
    run = project / "runs" / run_id
    context = resolve_data_column_cast_context(project, source_run_id=run_id, source_node_id="stage:source")
    frame = frames._read_frame(run / context["source_artifact_path"])
    selected = data_export._selected(frame, options)
    prepared = prepare_export(selected, data_export._labels_for(LABELS, list(selected.columns)), options.format,
                              value_label_mode=options.value_labels, missing_code_mode=options.missing_codes,
                              dta_version=options.dta_version)
    return run, context, frame, prepared, options


def options_for(fmt, labels, missing, filtered, version=14):
    return {"format": fmt, "value_labels": labels, "missing_codes": missing, "dta_version": version,
            "filename": "chosen-data", "columns": ["region", "educ", "observed_at", "city", "source_code"],
            "filters": [{"column": "region", "op": "ge", "value": 2}] if filtered else []}


def exported_file(run, result):
    record = next(item for item in read_json(run / "artifacts_index.json")["artifacts"] if item["artifact_id"] == result["artifact_id"])
    return run / record["path"]


@pytest.mark.parametrize("labels", ["labels", "strings", "none"])
@pytest.mark.parametrize("missing", ["as_missing", "keep_codes"])
@pytest.mark.parametrize("filtered", [False, True])
def test_CSV_bytes_content_identity_and_report_equal_old_preparation(source, tmp_path, labels, missing, filtered):
    project, run_id, _, _, path = source
    options = options_for("csv", labels, missing, filtered)
    run, context, old_frame, old, chosen = old_prepare(project, run_id, options)
    before = path.read_bytes()
    expected = tmp_path / "old.csv"
    write_prepared(old, expected)
    actual = data_export.export_dataset(project, run_id, "stage:source", options)
    output = exported_file(run, actual)
    assert output.read_bytes() == expected.read_bytes()
    digest = hashlib.sha256(expected.read_bytes() + b"chosen-data").hexdigest()[:16]
    assert actual["artifact_id"] == f"data_export_csv_{digest}"
    payload = data_export._summary(run_id, "stage:source", context, old_frame, old, chosen)
    assert actual["report"] == payload
    assert output.with_name(output.name + ".report.json").read_bytes() == json.dumps(payload, indent=2, ensure_ascii=False).encode()
    assert path.read_bytes() == before


@pytest.mark.parametrize("labels", ["labels", "strings", "none"])
@pytest.mark.parametrize("missing", ["as_missing", "keep_codes"])
@pytest.mark.parametrize("filtered", [False, True])
@pytest.mark.parametrize("version", [14, 15])
def test_DTA_writer_inputs_roundtrip_dates_labels_and_missing_equal_old_preparation(monkeypatch, source, tmp_path, labels, missing, filtered, version):
    project, run_id, _, _, path = source
    options = options_for("dta", labels, missing, filtered, version)
    run, context, old_frame, old, chosen = old_prepare(project, run_id, options)
    before = path.read_bytes()
    expected = tmp_path / "old.dta"
    write_prepared(old, expected)
    writer = data_export.write_prepared
    calls = []

    def checked(prepared, target):
        pd.testing.assert_frame_equal(prepared.data, old.data)
        assert prepared.fmt == old.fmt and prepared.options == old.options
        assert prepared.report.to_dict() == old.report.to_dict()
        calls.append(target)
        return writer(prepared, target)

    monkeypatch.setattr(data_export, "write_prepared", checked)
    actual = data_export.export_dataset(project, run_id, "stage:source", options)
    output = exported_file(run, actual)
    actual_frame, actual_meta = pyreadstat.read_dta(str(output))
    expected_frame, expected_meta = pyreadstat.read_dta(str(expected))
    pd.testing.assert_frame_equal(actual_frame, expected_frame)
    for field in ("column_names", "column_labels", "variable_value_labels", "original_variable_types",
                  "readstat_variable_types", "missing_user_values", "file_encoding"):
        assert getattr(actual_meta, field) == getattr(expected_meta, field)
    assert len(calls) == 1
    assert actual["report"] == data_export._summary(run_id, "stage:source", context, old_frame, old, chosen)
    assert (b"118" if version == 14 else b"119") in output.read_bytes()[:60]
    assert path.read_bytes() == before


@pytest.mark.parametrize("action", ["preview", "export"])
def test_wrong_artifact_SHA_refuses_before_decode_or_writer(monkeypatch, source, action):
    project, run_id, _, run, path = source
    index = read_json(run / "artifacts_index.json")
    index["artifacts"][0]["sha256"] = "0" * 64
    write_json(run / "artifacts_index.json", index)
    calls = count_decodes(monkeypatch, path)
    writer = []
    monkeypatch.setattr(data_export, "write_prepared", lambda *args: writer.append(args))
    function = data_export.preview_export if action == "preview" else data_export.export_dataset
    with pytest.raises(DataColumnCastValidationError, match="^source artifact fingerprint changed$"):
        function(project, run_id, "stage:source", "csv")
    assert not calls and not writer and not (run / "exports").exists()


def test_preview_decodes_once_per_request_and_does_not_cache_or_write(monkeypatch, source):
    project, run_id, _, run, path = source
    calls = count_decodes(monkeypatch, path)
    first = data_export.preview_export(project, run_id, "stage:source", "csv")
    second = data_export.preview_export(project, run_id, "stage:source", "csv")
    assert first == second and len(calls) == 2
    assert not (run / "exports").exists()


def test_export_hook_still_runs_before_source_decode(monkeypatch, source):
    project, run_id, _, _, path = source
    calls = count_decodes(monkeypatch, path)
    operations = []

    def denied(root, operation):
        operations.append((root, operation))
        raise egress.EgressPolicyError("export denied")

    monkeypatch.setattr(egress, "authorize_export", denied)
    with pytest.raises(egress.EgressPolicyError, match="export denied"):
        data_export.export_dataset(project, run_id, "stage:source", "csv")
    assert operations == [(project, "export.dataset")] and not calls


def test_Stata13_Unicode_refusal_matches_old_writer(source, tmp_path):
    project, run_id, _, _, _ = source
    options = options_for("dta", "labels", "as_missing", False, 13)
    _, _, _, old, _ = old_prepare(project, run_id, options)
    with pytest.raises(StatisticalFileError) as expected:
        write_prepared(old, tmp_path / "old.dta")
    with pytest.raises(StatisticalFileError) as actual:
        data_export.export_dataset(project, run_id, "stage:source", options)
    assert str(actual.value) == str(expected.value)
