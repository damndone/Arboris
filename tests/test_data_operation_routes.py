from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.artifacts import register_artifact, write_json
from workbench.graph_store import GraphStore
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


def _seed_confirmed_metadata(
    project: Path,
    run_id: str,
    source_artifact_id: str,
    metadata: dict[str, object],
    *,
    schema_revision: str = "schema:fixture-v1",
    metadata_revision: str = "metadata:fixture-v1",
    confirmed: bool = True,
) -> str:
    run_root = project / "runs" / run_id
    path = run_root / "metadata" / "registry.json"
    payload = {
        "payload_schema": "workbench.data-metadata",
        "schema_version": 1,
        "confirmed": confirmed,
        "schema_revision": schema_revision,
        "metadata_revision": metadata_revision,
        "source": {
            "run_id": run_id,
            "node_id": "stage:source",
            "artifact_id": source_artifact_id,
        },
        "metadata": metadata,
    }
    write_json(path, payload)
    artifact_id = "source_metadata_registry"
    register_artifact(
        run_root,
        artifact_id,
        path,
        "metadata",
        "fixture.metadata",
        [source_artifact_id],
    )
    return artifact_id


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


def test_feature_recipe_routes_preview_confirm_and_expose_typed_child(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"x": [2.0, 3.0], "z": [4.0, 5.0]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "recipe_id": "recipe_interaction",
        "operation_id": "interaction",
        "inputs": ["x", "z"],
        "output": "xz",
        "parameters": {"left": "x", "right": "z"},
    }
    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/feature-recipe/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["status"] == "ready"
        assert "xz" in preview["output_columns"]
        confirm_response = client.post(
            "/data-operations/feature-recipe/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    assert confirm_response.status_code == 200
    effect = confirm_response.json()["effect"]
    assert effect["child_node_id"].startswith("feature-recipe:")
    assert confirm_response.json()["confirmation"]["status"] == "confirmed"
    assert confirm_response.json()["proposal"]["operation_id"] == "data.feature_recipe"


def test_data_transform_routes_preview_confirm_subset(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20], "drop": [0, 1]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "subset",
        "parameters": {"columns": ["id", "value"], "equals": {"id": 2}},
    }
    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["row_count_after"] == 1
        confirm_response = client.post(
            "/data-operations/transform/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["effect"]["child_node_id"].startswith("data-subset:")
    assert confirm_response.json()["confirmation"]["status"] == "confirmed"
    assert confirm_response.json()["proposal"]["operation_id"] == "data.subset"


def test_data_operation_routes_require_a_project_runs_root(tmp_path: Path) -> None:
    project_without_runs = tmp_path / "not-a-workbench-project"
    project_without_runs.mkdir()

    response = TestClient(app).get(
        "/data-operations/profile",
        params={
            "project_root": str(project_without_runs),
            "source_run_id": "run-1",
            "source_node_id": "stage:source",
            "source_artifact_id": "artifact-1",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


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


def test_data_operation_manifest_is_read_only_and_exposes_closed_descriptors() -> None:
    response = TestClient(app).get("/data-operations/manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "data-operation-manifest.v1"
    operation_ids = {item["operation_id"] for item in payload["operations"]}
    assert {
        "data.column.cast",
        "data.columns.cast",
        "data.feature_recipe",
        "data.merge",
        "data.append",
        "data.reshape",
        "data.subset",
    } <= operation_ids
    assert all(item["preview_ref"].endswith("/preview") for item in payload["operations"])
    assert all(item["confirm_ref"].endswith("/confirm") for item in payload["operations"])
    assert all(item["confirm_requires"] == ["preview_fingerprint"] for item in payload["operations"])


def test_data_operation_profile_is_bounded_and_keeps_dataset_identity(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"customer_id": ["a", "b"], "score": [1.0, None]}),
    )
    _seed_confirmed_metadata(
        project,
        run_id,
        artifact_id,
        {"columns": {}},
        schema_revision="schema:source-real",
        metadata_revision="metadata:source-real",
    )

    response = TestClient(app).get(
        "/data-operations/profile",
        params={
            "project_root": str(project),
            "source_run_id": run_id,
            "source_node_id": "stage:source",
            "source_artifact_id": artifact_id,
        },
    )

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["dataset_ref"]["run_id"] == run_id
    assert profile["dataset_ref"]["node_id"] == "stage:source"
    assert profile["dataset_ref"]["artifact_id"] == artifact_id
    assert {column["name"] for column in profile["columns"]} == {"customer_id", "score"}
    assert all(column["inferred"]["confirmed"] is False for column in profile["columns"])


def test_metadata_loss_preview_is_explicit_and_read_only() -> None:
    response = TestClient(app).post(
        "/data-operations/metadata-loss/preview",
        json={
            "source_format": "workbench-json",
            "target_format": "csv",
            "metadata": {
                "score": {
                    "dtype": "float64",
                    "variable_label": "Outcome",
                }
            },
        },
    )

    assert response.status_code == 200
    manifest = response.json()["manifest"]
    assert manifest["has_loss"] is True
    assert {item["status"] for item in manifest["items"]} == {"converted", "dropped"}


def test_metadata_mutation_is_preview_confirmed_identity_bound_and_reloadable(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "group": [1, 2, 99],
                "weight": [1.0, 2.0, 1.0],
            }
        ),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "metadata": {
            "group": {
                "variable_label": "Treatment group",
                "value_labels": {"1": "Control", "2": "Treated"},
                "measurement_level": "nominal",
                "role": "group",
                "user_missing_values": [99],
            }
        },
        "weight": {"column": "weight", "kind": "frequency"},
        "split": {"columns": ["group"]},
        "group": {"columns": ["group"]},
    }

    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/metadata/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["status"] == "ready"
        assert preview["source_artifact_id"] == artifact_id
        assert preview["metadata_fingerprint"]

        confirm_response = client.post(
            "/data-operations/metadata/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
        assert confirm_response.status_code == 200
        operation = confirm_response.json()["operation"]
        assert operation["operation_id"] == "data.metadata.update"
        assert operation["status"] == "completed"

        reload_response = client.get(
            f"/data-operations/metadata/{operation['record_id']}",
            params={"project_root": str(project)},
        )

    assert reload_response.status_code == 200
    reloaded = reload_response.json()["metadata"]
    assert reloaded["source"]["artifact_id"] == artifact_id
    assert reloaded["columns"]["group"]["user_missing_values"] == [99]
    assert reloaded["weight"] == {"column": "weight", "kind": "frequency"}
    assert reloaded["split"]["columns"] == ["group"]


def test_metadata_mutation_replay_is_idempotent_and_stale_source_is_blocked(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"score": [1, 2]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "metadata": {"score": {"variable_label": "Score"}},
    }

    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/metadata/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        body = {**request, "preview_fingerprint": preview["fingerprint"]}
        first = client.post(
            "/data-operations/metadata/confirm",
            params={"project_root": str(project)},
            json=body,
        )
        second = client.post(
            "/data-operations/metadata/confirm",
            params={"project_root": str(project)},
            json=body,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["operation"]["record_id"] == first.json()["operation"]["record_id"]
    artifacts = json.loads((project / "runs" / run_id / "artifacts_index.json").read_text())[
        "artifacts"
    ]
    assert len([item for item in artifacts if item["artifact_type"] == "metadata"]) == 1

    source_path = project / "runs" / run_id / "data.csv"
    source_path.write_text(source_path.read_text() + "3\n", encoding="utf-8")
    stale = TestClient(app).post(
        "/data-operations/metadata/confirm",
        params={"project_root": str(project)},
        json=body,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "DATA_OPERATION_STALE"


def test_sort_split_and_batch_recode_are_real_previewable_transforms(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "group": ["b", "a", "b", "a"],
                "score": [2, 4, 1, 3],
                "code": [1, 2, 3, 99],
            }
        ),
    )
    requests = {
        "sort": {
            "keys": [
                {"column": "group", "ascending": True},
                {"column": "score", "ascending": False},
            ]
        },
        "split": {"by": ["group"], "mode": "split_file"},
        "recode": {
            "columns": [
                {
                    "column": "code",
                    "rules": [
                        {"from": 1, "to": "control"},
                        {"from": 2, "to": "treated"},
                    ],
                    "other": "keep",
                    "missing": "preserve",
                }
            ]
        },
    }

    with TestClient(app) as client:
        previews = {}
        for operation, parameters in requests.items():
            response = client.post(
                "/data-operations/transform/preview",
                params={"project_root": str(project)},
                json={
                    "source_run_id": run_id,
                    "source_node_id": "stage:source",
                    "source_artifact_id": artifact_id,
                    "operation": operation,
                    "parameters": parameters,
                },
            )
            assert response.status_code == 200
            previews[operation] = response.json()["preview"]

        assert previews["sort"]["row_count_after"] == 4
        assert previews["split"]["group_count"] == 2
        assert previews["recode"]["changed_value_count"] == 2

        for operation, parameters in requests.items():
            response = client.post(
                "/data-operations/transform/confirm",
                params={"project_root": str(project)},
                json={
                    "source_run_id": run_id,
                    "source_node_id": "stage:source",
                    "source_artifact_id": artifact_id,
                    "operation": operation,
                    "parameters": parameters,
                    "preview_fingerprint": previews[operation]["fingerprint"],
                },
            )
            assert response.status_code == 200
            assert response.json()["effect"]["child_node_id"].startswith(f"data-{operation}:")


def test_profile_reload_uses_server_metadata_revisions_after_confirmed_mutation(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"group": [1, 2, 99], "score": [10, 20, 30]}),
    )
    _seed_confirmed_metadata(
        project,
        run_id,
        artifact_id,
        {"columns": {"group": {"variable_label": "Group"}}},
        schema_revision="schema:before-mutation",
        metadata_revision="metadata:before-mutation",
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "metadata": {
            "group": {
                "variable_label": "Group",
                "user_missing_values": [99],
            }
        },
    }

    with TestClient(app) as client:
        before = client.get(
            "/data-operations/profile",
            params={
                "project_root": str(project),
                "source_run_id": run_id,
                "source_node_id": "stage:source",
                "source_artifact_id": artifact_id,
            },
        )
        assert before.status_code == 200
        before_profile = before.json()["profile"]
        assert before_profile["schema_revision"] == "schema:before-mutation"
        assert before_profile["metadata_revision"] == "metadata:before-mutation"

        preview = client.post(
            "/data-operations/metadata/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        confirmed = client.post(
            "/data-operations/metadata/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
        assert confirmed.status_code == 200
        effect = confirmed.json()["effect"]
        child = client.get(
            "/data-operations/profile",
            params={
                "project_root": str(project),
                "source_run_id": run_id,
                "source_node_id": effect["child_node_id"],
                "source_artifact_id": artifact_id,
            },
        )

    assert child.status_code == 200
    after_profile = child.json()["profile"]
    assert after_profile["dataset_ref"]["node_id"] == effect["child_node_id"]
    assert after_profile["metadata_revision"] != "metadata:before-mutation"
    assert after_profile["metadata_revision"] != "v1"
    assert after_profile["columns"][0]["declared"]["user_missing_values"] == [99]


def test_filter_transform_uses_confirmed_user_missing_registry_and_rejects_unknown(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"code": [1, 99, None], "value": [10, 20, 30]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "subset",
        "parameters": {
            "columns": ["code", "value"],
            "filter_ast": {"column": "code", "op": "is_missing"},
        },
    }
    with TestClient(app) as client:
        unknown = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert unknown.status_code == 422

        _seed_confirmed_metadata(
            project,
            run_id,
            artifact_id,
            {"columns": {"code": {"user_missing_values": [99]}}},
            schema_revision="schema:filter",
            metadata_revision="metadata:filter-confirmed",
        )
        confirmed = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=request,
        )

    assert confirmed.status_code == 200
    assert confirmed.json()["preview"]["row_count_after"] == 2


