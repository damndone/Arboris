from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app


def _v1_run_fixture(tmp_path: Path, *, missing_artifact: bool = False) -> tuple[TestClient, str, str]:
    """Create a project with one V1-shape run (no started_at/y/x, no schema_version).

    Returns (client, project_root, run_id).
    """
    client = TestClient(app)
    resp = client.post("/projects", json={"parent": str(tmp_path), "name": "v1test"})
    project_root = resp.json()["project_root"]
    run_root = Path(project_root) / "runs" / "v1-run"
    run_root.mkdir(parents=True)

    # V1 manifest — no started_at, y, x
    manifest = {
        "run_id": "v1-run",
        "mode": "auto",
        "status": "completed",
        "lineage": [],
    }
    (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Index without schema_version
    report_path = run_root / "reports" / "report.html"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html><body>OK</body></html>", encoding="utf-8")

    artifacts = [
        {
            "artifact_id": "report_html",
            "path": "reports/report.html",
            "artifact_type": "report",
            "step": "reporting",
            "sha256": "deadbeef",
        },
    ]
    if missing_artifact:
        artifacts.append({
            "artifact_id": "missing_file",
            "path": "data/missing.csv",
            "artifact_type": "data",
            "step": "ingest",
            "sha256": "x",
        })

    (run_root / "artifacts_index.json").write_text(
        json.dumps({"artifacts": artifacts}), encoding="utf-8"
    )

    return client, project_root, "v1-run"


class TestV1RunHappyPath:
    """A real V1 run (no started_at/y/x, no schema_version)
    must be fully readable by all V1.1 endpoints."""

    @pytest.fixture
    def v1_run(self, tmp_path: Path):
        return _v1_run_fixture(tmp_path)

    def test_list_runs_returns_null_for_missing_fields(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get("/runs", params={"project_root": project_root})
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 1
        r = runs[0]
        assert r["run_id"] == run_id
        assert r["status"] == "completed"
        assert r["started_at"] is None
        assert r["y"] is None
        assert r["x"] is None

    def test_run_detail_returns_null_fields_and_counts(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}", params={"project_root": project_root})
        assert resp.status_code == 200
        d = resp.json()
        assert d["run_id"] == run_id
        assert d["started_at"] is None
        assert d["y"] is None
        assert d["x"] is None
        assert "artifact_counts" in d
        assert d["artifact_counts"].get("report") == 1
        assert d["errors"] == {"issues": []}

    def test_list_artifacts_groups_correctly(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}/artifacts", params={"project_root": project_root})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        by_type = {g["artifact_type"]: g for g in groups}
        assert "report" in by_type
        items = by_type["report"]["items"]
        assert any(item["artifact_id"] == "report_html" for item in items)

    def test_download_artifact_returns_file(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(
            f"/runs/{run_id}/artifacts/report_html",
            params={"project_root": project_root},
        )
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert b"<html" in resp.content.lower()

    def test_get_report_returns_html(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}/report", params={"project_root": project_root})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert b"<html" in resp.content.lower()


class TestV1RunMissingArtifact:
    """When an artifact record exists but the file is missing on disk,
    list and detail must not fail; download must return 404."""

    @pytest.fixture
    def v1_run_broken(self, tmp_path: Path):
        return _v1_run_fixture(tmp_path, missing_artifact=True)

    def test_list_artifacts_includes_broken_record(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(f"/runs/{run_id}/artifacts", params={"project_root": project_root})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        all_items = [item for g in groups for item in g["items"]]
        artifact_ids = [item["artifact_id"] for item in all_items]
        assert "missing_file" in artifact_ids

    def test_detail_counts_include_broken_artifact(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(f"/runs/{run_id}", params={"project_root": project_root})
        assert resp.status_code == 200
        assert resp.json()["artifact_counts"].get("data") == 1

    def test_download_missing_returns_404(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(
            f"/runs/{run_id}/artifacts/missing_file",
            params={"project_root": project_root},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
