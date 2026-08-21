from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from tests.test_data_operation_routes import _seed_confirmed_metadata
from workbench.agent.operations import OperationRecord, OperationRecordStore
from workbench.app import app
from workbench.api_errors import WorkbenchAPIError


def _cast_request(run_id: str, artifact_id: str) -> dict[str, str]:
    return {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "column": "age",
        "target_dtype": "string",
    }


def _assert_no_unbounded_data_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character.lower() for character in str(key) if character.isalnum())
            assert normalized not in {
                "path",
                "file",
                "files",
                "rows",
                "rawrows",
                "filename",
                "filenames",
                "rawdata",
                "rawpayload",
                "stdout",
                "stderr",
            }
            assert not normalized.endswith("path")
            assert not normalized.endswith("filename")
            assert not normalized.endswith("rows")
            assert not normalized.startswith("raw")
            _assert_no_unbounded_data_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_unbounded_data_fields(nested)


def _assert_complete_typed_contract(body: dict[str, object], preview: dict[str, object]) -> None:
    record = body["operation_record"]
    assert isinstance(record, dict)
    assert record["status"] == "completed"
    outputs = record["outputs"]
    assert isinstance(outputs, dict)
    assert outputs["catalog_digest"] == preview["catalog_digest"]
    assert set(outputs["ports"]) == {"derived", "operation_record", "evidence"}
    assert set(outputs["consumer_slots"]) == {
        "data.agent",
        "data.notebook",
        "data.report",
    }
    assert outputs["ports"]["operation_record"]["record_id"] == record["record_id"]
    assert outputs["ports"]["evidence"]["record_id"] == record["record_id"]
    assert outputs["ports"]["derived"]["child_node_id"] == body["effect"]["child_node_id"]
    _assert_no_unbounded_data_fields(body)


def test_central_data_operation_confirmation_exposes_complete_typed_ports(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11], "name": ["a", "b"]}),
    )

    with TestClient(app) as client:
        manifest_response = client.get("/data-operations/manifest")
        assert manifest_response.status_code == 200
        manifest = manifest_response.json()
        descriptor = next(
            item
            for item in manifest["operations"]
            if item["operation_id"] == "data.column.cast"
        )

        preview_response = client.post(
            descriptor["preview_ref"],
            params={"project_root": str(project)},
            json=_cast_request(run_id, artifact_id),
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]

        response = client.post(
            descriptor["confirm_ref"],
            params={"project_root": str(project)},
            json={
                **_cast_request(run_id, artifact_id),
                "preview_fingerprint": preview["fingerprint"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    _assert_complete_typed_contract(body, preview)
    encoded = json.dumps(body, sort_keys=True)
    assert "raw_rows" not in encoded
    assert '"rows"' not in encoded
    assert '"path"' not in encoded
    assert '"file"' not in encoded


def test_central_data_operation_replay_preserves_same_typed_record_and_ports(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    request = _cast_request(run_id, artifact_id)

    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        body = {
            **request,
            "preview_fingerprint": preview["fingerprint"],
        }
        first = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json=body,
        )
        second = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json=body,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    first_record = first.json()["operation_record"]
    second_record = second.json()["operation_record"]
    assert second_record["record_id"] == first_record["record_id"]
    assert second_record["outputs"] == first_record["outputs"]
    assert second_record["outputs"]["consumer_slots"]["data.report"]["port"] == "evidence"


def test_central_feature_and_transform_confirm_share_the_same_typed_contract(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"x": [2.0, 3.0], "z": [4.0, 5.0], "id": [1, 2]}),
    )
    feature_request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "recipe_id": "recipe_interaction",
        "operation_id": "interaction",
        "inputs": ["x", "z"],
        "output": "xz",
        "parameters": {"left": "x", "right": "z"},
    }
    transform_request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "subset",
        "parameters": {"columns": ["id", "x"], "equals": {"id": 2}},
    }

    with TestClient(app) as client:
        feature_preview = client.post(
            "/data-operations/feature-recipe/preview",
            params={"project_root": str(project)},
            json=feature_request,
        )
        assert feature_preview.status_code == 200
        feature_payload = feature_preview.json()["preview"]
        feature_confirm = client.post(
            "/data-operations/feature-recipe/confirm",
            params={"project_root": str(project)},
            json={**feature_request, "preview_fingerprint": feature_payload["fingerprint"]},
        )
        transform_preview = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json=transform_request,
        )
        assert transform_preview.status_code == 200
        transform_payload = transform_preview.json()["preview"]
        transform_confirm = client.post(
            "/data-operations/transform/confirm",
            params={"project_root": str(project)},
            json={**transform_request, "preview_fingerprint": transform_payload["fingerprint"]},
        )

    assert feature_confirm.status_code == 200
    assert transform_confirm.status_code == 200
    _assert_complete_typed_contract(feature_confirm.json(), feature_payload)
    _assert_complete_typed_contract(transform_confirm.json(), transform_payload)


