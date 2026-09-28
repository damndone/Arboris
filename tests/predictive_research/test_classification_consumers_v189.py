from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import threading
import time

import numpy as np
import pandas as pd
import pytest

from workbench.predictive_research.consumer_projection import (
    project_classification_evidence,
    read_classification_evidence_from_run_root,
)
from workbench.predictive_research.graph_persistence import (
    build_classification_graph,
    persist_classification_graph,
)
from workbench.predictive_research.persistence import PredictionPersistenceAdmission, persist_classification_evidence_packet
from workbench.predictive_research.schema import (
    CLASSIFICATION_PACKET_SCHEMA,
    PayloadContractError,
    classification_content_hash,
    validate_classification_packet,
)
from workbench.providers.catalog import ProviderCatalogError, _load_catalog_from_root, load_builtin_catalog
from workbench.prediction import run_classification_model_v189
from workbench.predictive_research.classification_adapters import get_classification_adapter
from workbench.predictive_research.classification_contracts import (
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
)
from workbench.predictive_research.classification_protocol import HoldoutSealV1, run_classification_protocol
from workbench.predictive_research.contracts import StructureSpecV1
from workbench.predictive_research.classification_explanations import compute_permutation_explanations
from workbench.predictive_research.classification_metrics import classification_metric_bundle
from workbench.predictive_research.preprocessing import ClassificationFoldPreprocessingV1
from workbench.predictive_research.classification_contracts import ClassificationPreprocessingStepV1
from workbench.predictive_research.contracts import ContractError


def _packet() -> dict[str, object]:
    packet = {
        "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
        "schema_version": 1,
        "packet_id": "classification-packet-1",
        "status": "validated",
        "task": {
            "task_id": "task-1",
            "target": "converted",
            "class_mapping": {"0": "not_converted", "1": "converted"},
            "positive_class": "1",
            "structure": "iid",
        },
        "split": {
            "split_id": "split-1",
            "profile": "iid_stratified",
            "split_hash": "sha256:" + "a" * 64,
            "row_refs": {"train": ["r1"], "validation": ["r2"], "holdout": ["r3"]},
        },
        "models": [
            {"model_id": "logistic-1", "model_family": "logistic", "status": "candidate"},
            {"model_id": "rf-1", "model_family": "random_forest", "status": "selected"},
        ],
        "selected_model": {"model_id": "rf-1", "selection_artifact_ref": "artifact:comparison-1"},
        "evaluation": {
            "metrics": {
                "accuracy": {"value": 0.8, "source": "holdout-evaluation-1"},
                "roc_auc": {"value": 0.84, "source": "holdout-evaluation-1"},
            },
            "sample_scope": "holdout",
            "row_count": 10,
        },
        "calibration": {"status": "available", "brier": {"value": 0.16, "source": "calibration-1"}},
        "baselines": [{"baseline_id": "prevalence", "metrics": {"accuracy": 0.5}}],
        "controls": [{"control_id": "shuffle_target", "status": "pass", "source": "control-1"}],
        "comparison": {
            "comparison_id": "comparison-1",
            "selection_status": "selected",
            "metric_differences": {"roc_auc": 0.04},
        },
        "explanations": {"status": "available", "permutation_importance": [{"feature": "age", "value": 0.2}]},
        "decision_policy": {
            "status": "frozen",
            "threshold": 0.5,
            "scope": "development_oof",
            "cost_policy_ref": "policy:confirmed-1",
        },
        "holdout_boundary": {
            "status": "evaluated_once",
            "metric_release_plan_hash": "sha256:" + "b" * 64,
            "authorization_ref": "holdout-auth:1",
            "access_count": 1,
        },
        "availability": {"status": "validated", "feature_set_ref": "features:1"},
        "warnings": ["Prediction explanations are descriptive, not causal."],
        "artifact_refs": {
            "task": "artifact:task-1",
            "split": "artifact:split-1",
            "comparison": "artifact:comparison-1",
            "holdout": "artifact:holdout-1",
        },
        "evidence_receipt": {
            "receipt_id": "receipt:classification-1",
            "source_artifacts": ["artifact:holdout-1", "artifact:comparison-1"],
            "validation_level": "formal",
        },
    }
    packet["packet_hash"] = classification_content_hash(packet)
    return packet


def _task() -> ClassificationTaskSpecV1:
    return ClassificationTaskSpecV1(
        target_column="target",
        task_type="binary",
        class_mapping={0: "negative", 1: "positive"},
        positive_class="positive",
        feature_columns=("signal", "noise"),
        feature_availability=(
            FeatureAvailabilityContractV1("signal", "t0", "t0", "t1", "recipe:signal", "validated"),
            FeatureAvailabilityContractV1("noise", "t0", "t0", "t1", "recipe:noise", "validated"),
        ),
        label_definition=LabelDefinitionV1("observed target", None, None, None, "frozen_snapshot"),
        structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
        primary_metric="roc_auc",
        secondary_metrics=("accuracy", "log_loss"),
        split_profile="iid_stratified",
        seed=17,
        resource_budget={"max_trials": 2, "max_cpu_seconds": 30},
    )


def test_classification_projection_is_packet_backed_and_does_not_recompute() -> None:
    packet = _packet()

    validated = validate_classification_packet(packet)
    projected = project_classification_evidence(validated, consumer="report")

    assert projected["status"] == "validated"
    assert projected["projection_kind"] == "typed_classification_evidence"
    assert projected["task"] == packet["task"]
    assert projected["evaluation"] == packet["evaluation"]
    assert projected["metrics"] == packet["evaluation"]["metrics"]
    assert projected["derived_from_raw_rows"] is False
    assert projected["evidence_receipt"] == packet["evidence_receipt"]


