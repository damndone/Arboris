from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app
from workbench.lineage.headset import _dataset_artifacts


def _request(run_id: str, artifact_id: str) -> dict:
    return {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "summarize",
        "selected_columns": ["bdsnew", "pfl"],
        "filters": [
            {"column": "year", "operator": "eq", "value": 1998},
            {"column": "middle", "operator": "eq", "value": 0},
        ],
    }


def test_statistical_exploration_preview_confirm_is_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "year": [1998, 1998, 2002],
                "bdsnew": [101015, 531075, 250000],
                "middle": [0, 0, 1],
                "pfl": [6.3, 96.5, 25.0],
            }
        ),
    )

    with TestClient(app) as client:
        preview_response = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id),
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["status"] == "ready"
        assert preview["result"]["filtered_row_count"] == 2
        assert preview["fingerprint"]

        body = {
            **_request(run_id, artifact_id),
            "preview_fingerprint": preview["fingerprint"],
        }
        first = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json=body,
        )
        second = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json=body,
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_record = first.json()["exploration"]
    second_record = second.json()["exploration"]
    assert second_record == first_record
    index = json.loads((project / "runs" / run_id / "artifacts_index.json").read_text())
    records = index["artifacts"]
    assert len([item for item in records if item["artifact_type"] == "statistical_exploration"]) == 1
    assert len([item for item in records if item["artifact_type"] == "transcript"]) == 1
    assert (project / "runs" / run_id / first_record["path"]).is_file()
    assert (project / "runs" / run_id / first_record["transcript_path"]).is_file()
    exports = first.json()["exports"]
    assert {item["format"] for item in exports} == {"html", "pdf", "xlsx"}
    for item in exports:
        assert (project / "runs" / run_id / item["path"]).is_file()
    assert len([item for item in records if item["artifact_type"] == "report"]) == 2
    assert len([item for item in records if item["artifact_type"] == "table_export"]) == 1


def test_statistical_exploration_confirm_fails_closed_when_source_changes(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"year": [1998, 2002], "bdsnew": [1, 2], "middle": [0, 1]}),
    )

    with TestClient(app) as client:
        preview = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json={**_request(run_id, artifact_id), "selected_columns": ["bdsnew"]},
        ).json()["preview"]
        source_path = project / "runs" / run_id / "data.csv"
        source_path.write_text(source_path.read_text() + "3,3,0\n", encoding="utf-8")
        response = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id),
                "selected_columns": ["bdsnew"],
                "preview_fingerprint": preview["fingerprint"],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STATISTICAL_EXPLORATION_STALE"


def test_statistical_exploration_routes_reject_untyped_extra_fields(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"year": [1998], "bdsnew": [1]}),
    )
    response = TestClient(app).post(
        "/statistical-explorations/preview",
        params={"project_root": str(project)},
        json={**_request(run_id, artifact_id), "python_expression": "bdsnew + 1"},
    )

    assert response.status_code == 422


def test_raw_node_graph_decoration_exposes_compact_exploration_metadata(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"year": [1998, 2002], "bdsnew": [1, 2]}),
    )
    with TestClient(app) as client:
        preview = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id),
                "selected_columns": ["bdsnew"],
                "filters": [],
            },
        ).json()["preview"]
        client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id),
                "selected_columns": ["bdsnew"],
                "filters": [],
                "preview_fingerprint": preview["fingerprint"],
            },
        )

    entries = _dataset_artifacts(project / "runs", run_id, "stage:source")
    exploration = [item for item in entries or [] if item.get("artifact_id", "").startswith("statistical_exploration_")]
    assert len(exploration) == 1
    assert exploration[0]["mime"] == "application/json"
    assert "result" not in exploration[0]
    assert "preview" not in exploration[0]