def test_split_confirm_materializes_group_children_manifest_and_lineage(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"group": ["b", "a", "b", "a"], "value": [1, 2, 3, 4]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "split",
        "parameters": {"by": ["group"], "mode": "split_file"},
    }
    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        assert preview["group_counts"] == [
            {"key": {"group": "a"}, "count": 2},
            {"key": {"group": "b"}, "count": 2},
        ]
        confirmed = client.post(
            "/data-operations/transform/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    assert confirmed.status_code == 200
    effect = confirmed.json()["effect"]
    assert len(effect["group_artifacts"]) == 2
    assert len({item["artifact_id"] for item in effect["group_artifacts"]}) == 2
    manifest_path = project / "runs" / run_id / effect["group_manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["execution_key"] == effect["execution_key"]
    assert manifest["group_count"] == 2
    assert all(
        (project / "runs" / run_id / item["path"]).is_file()
        for item in manifest["groups"]
    )
    graph = GraphStore(project / "runs").read(run_id)
    assert all(item["child_node_id"] in graph.nodes for item in effect["group_artifacts"])
    assert all(
        any(
            edge.source_id == effect["child_node_id"]
            and edge.target_id == item["child_node_id"]
            for edge in graph.edges.values()
        )
        for item in effect["group_artifacts"]
    )


def test_declared_weight_is_consumed_by_supported_aggregate_and_recorded(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "group": ["a", "a", "b"],
                "value": [10.0, 20.0, 100.0],
                "weight": [1.0, 3.0, 1.0],
            }
        ),
    )
    _seed_confirmed_metadata(
        project,
        run_id,
        artifact_id,
        {
            "columns": {},
            "weight": {"column": "weight", "kind": "frequency"},
        },
        schema_revision="schema:weighted",
        metadata_revision="metadata:weighted",
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "aggregate",
        "parameters": {
            "group_by": ["group"],
            "aggregations": [
                {"column": "value", "func": "mean", "output": "mean_value"}
            ],
        },
    }
    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["method"] == "weighted_mean"
        assert preview["evidence"]["weight"]["column"] == "weight"
        confirmed = client.post(
            "/data-operations/transform/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
        unsupported = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json={
                **request,
                "parameters": {
                    **request["parameters"],
                    "aggregations": [
                        {"column": "value", "func": "sum", "output": "sum_value"}
                    ],
                },
            },
        )
        assert unsupported.status_code == 422
        assert "weight" in unsupported.json()["error"]["details"]["reason"]

    assert confirmed.status_code == 200
    effect = confirmed.json()["effect"]
    output = pd.read_csv(project / "runs" / run_id / effect["artifact_path"])
    assert output.set_index("group").loc["a", "mean_value"] == 17.5
    assert (
        confirmed.json()["operation"]["outputs"]["ports"]["evidence"]["method"]
        == "weighted_mean"
    )