def test_classification_packet_hash_validates_and_rejects_tampered_hash() -> None:
    packet = _packet()
    packet["packet_hash"] = classification_content_hash(packet)

    validated = validate_classification_packet(packet)

    assert validated["packet_hash"] == packet["packet_hash"]

    tampered_body = json.loads(json.dumps(packet))
    tampered_body["evaluation"]["metrics"]["accuracy"]["value"] = 0.81
    with pytest.raises(PayloadContractError) as error:
        validate_classification_packet(tampered_body)

    assert error.value.code == "CLASSIFICATION_PACKET_HASH_INVALID"

    tampered_hash = dict(packet)
    tampered_hash["packet_hash"] = "sha256:" + "0" * 64
    with pytest.raises(PayloadContractError) as error:
        validate_classification_packet(tampered_hash)

    assert error.value.code == "CLASSIFICATION_PACKET_HASH_INVALID"


def test_classification_packet_hash_is_required() -> None:
    packet = _packet()
    packet.pop("packet_hash")

    with pytest.raises(PayloadContractError) as error:
        validate_classification_packet(packet)

    assert error.value.code == "CLASSIFICATION_PACKET_HASH_REQUIRED"


@pytest.mark.parametrize("consumer", ("agent", "notebook", "report", "table", "compare"))
def test_classification_projection_keeps_blocked_evidence_unavailable(consumer: str) -> None:
    packet = _blocked_packet()

    projected = project_classification_evidence(packet, consumer=consumer)

    assert projected["status"] == "blocked"
    assert projected["evaluation"] == {"status": "unavailable", "metrics": {}}
    assert projected["metrics"] == {}
    assert projected["calibration"] == {"status": "unavailable"}
    assert projected["models"] == []
    assert projected["selected_model"] is None
    assert projected["model_id"] is None
    assert projected["baselines"] == []
    assert projected["controls"] == []
    assert projected["comparison"] == {"status": "unavailable"}
    assert projected["explanations"] == {"status": "unavailable"}
    assert projected["decision_policy"] == {"status": "unavailable"}
    assert projected["blocked_reasons"] == ["availability could not be proven"]
    assert projected["holdout_boundary"]["status"] == "blocked"


def _blocked_packet() -> dict[str, object]:
    packet = _packet()
    packet.update(
        {
            "status": "blocked",
            "models": [],
            "selected_model": None,
            "evaluation": {"status": "unavailable", "metrics": {}},
            "calibration": {"status": "unavailable"},
            "baselines": [],
            "controls": [],
            "comparison": {"status": "unavailable"},
            "explanations": {"status": "unavailable"},
            "decision_policy": {"status": "unavailable"},
            "holdout_boundary": {
                "status": "blocked",
                "metric_release_plan_hash": "sha256:" + "c" * 64,
                "access_count": 0,
            },
            "warnings": ["availability could not be proven"],
        }
    )
    packet["packet_hash"] = classification_content_hash(packet)
    return packet


@pytest.mark.parametrize(
    "mutate",
    (
        lambda packet: packet["holdout_boundary"].update(
            {"status": "evaluated_once", "authorization_ref": "holdout:1", "access_count": 1}
        ),
        lambda packet: packet["evaluation"].update(
            {"status": "computed", "metrics": {"accuracy": {"point_estimate": 0.8}}}
        ),
        lambda packet: packet.update({"selected_model": {"model_id": "rf-1"}}),
    ),
)
def test_schema_rejects_blocked_packet_with_released_or_formal_evidence(mutate) -> None:
    packet = _blocked_packet()
    mutate(packet)
    packet["packet_hash"] = classification_content_hash(packet)

    with pytest.raises(PayloadContractError) as error:
        validate_classification_packet(packet)

    assert error.value.code == "CLASSIFICATION_BLOCKED_PACKET_EVIDENCE_INVALID"


@pytest.mark.parametrize("identity_input", ("task", "split", "model", "policy"))
def test_classification_packet_identity_changes_when_inputs_change(identity_input: str) -> None:
    packet = _packet()
    packet["packet_hash"] = classification_content_hash(packet)
    changed = json.loads(json.dumps(packet))

    if identity_input == "task":
        changed["task"]["target"] = "retained"
    elif identity_input == "split":
        changed["split"]["split_hash"] = "sha256:" + "d" * 64
    elif identity_input == "model":
        changed["models"][1]["model_id"] = "rf-2"
        changed["selected_model"]["model_id"] = "rf-2"
    else:
        changed["decision_policy"]["threshold"] = 0.6

    changed_hash = classification_content_hash(changed)

    assert changed_hash != packet["packet_hash"]
    changed["packet_hash"] = packet["packet_hash"]
    with pytest.raises(PayloadContractError) as error:
        validate_classification_packet(changed)

    assert error.value.code == "CLASSIFICATION_PACKET_HASH_INVALID"


def test_protocol_packet_identity_binds_model_set_and_decision_policy() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    policy = DecisionPolicyV1(
        cost_matrix=None,
        capacity=None,
        abstain_allowed=True,
        manual_review_allowed=True,
        threshold_scope="development_oof",
        threshold_method="max_f1",
        policy_version="1.0",
        population="snapshot",
        time_validity="snapshot",
    )
    model_result = run_classification_protocol(
        frame,
        task=_task(),
        model_ids=("logistic_regression",),
        decision_policy=policy,
        calibration_method="none",
    )
    other_model_result = run_classification_protocol(
        frame,
        task=_task(),
        model_ids=("random_forest",),
        decision_policy=policy,
        calibration_method="none",
    )
    other_policy = replace(
        policy,
        cost_matrix={"false_positive": 1, "false_negative": 1},
        capacity=1.0,
        threshold_method="fixed",
        selected_threshold=0.5,
    )
    policy_result = run_classification_protocol(
        frame,
        task=_task(),
        model_ids=("logistic_regression",),
        decision_policy=other_policy,
        calibration_method="none",
    )

    packet_ids = {
        model_result["packet_id"],
        other_model_result["packet_id"],
        policy_result["packet_id"],
    }
    assert len(packet_ids) == 3


