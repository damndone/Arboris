from __future__ import annotations

import gc
import hashlib
import json
import shutil
import weakref

import pytest
from fastapi.testclient import TestClient

import workbench.predictive_research.consumer_projection as consumer_projection
import workbench.services.classification_consumer_service as classification_service
import workbench.agent.context_tools as context_tools
import workbench.agent.notebook.evidence as notebook_evidence
import workbench.http.runs_routes as runs_routes
from workbench.api import app
from workbench.prediction import run_classification_model_v189
from workbench.predictive_research.contracts import ContractError
from workbench.predictive_research.schema import PayloadContractError
from workbench.services.classification_consumer_service import (
    read_classification_consumer_projection,
)
from test_v189_classification_production import (
    _ordered_frame,
    _ordered_task,
    _production_dependencies,
)


def _materialize_run(project_root, run_id: str = "run-classification"):
    run_root = project_root / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    run_classification_model_v189(
        frame,
        run_root,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "mode": "auto",
                "status": "completed",
                "lineage": [],
            }
        ),
        encoding="utf-8",
    )
    return run_root


def _server_capability(project_root, run_id: str):
    return classification_service._mint_classification_run_capability(
        project_root / "runs" / run_id
    )


def _tamper_indexed_artifact_after_snapshot(run_root) -> None:
    artifact = run_root / "classification_artifacts.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["evidence"]["metrics"]["oof"]["metrics"]["accuracy"] = 0.0
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(item for item in index["artifacts"] if item["artifact_type"] == "classification_artifacts")
    record["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index), encoding="utf-8")


def test_three_central_consumers_share_persisted_source_identity(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)

    projections = {
        consumer_id: read_classification_consumer_projection(
            _server_capability(project_root, run_root.name),
            consumer_id,
        )
        for consumer_id in ("agent", "notebook", "report")
    }

    assert {projection["consumer"] for projection in projections.values()} == {
        "agent",
        "notebook",
        "report",
    }
    source_identity = {
        (
            projection["source_artifact_id"],
            projection["source_artifact_sha256"],
            projection["source_receipt_digest"],
            json.dumps(projection["server_identity"], sort_keys=True),
        )
        for projection in projections.values()
    }
    assert len(source_identity) == 1
    assert projections["agent"]["status"] == "degraded"
    assert projections["agent"]["blocked_reasons"]


def test_normal_classification_projection_fits_catalog_budget(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)

    projections = {
        consumer_id: read_classification_consumer_projection(
            _server_capability(project_root, run_root.name),
            consumer_id,
        )
        for consumer_id in ("agent", "notebook", "report")
    }

    for consumer_id, projection in projections.items():
        assert projection["payload_schema"] == "workbench.prediction.classification-evidence"
        assert projection["status"] in {"completed", "degraded"}
        constraints = projection["projection_constraints"]
        assert constraints["max_token_budget"] == 8192
        assert constraints["token_count"] <= constraints["max_token_budget"]
        assert constraints["row_count"] <= constraints["max_row_budget"]
        assert projection["consumer"] == consumer_id
        assert projection["server_identity"]["run_id"] == run_root.name


def test_central_reader_rejects_path_and_arbitrary_project_root(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)

    with pytest.raises(ContractError) as path_error:
        read_classification_consumer_projection(run_root, "agent")
    assert path_error.value.code == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"

    with pytest.raises(ContractError) as root_error:
        read_classification_consumer_projection(str(project_root), "agent")
    assert root_error.value.code == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"

    with pytest.raises(ContractError) as child_error:
        read_classification_consumer_projection(tmp_path / "attacker" / "run", "agent")
    assert child_error.value.code == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"


def test_central_reader_uses_one_wrapper_snapshot(monkeypatch, tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    capability = _server_capability(project_root, run_root.name)
    original = consumer_projection.read_classification_artifacts_wrapper_from_run_root
    calls = 0

    def mutate_after_snapshot(run_root_arg):
        nonlocal calls
        calls += 1
        wrapper = original(run_root_arg)
        _tamper_indexed_artifact_after_snapshot(run_root_arg)
        return wrapper

    monkeypatch.setattr(
        consumer_projection,
        "read_classification_artifacts_wrapper_from_run_root",
        mutate_after_snapshot,
    )

    projection = read_classification_consumer_projection(capability, "agent")

    assert calls == 1
    assert projection["source_receipt_digest"]
    assert projection["server_identity"]["run_id"] == run_root.name


def test_degraded_report_reason_is_preserved_by_central_service(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    capability = _server_capability(project_root, run_root.name)

    projection = read_classification_consumer_projection(capability, "report")
    report = classification_service.read_classification_report_evidence(capability)

    assert projection["status"] == "degraded"
    assert projection["blocked_reasons"]
    assert report["status"] == "degraded"
    assert report["reason"] == projection["blocked_reasons"]


def test_agent_and_notebook_path_and_capability_use_central_reader(monkeypatch, tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    capability = _server_capability(project_root, run_root.name)
    seen: list[tuple[object, str]] = []

    def central_reader(received_capability: object, consumer_id: str):
        seen.append((received_capability, consumer_id))
        return {"consumer": consumer_id}

    monkeypatch.setattr(context_tools, "read_classification_consumer_projection", central_reader)
    monkeypatch.setattr(
        classification_service,
        "read_classification_consumer_projection",
        central_reader,
    )

    assert context_tools.read_classification_evidence_for_agent(capability) == {
        "consumer": "agent"
    }
    assert notebook_evidence.read_classification_evidence_for_notebook(capability) == {
        "consumer": "notebook"
    }
    assert [consumer_id for _, consumer_id in seen] == [
        "agent",
        "notebook",
    ]
    assert all(type(received_capability) is not type(run_root) for received_capability, _ in seen)

    monkeypatch.undo()
    with pytest.raises(ContractError) as agent_path:
        context_tools.read_classification_evidence_for_agent(run_root)
    assert agent_path.value.code == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"
    with pytest.raises(ContractError) as notebook_path:
        notebook_evidence.read_classification_evidence_for_notebook(run_root)
    assert notebook_path.value.code == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"


def test_dead_capability_does_not_retain_registry_record(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    initial_registry_size = len(classification_service._CAPABILITY_RECORDS)
    capability = _server_capability(project_root, run_root.name)
    assert len(classification_service._CAPABILITY_RECORDS) == initial_registry_size + 1
    capability_ref = weakref.ref(capability)

    del capability
    gc.collect()

    assert capability_ref() is None
    assert len(classification_service._CAPABILITY_RECORDS) <= initial_registry_size


def test_notebook_evidence_record_freezes_hashed_nested_payloads() -> None:
    from workbench.agent.notebook.evidence import EvidenceRecord

    record = EvidenceRecord(
        evidence_id="evidence:test",
        inspection_id="profile.v1",
        source_refs=("dataset:test",),
        protocol_version="profile/v1",
        status="completed",
        observations={"nested": {"value": 1}},
        result_hash="sha256:fixed",
    )

    with pytest.raises(TypeError):
        record.observations["nested"]["value"] = 2
    wire = record.to_dict()
    wire["observations"]["nested"]["value"] = 2

    assert record.to_dict()["observations"]["nested"]["value"] == 1
    assert record.result_hash == "sha256:fixed"


def test_run_route_uses_server_owned_classification_projection(tmp_path) -> None:
    project_root = tmp_path / "project"
    _materialize_run(project_root)

    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/run-classification",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200, response.text
    classification = response.json()["classification_evidence"]
    assert response.json()["classification_evidence_authority"] == "server-owned"
    assert classification["projection"]["consumer"] == "report"
    assert classification["server_identity"] == classification["source"]["server_identity"]
    assert classification["server_identity"] == classification["projection"]["server_identity"]
    assert classification["server_identity"]["run_id"] == "run-classification"
    assert "artifact" not in classification
    assert classification["receipt"]["payload_schema"] == (
        "workbench.prediction.classification-consumer-receipt"
    )


def test_run_route_keeps_missing_classification_typed_and_without_receipt(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-missing-classification"
    run_root.mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_root.name,
                "mode": "auto",
                "status": "completed",
                "lineage": [],
            }
        ),
        encoding="utf-8",
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        f"/runs/{run_root.name}",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200, response.text
    classification = response.json()["classification_evidence"]
    assert response.json()["classification_evidence_authority"] == "server-owned"
    assert classification["status"] == "unavailable"
    assert classification["reason"] == "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE"
    assert "receipt" not in classification


def test_run_route_exception_fallback_keeps_catalog_bound_unavailable(
    monkeypatch, tmp_path
) -> None:
    project_root = tmp_path / "project"
    _materialize_run(project_root)

    def reject_capability(_run_root):
        raise ContractError(
            "CLASSIFICATION_RUN_CAPABILITY_REQUIRED",
            "test authority rejection",
        )

    monkeypatch.setattr(runs_routes, "_mint_classification_run_capability", reject_capability)
    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/run-classification",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200, response.text
    classification = response.json()["classification_evidence"]
    assert classification["status"] == "unavailable"
    assert classification["reason"] == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"
    assert classification["provider_id"] == "workbench.classification_ml"
    assert classification["exposure_path"] == "workbench.classification_ml.direct"
    assert classification["projection_ref"]["logical_id"] == "workbench.classification_ml.report"
    assert classification["policy_ref"]["logical_id"] == "workbench.classification_ml.policy"
    assert classification["catalog_digest"]
    assert classification["provider_digest"]
    assert "artifact" not in classification
    assert "source" not in classification


def test_central_reader_requires_source_contract_in_server_receipt(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    receipt_path = run_root / "classification_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("source_contract")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(PayloadContractError) as error:
        read_classification_consumer_projection(
            _server_capability(project_root, run_root.name),
            "report",
        )
    assert error.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"


@pytest.mark.parametrize(
    ("failure_mode", "expected_reason"),
    (
        ("receipt_invalid", "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"),
        ("foreign", "CLASSIFICATION_SERVER_IDENTITY_MISMATCH"),
    ),
)
def test_run_route_classification_failures_are_typed_and_no_raw_fallback(
    tmp_path,
    failure_mode: str,
    expected_reason: str,
) -> None:
    if failure_mode == "receipt_invalid":
        project_root = tmp_path / "project"
        run_root = _materialize_run(project_root)
        _tamper_indexed_artifact_after_snapshot(run_root)
    else:
        source_project = tmp_path / "source"
        source_run = _materialize_run(source_project)
        project_root = tmp_path / "foreign"
        run_root = project_root / "runs" / source_run.name
        run_root.parent.mkdir(parents=True)
        shutil.copytree(source_run, run_root)

    response = TestClient(app, raise_server_exceptions=False).get(
        f"/runs/{run_root.name}",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    classification = body["classification_evidence"]
    assert body["classification_evidence_authority"] == "server-owned"
    assert classification["status"] == "unavailable"
    assert classification["reason"] == expected_reason
    assert "artifact" not in classification
    assert "receipt" not in classification
    assert "source" not in classification
    assert "projection" not in classification


def test_tampered_foreign_and_missing_runs_fail_closed_without_raw_fallback(tmp_path) -> None:
    source_project = tmp_path / "source"
    source_run = _materialize_run(source_project)
    artifact = source_run / "classification_artifacts.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["evidence"]["metrics"]["oof"]["metrics"]["accuracy"] = 0.0
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    index_path = source_run / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(item for item in index["artifacts"] if item["artifact_type"] == "classification_artifacts")
    record["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(ContractError) as tamper:
        read_classification_consumer_projection(
            _server_capability(source_project, source_run.name),
            "agent",
        )
    assert tamper.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"

    foreign_project = tmp_path / "foreign"
    foreign_run = foreign_project / "runs" / source_run.name
    foreign_run.parent.mkdir(parents=True)
    shutil.copytree(source_run, foreign_run)
    with pytest.raises(ContractError) as foreign:
        read_classification_consumer_projection(
            _server_capability(foreign_project, foreign_run.name),
            "report",
        )
    assert foreign.value.code == "CLASSIFICATION_SERVER_IDENTITY_MISMATCH"

    with pytest.raises(TypeError):
        read_classification_consumer_projection(
            _server_capability(source_project, source_run.name),
            "agent",
            packet=payload,
        )


def test_missing_index_returns_typed_unavailable_and_rejects_path_bypass(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "missing-index"
    run_root.mkdir(parents=True)

    projection = read_classification_consumer_projection(
        _server_capability(project_root, run_root.name),
        "notebook",
    )
    assert projection["payload_schema"] == "workbench.prediction.classification-evidence.unavailable"
    assert projection["schema_version"] == 1
    assert projection["status"] == "unavailable"
    assert projection["consumer"] == "notebook"
    assert projection["code"] == "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE"
    assert projection["blocked_reasons"] == ["CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE"]
    assert projection["provider_id"] == "workbench.classification_ml"
    assert projection["exposure_path"] == "workbench.classification_ml.direct"
    assert projection["projection_ref"]["logical_id"] == "workbench.classification_ml.notebook"
    assert projection["policy_ref"]["logical_id"] == "workbench.classification_ml.policy"
    assert projection["renderer_ref"]["logical_id"] == "workbench.classification_ml.report"

    with pytest.raises(ContractError) as bypass:
        read_classification_consumer_projection(
            {"runs": "caller-packet"},
            "notebook",
        )
    assert bypass.value.code == "CLASSIFICATION_RUN_CAPABILITY_REQUIRED"
