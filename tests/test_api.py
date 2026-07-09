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


def test_create_project_invalid_parent_returns_structured_422(tmp_path: Path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("not a directory", encoding="utf-8")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/projects",
        json={"parent": str(parent_file), "name": "demo"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "INVALID_PATH"
    assert "parent" in payload["error"]["details"]


def test_create_project_rejects_dot_names(tmp_path: Path):
    client = TestClient(app, raise_server_exceptions=False)

    for name in (".", ".."):
        response = client.post(
            "/projects",
            json={"parent": str(tmp_path), "name": name},
        )
        assert response.status_code == 422
        payload = response.json()
        assert payload["error"]["code"] == "INVALID_PATH"
        assert payload["error"]["details"]["field"] == "name"
    # The rejected attempts must not scaffold project files at or above parent.
    assert not (tmp_path / "project.yaml").exists()
    assert not (tmp_path.parent / "project.yaml").exists()


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
    # Drain rr2 so its background thread releases the process-global run slot
    # before the next slot-acquiring test — otherwise the leftover run 429s the
    # next test under a combined `-k` selection (full gate stays green because
    # intervening tests give the run time to finish).
    run_id2 = rr2.json()["run_id"]
    import time
    for _ in range(120):
        detail = client.get(f"/runs/{run_id2}", params={"project_root": proot2})
        if detail.json()["status"] in ("completed", "blocked", "failed"):
            break
        time.sleep(0.5)
    time.sleep(0.2)


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
    assert detail["model_results"][0]["model_id"] == "ols_1"
    assert "x" in detail["model_results"][0]["coefficients"]


def test_get_run_detail_normalizes_stale_categorical_candidate(tmp_path: Path):
    from workbench.artifacts import write_json
    from workbench.projects import create_project, create_run

    client = TestClient(app)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    write_json(
        run.root / "run_manifest.json",
        {
            "run_id": run.run_id,
            "status": "completed",
            "mode": "auto",
            "started_at": "2026-05-08T00:00:00+00:00",
            "y": "continuous_score_y",
            "x": ["x7_region_code"],
            "lineage": [],
        },
    )
    write_json(
        run.root / "errors.json",
        {
            "issues": [
                {
                    "severity": "INFO",
                    "code": "CATEGORICAL_CANDIDATE",
                    "message": "Column 'x7_region_code' may be categorical (3 unique values). Consider one-hot encoding.",
                    "evidence": {"column": "x7_region_code", "nunique": 3},
                }
            ]
        },
    )
    write_json(
        run.root / "model_results" / "ols_1.json",
        {
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "coefficients": {
                "Intercept": {"estimate": 1.0},
                "C(Q('x7_region_code'))[T.region_B]": {"estimate": 0.2},
            },
        },
    )

    detail_response = client.get(
        f"/runs/{run.run_id}", params={"project_root": str(project.root)}
    )

    assert detail_response.status_code == 200
    issues = detail_response.json()["errors"]["issues"]
    assert not any(issue["code"] == "CATEGORICAL_CANDIDATE" for issue in issues)
    auto_dummy = [i for i in issues if i["code"] == "CATEGORICAL_AUTO_DUMMY_CODED"]
    assert len(auto_dummy) == 1
    assert auto_dummy[0]["severity"] == "INFO"
    assert auto_dummy[0]["code"] == "CATEGORICAL_AUTO_DUMMY_CODED"
    assert auto_dummy[0]["message"] == (
        "Column 'x7_region_code' was detected as categorical and automatically dummy-coded."
    )
    assert auto_dummy[0]["evidence"] == {"column": "x7_region_code", "preprocessing": "dummy_coded"}
    assert auto_dummy[0]["affected_stage"] == "data_cleaning"
    assert auto_dummy[0]["variables"] == ["x7_region_code"]
    assert auto_dummy[0]["template_key"] == "categorical_auto_dummy"
    assert auto_dummy[0]["issue_id"] == ""
    assert auto_dummy[0]["metric"] == ""
    assert auto_dummy[0]["value"] is None
    assert auto_dummy[0]["threshold"] is None
    assert auto_dummy[0]["recommended_action_key"] == ""
    assert auto_dummy[0]["is_user_action_required"] is False


def test_get_run_detail_returns_diagnostic_summary_preview(completed_run):
    client, project_root, run_id = completed_run

    detail_response = client.get(
        f"/runs/{run_id}", params={"project_root": project_root}
    )

    assert detail_response.status_code == 200
    preview = detail_response.json()["diagnostic_summary_preview"]
    assert preview["available"] is True
    assert preview["preview_contract_version"] == "1.0"
    assert preview["preview_status"] == "complete"
    assert preview["run_lifecycle_status"] == "completed"
    assert "run_status" in preview
    assert "trust_label" in preview
    assert "trust_counts" in preview
    assert "model_identity" in preview
    assert "primary_reasons" in preview
    assert "artifact_manifest" in preview
    assert "diagnostic_highlights" in preview
    assert "recommended_actions" in preview


def test_running_run_returns_pending_preview(tmp_path: Path):
    """A manually-written 'running' manifest returns preview_status=pending
    only when the worker is still active."""
    from workbench.artifacts import write_json
    from workbench.events import get_event_manager
    from workbench.projects import create_project, create_run

    client = TestClient(app)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    write_json(
        run.root / "run_manifest.json",
        {
            "run_id": run.run_id,
            "status": "running",
            "mode": "auto",
            "started_at": "2026-05-11T00:00:00+00:00",
            "y": "y", "x": ["x1"],
            "lineage": [],
        },
    )
    # Register the run as active so _mark_interrupted_if_dead leaves it alone
    events = get_event_manager()
    events.register_run(run.run_id)
    events.mark_active(run.run_id)

    detail_response = client.get(
        f"/runs/{run.run_id}", params={"project_root": str(project.root)}
    )

    assert detail_response.status_code == 200
    preview = detail_response.json()["diagnostic_summary_preview"]
    assert preview["available"] is False
    assert preview["preview_status"] == "pending"
    assert preview["trust_label"] == "analysis_running"
    assert preview["run_lifecycle_status"] == "running"


def test_legacy_run_without_diagnostic_summary_returns_legacy_fallback(tmp_path: Path):
    """Completed run with no diagnostic_summary.json → legacy_unavailable."""
    from workbench.artifacts import write_json
    from workbench.projects import create_project, create_run

    client = TestClient(app)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    write_json(
        run.root / "run_manifest.json",
        {
            "run_id": run.run_id,
            "status": "completed",
            "mode": "auto",
            "started_at": "2026-05-11T00:00:00+00:00",
            "y": "y", "x": ["x1"],
            "lineage": [],
        },
    )

    detail_response = client.get(
        f"/runs/{run.run_id}", params={"project_root": str(project.root)}
    )

    assert detail_response.status_code == 200
    preview = detail_response.json()["diagnostic_summary_preview"]
    assert preview["available"] is False
    assert preview["preview_status"] == "unavailable"
    assert preview["trust_label"] == "legacy_unavailable"
    assert any("missing" in w for w in preview["contract_warnings"])


def test_malformed_diagnostic_summary_via_api_returns_contract_unavailable(tmp_path: Path):
    """diagnostic_summary.json with invalid JSON → contract_unavailable."""
    from workbench.artifacts import write_json
    from workbench.projects import create_project, create_run

    client = TestClient(app)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    write_json(
        run.root / "run_manifest.json",
        {
            "run_id": run.run_id,
            "status": "completed",
            "mode": "auto",
            "started_at": "2026-05-11T00:00:00+00:00",
            "y": "y", "x": ["x1"],
            "lineage": [],
        },
    )
    (run.root / "diagnostic_summary.json").write_text("not json", encoding="utf-8")

    detail_response = client.get(
        f"/runs/{run.run_id}", params={"project_root": str(project.root)}
    )

    assert detail_response.status_code == 200
    preview = detail_response.json()["diagnostic_summary_preview"]
    assert preview["available"] is False
    assert preview["preview_status"] == "malformed"
    assert preview["trust_label"] == "contract_unavailable"


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


# --- V1.2.2 async/SSE tests ---

import threading


def test_post_runs_returns_immediately_running(tmp_path: Path):
    """POST returns immediately with status 'running', proven by blocking worker."""
    from workbench.orchestrator import _run_workflow as orig_run

    client = TestClient(app)
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    proot = r.json()["project_root"]

    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    blocker = threading.Event()
    def _slow_run(*args, **kwargs):
        blocker.wait()
        return {"run_id": "x", "status": "completed"}

    import workbench.api as api_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(api_mod, "_run_workflow", _slow_run)

    try:
        with data.open("rb") as handle:
            rr = client.post(
                "/runs",
                data={"project_root": proot, "mode": "auto", "y": "y", "x": "x"},
                files={"file": ("data.csv", handle, "text/csv")},
            )
        assert rr.status_code == 200
        body = rr.json()
        assert body["status"] == "running"
        assert "run_id" in body
    finally:
        blocker.set()
        monkeypatch.undo()


def test_post_runs_429_when_busy(tmp_path: Path):
    """Second concurrent POST returns 429 when worker slot is occupied."""
    from workbench.orchestrator import _run_workflow as orig_run

    client = TestClient(app)
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    proot = r.json()["project_root"]

    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    blocker = threading.Event()
    def _slow_run(*args, **kwargs):
        blocker.wait()
        return {"run_id": "x", "status": "completed"}

    import workbench.api as api_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(api_mod, "_run_workflow", _slow_run)

    try:
        with data.open("rb") as handle:
            rr1 = client.post(
                "/runs",
                data={"project_root": proot, "mode": "auto", "y": "y", "x": "x"},
                files={"file": ("data.csv", handle, "text/csv")},
            )
        assert rr1.status_code == 200

        with data.open("rb") as handle:
            rr2 = client.post(
                "/runs",
                data={"project_root": proot, "mode": "auto", "y": "y", "x": "x"},
                files={"file": ("data.csv", handle, "text/csv")},
            )
        assert rr2.status_code == 429
    finally:
        blocker.set()
        monkeypatch.undo()


def test_sse_streams_step_events(tmp_path: Path):
    """SSE endpoint streams step_start, step_complete, and a terminal event."""
    client = TestClient(app)
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    proot = r.json()["project_root"]

    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    with data.open("rb") as handle:
        rr = client.post(
            "/runs",
            data={"project_root": proot, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert rr.status_code == 200
    run_id = rr.json()["run_id"]

    events_seen: list[str] = []
    terminal_seen = False
    import time
    # Poll the run first to make sure it completes (so SSE has full history)
    for _ in range(120):
        d = client.get(f"/runs/{run_id}", params={"project_root": proot})
        if d.json()["status"] in ("completed", "blocked", "failed"):
            break
        time.sleep(0.5)

    # Connect SSE after completion; should get snapshot replay
    with client.stream(
        "GET", f"/runs/{run_id}/events", params={"project_root": proot}
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event: "):
                event_name = line[len("event: "):].strip()
                events_seen.append(event_name)
                if event_name.startswith("workflow_"):
                    terminal_seen = True
                    break

    assert terminal_seen
    assert any(e == "step_start" for e in events_seen)
    assert any(e == "step_complete" for e in events_seen)


def test_sse_replay_on_reconnect(tmp_path: Path):
    """A late SSE connection receives snapshot replay of past events."""
    client = TestClient(app)
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    proot = r.json()["project_root"]

    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    with data.open("rb") as handle:
        rr = client.post(
            "/runs",
            data={"project_root": proot, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert rr.status_code == 200
    run_id = rr.json()["run_id"]

    import time
    for _ in range(120):
        d = client.get(f"/runs/{run_id}", params={"project_root": proot})
        if d.json()["status"] in ("completed", "blocked", "failed"):
            break
        time.sleep(0.5)
    time.sleep(0.5)  # let cleanup thread settle

    # Second SSE connection: should get same events via snapshot replay
    events2: list[str] = []
    terminal2 = False
    with client.stream(
        "GET", f"/runs/{run_id}/events", params={"project_root": proot}
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event: "):
                event_name = line[len("event: "):].strip()
                events2.append(event_name)
                if event_name.startswith("workflow_"):
                    terminal2 = True
                    break

    assert terminal2
    assert any(e == "step_start" for e in events2)
    assert any(e == "step_complete" for e in events2)


def test_sse_interrupted_for_dead_run(tmp_path: Path):
    """Manually-written 'running' manifest with no worker → SSE returns interrupted."""
    from workbench.projects import create_project, create_run
    from workbench.orchestrator import _write_manifest, _lineage
    from workbench.artifacts import write_json
    from datetime import datetime, timezone

    client = TestClient(app)
    proot = tmp_path / "demo"
    create_project(tmp_path, "demo")
    run = create_run(proot, mode="auto")
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([tmp_path / "data.csv"]),
        started_at=datetime.now(timezone.utc).isoformat(),
        y="y", x=["x"],
    )

    with client.stream(
        "GET", f"/runs/{run.run_id}/events",
        params={"project_root": str(proot)},
    ) as stream:
        events: list[str] = []
        for line in stream.iter_lines():
            if line.startswith("event: "):
                events.append(line[len("event: "):].strip())

    assert "workflow_interrupted" in events

    # Verify errors.json was written
    errors_path = run.root / "errors.json"
    assert errors_path.is_file()
    errors = json.loads(errors_path.read_text())
    codes = [i["code"] for i in errors.get("issues", [])]
    assert "WORKFLOW_INTERRUPTED" in codes


def test_post_runs_file_persisted_in_run_dir(tmp_path: Path):
    """Uploaded file is saved under _uploads/ in the run directory, not temp."""
    client = TestClient(app)
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    proot = Path(r.json()["project_root"])

    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    with data.open("rb") as handle:
        rr = client.post(
            "/runs",
            data={"project_root": str(proot), "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert rr.status_code == 200
    run_id = rr.json()["run_id"]

    uploads_dir = proot / "runs" / run_id / "_uploads"
    assert uploads_dir.is_dir()
    assert (uploads_dir / "data.csv").is_file()

    # Manifest lineage should reference the persistent path
    import time
    for _ in range(120):
        d = client.get(f"/runs/{run_id}", params={"project_root": str(proot)})
        if d.json()["status"] in ("completed", "blocked", "failed"):
            break
        time.sleep(0.5)

    detail = client.get(f"/runs/{run_id}", params={"project_root": str(proot)})
    lineage = detail.json().get("lineage", [])
    assert any("_uploads" in l.get("source", "") for l in lineage)


def test_runs_rejects_missing_project_with_404(tmp_path: Path):
    client = TestClient(app)
    data = tmp_path / "data.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")
    missing = tmp_path / "does_not_exist"
    with data.open("rb") as handle:
        resp = client.post(
            "/runs",
            data={"project_root": str(missing), "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_batch_runs_rejects_missing_project_with_404(tmp_path: Path):
    client = TestClient(app)
    data = tmp_path / "data.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")
    missing = tmp_path / "does_not_exist"
    with data.open("rb") as handle:
        resp = client.post(
            "/runs/batch",
            data={"project_root": str(missing), "mode": "auto", "y_list": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"