def test_classification_graph_separates_selection_from_holdout_evaluation() -> None:
    graph = build_classification_graph(_packet())

    node_ids = {node["node_id"] for node in graph["nodes"]}
    assert {
        "classification:dataset",
        "classification:split",
        "classification:comparison",
        "classification:selected_model",
        "classification:decision_policy",
        "classification:holdout_evaluation",
        "classification:evidence",
    } <= node_ids
    edge_pairs = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("classification:comparison", "classification:selected_model") in edge_pairs
    assert ("classification:selected_model", "classification:holdout_evaluation") in edge_pairs
    assert graph["nodes"][0]["operation"] != graph["nodes"][-1]["operation"]


def test_classification_packet_persists_with_hash_and_is_read_by_projection(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        reference = persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )

    assert reference["artifact_id"] == "classification-1"
    assert reference["payload_schema"] == CLASSIFICATION_PACKET_SCHEMA
    assert len(reference["sha256"]) == 64
    projected = read_classification_evidence_from_run_root(tmp_path, consumer="report")
    assert projected["packet_id"] == "classification-packet-1"
    assert projected["model_id"] == "rf-1"


def test_classification_packet_persistence_is_idempotent_for_same_artifact_and_content(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        first = persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )
        second = persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )

    assert second == first
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    assert len(index["artifacts"]) == 1
    assert index["artifacts"][0]["artifact_id"] == "classification-1"


