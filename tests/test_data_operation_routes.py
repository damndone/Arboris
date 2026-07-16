from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app


def _request(
    run_id: str,
    artifact_id: str,
    *,
    column: str = "age",
    target_dtype: str = "string",
) -> dict[str, str]:
    return {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "column": column,
        "target_dtype": target_dtype,
    }


def test_column_cast_routes_preview_confirm_and_reload_readback(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]}),
    )

    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id),
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["status"] == "ready"
        assert preview["column"] == "age"
        assert preview["before_dtype"] == "int64"
        assert preview["after_dtype"].startswith("string")

        confirm_response = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id),
                "preview_fingerprint": preview["fingerprint"],
                "session_id": "agent_data_ui",
            },
        )
        assert confirm_response.status_code == 200
        operation = confirm_response.json()["operation"]
        assert operation["operation_id"] == "data.column.cast"
        assert operation["actor_type"] == "human_ui"
        assert operation["status"] == "completed"

        readback = client.get(
            f"/data-operations/column-cast/{operation['record_id']}",
            params={"project_root": str(project)},
        )
        assert readback.status_code == 200
        assert readback.json()["operation"]["record_id"] == operation["record_id"]


def test_column_cast_context_resolves_existing_columns_from_dataset_node(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]}),
    )

    response = TestClient(app).get(
        "/data-operations/column-cast/context",
        params={
            "project_root": str(project),
            "source_run_id": run_id,
            "source_node_id": "stage:source",
        },
    )

    assert response.status_code == 200
    context = response.json()
    assert context["source_artifact_id"] == artifact_id
    assert context["source_node_id"] == "stage:source"
    assert context["columns"] == [
        {"name": "age", "dtype": "int64"},
        {"name": "name", "dtype": "str"},
    ]


def test_column_cast_confirm_fails_closed_when_preview_is_stale(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"]}),
    )

    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id),
        )
        preview = preview_response.json()["preview"]
        source_path = project / "runs" / run_id / "data.csv"
        source_path.write_text(source_path.read_text() + "12\n", encoding="utf-8")

        response = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id),
                "preview_fingerprint": preview["fingerprint"],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATA_OPERATION_STALE"


def test_column_cast_routes_reject_untyped_extra_fields(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"]}),
    )
    response = TestClient(app).post(
        "/data-operations/column-cast/preview",
        params={"project_root": str(project)},
        json={**_request(run_id, artifact_id), "python_expression": "float(age)"},
    )

    assert response.status_code == 422


def test_column_cast_confirm_is_idempotent_for_same_preview(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"]}),
    )

    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id),
        ).json()["preview"]
        body = {
            **_request(run_id, artifact_id),
            "preview_fingerprint": preview["fingerprint"],
        }
        first = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json=body,
        ).json()["operation"]
        second = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json=body,
        ).json()["operation"]

    assert second["record_id"] == first["record_id"]
    assert second["execution"]["bindings"] == first["execution"]["bindings"]
    artifacts = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text()
    )["artifacts"]
    assert len([item for item in artifacts if item["artifact_type"] == "derived_data"]) == 1


def test_column_cast_record_readback_by_child_node(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"]}),
    )

    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id),
        ).json()["preview"]
        confirmed = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id),
                "preview_fingerprint": preview["fingerprint"],
            },
        ).json()["operation"]
        child_node_id = confirmed["execution"]["bindings"]["data_child_node_id"]

        readback = client.get(
            "/data-operations/column-cast/by-child-node",
            params={"project_root": str(project), "child_node_id": child_node_id},
        )
        missing = client.get(
            "/data-operations/column-cast/by-child-node",
            params={"project_root": str(project), "child_node_id": "data-cast:unknown"},
        )

    assert readback.status_code == 200
    operation = readback.json()["operation"]
    assert operation["record_id"] == confirmed["record_id"]
    assert operation["status"] == "completed"
    assert operation["diff_ref"]["kind"] == "data.schema_diff.v1"
    assert operation["verification"]["passed"] is True
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DATA_OPERATION_NOT_FOUND"


def _batch_request(run_id, artifact_id, casts):
    return {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "casts": [{"column": c, "target_dtype": d} for c, d in casts],
    }


def test_columns_cast_routes_preview_confirm_reload_and_by_child(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"], "keep": [1, 2]}),
    )
    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/columns-cast/preview",
            params={"project_root": str(project)},
            json=_batch_request(run_id, artifact_id, [("age", "numeric"), ("city", "string")]),
        )
        assert preview.status_code == 200
        pv = preview.json()["preview"]
        assert pv["status"] == "ready"
        assert [i["column"] for i in pv["items"]] == ["age", "city"]

        confirm = client.post(
            "/data-operations/columns-cast/confirm",
            params={"project_root": str(project)},
            json={
                **_batch_request(run_id, artifact_id, [("age", "numeric"), ("city", "string")]),
                "preview_fingerprint": pv["fingerprint"],
            },
        )
        assert confirm.status_code == 200
        op = confirm.json()["operation"]
        assert op["operation_id"] == "data.columns.cast"
        assert op["status"] == "completed"
        child = op["execution"]["bindings"]["data_child_node_id"]
        assert child.startswith("data-casts:")

        # idempotent replay -> same record, one derived artifact
        again = client.post(
            "/data-operations/columns-cast/confirm",
            params={"project_root": str(project)},
            json={
                **_batch_request(run_id, artifact_id, [("age", "numeric"), ("city", "string")]),
                "preview_fingerprint": pv["fingerprint"],
            },
        ).json()["operation"]
        assert again["record_id"] == op["record_id"]

        # by-child-node readback resolves the batch record
        readback = client.get(
            "/data-operations/column-cast/by-child-node",
            params={"project_root": str(project), "child_node_id": child},
        )
        assert readback.status_code == 200
        assert readback.json()["operation"]["operation_id"] == "data.columns.cast"

    arts = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text()
    )["artifacts"]
    assert len([i for i in arts if i["artifact_type"] == "derived_data"]) == 1


def test_columns_cast_confirm_blocks_when_any_column_fails(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "x"], "city": ["a", "b"]}),
    )
    with TestClient(app) as client:
        pv = client.post(
            "/data-operations/columns-cast/preview",
            params={"project_root": str(project)},
            json=_batch_request(run_id, artifact_id, [("age", "numeric"), ("city", "string")]),
        ).json()["preview"]
        assert pv["status"] == "blocked"
        resp = client.post(
            "/data-operations/columns-cast/confirm",
            params={"project_root": str(project)},
            json={
                **_batch_request(run_id, artifact_id, [("age", "numeric"), ("city", "string")]),
                "preview_fingerprint": pv["fingerprint"],
            },
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "DATA_OPERATION_BLOCKED"


def test_columns_cast_rejects_duplicate_column(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"age": ["10", "11"]}))
    resp = TestClient(app).post(
        "/data-operations/columns-cast/preview",
        params={"project_root": str(project)},
        json=_batch_request(run_id, artifact_id, [("age", "numeric"), ("age", "string")]),
    )
    assert resp.status_code == 422
