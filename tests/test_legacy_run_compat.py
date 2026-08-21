from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app


def _assert_unavailable_report_projection(projection: dict) -> None:
    assert projection["status"] == "unavailable"
    assert projection["availability"] == "unavailable"
    assert projection["validationStatus"] == "unavailable"
    assert projection["reasonCode"] == "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED"
    assert projection["facts"] == []


def _v1_run_fixture(tmp_path: Path) -> tuple[TestClient, str, str]:
    """Create a V1-shape run with durable typed model evidence but no Report owner.

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

    # Keep a raw legacy HTML file unindexed.  It must never become Report
    # authority or a downloadable artifact without owner-admitted evidence.
    report_path = run_root / "reports" / "report.html"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html><body>OK</body></html>", encoding="utf-8")

    model_path = run_root / "model_results" / "ols_1.json"
    model_path.parent.mkdir(parents=True)
    model_payload = json.dumps(
        {
            "model_type": "ols",
            "nobs": 2,
            "coefficients": {"x": {"estimate": 2.0}},
        },
        sort_keys=True,
    ).encode("utf-8")
    model_path.write_bytes(model_payload)
    artifacts = [
        {
            "artifact_id": "ols_1",
            "path": "model_results/ols_1.json",
            "artifact_type": "model_result",
            "step": "econometrics",
            "sha256": hashlib.sha256(model_payload).hexdigest(),
            "inputs": [],
            "config_hash": "",
            "code_version": "1.8.9",
        },
    ]

    (run_root / "artifacts_index.json").write_text(
        json.dumps({"artifacts": artifacts}), encoding="utf-8"
    )

    return client, project_root, "v1-run"


class TestV1RunHappyPath:
    """A V1-shaped run remains readable while Report stays owner-gated."""

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
        assert d["artifact_counts"].get("model_result") == 1
        assert "report" not in d["artifact_counts"]
        assert d["errors"] == {"issues": []}
        _assert_unavailable_report_projection(d["report_evidence"])

    def test_list_artifacts_groups_correctly(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}/artifacts", params={"project_root": project_root})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        by_type = {g["artifact_type"]: g for g in groups}
        assert "model_result" in by_type
        items = by_type["model_result"]["items"]
        assert any(item["artifact_id"] == "ols_1" for item in items)
        assert "report" not in by_type

    def test_download_artifact_returns_durable_model_file(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(
            f"/runs/{run_id}/artifacts/ols_1",
            params={"project_root": project_root},
        )
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.json()["model_type"] == "ols"
        assert resp.json()["coefficients"]["x"]["estimate"] == 2.0

    def test_get_report_returns_typed_unavailable_without_owner(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}/report", params={"project_root": project_root})
        assert resp.status_code == 409
        error = resp.json()["error"]
        assert error["code"] == "REPORT_EVIDENCE_UNAVAILABLE"
        _assert_unavailable_report_projection(error["details"]["projection"])


class TestV1RunMissingArtifact:
    """Unindexed legacy files do not change the typed artifact boundary."""

    @pytest.fixture
    def v1_run_broken(self, tmp_path: Path):
        return _v1_run_fixture(tmp_path)

    def test_list_artifacts_excludes_unindexed_legacy_report(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(f"/runs/{run_id}/artifacts", params={"project_root": project_root})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        all_items = [item for g in groups for item in g["items"]]
        artifact_ids = [item["artifact_id"] for item in all_items]
        assert artifact_ids == ["ols_1"]

    def test_detail_counts_include_durable_model_artifact(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(f"/runs/{run_id}", params={"project_root": project_root})
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["artifact_counts"].get("model_result") == 1
        assert "report" not in detail["artifact_counts"]
        _assert_unavailable_report_projection(detail["report_evidence"])

    def test_download_unindexed_artifact_returns_404(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(
            f"/runs/{run_id}/artifacts/missing_file",
            params={"project_root": project_root},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