def test_persistence_admission_serializes_cross_admission_index_updates(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    first = PredictionPersistenceAdmission.admit(tmp_path)
    attempted = threading.Event()
    acquired = threading.Event()

    def acquire_second_admission() -> None:
        attempted.set()
        with PredictionPersistenceAdmission.admit(tmp_path):
            acquired.set()

    worker = threading.Thread(target=acquire_second_admission)
    worker.start()
    assert attempted.wait(timeout=1)
    time.sleep(0.1)
    assert not acquired.is_set()
    first.close()
    assert acquired.wait(timeout=1)
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_classification_packet_persistence_rejects_content_conflict_without_overwriting(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()
    changed_packet = json.loads(json.dumps(packet))
    changed_packet["evaluation"]["metrics"]["accuracy"]["value"] = 0.81
    changed_packet["packet_hash"] = classification_content_hash(changed_packet)

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        original = persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )
        packet_path = tmp_path / "classification_evidence" / "classification-1.json"
        original_contents = packet_path.read_bytes()

        with pytest.raises(PayloadContractError) as error:
            persist_classification_evidence_packet(
                admission,
                artifact_id="classification-1",
                packet=changed_packet,
                inputs=["comparison-1", "holdout-1"],
            )

    assert error.value.code == "ARTIFACT_ID_CONFLICT"
    assert packet_path.read_bytes() == original_contents
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    assert len(index["artifacts"]) == 1
    assert index["artifacts"][0]["sha256"] == original["sha256"]


def test_register_artifact_rejects_disk_digest_mismatch(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    relative_parts = ("classification_evidence", "classification-1.json")

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        admission.write_json(relative_parts, _packet())

        with pytest.raises(PayloadContractError) as error:
            admission.register_artifact(
                artifact_id="classification-1",
                relative_parts=relative_parts,
                artifact_type="classification_evidence_packet",
                step="classification",
                inputs=["comparison-1", "holdout-1"],
                sha256="0" * 64,
                payload_contract={
                    "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
                    "schema_version": 1,
                },
            )

    assert error.value.code == "ARTIFACT_DIGEST_MISMATCH"
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    assert index["artifacts"] == []


def test_classification_packet_idempotency_rejects_missing_file(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )
        (tmp_path / "classification_evidence" / "classification-1.json").unlink()

        with pytest.raises(PayloadContractError) as error:
            persist_classification_evidence_packet(
                admission,
                artifact_id="classification-1",
                packet=packet,
                inputs=["comparison-1", "holdout-1"],
            )

    assert error.value.code == "ARTIFACT_FILE_MISSING"


def test_classification_packet_idempotency_rejects_digest_mismatch(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )
        packet_path = tmp_path / "classification_evidence" / "classification-1.json"
        packet_path.write_bytes(packet_path.read_bytes() + b"\n tampered")

        with pytest.raises(PayloadContractError) as error:
            persist_classification_evidence_packet(
                admission,
                artifact_id="classification-1",
                packet=packet,
                inputs=["comparison-1", "holdout-1"],
            )

    assert error.value.code == "ARTIFACT_DIGEST_MISMATCH"


def test_classification_graph_conflict_is_preflighted_without_overwriting(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "artifact_id": "classification-graph-1",
                        "path": "other/classification-graph-1.json",
                        "artifact_type": "other",
                        "step": "other",
                        "sha256": "1" * 64,
                        "inputs": [],
                        "code_version": "other",
                        "payload_contract": {"payload_schema": "other", "schema_version": 1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    graph_path = tmp_path / "classification_graph" / "classification-graph-1.json"
    graph_path.parent.mkdir()
    original_contents = b"original graph bytes"
    graph_path.write_bytes(original_contents)

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        with pytest.raises(PayloadContractError) as error:
            persist_classification_graph(
                admission,
                artifact_id="classification-graph-1",
                packet=_packet(),
                inputs=["classification-1"],
            )

    assert error.value.code == "ARTIFACT_ID_CONFLICT"
    assert graph_path.read_bytes() == original_contents


def test_classification_packet_reader_rejects_tampered_persisted_payload(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        reference = persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )

    packet_path = tmp_path / str(reference["path"])
    persisted = json.loads(packet_path.read_text(encoding="utf-8"))
    persisted["evaluation"]["metrics"]["accuracy"]["value"] = 0.81
    packet_path.write_text(json.dumps(persisted), encoding="utf-8")

    with pytest.raises(PayloadContractError) as error:
        read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert error.value.code == "ARTIFACT_PAYLOAD_HASH_MISMATCH"


def test_classification_packet_reader_rejects_duplicate_index_records(tmp_path) -> None:
    index_path = tmp_path / "artifacts_index.json"
    index_path.write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["artifacts"].append(dict(index["artifacts"][0]))
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(PayloadContractError) as error:
        read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert error.value.code == "CLASSIFICATION_PACKET_DUPLICATE"


def test_classification_packet_reader_returns_unavailable_when_packet_is_missing(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")

    projected = read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert projected == {
        "status": "unavailable",
        "consumer": "report",
        "protocol": "classification_ml_v1",
        "projection_kind": "typed_classification_evidence",
        "reason": "classification evidence packet is unavailable",
        "derived_from_raw_rows": False,
    }


def test_classification_packet_reader_rejects_missing_packet_file(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        reference = persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )

    (tmp_path / str(reference["path"])).unlink()

    with pytest.raises(PayloadContractError) as error:
        read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert error.value.code == "ARTIFACT_PAYLOAD_HASH_MISMATCH"


def test_classification_packet_reader_rejects_packet_path_escape(tmp_path) -> None:
    index_path = tmp_path / "artifacts_index.json"
    index_path.write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    packet = _packet()

    with PredictionPersistenceAdmission.admit(tmp_path) as admission:
        persist_classification_evidence_packet(
            admission,
            artifact_id="classification-1",
            packet=packet,
            inputs=["comparison-1", "holdout-1"],
        )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["artifacts"][0]["path"] = "../classification-1.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(PayloadContractError) as error:
        read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert error.value.code == "ARTIFACT_PATH_INVALID"


def test_classification_packet_rejects_receipt_without_sources() -> None:
    packet = _packet()
    packet["evidence_receipt"] = {"receipt_id": "receipt:empty", "source_artifacts": []}
    packet["packet_hash"] = classification_content_hash(packet)

    with pytest.raises(PayloadContractError) as error:
        validate_classification_packet(packet)

    assert error.value.code == "CLASSIFICATION_EVIDENCE_RECEIPT_INVALID"


def test_classification_provider_is_declaration_only_and_discoverable() -> None:
    catalog = load_builtin_catalog()
    provider = next(item for item in catalog.providers if item.provider_id == "classification.ml")

    assert {path.path_id for path in provider.exposure_paths} == {
        "workbench.classification.fit-path",
        "workbench.classification.compare-path",
        "workbench.classification.explain-path",
        "workbench.classification.decision-path",
    }
    assert all(adapter.executor_ref.startswith("executor:") for adapter in provider.adapter_declarations)
    assert not any("/" in adapter.executor_ref or ".." in adapter.executor_ref for adapter in provider.adapter_declarations)


def test_classification_provider_fixture_rejects_path_like_executor_refs(tmp_path) -> None:
    source = Path(__file__).parents[2] / "backend" / "workbench" / "providers" / "builtin" / "classification_ml.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["adapter_declarations"][0]["executor_ref"] = "file:///tmp/classification.py"
    manifest = tmp_path / "classification_ml.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProviderCatalogError) as error:
        _load_catalog_from_root(tmp_path)

    assert error.value.code == "PROVIDER_EXECUTOR_INVALID"


def test_protocol_runs_two_model_families_through_one_sealed_holdout_boundary() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    result = run_classification_protocol(
        frame,
        task=_task(),
        model_ids=("logistic_regression", "random_forest"),
        decision_policy=DecisionPolicyV1(
            cost_matrix={"false_positive": 1, "false_negative": 2},
            capacity=1.0,
            abstain_allowed=False,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )

    assert result["status"] == "validated"
    assert {item["model_id"] for item in result["models"]} == {"logistic_regression", "random_forest"}
    assert result["comparison"]["selection_status"] == "selected"
    assert result["holdout_boundary"]["status"] == "evaluated_once"
    assert result["holdout_boundary"]["access_count"] == 1
    assert result["comparison"]["sample_scope"] == "development_oof"
    assert result["evaluation"]["sample_scope"] == "final_holdout"
    assert result["evidence_receipt"]["source_artifacts"]
    assert result["decision_policy"]["threshold_receipt"]["capacity_constraint"]["status"] == "applied"
    assert result["calibration"]["status"] == "applied"
    assert result["calibration"]["fit_scope"] == "development_oof"
    assert result["calibration"]["fit_row_refs"]
    assert all(isinstance(ref, str) for ref in result["calibration"]["fit_row_refs"])
    assert not any("holdout" in ref for ref in result["calibration"]["fit_row_refs"])
    assert result["calibration"]["nested_calibration"] is True
    assert set(result["calibration"]["fit_row_refs"]).isdisjoint(
        result["calibration"]["evaluation_row_refs"]
    )
    assert result["decision_policy"]["threshold_receipt"]["input_scope"] == "development_calibration_eval"
    assert result["decision_policy"]["threshold_receipt"]["input_row_refs"] == result["calibration"]["evaluation_row_refs"]
    assert result["controls"][0]["status"] == "computed"
    assert result["controls"][0]["exchangeability_unit"] == "row"
    assert result["controls"][0]["metric"]["sample_scope"] == "development_control_oof"


def test_compare_consumer_preserves_bounded_search_and_comparison_evidence() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    result = run_classification_protocol(
        frame,
        task=_task(),
        model_ids=("logistic_regression", "random_forest"),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
        calibration_method="none",
    )

    projected = project_classification_evidence(result, consumer="compare")
    comparison = projected["comparison"]

    assert comparison["search_receipt"]["candidate_space"]["candidate_ids"] == [
        "logistic_regression",
        "random_forest",
    ]
    assert comparison["search_receipt"]["resource_enforcement"]["cpu_hard_kill"] is False
    assert comparison["paired_prediction_refs"]["sample_scope"] == "development_oof"
    assert comparison["evidence_state"]["insufficient_evidence"] is False
    assert comparison["insufficient_evidence_state"]["status"] == "not_present"
    assert comparison["pareto_tradeoff"]["causal_interpretation"] == "not_causal"


def test_random_forest_seed_replay_and_bounded_multi_seed_sensitivity_receipt() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
        }
    )
    target = pd.Series([0, 0, 0, 0, 1, 1, 1, 1] * 3)
    seeds = (17, 29, 41)

    def evaluate(seed: int) -> dict[str, object]:
        adapter = get_classification_adapter(
            "random_forest",
            seed=seed,
            class_order=(0, 1),
            parameters={"n_estimators": 32, "max_cpu_seconds": 10},
        )
        adapter.fit(frame, target)
        probabilities = adapter.predict_proba(frame)
        predictions = adapter.predict_at_threshold(frame, threshold=0.5, positive_class=1)
        bundle = classification_metric_bundle(
            actual=target.tolist(),
            probabilities=probabilities,
            predictions=predictions.tolist(),
            class_order=(0, 1),
            positive_class=1,
            sample_scope="same_validation_snapshot",
            evaluation_design="same_library_regression",
            numerical_method="sklearn_1.x",
            inference_basis="descriptive",
            validation_level="bounded_sensitivity",
        )
        return {"seed": seed, "probabilities": probabilities, "bundle": bundle}

    first = evaluate(seeds[0])
    replay = evaluate(seeds[0])
    assert np.array_equal(first["probabilities"], replay["probabilities"])
    runs = [first, *(evaluate(seed) for seed in seeds[1:])]
    estimates = [run["bundle"]["metrics"]["roc_auc"]["point_estimate"] for run in runs]
    receipt = {
        "status": "computed",
        "kind": "bounded_multi_seed_sensitivity",
        "model_id": "random_forest",
        "metric": "roc_auc",
        "seeds": list(seeds),
        "max_seed_count": 3,
        "point_estimates": estimates,
        "range": max(estimates) - min(estimates),
        "evidence_basis": "same_library_regression",
        "independent_oracle": False,
    }

    assert len(receipt["seeds"]) <= receipt["max_seed_count"]
    assert receipt["seeds"] == list(seeds)
    assert all(np.isfinite(value) for value in receipt["point_estimates"])
    assert receipt["range"] >= 0.0
    assert receipt["evidence_basis"] == "same_library_regression"
    assert receipt["independent_oracle"] is False


def test_protocol_propagates_declared_weights_through_calibration_metrics_and_baseline() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
            "analysis_weight": [1.0, 2.0, 1.0, 3.0, 2.0, 4.0, 1.0, 5.0] * 3,
        }
    )
    result = run_classification_protocol(
        frame,
        task=replace(_task(), weights="analysis_weight"),
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )

    assert result["calibration"]["weighted_fit"] is True
    assert result["calibration"]["weight_sum"] > 0
    assert result["evaluation"]["weight_sum"] > 0
    assert result["baselines"][0]["metrics"]["weight_sum"] > 0
    assert result["baselines"][0]["metrics"]["metrics"]["accuracy"]["weight_sum"] > 0


@pytest.mark.parametrize(
    ("primary_metric", "expected_direction"),
    (
        ("accuracy", "higher_is_better"),
        ("roc_auc", "higher_is_better"),
        ("balanced_accuracy", "higher_is_better"),
        ("pr_auc", "higher_is_better"),
        ("f1", "higher_is_better"),
        ("precision", "higher_is_better"),
        ("recall", "higher_is_better"),
        ("log_loss", "lower_is_better"),
        ("brier_score", "lower_is_better"),
    ),
)
def test_comparison_records_primary_metric_direction(
    primary_metric: str,
    expected_direction: str,
) -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    result = run_classification_protocol(
        frame,
        task=replace(_task(), primary_metric=primary_metric),
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )

    assert result["comparison"]["direction"] == expected_direction


def test_model_selection_minimizes_lower_is_better_primary_metric() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    result = run_classification_protocol(
        frame,
        task=replace(_task(), primary_metric="log_loss"),
        model_ids=("logistic_regression", "random_forest"),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )
    scores = {
        model["model_id"]: model["selection_score"]
        for model in result["models"]
    }

    assert result["comparison"]["direction"] == "lower_is_better"
    assert result["comparison"]["selected_model_id"] == min(scores, key=scores.get)


def test_multiclass_majority_baseline_probability_matrix_follows_class_order() -> None:
    task = ClassificationTaskSpecV1(
        target_column="target",
        task_type="multiclass",
        class_mapping={2: "majority", 0: "class_a", 1: "class_b"},
        positive_class=None,
        feature_columns=("signal", "noise"),
        feature_availability=(
            FeatureAvailabilityContractV1("signal", "t0", "t0", "t1", "recipe:signal", "validated"),
            FeatureAvailabilityContractV1("noise", "t0", "t0", "t1", "recipe:noise", "validated"),
        ),
        label_definition=LabelDefinitionV1("observed target", None, None, None, "frozen_snapshot"),
        structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
        primary_metric="accuracy",
        secondary_metrics=("log_loss",),
        split_profile="iid_stratified",
        seed=23,
        resource_budget={"max_trials": 1},
    )
    frame = pd.DataFrame(
        {
            "signal": [float(value) for value in range(30)],
            "noise": [float(value % 5) for value in range(30)],
            "target": [2] * 12 + [0] * 9 + [1] * 9,
        }
    )

    result = run_classification_protocol(
        frame,
        task=task,
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )
    baseline = result["baselines"][0]

    assert baseline["class_order"] == [2, 0, 1]
    assert baseline["majority_class"] == 2
    assert baseline["probability_matrix"]
    assert all(row == [1.0, 0.0, 0.0] for row in baseline["probability_matrix"])


def test_exploration_only_availability_cannot_produce_validated_packet() -> None:
    task = replace(
        _task(),
        allow_exploration=True,
        feature_availability=(
            FeatureAvailabilityContractV1("signal", None, None, None, None, "unknown"),
            FeatureAvailabilityContractV1("noise", None, None, None, None, "unknown"),
        ),
    )
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )

    result = run_classification_protocol(
        frame,
        task=task,
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )

    assert result["status"] in {"blocked", "unavailable"}
    assert result["status"] != "validated"
    assert result["availability"]["status"] == "UNKNOWN_EXPLORATION_ONLY"
    assert any("exploration-only" in warning.lower() for warning in result["warnings"])
    assert result["selected_model"] is None
    assert result["evaluation"] == {"status": "unavailable", "metrics": {}}
    assert result["calibration"]["status"] == "unavailable"
    assert result["baselines"] == []
    assert result["controls"] == []
    assert result["holdout_boundary"]["status"] == "blocked"
    assert result["holdout_boundary"]["access_count"] == 0


def test_selectable_undefined_threshold_cannot_fall_back_to_half() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    policy = DecisionPolicyV1(
        cost_matrix={"false_positive": 1, "false_negative": 1},
        capacity=1.0,
        abstain_allowed=False,
        manual_review_allowed=False,
        threshold_scope="development_oof",
        threshold_method="min_log_loss",
        policy_version="1.0",
        population="snapshot",
        time_validity="snapshot",
    )

    with pytest.raises(ContractError) as error:
        run_classification_protocol(
            frame,
            task=_task(),
            model_ids=("logistic_regression",),
            decision_policy=policy,
            calibration_method="none",
        )

    assert error.value.code == "CLASSIFICATION_THRESHOLD_SELECTION_UNDEFINED"


def test_temporal_protocol_training_rows_are_future_free() -> None:
    temporal_task = replace(
        _task(),
        structure=StructureSpecV1(kind="temporal", time_column="period", provenance="user_confirmed"),
        split_profile="temporal_rolling",
        label_definition=LabelDefinitionV1(
            "event_within_horizon",
            "event_at",
            "30d",
            "30d",
            "as_of_prediction_origin",
        ),
    )
    periods = [period for period in range(9) for _ in (0, 1)]
    frame = pd.DataFrame(
        {
            "signal": [float(period) + 0.1 * (index % 2) for index, period in enumerate(periods)],
            "noise": [float(index % 3) for index in range(len(periods))],
            "target": [index % 2 for index in range(len(periods))],
            "period": periods,
        }
    )

    result = run_classification_protocol(
        frame,
        task=temporal_task,
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
        feature_available_at=[0] * len(frame),
        prediction_origins=[1] * len(frame),
        label_windows=[(period * 2, period * 2) for period in periods],
        periods=periods,
    )

    for fold in result["models"][0]["folds"]:
        training_periods = [periods[int(row_ref)] for row_ref in fold["train_row_refs"]]
        validation_periods = [periods[int(row_ref)] for row_ref in fold["validation_row_refs"]]
        assert training_periods
        assert validation_periods
        assert max(training_periods) < min(validation_periods)


def test_temporal_target_shuffle_control_is_unavailable_without_declared_exchangeability_unit() -> None:
    temporal_task = replace(
        _task(),
        structure=StructureSpecV1(kind="temporal", time_column="period", provenance="user_confirmed"),
        split_profile="temporal_rolling",
        label_definition=LabelDefinitionV1(
            "event_within_horizon",
            "event_at",
            "30d",
            "30d",
            "as_of_prediction_origin",
        ),
    )
    periods = [period for period in range(9) for _ in (0, 1)]
    frame = pd.DataFrame(
        {
            "signal": [float(period) + 0.1 * (index % 2) for index, period in enumerate(periods)],
            "noise": [float(index % 3) for index in range(len(periods))],
            "target": [index % 2 for index in range(len(periods))],
            "period": periods,
        }
    )

    result = run_classification_protocol(
        frame,
        task=temporal_task,
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
        feature_available_at=[0] * len(frame),
        prediction_origins=[1] * len(frame),
        label_windows=[(period * 2, period * 2 + 1) for period in periods],
        periods=periods,
        purge_gap=0,
    )

    assert result["controls"][0]["status"] == "unavailable"
    assert result["controls"][0]["exchangeability_unit"] == "not_declared"
    assert "temporal or panel" in result["controls"][0]["reason"]


def test_temporal_protocol_binds_split_periods_to_the_declared_frame_column() -> None:
    temporal_task = replace(
        _task(),
        structure=StructureSpecV1(kind="temporal", time_column="period", provenance="user_confirmed"),
        split_profile="temporal_rolling",
        label_definition=LabelDefinitionV1(
            "event_within_horizon",
            "event_at",
            "30d",
            "30d",
            "as_of_prediction_origin",
        ),
    )
    periods = [period for period in range(9) for _ in (0, 1)]
    frame = pd.DataFrame(
        {
            "signal": [float(period) + 0.1 * (index % 2) for index, period in enumerate(periods)],
            "noise": [float(index % 3) for index in range(len(periods))],
            "target": [index % 2 for index in range(len(periods))],
            "period": periods,
        }
    )

    with pytest.raises(ContractError) as error:
        run_classification_protocol(
            frame,
            task=temporal_task,
            model_ids=("logistic_regression",),
            decision_policy=DecisionPolicyV1(
                cost_matrix=None,
                capacity=None,
                abstain_allowed=True,
                manual_review_allowed=True,
                threshold_scope="development_oof",
                threshold_method="max_f1",
                policy_version="1.0",
                population="snapshot",
                time_validity="snapshot",
            ),
            feature_available_at=[0] * len(frame),
            prediction_origins=[1] * len(frame),
            label_windows=[(period * 2, period * 2) for period in periods],
            periods=list(reversed(periods)),
        )

    assert error.value.code == "CLASSIFICATION_TIME_METADATA_MISMATCH"


def test_temporal_protocol_requires_the_declared_time_column_even_when_external_periods_are_supplied() -> None:
    temporal_task = replace(
        _task(),
        structure=StructureSpecV1(kind="temporal", time_column="period", provenance="user_confirmed"),
        split_profile="temporal_rolling",
        label_definition=LabelDefinitionV1(
            "event_within_horizon",
            "event_at",
            "30d",
            "30d",
            "as_of_prediction_origin",
        ),
    )
    periods = [period for period in range(9) for _ in (0, 1)]
    frame = pd.DataFrame(
        {
            "signal": [float(period) for period in periods],
            "noise": [float(index % 3) for index in range(len(periods))],
            "target": [index % 2 for index in range(len(periods))],
        }
    )

    with pytest.raises(ContractError) as error:
        run_classification_protocol(
            frame,
            task=temporal_task,
            model_ids=("logistic_regression",),
            decision_policy=DecisionPolicyV1(
                cost_matrix=None,
                capacity=None,
                abstain_allowed=True,
                manual_review_allowed=True,
                threshold_scope="development_oof",
                threshold_method="max_f1",
                policy_version="1.0",
                population="snapshot",
                time_validity="snapshot",
            ),
            feature_available_at=[0] * len(frame),
            prediction_origins=[1] * len(frame),
            label_windows=[(period * 2, period * 2) for period in periods],
            periods=periods,
        )

    assert error.value.code == "CLASSIFICATION_TIME_COLUMN_MISSING"


def test_holdout_seal_releases_one_frozen_metric_bundle_only() -> None:
    seal = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan={"metrics": ["accuracy"], "subgroups": []},
    )
    first = seal.release({"accuracy": {"point_estimate": 0.8}})

    assert first["access_count"] == 1
    with pytest.raises(Exception) as error:
        seal.release({"accuracy": {"point_estimate": 0.9}})
    assert getattr(error.value, "code", None) == "CLASSIFICATION_HOLDOUT_ALREADY_RELEASED"


