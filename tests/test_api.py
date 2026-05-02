from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench import api
from workbench.api import app


@pytest.fixture
def completed_run(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    return client, project_root, run_response.json()["run_id"]


def test_api_creates_project_and_runs_upload(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    assert response.status_code == 200
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"


def test_api_rejects_oversized_upload_and_cleans_temp_dir(
    tmp_path: Path, monkeypatch
):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = Path(response.json()["project_root"])
    (project_root / "config.yml").write_text(
        "max_single_file_gb: 0.000000001\n", encoding="utf-8"
    )
    original_temp_dir = api.tempfile.TemporaryDirectory

    def tracked_temp_dir(prefix: str):
        return original_temp_dir(prefix=prefix, dir=tmp_path)

    monkeypatch.setattr(api.tempfile, "TemporaryDirectory", tracked_temp_dir)
    data = tmp_path / "large.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")

    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": str(project_root), "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("large.csv", handle, "text/csv")},
        )

    assert run_response.status_code == 413
    assert not list(tmp_path.glob("workbench_upload_*"))


def test_list_runs_returns_summary_for_completed_run(completed_run):
    client, project_root, _run_id = completed_run

    list_response = client.get("/runs", params={"project_root": project_root})

    assert list_response.status_code == 200
    payload = list_response.json()
    assert "runs" in payload
    assert len(payload["runs"]) == 1
    summary = payload["runs"][0]
    assert summary["status"] == "completed"
    assert summary["mode"] == "auto"
    assert summary["y"] == "y"
    assert summary["x"] == ["x"]
    assert "started_at" in summary
    assert "run_id" in summary


def test_list_runs_returns_empty_for_project_with_no_runs(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]

    list_response = client.get("/runs", params={"project_root": project_root})

    assert list_response.status_code == 200
    assert list_response.json() == {"runs": []}


def test_list_runs_returns_invalid_path_for_missing_project(tmp_path: Path):
    client = TestClient(app)
    list_response = client.get(
        "/runs", params={"project_root": str(tmp_path / "does_not_exist")}
    )

    assert list_response.status_code == 404
    assert list_response.json() == {
        "error": {
            "code": "PROJECT_NOT_FOUND",
            "message": f"Project not found: {tmp_path / 'does_not_exist'}",
            "details": {"project_root": str(tmp_path / "does_not_exist")},
        }
    }


def test_get_run_detail_returns_artifact_counts(completed_run):
    client, project_root, run_id = completed_run

    detail_response = client.get(
        f"/runs/{run_id}", params={"project_root": project_root}
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run_id"] == run_id
    assert detail["status"] == "completed"
    assert detail["y"] == "y"
    assert detail["x"] == ["x"]
    assert "artifact_counts" in detail
    assert isinstance(detail["artifact_counts"], dict)
    assert sum(detail["artifact_counts"].values()) > 0
    assert detail["errors"] == {"issues": []}


def test_get_run_detail_returns_run_not_found(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]

    detail_response = client.get(
        "/runs/missing-run", params={"project_root": project_root}
    )

    assert detail_response.status_code == 404
    assert detail_response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_resolve_run_root_rejects_path_escape(tmp_path: Path):
    from workbench.api import _resolve_run_root
    from workbench.api_errors import WorkbenchAPIError

    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]

    with pytest.raises(WorkbenchAPIError) as exc_info:
        _resolve_run_root(project_root, "../escape")

    assert exc_info.value.code == "INVALID_PATH"
    assert exc_info.value.status_code == 400
