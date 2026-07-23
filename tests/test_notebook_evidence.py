"""Bounded, source-bound Data Evidence Pack tests."""
from __future__ import annotations

import json
from pathlib import Path

from workbench.agent.notebook.evidence import (
    DatasetSource,
    InspectionRequest,
    RunSource,
    compile_evidence_pack,
)
from workbench.agent.notebook import NotebookService
from workbench.agent.notebook.store import NotebookStore
from workbench.artifacts import register_artifact
from workbench.lineage.upload_store import store_upload_bytes

from tests.test_notebook_support import make_project, make_run, make_trace


def _raw_run(project: Path, run_id: str = "run_001") -> Path:
    run_root = make_run(project, run_id)
    raw = run_root / "raw_snapshot" / "observations.csv"
    raw.parent.mkdir(parents=True)
    rows = [
        "patient_id,when,y,notes,feature",
        "p-001,2024-01-01,1,first patient note,10",
        "p-002,2024-01-02,,second patient note,11",
        "p-003,2024-01-03,3,third patient note,12",
        "p-004,2024-01-04,4,fourth patient note,13",
    ]
    raw.write_text("\n".join(rows) + "\n", encoding="utf-8")
    register_artifact(run_root, "raw_observations", raw, "raw_data", "ingestion", [])
    return run_root


def test_evidence_pack_is_bounded_and_redacts_identifier_sample(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _raw_run(project)
    pack = compile_evidence_pack(
        project,
        source=RunSource("run_001"),
        requests=(
            InspectionRequest("profile.v1", "run:active", {"max_rows": 5}),
            InspectionRequest("sample.v1", "run:active", {"max_rows": 5}),
            InspectionRequest("quality.v1", "run:active", {"max_rows": 5}),
            InspectionRequest("time_index.v1", "run:active", {"max_rows": 5}),
        ),
    )

    assert pack.content_hash.startswith("sha256:")
    assert pack.evidence_pack_hash == pack.content_hash
    assert pack.records[0].source_refs == ("dataset_profile:run_001",)
    assert pack.records[0].result_hash.startswith("sha256:")
    sample = next(record for record in pack.records if record.inspection_id == "sample.v1")
    assert all("patient_id" not in row for row in sample.observations["rows"])
    assert all("notes" not in row for row in sample.observations["rows"])
    assert len(sample.observations["rows"]) <= 10
    assert len(json.dumps(pack.to_dict(), ensure_ascii=False).encode("utf-8")) <= 48 * 1024


def test_profile_cap_is_visible_as_partial_omission(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_root = _raw_run(project)
    raw = run_root / "raw_snapshot" / "observations.csv"
    raw.write_text(
        "patient_id,when,y,feature\n"
        + "\n".join(f"p-{i:03d},2024-01-{(i % 28) + 1:02d},{i},{i + 1}" for i in range(1, 8))
        + "\n",
        encoding="utf-8",
    )
    # The artifact must be re-registered after changing the fixture bytes.
    (run_root / "artifacts_index.json").write_text(json.dumps({"artifacts": []}))
    register_artifact(run_root, "raw_observations", raw, "raw_data", "ingestion", [])

    record = compile_evidence_pack(
        project,
        source=RunSource("run_001"),
        requests=(InspectionRequest("profile.v1", "run:active", {"max_rows": 2}),),
    ).records[0]

    assert record.status == "partial"
    assert any(item["reason"] == "source_row_cap" for item in record.omissions)


def test_rolling_origin_requires_registered_matching_capability(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _raw_run(project)
    request = InspectionRequest(
        "forecast_rolling_origin.v1",
        "run:active",
        {
            "target_column": "y",
            "capability_id": "forecast.v1",
            "cohort": "forecast.v1",
            "protocol_version": "forecast-rolling-origin/v1",
            "horizon": 1,
            "folds": 2,
        },
    )

    failed = compile_evidence_pack(project, source=RunSource("run_001"), requests=(request,)).records[0]
    assert failed.status == "failed"
    assert failed.failure_code == "CAPABILITY_NOT_REGISTERED"

    completed = compile_evidence_pack(
        project,
        source=RunSource("run_001"),
        requests=(request,),
        capabilities={
            "forecast.v1": {
                "cohort": "forecast.v1",
                "protocol_version": "forecast-rolling-origin/v1",
                "horizon": 1,
                "folds": 2,
            }
        },
    ).records[0]
    assert completed.status == "completed"
    assert "fitted_model" not in completed.observations
    assert "metrics" in completed.to_dict()


def test_unsupported_raw_source_is_typed_failure(tmp_path: Path) -> None:
    raw = tmp_path / "outside.csv"
    raw.write_text("x\n1\n", encoding="utf-8")
    record = compile_evidence_pack(
        tmp_path,
        source=raw,
        requests=(InspectionRequest("profile.v1", "run:active", {}),),
    ).records[0]

    assert record.status == "failed"
    assert record.failure_code == "UNSUPPORTED_SOURCE"
    assert "raw_path" not in json.dumps(record.to_dict())


def test_service_persists_pack_before_context_can_reference_it(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _raw_run(project)
    service = NotebookService(project)
    notebook = service.ensure_default_projection(from_run_id="run_001", created_by="test")
    trace = make_trace(project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id)

    pack = service.compile_evidence_pack(
        notebook.notebook_id,
        requests=(InspectionRequest("profile.v1", "run:active", {"max_rows": 5}),),
        trace=trace,
    )
    assert NotebookStore(project).read_evidence_pack(
        notebook.notebook_id, pack.evidence_pack_hash
    ) is not None
    context = service.compile_context(notebook.notebook_id)
    assert context.evidence_pack_refs == [pack.evidence_pack_hash]
    events = trace.replay(project, trace.trace_id)
    assert [event["event_type"] for event in events] == [
        "evidence.inspection.requested/v1",
        "evidence.inspection.completed/v1",
    ]


def test_dataset_source_uses_verified_upload_identity(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sha = store_upload_bytes(
        project,
        b"id,y,notes\n1,10,hello\n2,11,world\n",
        filename="observations.csv",
    )
    record = compile_evidence_pack(
        project,
        source=DatasetSource(sha, "observations.csv"),
        requests=(InspectionRequest("profile.v1", "dataset:active", {}),),
    ).records[0]

    assert record.status == "completed"
    assert record.source_refs == (f"dataset_profile:{sha}",)
