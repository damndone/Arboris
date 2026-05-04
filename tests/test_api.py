import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench import api
from workbench.api import app
from workbench.events import get_event_manager


@pytest.fixture(autouse=True)
def _reset_event_manager():
    get_event_manager()._reset_for_testing()


@pytest.fixture
def completed_run(tmp_path: Path):
    import time
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
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]
    # Poll until terminal (POST is now async)
    for _ in range(120):
        detail = client.get(
            f"/runs/{run_id}", params={"project_root": project_root}
        )
        status = detail.json()["status"]
        if status in ("completed", "blocked", "failed"):
            break
        time.sleep(0.5)
    else:
        pytest.fail(f"Run {run_id} did not reach terminal status within 60s")
    # Give the background thread a moment to release its slot
    time.sleep(0.2)
    return client, project_root, run_id


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
    assert run_response.json()["status"] == "running"
    # Wait for background thread to finish so slot is released for next test
    run_id = run_response.json()["run_id"]
    import time
    for _ in range(120):
        detail = client.get(
            f"/runs/{run_id}", params={"project_root": project_root}
        )
        if detail.json()["status"] in ("completed", "blocked", "failed"):
            break
        time.sleep(0.5)
    time.sleep(0.2)


def test_api_rejects_oversized_upload_and_slot_released(
    tmp_path: Path,
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
    data = tmp_path / "large.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")

    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": str(project_root), "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("large.csv", handle, "text/csv")},
        )

    assert run_response.status_code == 413
    # Slot should be released — a subsequent run in a different project should succeed
    r2 = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo2"},
    )
    proot2 = r2.json()["project_root"]
    small = tmp_path / "small.csv"
    pd.DataFrame({"y": [1, 2, 3], "x": [4, 5, 6]}).to_csv(small, index=False)
    with small.open("rb") as handle:
        rr2 = client.post(
            "/runs",
            data={"project_root": str(proot2), "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("small.csv", handle, "text/csv")},
        )
    assert rr2.status_code == 200
    assert rr2.json()["status"] == "running"


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


def test_list_artifacts_groups_by_type(completed_run):
    client, project_root, run_id = completed_run

    artifacts_response = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    )

    assert artifacts_response.status_code == 200
    payload = artifacts_response.json()
    assert "groups" in payload
    by_type = {group["artifact_type"]: group for group in payload["groups"]}
    assert "report" in by_type
    assert "model_result" in by_type
    report_items = by_type["report"]["items"]
    assert any(item["artifact_id"] == "report_html" for item in report_items)
    for group in payload["groups"]:
        for item in group["items"]:
            assert "artifact_id" in item
            assert "path" in item
            assert "step" in item


def test_download_artifact_returns_file_with_attachment_disposition(completed_run):
    client, project_root, run_id = completed_run

    download_response = client.get(
        f"/runs/{run_id}/artifacts/report_html",
        params={"project_root": project_root},
    )

    assert download_response.status_code == 200
    assert "attachment" in download_response.headers["content-disposition"]
    assert b"<html" in download_response.content.lower()


def test_download_artifact_returns_artifact_not_found(completed_run):
    client, project_root, run_id = completed_run

    download_response = client.get(
        f"/runs/{run_id}/artifacts/does_not_exist",
        params={"project_root": project_root},
    )

    assert download_response.status_code == 404
    assert download_response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


def test_resolve_artifact_path_rejects_escape(tmp_path: Path):
    from workbench.api import _resolve_artifact_path
    from workbench.api_errors import WorkbenchAPIError

    run_root = tmp_path / "runs" / "r1"
    run_root.mkdir(parents=True)
    record = {"artifact_id": "x", "path": "../../etc/passwd"}

    with pytest.raises(WorkbenchAPIError) as exc_info:
        _resolve_artifact_path(run_root, record)

    assert exc_info.value.code == "INVALID_PATH"
    assert exc_info.value.status_code == 400


def test_download_artifact_returns_not_found_when_file_missing_on_disk(completed_run):
    client, project_root, run_id = completed_run

    # Registry says the report exists; delete the actual file behind it.
    report_file = Path(project_root) / "runs" / run_id / "reports" / "report.html"
    assert report_file.is_file()
    report_file.unlink()

    download_response = client.get(
        f"/runs/{run_id}/artifacts/report_html",
        params={"project_root": project_root},
    )

    assert download_response.status_code == 404
    assert download_response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


def test_get_report_returns_html(completed_run):
    client, project_root, run_id = completed_run

    report_response = client.get(
        f"/runs/{run_id}/report", params={"project_root": project_root}
    )

    assert report_response.status_code == 200
    assert report_response.headers["content-type"].startswith("text/html")
    assert b"<html" in report_response.content.lower()


def test_get_report_returns_report_not_found_when_missing(tmp_path: Path):
    from workbench.projects import create_project, create_run

    create_project(tmp_path, "demo")
    project_root = tmp_path / "demo"
    run = create_run(project_root, mode="auto")

    client = TestClient(app)
    report_response = client.get(
        f"/runs/{run.run_id}/report", params={"project_root": str(project_root)}
    )

    assert report_response.status_code == 404
    assert report_response.json()["error"]["code"] == "REPORT_NOT_FOUND"


def test_artifacts_index_missing_schema_version_is_ok(tmp_path: Path):
    from workbench.api import _read_artifacts_index
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"artifacts": [{"artifact_id": "a", "path": "a.txt", "artifact_type": "data", "step": "ingest", "sha256": "x"}]}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")
    (run_root / "a.txt").write_text("content", encoding="utf-8")

    data = _read_artifacts_index(run_root)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["artifact_id"] == "a"


def test_artifacts_index_version_1_is_ok(tmp_path: Path):
    from workbench.api import _read_artifacts_index
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": 1, "artifacts": [{"artifact_id": "a", "path": "a.txt", "artifact_type": "data", "step": "ingest", "sha256": "x"}]}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")
    (run_root / "a.txt").write_text("content", encoding="utf-8")

    data = _read_artifacts_index(run_root)
    assert len(data["artifacts"]) == 1


def test_artifacts_index_version_2_rejected(tmp_path: Path):
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": 2, "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_UNSUPPORTED"


def test_artifacts_index_version_string_rejected(tmp_path: Path):
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": "1", "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_INVALID"


def test_artifacts_index_version_zero_rejected(tmp_path: Path):
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": 0, "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_INVALID"


def test_artifacts_index_version_bool_true_rejected(tmp_path: Path):
    """JSON boolean true is an int subclass in Python; must be rejected."""
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": True, "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_INVALID"


def test_artifacts_list_and_download_use_schema_validated_index(completed_run):
    client, project_root, run_id = completed_run

    list_resp = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    )
    assert list_resp.status_code == 200
    assert "groups" in list_resp.json()

    dl_resp = client.get(
        f"/runs/{run_id}/artifacts/report_html",
        params={"project_root": project_root},
    )
    assert dl_resp.status_code == 200