def test_holdout_seal_requires_exact_declared_metric_keys_and_sections() -> None:
    plan = {
        "metrics": ["accuracy"],
        "sections": ["selected_model"],
        "subgroups": [],
    }

    extra_metric = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan=plan,
    )
    with pytest.raises(ContractError) as error:
        extra_metric.consume(
            {"selected_model": {"metrics": {"accuracy": {"point_estimate": 0.8}, "roc_auc": {"point_estimate": 0.9}}}}
        )
    assert error.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH"


def test_holdout_seal_freezes_release_identity_and_plan_after_construction() -> None:
    plan = {
        "metrics": ["accuracy"],
        "sections": ["selected_model"],
        "subgroups": [],
    }
    seal = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan=plan,
    )

    plan["metrics"].append("roc_auc")
    assert tuple(seal.metric_release_plan["metrics"]) == ("accuracy",)
    with pytest.raises(TypeError):
        seal.metric_release_plan["metrics"] = ("roc_auc",)
    with pytest.raises(AttributeError):
        seal.split_hash = "sha256:" + "c" * 64

    extra_section = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan=plan,
    )
    with pytest.raises(ContractError) as error:
        extra_section.consume(
            {
                "selected_model": {"metrics": {"accuracy": {"point_estimate": 0.8}}},
                "unexpected": {},
            }
        )
    assert error.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH"