def test_transform_child_reloads_all_confirmed_metadata_and_provenance_sidecar(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"code": [1, 2], "group": ["a", "b"], "weight": [1.0, 2.0]}),
    )
    _seed_confirmed_metadata(
        project,
        run_id,
        artifact_id,
        {
            "columns": {
                "code": {
                    "variable_label": "Code",
                    "value_labels": {"1": "One", "2": "Two"},
                    "user_missing_values": [99],
                }
            },
            "weight": {"column": "weight", "kind": "frequency"},
            "split": {"columns": ["group"], "mode": "split_file"},
            "group": {"columns": ["group"], "mode": "group"},
        },
        schema_revision="schema:all-metadata",
        metadata_revision="metadata:all-metadata",
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "recode",
        "parameters": {
            "columns": [
                {"column": "code", "rules": [{"from": 1, "to": 10}]}
            ]
        },
    }
    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        confirmed = client.post(
            "/data-operations/transform/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
        assert confirmed.status_code == 200
        effect = confirmed.json()["effect"]
        profile = client.get(
            "/data-operations/profile",
            params={
                "project_root": str(project),
                "source_run_id": run_id,
                "source_node_id": effect["child_node_id"],
                "source_artifact_id": effect["artifact_id"],
            },
        )

    assert profile.status_code == 200
    assert effect["metadata_artifact_id"]
    sidecar = json.loads(
        (project / "runs" / run_id / effect["metadata_artifact_path"]).read_text()
    )
    assert sidecar["metadata"]["columns"]["code"]["value_labels"] == {
        "1": "One",
        "2": "Two",
    }
    assert sidecar["metadata"]["columns"]["code"]["user_missing_values"] == [99]
    assert sidecar["metadata"]["weight"] == {"column": "weight", "kind": "frequency"}
    assert sidecar["metadata"]["split"]["columns"] == ["group"]
    assert sidecar["metadata"]["group"]["columns"] == ["group"]
    assert sidecar["provenance"]["source_artifact_id"] == artifact_id
    assert profile.json()["profile"]["columns"][0]["declared"]["value_labels"] == {
        "1": "One",
        "2": "Two",
    }
