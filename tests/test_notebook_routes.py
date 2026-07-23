"""HTTP contract tests for the v1.8.1 Notebook lifecycle seam."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_notebook_support import make_project, make_run, model_rerun_proposal
from workbench.api import app
from workbench.lineage.upload_store import store_upload_bytes


def _persisted_run(project: Path, run_id: str, *, rerun_of: str | None = None) -> None:
    root = make_run(project, run_id, rerun_of=rerun_of)
    (root / "graph.json").write_text(
        json.dumps({"nodes": {"model": {"id": "model", "stage": "model"}}}),
        encoding="utf-8",
    )
    (root / "staged").mkdir()
    (root / "staged" / "data_profile.json").write_text(
        json.dumps({"columns": [{"name": "outcome", "dtype": "float64"}]}),
        encoding="utf-8",
    )
    (root / "errors.json").write_text(json.dumps({"issues": []}), encoding="utf-8")


def _create(client: TestClient, project: Path) -> dict:
    response = client.post(
        "/notebooks",
        params={"project_root": str(project)},
        json={
            "title": "Notebook route test",
            "created_by": "user_1",
            "analysis_contract": {"revision": 1, "target": "y"},
            "user_focus": {"selected_text_hash": "sha256:seed"},
            "available_capabilities": ["time_series.arma_garch"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _drafts() -> list[dict]:
    return [
        {
            "rank": 1,
            "rationale": "Use the robust covariance option as the first path.",
            "assumptions": ["The residual structure is stable."],
            "proposal": model_rerun_proposal("p1", covariance="robust"),
            "expected_artifacts": [
                {
                    "artifact_id": "ts.parameters",
                    "artifact_type": "time_series_json",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "option_id": "opt_route_1",
        }
    ]


def test_notebook_route_creates_reads_and_compiles_a_runless_notebook(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)

    notebook = _create(client, project)

    fetched = client.get(
        f"/notebooks/{notebook['notebook_id']}",
        params={"project_root": str(project)},
    )
    assert fetched.status_code == 200
    assert fetched.json()["run_family_id"] == notebook["run_family_id"]
    assert fetched.json()["active_head_run_id"] is None

    compiled = client.post(
        f"/notebooks/{notebook['notebook_id']}/context/compile",
        params={"project_root": str(project)},
    )
    assert compiled.status_code == 200, compiled.text
    assert compiled.json()["run_family_id"] == notebook["run_family_id"]
    assert compiled.json()["active_head_run_id"] is None
    assert compiled.json()["source_manifest"] == []
    assert compiled.json()["trace_id"].startswith("trace_")


def test_notebook_route_runs_option_lifecycle_through_artifact_validation(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    notebook = _create(client, project)
    notebook_id = notebook["notebook_id"]
    params = {"project_root": str(project)}

    proposed = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"drafts": _drafts()},
    )
    assert proposed.status_code == 200, proposed.text
    assert [option["option_id"] for option in proposed.json()["options"]] == [
        "opt_route_1"
    ]
    assert proposed.json()["options"][0]["freshness_status"] == "fresh"
    assert proposed.json()["context"]["active_head_run_id"] is None
    assert proposed.json()["trace_id"].startswith("trace_")

    snapshot = client.get(
        f"/notebooks/{notebook_id}/options",
        params=params,
    )
    assert snapshot.status_code == 200, snapshot.text
    assert [item["option_id"] for item in snapshot.json()["options"]] == [
        "opt_route_1"
    ]
    assert snapshot.json()["options"][0]["freshness_status"] == "fresh"

    trace = client.get(
        f"/notebooks/{notebook_id}/traces/{snapshot.json()['trace_id']}",
        params=params,
    )
    assert trace.status_code == 200, trace.text
    assert trace.json()["events"]
    assert trace.json()["events"][0]["trace_id"] == snapshot.json()["trace_id"]

    decision = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/decision",
        params=params,
        json={"decision": "selected", "actor": "user_1"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["lifecycle_status"] == "selected"

    confirmed = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/confirm",
        params=params,
        json={
            "option_revision": 1,
            "proposal_id": "p1",
            "proposal_revision": 1,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["execution"]["option_id"] == "opt_route_1"
    assert confirmed.json()["execution"]["run_id"] is None

    after_confirm = client.get(
        f"/notebooks/{notebook_id}/options",
        params=params,
    )
    assert after_confirm.status_code == 200, after_confirm.text
    assert after_confirm.json()["options"][0]["lifecycle_status"] == "executing"

    completed = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/execute",
        params=params,
        json={
            "execution_status": "succeeded",
            "produced_artifacts": [
                {
                    "artifact_id": "ts.parameters",
                    "artifact_type": "time_series_json",
                    "count": 1,
                    "step": None,
                }
            ],
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["execution_status"] == "succeeded"
    assert completed.json()["artifact_validation"]["validation_status"] == "passed"
    assert completed.json()["lifecycle_status"] == "executed"


def test_notebook_route_uses_server_planner_when_drafts_are_omitted(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    notebook = _create(client, project)

    response = client.post(
        f"/notebooks/{notebook['notebook_id']}/options/propose",
        params={"project_root": str(project)},
        json={"count": 3},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "NOTEBOOK_PLANNING_UNAVAILABLE"


def test_projection_route_binds_real_run_context_and_hashes_graph(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _persisted_run(project, "run_001")
    client = TestClient(app)

    projection = client.post(
        "/notebooks/projection",
        params={"project_root": str(project)},
        json={"from_run_id": "run_001", "created_by": "ui"},
    )
    assert projection.status_code == 200, projection.text
    notebook = projection.json()
    assert notebook["projection_source"] == {"kind": "run", "run_id": "run_001"}
    assert notebook["active_head_run_id"] == "run_001"

    context = client.post(
        f"/notebooks/{notebook['notebook_id']}/context/compile",
        params={"project_root": str(project)},
    )
    assert context.status_code == 200, context.text
    packet = context.json()
    assert packet["active_head_run_id"] == "run_001"
    assert packet["current_family_head_run_id"] == "run_001"
    assert packet["graph_hash"].startswith("sha256:")
    assert {item["kind"] for item in packet["source_manifest"]} >= {"graph", "errors"}


def test_projection_route_compiles_verified_dataset_without_inventing_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sha256 = store_upload_bytes(project, b"outcome,predictor\n1,2\n", filename="data.csv")
    client = TestClient(app)

    projection = client.post(
        "/notebooks/projection",
        params={"project_root": str(project)},
        json={
            "dataset": {"upload_sha256": sha256, "filename": "data.csv", "sheet_names": []},
            "created_by": "ui",
        },
    )
    assert projection.status_code == 200, projection.text
    notebook = projection.json()
    assert notebook["projection_source"]["kind"] == "dataset"
    assert notebook["active_head_run_id"] is None
    assert list((project / "runs").iterdir()) == []

    context = client.post(
        f"/notebooks/{notebook['notebook_id']}/context/compile",
        params={"project_root": str(project)},
    )
    assert context.status_code == 200, context.text
    packet = context.json()
    assert packet["active_head_run_id"] is None
    assert packet["current_family_head_run_id"] is None
    assert [column["name"] for column in packet["dataset_profile"]["columns"]] == [
        "outcome",
        "predictor",
    ]
    assert "rows" not in packet["dataset_profile"]


def test_projection_route_rejects_ambiguous_source(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/notebooks/projection",
        params={"project_root": str(project)},
        json={"created_by": "ui"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NOTEBOOK_PROJECTION_SOURCE_INVALID"


def test_external_family_focus_marks_options_stale_without_rebinding_source(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    _persisted_run(project, "run_001")
    _persisted_run(project, "run_002", rerun_of="run_001")
    client = TestClient(app)
    params = {"project_root": str(project)}
    projection = client.post(
        "/notebooks/projection",
        params=params,
        json={"from_run_id": "run_001", "created_by": "ui"},
    ).json()
    notebook_id = projection["notebook_id"]

    proposed = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"drafts": _drafts()},
    )
    assert proposed.status_code == 200, proposed.text

    after = client.get(
        f"/notebooks/{notebook_id}/options",
        params={**params, "focused_run_id": "run_002"},
    )
    assert after.status_code == 200, after.text
    assert after.json()["context"]["active_head_run_id"] == "run_001"
    assert after.json()["context"]["current_family_head_run_id"] == "run_002"
    assert after.json()["options"][0]["freshness_status"] == "stale"
    assert client.get(
        f"/notebooks/{notebook_id}", params=params
    ).json()["projection_source"] == {"kind": "run", "run_id": "run_001"}