def test_holdout_seal_callback_failure_does_not_consume_capability() -> None:
    seal = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan={"metrics": ["accuracy"], "subgroups": []},
    )

    def callback() -> dict[str, object]:
        raise RuntimeError("release callback failed")

    with pytest.raises(ContractError) as error:
        seal.consume(callback)

    assert error.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_FAILED"
    assert seal.access_count == 0
    released = seal.consume({"accuracy": {"point_estimate": 0.8}})
    assert released["status"] == "evaluated_once"
    assert released["access_count"] == 1


def test_blocked_projection_does_not_forward_hidden_task_or_split_payloads() -> None:
    packet = _blocked_packet()
    packet["task"]["hidden_metric"] = {"point_estimate": 0.99}
    packet["split"]["raw_rows"] = [{"target": 1, "feature": 9.0}]
    packet["packet_hash"] = classification_content_hash(packet)

    projected = project_classification_evidence(packet, consumer="report")

    assert projected["task"] == {"status": "unavailable"}
    assert projected["split"] == {"status": "unavailable"}
    assert "hidden_metric" not in json.dumps(projected, sort_keys=True)
    assert "feature" not in json.dumps(projected, sort_keys=True)


def test_holdout_seal_concurrent_and_reentrant_consume_fail_closed() -> None:
    seal = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan={"metrics": ["accuracy"], "subgroups": []},
    )
    entered = threading.Event()
    continue_callback = threading.Event()
    first_result: dict[str, object] = {}

    def callback() -> dict[str, object]:
        entered.set()
        assert continue_callback.wait(timeout=2)
        return {"accuracy": {"point_estimate": 0.8}}

    worker = threading.Thread(target=lambda: first_result.setdefault("release", seal.consume(callback)))
    worker.start()
    assert entered.wait(timeout=2)

    with pytest.raises(ContractError) as concurrent_error:
        seal.consume({"accuracy": {"point_estimate": 0.9}})
    assert concurrent_error.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_IN_PROGRESS"

    continue_callback.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert first_result["release"]["access_count"] == 1

    reentrant = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan={"metrics": ["accuracy"], "subgroups": []},
    )

    def reentrant_callback() -> dict[str, object]:
        reentrant.consume({"accuracy": {"point_estimate": 0.7}})
        return {"accuracy": {"point_estimate": 0.8}}

    with pytest.raises(ContractError) as reentrant_error:
        reentrant.consume(reentrant_callback)
    assert reentrant_error.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_IN_PROGRESS"
    assert reentrant.access_count == 0


