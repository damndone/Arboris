"""v1.8.9 step 5 — an SPSS/Stata upload runs end to end with its metadata."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project
from workbench.tabular_io import write_statistical

client = TestClient(app)

FILE_LABELS = {
    "variable_labels": {"educ": "受教育年限", "region": "地区"},
    "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部"}},
    "measurement_level": {"region": "nominal", "educ": "scale"},
    "user_missing_values": {"educ": [-99]},
}


def _survey(tmp_path: Path, fmt: str) -> tuple[bytes, pd.DataFrame]:
    rng = np.random.default_rng(5)
    n = 220
    frame = pd.DataFrame(
        {
            "wage": rng.normal(20, 4, n).round(3),
            "educ": rng.integers(9, 20, n).astype(float),
            "region": rng.integers(1, 4, n).astype(float),
        }
    )
    frame.loc[:9, "educ"] = -99
    path = tmp_path / f"survey.{fmt}"
    write_statistical(frame, FILE_LABELS, path, fmt)
    return path.read_bytes(), frame


def _run(project_root: Path, data: bytes, filename: str, **form) -> dict:
    created = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto", "model_type": "ols",
              "y": "wage", "x": "educ,region", **form},
        files={"file": (filename, io.BytesIO(data), "application/octet-stream")},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    for _ in range(400):
        detail = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if detail.get("status") in {"completed", "failed", "blocked"}:
            break
        time.sleep(0.1)
    assert detail["status"] == "completed", detail.get("status")
    return detail


@pytest.mark.parametrize("fmt", ["sav", "dta"])
def test_an_uploaded_statistical_file_brings_its_metadata_into_the_run(tmp_path, fmt) -> None:
    data, frame = _survey(tmp_path, fmt)
    project = create_project(tmp_path, f"upload-{fmt}")
    detail = _run(project.root, data, f"survey.{fmt}")
    run_root = project.root / "runs" / detail["run_id"]

    labels = json.loads((run_root / "run_inputs.json").read_text())["form"]["labels"]
    assert labels["variable_labels"]["educ"] == "受教育年限"
    assert labels["value_labels"]["region"]["2"] == "南方"
    model = json.loads((run_root / "model_results" / "ols_1.json").read_text())
    assert model["nobs"] == len(frame) - 10  # the -99 codes are not education years
    if fmt == "sav":
        assert labels["user_missing_values"] == {"educ": [-99]}
        applied = json.loads((run_root / "measurement" / "user_missing.json").read_text())
        assert applied["columns"]["educ"]["converted"] == 10
    assert any(label == "地区: 南方" for label in detail["term_labels"].values())


def test_explicit_labels_override_the_files_labels(tmp_path) -> None:
    data, _frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "override")
    detail = _run(
        project.root, data, "survey.sav",
        labels=json.dumps({"variable_labels": {"educ": "Years of schooling"}}),
    )
    labels = json.loads(
        (project.root / "runs" / detail["run_id"] / "run_inputs.json").read_text()
    )["form"]["labels"]
    assert labels["variable_labels"] == {"educ": "Years of schooling", "region": "地区"}
    assert labels["user_missing_values"] == {"educ": [-99]}


def test_a_corrupt_upload_fails_without_a_completed_run(tmp_path) -> None:
    project = create_project(tmp_path, "corrupt")
    created = client.post(
        "/runs",
        data={"project_root": str(project.root), "mode": "auto", "model_type": "ols", "y": "wage", "x": "educ"},
        files={"file": ("survey.sav", io.BytesIO(b"not an spss file"), "application/octet-stream")},
    )
    assert created.status_code in {400, 422}, created.text
    assert "not a readable SAV file" in created.text


def test_data_operations_read_the_raw_statistical_snapshot(tmp_path) -> None:
    from workbench.data_operations import resolve_data_column_cast_context
    from workbench.statistical_exploration import resolve_statistical_source

    data, frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "raw-node")
    detail = _run(project.root, data, "survey.sav")
    context = resolve_data_column_cast_context(
        project.root, source_run_id=detail["run_id"], source_node_id="stage:raw"
    )
    _context, raw = resolve_statistical_source(
        project.root,
        source_run_id=detail["run_id"],
        source_node_id="stage:raw",
        source_artifact_id=context["source_artifact_id"],
    )
    assert list(raw.columns) == ["wage", "educ", "region"]
    assert (raw["educ"] == -99).sum() == 10


def _export(project_root: Path, run_id: str, node_id: str, fmt: str):
    return client.post(
        f"/runs/{run_id}/datasets/export",
        params={"project_root": str(project_root)},
        json={"node_id": node_id, "format": fmt},
    )


def test_import_relabel_export_reimport_keeps_the_labels(tmp_path) -> None:
    """The step-5 acceptance scenario, on the real HTTP path.

    Import .sav -> change a label through a rerun -> export .dta -> import it
    again: the relabelled metadata survives, and the -99 code never comes back
    as an education value.
    """

    from workbench.services.rerun_service import RerunService, RerunSubmissionRequest

    data, _frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "round-trip")
    first = _run(project.root, data, "survey.sav")["run_id"]
    relabel = RerunService(project.root).submit(
        RerunSubmissionRequest(
            source_run_id=first,
            from_node="model:ols_1",
            op_overrides={"labels": {"value_labels": {"region": {"1": "North", "2": "South", "3": "West"}}}},
            rerun_reason="manual_override",
        )
    )
    for _ in range(400):
        status = client.get(f"/runs/{relabel.run_id}", params={"project_root": str(project.root)}).json()["status"]
        if status in {"completed", "failed"}:
            break
        time.sleep(0.1)
    assert status == "completed"

    exported = _export(project.root, relabel.run_id, "stage:raw", "dta")
    assert exported.status_code == 200, exported.text
    body = exported.json()
    notes = {(note["column"], note["field"]) for note in body["report"]["notes"]}
    assert ("educ", "user_missing_values") in notes  # Stata cannot keep -99 as a code
    download = client.get(body["download_url"], params={"project_root": str(project.root)})
    assert download.status_code == 200

    reimport = create_project(tmp_path, "reimport")
    detail = _run(reimport.root, download.content, "survey.dta")
    labels = json.loads(
        (reimport.root / "runs" / detail["run_id"] / "run_inputs.json").read_text()
    )["form"]["labels"]
    assert labels["value_labels"]["region"] == {"1": "North", "2": "South", "3": "West"}
    assert labels["variable_labels"]["educ"] == "受教育年限"
    model = json.loads(
        (reimport.root / "runs" / detail["run_id"] / "model_results" / "ols_1.json").read_text()
    )
    assert model["nobs"] == 210


def test_exporting_the_same_data_twice_returns_the_same_artifact(tmp_path) -> None:
    data, _frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "idempotent")
    run_id = _run(project.root, data, "survey.sav")["run_id"]
    first = _export(project.root, run_id, "stage:raw", "sav").json()
    second = _export(project.root, run_id, "stage:raw", "sav").json()
    assert first["artifact_id"] == second["artifact_id"]
    index = json.loads((project.root / "runs" / run_id / "artifacts_index.json").read_text())
    assert [r["artifact_id"] for r in index["artifacts"]].count(first["artifact_id"]) == 1
    # The SPSS export keeps -99 as a declared code, not as data loss.
    assert first["report"]["notes"] == []


def test_exporting_a_non_dataset_node_is_refused(tmp_path) -> None:
    data, _frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "refused")
    run_id = _run(project.root, data, "survey.sav")["run_id"]
    response = _export(project.root, run_id, "model:ols_1", "sav")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATASET_EXPORT_UNAVAILABLE"


def test_upload_preview_returns_rows_labels_and_the_full_row_count(tmp_path) -> None:
    data, frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "preview")
    response = client.post(
        "/uploads/preview",
        data={"project_root": str(project.root)},
        files={"file": ("survey.sav", io.BytesIO(data), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["columns"] == ["wage", "educ", "region"]
    assert body["total_rows"] == len(frame)
    assert body["rows"][0]["educ"] == -99  # codes as stored; the run declares them missing
    assert body["labels"]["value_labels"]["region"]["2"] == "南方"


def test_upload_preview_refuses_csv_and_corrupt_files(tmp_path) -> None:
    project = create_project(tmp_path, "preview-refused")
    for name, payload, code in (
        ("d.csv", b"a,b\n1,2\n", "UPLOAD_PREVIEW_UNSUPPORTED"),
        ("d.sav", b"garbage", "UPLOAD_PREVIEW_UNREADABLE"),
    ):
        response = client.post(
            "/uploads/preview",
            data={"project_root": str(project.root)},
            files={"file": (name, io.BytesIO(payload), "application/octet-stream")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code


def test_the_absent_column_guard_reads_statistical_uploads(tmp_path) -> None:
    """The guard read the parent upload as CSV; on a .sav it silently gave up."""

    from workbench.services.rerun_service import (
        RerunService,
        RerunServiceError,
        RerunSubmissionRequest,
    )

    data, _frame = _survey(tmp_path, "sav")
    project = create_project(tmp_path, "guard")
    run_id = _run(project.root, data, "survey.sav")["run_id"]
    with pytest.raises(RerunServiceError) as caught:
        RerunService(project.root).submit(
            RerunSubmissionRequest(
                source_run_id=run_id,
                from_node="model:ols_1",
                op_overrides={"labels": {"measurement_level": {"educ": "scale", "not_a_column": "nominal"}}},
                rerun_reason="manual_override",
            )
        )
    assert caught.value.code == "MEASUREMENT_LEVEL_UNKNOWN_COLUMN"
