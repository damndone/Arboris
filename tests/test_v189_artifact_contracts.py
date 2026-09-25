from __future__ import annotations

import json

import pytest

from workbench import __version__
from workbench.artifacts import sha256_file
from workbench.api_errors import WorkbenchAPIError
from workbench.domain import ArtifactRecord
from workbench.repository.run_repository import (
    _artifact_counts,
    _group_artifacts,
    _read_artifacts_index,
    _validate_artifact_record,
)


@pytest.mark.parametrize("mutation", ["prefix", "empty_segment", "path_segment", "row_path", "run_path", "type", "step"])
def test_time_series_dependency_namespace_requires_exact_declared_binding(mutation):
    from workbench.evidence.contracts import (
        EvidenceCoreContractError, _model_packet_dependency_namespace_v1,
    )
    identity = "ts.chart.acf"
    relative = f"artifacts/time_series/{identity}.json"
    row = {"artifact_id": identity, "path": ["runs", "r1", "artifacts", "time_series", f"{identity}.json"],
           "index_record": {"artifact_type": "time_series_json", "step": "arma_garch", "path": relative}}
    manifest = {"run_id": "r1", "records": [row]}
    assert _model_packet_dependency_namespace_v1(manifest) == {identity}
    if mutation in {"prefix", "empty_segment", "path_segment"}:
        row["artifact_id"] = {"prefix": "foreign.chart.acf", "empty_segment": "ts..acf",
                              "path_segment": "ts.chart./acf"}[mutation]
    elif mutation == "row_path":
        row["index_record"]["path"] = "artifacts/foreign/ts.chart.acf.json"
    elif mutation == "run_path":
        row["path"][1] = "foreign-run"
    elif mutation == "type":
        row["index_record"]["artifact_type"] = "model_result"
    else:
        row["index_record"]["step"] = "export"
    with pytest.raises(EvidenceCoreContractError):
        _model_packet_dependency_namespace_v1(manifest)


def _record(run_root, artifact_type: str) -> dict[str, object]:
    is_measurement_advisory = artifact_type == "measurement_advisory"
    path = run_root / "measurement" / (
        "advisory.json" if is_measurement_advisory else "design_precheck.json"
    )
    path.parent.mkdir(parents=True)
    content = (
        json.dumps(
            {
                "contract": "workbench.measurement_advisory.v1",
                "schema_version": 1,
                "entries": [],
                "note": "Evidence only.",
            }
        )
        if is_measurement_advisory
        else '{"contract":"workbench.design_precheck.v1"}\n'
    )
    path.write_text(content, encoding="utf-8")
    return {
        "artifact_id": (
            "measurement_advisory" if is_measurement_advisory else "design_precheck"
        ),
        "path": (
            "measurement/advisory.json"
            if is_measurement_advisory
            else "measurement/design_precheck.json"
        ),
        "artifact_type": artifact_type,
        "step": "ytype" if is_measurement_advisory else "estimation",
        "sha256": sha256_file(path),
        "inputs": ["cleaned_dataset"],
        "config_hash": "",
        "code_version": "0.1.0",
    }


def test_measurement_advisory_is_listed_and_summarized_from_the_validated_index(tmp_path):
    record = _record(tmp_path, "measurement_advisory")
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record]}),
        encoding="utf-8",
    )

    index = _read_artifacts_index(tmp_path)

    assert _artifact_counts(tmp_path) == {"measurement_advisory": 1}
    assert _group_artifacts(index["artifacts"]) == [
        {
            "artifact_type": "measurement_advisory",
            "items": [
                {
                    "artifact_id": "measurement_advisory",
                    "path": "measurement/advisory.json",
                    "artifact_type": "measurement_advisory",
                    "step": "ytype",
                    "sha256": record["sha256"],
                }
            ],
        }
    ]


def test_unknown_artifact_type_is_rejected_before_list_or_summary(tmp_path):
    record = _record(tmp_path, "unknown_future_artifact")
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record]}),
        encoding="utf-8",
    )

    try:
        _read_artifacts_index(tmp_path)
    except WorkbenchAPIError as exc:
        assert exc.code == "ARTIFACTS_INDEX_INVALID"
    else:
        raise AssertionError("unknown artifact type reached the list boundary")


def test_design_precheck_is_accepted_by_the_canonical_artifact_reader(tmp_path):
    record = _record(tmp_path, "design_precheck")

    validated = _validate_artifact_record(tmp_path, record)

    assert validated["artifact_type"] == "design_precheck"


def test_ai_report_producer_type_is_accepted_by_the_canonical_artifact_reader(tmp_path):
    record = _record(tmp_path, "ai_report")

    validated = _validate_artifact_record(tmp_path, record)

    assert validated["artifact_type"] == "ai_report"


def test_unknown_artifact_types_remain_rejected(tmp_path):
    record = _record(tmp_path, "unknown_future_artifact")

    try:
        _validate_artifact_record(tmp_path, record)
    except ValueError as exc:
        assert "canonical vocabulary" in str(exc)
    else:
        raise AssertionError("unknown artifact type was admitted")


def _result_input_record(run_root):
    path = run_root / "result_input.json"
    path.write_text('{"schema_version":1}', encoding="utf-8")
    return ArtifactRecord(
        artifact_id=f"result-input:{run_root.name}",
        path="result_input.json",
        artifact_type="result_input",
        step="result_input",
        sha256=sha256_file(path),
        inputs=("ols_1",),
        code_version=__version__,
    ).to_dict()


def test_result_input_is_listed_from_the_canonical_index(tmp_path):
    record = _result_input_record(tmp_path)
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record]}),
        encoding="utf-8",
    )

    assert _read_artifacts_index(tmp_path)["artifacts"] == [record]
    assert _artifact_counts(tmp_path) == {"result_input": 1}
    assert _group_artifacts([record])[0]["artifact_type"] == "result_input"


@pytest.mark.parametrize("missing", ["config_hash", "code_version"])
def test_result_input_requires_canonical_metadata(tmp_path, missing):
    record = _result_input_record(tmp_path)
    del record[missing]

    with pytest.raises(ValueError, match="shape is not canonical"):
        _validate_artifact_record(tmp_path, record)


@pytest.mark.parametrize("artifact_type", ["result_input", "metadata"])
def test_input_rows_cannot_claim_partial_report_authority(tmp_path, artifact_type):
    record = _result_input_record(tmp_path)
    record.update(artifact_type=artifact_type, project_ref="project:e2e", run_id=tmp_path.name)

    with pytest.raises(ValueError, match="provenance fields must be supplied together"):
        _validate_artifact_record(tmp_path, record)