def test_central_metadata_confirm_returns_the_same_bounded_typed_contract(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"group": [1, 2], "weight": [1.0, 2.0]}),
    )
    _seed_confirmed_metadata(project, run_id, artifact_id, {"columns": {}})
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "metadata": {
            "group": {
                "variable_label": "Treatment group",
                "measurement_level": "nominal",
            }
        },
    }
    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/metadata/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        response = client.post(
            "/data-operations/metadata/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    assert response.status_code == 200
    body = response.json()
    _assert_complete_typed_contract(body, preview)
    assert set(body["operation_record"]["verification"]) <= {
        "passed",
        "mode",
        "child_node_id",
    }
    assert set(body["operation_record"]["diff_ref"]) <= {
        "kind",
        "artifact_id",
        "metadata_artifact_id",
        "recipe_artifact_id",
        "group_manifest_id",
        "child_node_id",
    }
    assert "path" not in json.dumps(body["operation"], sort_keys=True)
    history_response = TestClient(app).get(
        f"/data-operations/metadata/{body['operation']['record_id']}",
        params={"project_root": str(project)},
    )
    assert history_response.status_code == 200
    _assert_no_unbounded_data_fields(history_response.json())


def test_central_confirm_rejects_a_completed_record_without_typed_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    request = _cast_request(run_id, artifact_id)
    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        response = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    assert response.status_code == 200
    record_id = response.json()["operation_record"]["record_id"]
    malformed = OperationRecordStore(project / "workbench", create=False).get(record_id).to_dict()
    malformed["outputs"] = {}
    malformed_record = OperationRecord.from_dict(malformed)

    from workbench.http import data_operation_routes

    monkeypatch.setattr(
        data_operation_routes.OperationRecordStore,
        "get",
        lambda _store, _record_id: malformed_record,
    )
    with pytest.raises(WorkbenchAPIError) as error:
        data_operation_routes._complete_direct_data_operation(
            project,
            {"operation_record": malformed},
            object(),
            method="data.column.cast",
        )
    assert error.value.code == "DATA_OPERATION_OUTPUT_UNAVAILABLE"


def test_central_boundary_uses_case_insensitive_field_filtering_and_group_identity_allowlist() -> None:
    from workbench.http.data_operation_routes import (
        _bounded_data_consumer_evidence,
        _bounded_data_consumer_effect,
        _bounded_data_consumer_diff_ref,
        _bounded_data_consumer_operation_record,
        _bounded_data_consumer_output_ports,
        _bounded_data_consumer_value,
        _bounded_data_consumer_verification,
    )

    bounded = _bounded_data_consumer_value(
        {
            "artifactPath": "runs/run-1/data.csv",
            "rawRows": [{"secret": "value"}],
            "fileName": "data.csv",
            "rawData": [{"secret": "value"}],
            "result_preview_rows": [{"secret": "value"}],
            "stdout": "secret output",
            "nested": {"filePath": "private.txt", "keep": "identity"},
        }
    )
    assert bounded == {"nested": {"keep": "identity"}}

    class ServerEffect:
        def to_dict(self) -> dict[str, object]:
            return {
                "execution_key": "exec-1",
                "artifact_id": "artifact-1",
                "child_node_id": "child-1",
                "group_artifacts": [
                    {
                        "artifact_id": "group-artifact-1",
                        "child_node_id": "group-child-1",
                        "metadata_artifact_id": "group-metadata-1",
                        "unexpected": "must not cross",
                        "artifactPath": "runs/run-1/group.csv",
                    }
                ],
            }

    effect = _bounded_data_consumer_effect(ServerEffect())
    assert effect["group_artifacts"] == [
        {
            "artifact_id": "group-artifact-1",
            "child_node_id": "group-child-1",
            "metadata_artifact_id": "group-metadata-1",
        }
    ]

    class BadEffect:
        def to_dict(self) -> dict[str, object]:
            return {"artifact_id": {"secret": "must not cross"}}

    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_effect(BadEffect())

    class BadGroupEffect:
        def to_dict(self) -> dict[str, object]:
            return {
                "artifact_id": "artifact-1",
                "group_artifacts": [{"artifact_id": {"secret": "must not cross"}}],
            }

    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_effect(BadGroupEffect())

    class EmptyGroupEffect:
        def to_dict(self) -> dict[str, object]:
            return {"artifact_id": "artifact-1", "group_artifacts": [{}]}

    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_effect(EmptyGroupEffect())

    class MalformedOutputPorts:
        def to_dict(self, *, catalog_digest: str) -> dict[str, object]:
            return {
                "ports": {
                    "derived": {},
                    "operation_record": {
                        "record_id": "record-1",
                        "operation_id": "data.column.cast",
                        "operation_version": "v1",
                    },
                    "evidence": {
                        "method": "data.column.cast",
                        "record_id": "record-1",
                        "operation_id": "data.column.cast",
                        "execution_key": "exec-1",
                        "child_node_id": "child-1",
                    },
                },
                "consumer_slots": {
                    "data.agent": {"record_id": "record-1", "port": "derived"},
                    "data.notebook": {"record_id": "record-1", "port": "derived"},
                    "data.report": {"record_id": "record-1", "port": "evidence"},
                },
                "catalog_digest": {"secret": "must not cross"},
            }

    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_output_ports(
            MalformedOutputPorts(),
            effect=ServerEffect(),
            catalog_digest="catalog-1",
        )

    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_evidence(
            {
                "method": "data.column.cast",
                "record_id": "record-1",
                "operation_id": "data.column.cast",
                "execution_key": "exec-1",
                "child_node_id": "child-1",
                "artifact_id": {"not": "a scalar"},
            }
        )
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_evidence(
            {
                "method": "aggregate",
                "record_id": "record-1",
                "operation_id": "data.aggregate",
                "execution_key": "exec-1",
                "child_node_id": "child-1",
                "group_count": True,
            }
        )
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_diff_ref({})
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_diff_ref(None)
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_verification({})

    operation_record = {
        "record_id": "record-1",
        "operation_id": "data.column.cast",
        "operation_version": "v1",
        "status": "completed",
        "target": {
            "run_id": "run-1",
            "node_ref": "node-1",
            "artifact_id": "artifact-1",
        },
        "execution": {
            "execution_key": "exec-1",
            "bindings": {"artifact_id": "artifact-1", "child_node_id": "child-1"},
        },
        "outputs": {
            "ports": {
                "derived": {
                    "execution_key": "exec-1",
                    "artifact_id": "artifact-1",
                    "child_node_id": "child-1",
                },
                "operation_record": {
                    "record_id": "record-1",
                    "operation_id": "data.column.cast",
                    "operation_version": "v1",
                },
                "evidence": {
                    "method": "data.column.cast",
                    "record_id": "record-1",
                    "operation_id": "data.column.cast",
                    "execution_key": "exec-1",
                    "child_node_id": "child-1",
                },
            },
            "consumer_slots": {
                "data.agent": {"record_id": "record-1", "port": "derived"},
                "data.notebook": {"record_id": "record-1", "port": "derived"},
                "data.report": {"record_id": "record-1", "port": "evidence"},
            },
            "catalog_digest": "catalog-1",
        },
        "diff_ref": {"kind": "data-consumer-effect.v1", "artifact_id": "artifact-1"},
        "verification": {"passed": True, "mode": "immutable_artifact_and_lineage"},
    }
    assert _bounded_data_consumer_operation_record(operation_record)["record_id"] == "record-1"
    with_internal_lease_fields = json.loads(json.dumps(operation_record))
    with_internal_lease_fields["execution"]["lease_owner"] = {"secret": "must not cross"}
    with_internal_lease_fields["execution"]["claim_status"] = {"secret": "must not cross"}
    projected = _bounded_data_consumer_operation_record(with_internal_lease_fields)
    assert "lease_owner" not in projected["execution"]
    assert "claim_status" not in projected["execution"]
    bad_operation_port = json.loads(json.dumps(operation_record))
    bad_operation_port["outputs"]["ports"]["operation_record"]["record_id"] = {"bad": "id"}
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_operation_record(bad_operation_port)
    bad_consumer_slot = json.loads(json.dumps(operation_record))
    bad_consumer_slot["outputs"]["consumer_slots"]["data.agent"]["record_id"] = {"bad": "id"}
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_operation_record(bad_consumer_slot)
    bad_catalog_digest = json.loads(json.dumps(operation_record))
    bad_catalog_digest["outputs"]["catalog_digest"] = {"secret": "must not cross"}
    with pytest.raises(WorkbenchAPIError):
        _bounded_data_consumer_operation_record(bad_catalog_digest)


def test_central_confirm_uses_bounded_spec_and_confirmation_projections(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    request = _cast_request(run_id, artifact_id)
    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200
        preview_body = preview_response.json()
        preview = preview_body["preview"]
        confirmed = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert set(preview_body["spec"]) <= {
        "operation_id",
        "operation_version",
        "source_run_id",
        "source_node_id",
        "source_artifact_id",
        "column",
        "target_dtype",
    }
    assert set(body["proposal"]) <= {
        "record_type",
        "proposal_id",
        "operation_id",
        "operation_version",
        "revision",
        "fingerprint",
        "status",
    }
    assert set(body["confirmation"]) <= {
        "record_type",
        "proposal_id",
        "operation_id",
        "operation_version",
        "revision",
        "fingerprint",
        "actor_type",
        "status",
    }
    for field in ("target", "preconditions", "changes", "parameters"):
        assert field not in body["proposal"]
        assert field not in body["confirmation"]
    assert "changes" not in body["operation_record"]
    assert "preconditions" not in body["operation_record"]
    assert "confirmation" not in body["operation_record"]


def test_central_replay_rejects_an_undeclared_evidence_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    request = _cast_request(run_id, artifact_id)
    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        response = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    record_id = response.json()["operation_record"]["record_id"]
    record_payload = OperationRecordStore(project / "workbench", create=False).get(record_id).to_dict()
    outputs = dict(record_payload["outputs"])
    ports = dict(outputs["ports"])
    evidence = dict(ports["evidence"])
    evidence["unexpected_evidence"] = "must be rejected"
    ports["evidence"] = evidence
    outputs["ports"] = ports
    record_payload["outputs"] = outputs
    malformed_record = OperationRecord.from_dict(record_payload)

    from workbench.http import data_operation_routes

    monkeypatch.setattr(
        data_operation_routes.OperationRecordStore,
        "get",
        lambda _store, _record_id: malformed_record,
    )

    class ReplayEffect:
        def to_dict(self) -> dict[str, object]:
            derived = outputs["ports"]["derived"]
            return dict(derived)

    with pytest.raises(WorkbenchAPIError) as error:
        data_operation_routes._complete_direct_data_operation(
            project,
            {"operation_record": record_payload},
            ReplayEffect(),
            method="data.column.cast",
        )
    assert error.value.code == "DATA_OPERATION_OUTPUT_UNAVAILABLE"


def test_central_replay_rejects_a_record_from_a_stale_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    request = _cast_request(run_id, artifact_id)
    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/column-cast/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        response = client.post(
            "/data-operations/column-cast/confirm",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    record_id = response.json()["operation_record"]["record_id"]
    record_payload = OperationRecordStore(project / "workbench", create=False).get(record_id).to_dict()
    outputs = dict(record_payload["outputs"])
    outputs["catalog_digest"] = "stale-catalog"
    record_payload["outputs"] = outputs
    stale_record = OperationRecord.from_dict(record_payload)

    from workbench.http import data_operation_routes

    monkeypatch.setattr(
        data_operation_routes.OperationRecordStore,
        "get",
        lambda _store, _record_id: stale_record,
    )
    with pytest.raises(WorkbenchAPIError) as error:
        data_operation_routes._complete_direct_data_operation(
            project,
            {"operation_record": record_payload},
            object(),
            method="data.column.cast",
        )
    assert error.value.code == "DATA_OPERATION_OUTPUT_UNAVAILABLE"