def test_typed_classification_entrypoint_persists_evidence_and_graph(tmp_path) -> None:
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )
    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_task(),
        model_ids=["logistic_regression"],
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )

    assert result["protocol"] == "classification_ml_v1"
    assert result["evidence_artifact"]["artifact_type"] == "classification_evidence_packet"
    assert result["graph_artifact"]["artifact_type"] == "classification_graph"
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    assert {item["artifact_type"] for item in index["artifacts"]} == {
        "classification_evidence_packet",
        "classification_graph",
    }


def test_fold_preprocessing_preserves_non_default_row_identity() -> None:
    steps = (
        ClassificationPreprocessingStepV1(
            step_id="impute",
            kind="mean_impute",
            columns=("signal",),
            supports_weight=True,
        ),
        ClassificationPreprocessingStepV1(
            step_id="scale",
            kind="standard_scale",
            columns=("signal",),
            supports_weight=True,
        ),
    )
    frame = pd.DataFrame({"signal": [1.0, None, 3.0]}, index=["row-a", "row-b", "row-c"])
    fit_rows = frame.to_dict(orient="index")
    fitted = ClassificationFoldPreprocessingV1(steps=steps).fit(
        frame,
        fit_row_refs=("row-a", "row-b", "row-c"),
        fit_rows=fit_rows,
    )

    transformed = fitted.transform(frame, row_refs=("row-a", "row-b", "row-c"))

    assert tuple(transformed.index) == ("row-a", "row-b", "row-c")
    assert transformed["signal"].notna().all()


