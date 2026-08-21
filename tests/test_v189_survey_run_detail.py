from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from test_v189_survey_central_consumer import _materialize_survey_run


def test_run_detail_exposes_the_server_owned_survey_report_projection(tmp_path: Path) -> None:
    project_root, run_root = _materialize_survey_run(tmp_path, model_type="ols")

    response = TestClient(app).get(
        f"/runs/{run_root.name}",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200
    body = response.json()
    evidence = body["survey_evidence"]
    assert body["survey_evidence_authority"] == "server-owned"
    assert evidence["payload_schema"] == "workbench.survey.report-evidence.v1"
    assert evidence["consumer"] == "report"
    assert evidence["status"] == "validated"
    assert evidence["model_family"] == "ols"
    assert evidence["source"]["server_identity"]["run_id"] == run_root.name
    assert body["survey_evidence_receipt"]["kind"] == "evidence.survey.server-receipt.v1"
    assert body["survey_evidence_receipt"]["identity"]["runId"] == run_root.name
    assert "model_results/" not in json.dumps(evidence, sort_keys=True)


def test_run_detail_keeps_missing_survey_evidence_typed_unavailable(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-no-survey"
    run_root.mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps({"run_id": run_root.name, "status": "completed", "lineage": []}),
        encoding="utf-8",
    )
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    response = TestClient(app).get(
        f"/runs/{run_root.name}",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200
    evidence = response.json()["survey_evidence"]
    assert evidence["payload_schema"] == "workbench.survey.report-evidence.v1"
    assert evidence["status"] == "unavailable"
    assert evidence["reason"] in {
        "SURVEY_PERSISTED_ARTIFACT_REQUIRED",
        "SURVEY_PERSISTED_ARTIFACT_UNAVAILABLE",
        "SURVEY_RUN_CAPABILITY_MINT_INVALID",
    }
    assert "raw" not in json.dumps(evidence, sort_keys=True).lower()
    assert response.json()["survey_evidence_receipt"] is None
