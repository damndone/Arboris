from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_notebook_support import make_project, make_run
from workbench.api import app
from workbench.artifacts import sha256_file


def _index(run_root: Path, record: dict[str, object]) -> None:
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record]}),
        encoding="utf-8",
    )


def test_artifact_download_verifies_indexed_sha256(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="artifact-integrity")
    run_root = make_run(project, "run-1")
    artifact = run_root / "classification_evidence.json"
    artifact.write_text('{"payload_schema":"workbench.prediction.classification-evidence"}', encoding="utf-8")
    _index(
        run_root,
        {
            "artifact_id": "classification_evidence",
            "path": artifact.name,
            "artifact_type": "classification_evidence",
            "step": "classification",
            "sha256": sha256_file(artifact),
        },
    )

    response = TestClient(app).get(
        "/runs/run-1/artifacts/classification_evidence",
        params={"project_root": str(project)},
    )

    assert response.status_code == 200, response.text
    assert "classification-evidence" in response.text


def test_typed_evidence_download_fails_closed_on_hash_mismatch(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="artifact-integrity-mismatch")
    run_root = make_run(project, "run-1")
    artifact = run_root / "classification_evidence.json"
    artifact.write_text('{"secret":"must not be served as evidence"}', encoding="utf-8")
    _index(
        run_root,
        {
            "artifact_id": "classification_evidence",
            "path": artifact.name,
            "artifact_type": "classification_evidence",
            "step": "classification",
            "sha256": "0" * 64,
        },
    )

    response = TestClient(app).get(
        "/runs/run-1/artifacts/classification_evidence",
        params={"project_root": str(project)},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ARTIFACT_INTEGRITY_MISMATCH"
    assert "secret" not in response.text


def test_typed_evidence_download_rejects_placeholder_digest(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="artifact-integrity-placeholder")
    run_root = make_run(project, "run-1")
    artifact = run_root / "classification_evidence.json"
    artifact.write_text("{}", encoding="utf-8")
    _index(
        run_root,
        {
            "artifact_id": "classification_evidence",
            "path": artifact.name,
            "artifact_type": "classification_evidence",
            "step": "classification",
            "sha256": "placeholder",
        },
    )

    response = TestClient(app).get(
        "/runs/run-1/artifacts/classification_evidence",
        params={"project_root": str(project)},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ARTIFACT_INTEGRITY_UNVERIFIED"