def test_protocol_keeps_multiclass_probability_columns_typed_and_ordered() -> None:
    task = ClassificationTaskSpecV1(
        target_column="target",
        task_type="multiclass",
        class_mapping={0: "a", 1: "b", 2: "c"},
        positive_class=None,
        feature_columns=("signal", "noise"),
        feature_availability=(
            FeatureAvailabilityContractV1("signal", "t0", "t0", "t1", "recipe:signal", "validated"),
            FeatureAvailabilityContractV1("noise", "t0", "t0", "t1", "recipe:noise", "validated"),
        ),
        label_definition=LabelDefinitionV1("observed target", None, None, None, "frozen_snapshot"),
        structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
        primary_metric="accuracy",
        secondary_metrics=("log_loss",),
        split_profile="iid_stratified",
        seed=9,
        resource_budget={"max_trials": 1},
    )
    frame = pd.DataFrame(
        {
            "signal": [0.0, 1.0, 2.0, 0.2, 1.2, 2.2] * 5,
            "noise": [0.1, -0.1, 0.3, 0.2, -0.2, 0.4] * 5,
            "target": [0, 1, 2, 0, 1, 2] * 5,
        }
    )
    result = run_classification_protocol(
        frame,
        task=task,
        model_ids=("logistic_regression",),
        decision_policy=DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ),
    )

    row = result["models"][0]["oof_probability_rows"][0]
    assert len(row["probabilities"]) == 3
    assert row["positive_probability"] is None
    assert result["evaluation"]["class_order"] == [0, 1, 2]


def test_permutation_explanations_reject_duplicate_validation_row_refs() -> None:
    frame = pd.DataFrame({"signal": [0.0, 1.0, 2.0, 3.0]})

    with pytest.raises(ContractError) as error:
        compute_permutation_explanations(
            frame,
            [0, 0, 1, 1],
            model_id="logistic-1",
            predict_proba=lambda values: values["signal"].to_numpy() / 3.0,
            validation_row_refs=("row-1", "row-2", "row-2", "row-4"),
            feature_mapping={"signal": "signal"},
            seed=17,
            class_order=(0, 1),
            positive_class=1,
        )

    assert error.value.code == "CLASSIFICATION_EXPLANATION_INPUT_INVALID"
