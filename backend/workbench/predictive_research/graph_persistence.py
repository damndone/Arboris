"""Persistence bridge for typed prediction graph node identities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..lineage.hashing import node_hash
from .contracts import ContractError
from .persistence import PredictionPersistenceAdmission, _json_bytes, _sha256
from .schema import (
    CLASSIFICATION_GRAPH_SCHEMA,
    PayloadContractError,
    classification_content_hash,
    validate_classification_packet,
)


def persist_prediction_node_index(
    run_root: Path,
    entries: dict[str, dict[str, Any]],
) -> None:
    """Merge prediction node hashes into the run's Graph persistence index."""

    with PredictionPersistenceAdmission.admit(Path(run_root)) as admission:
        index = admission._read_json(("node_index.json",), allow_missing=True)
        if index is None:
            index = {}
        if not isinstance(index, dict):
            raise ContractError(
                "PREDICTION_GRAPH_NODE_INDEX_INVALID",
                "prediction graph node_index.json is not a valid JSON object",
            )
        for node_id, entry in entries.items():
            existing = index.get(node_id)
            if existing is not None and (
                not isinstance(existing, dict)
                or existing.get("node_hash") != entry.get("node_hash")
            ):
                raise ContractError(
                    "PREDICTION_GRAPH_NODE_IDENTITY_CONFLICT",
                    f"prediction graph node {node_id!r} already has a different node_hash",
                )
            index[node_id] = {**(existing or {}), **entry}
        admission.write_json(("node_index.json",), index)


def build_classification_graph(packet: dict[str, Any]) -> dict[str, Any]:
    """Build the explicit classification lineage without touching execution.

    Selection and final holdout evaluation are different nodes and operations.
    That distinction prevents a consumer from interpreting a selected model
    as if its holdout score had been available during selection.
    """

    validated = validate_classification_packet(packet)
    refs = validated["artifact_refs"]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}

    def add_node(node_id: str, operation: str, parents: list[str], payload: dict[str, Any]) -> None:
        parent_hashes = [hashes[parent] for parent in parents]
        digest = node_hash(parent_hashes, {"protocol": "classification_ml_v1", **payload})
        hashes[node_id] = digest
        nodes.append(
            {
                "node_id": node_id,
                "node_hash": digest,
                "operation": operation,
                "artifact_ref": payload.get("artifact_ref"),
                "packet_id": validated["packet_id"],
            }
        )
        for index, parent in enumerate(parents):
            edges.append(
                {
                    "edge_id": f"classification:e:{parent.split(':', 1)[-1]}-{node_id.split(':', 1)[-1]}-{index}",
                    "source": parent,
                    "target": node_id,
                    "op": operation,
                }
            )

    add_node(
        "classification:dataset",
        "data_snapshot",
        [],
        {"artifact_ref": refs.get("dataset", "artifact:dataset"), "task": validated["task"]},
    )
    add_node(
        "classification:split",
        "split_manifest",
        ["classification:dataset"],
        {"artifact_ref": refs.get("split", "artifact:split"), "split": validated["split"]},
    )
    add_node(
        "classification:preprocessing",
        "fold_local_preprocessing",
        ["classification:split"],
        {"artifact_ref": refs.get("preprocessing", "artifact:preprocessing"), "availability": validated["availability"]},
    )
    add_node(
        "classification:candidates",
        "candidate_models",
        ["classification:preprocessing"],
        {"artifact_ref": refs.get("candidates", "artifact:candidates"), "models": validated["models"]},
    )
    add_node(
        "classification:comparison",
        "model_comparison",
        ["classification:candidates"],
        {"artifact_ref": refs.get("comparison", "artifact:comparison"), "comparison": validated["comparison"]},
    )
    add_node(
        "classification:selected_model",
        "model_selection",
        ["classification:comparison"],
        {"artifact_ref": refs.get("selected_model", "artifact:selected_model"), "selected_model": validated["selected_model"]},
    )
    add_node(
        "classification:decision_policy",
        "policy_freeze",
        ["classification:selected_model"],
        {"artifact_ref": refs.get("decision_policy", "artifact:decision_policy"), "decision_policy": validated["decision_policy"]},
    )
    add_node(
        "classification:holdout_evaluation",
        "holdout_evaluation",
        ["classification:selected_model", "classification:decision_policy"],
        {"artifact_ref": refs.get("holdout", "artifact:holdout"), "evaluation": validated["evaluation"], "holdout_boundary": validated["holdout_boundary"]},
    )
    add_node(
        "classification:evidence",
        "evidence_receipt",
        ["classification:holdout_evaluation"],
        {"artifact_ref": refs.get("evidence", "artifact:evidence"), "receipt": validated["evidence_receipt"]},
    )
    return {
        "payload_schema": CLASSIFICATION_GRAPH_SCHEMA,
        "schema_version": 1,
        "packet_id": validated["packet_id"],
        "graph_hash": classification_content_hash({"nodes": nodes, "edges": edges}),
        "nodes": nodes,
        "edges": edges,
    }


def persist_classification_graph(
    admission: Any,
    *,
    artifact_id: str,
    packet: dict[str, Any],
    inputs: list[str],
) -> dict[str, Any]:
    """Persist the graph contribution through the same admitted writer."""

    if not isinstance(admission, PredictionPersistenceAdmission):
        raise ContractError(
            "PREDICTION_PERSISTENCE_ADMISSION_REQUIRED",
            "classification graph requires a PredictionPersistenceAdmission",
        )
    if not isinstance(artifact_id, str) or not artifact_id or "/" in artifact_id or "\\" in artifact_id:
        raise ContractError("PREDICTION_PERSISTENCE_PATH_INVALID", "classification graph artifact_id is unsafe")
    graph = build_classification_graph(packet)
    relative_parts = ("classification_graph", f"{artifact_id}.json")
    digest = _sha256(_json_bytes(graph))
    existing_records = admission._artifact_records(artifact_id)
    if existing_records:
        if len(existing_records) != 1:
            raise PayloadContractError(
                "ARTIFACT_ID_CONFLICT",
                f"artifact_id {artifact_id!r} has duplicate index records",
            )
        existing = existing_records[0]
        expected = {
            "artifact_id": artifact_id,
            "path": "/".join(relative_parts),
            "artifact_type": "classification_graph",
            "sha256": digest,
            "inputs": list(inputs),
            "payload_contract": {"payload_schema": CLASSIFICATION_GRAPH_SCHEMA, "schema_version": 1},
        }
        if not all(existing.get(key) == value for key, value in expected.items()):
            raise PayloadContractError(
                "ARTIFACT_ID_CONFLICT",
                f"artifact_id {artifact_id!r} is already bound to a different artifact",
            )
        actual_sha256 = admission._file_sha256(relative_parts)
        if actual_sha256 != existing["sha256"]:
            raise PayloadContractError(
                "ARTIFACT_DIGEST_MISMATCH",
                f"artifact {artifact_id!r} index digest does not match the persisted file",
            )
        return {
            "artifact_id": artifact_id,
            "path": "/".join(relative_parts),
            "artifact_type": "classification_graph",
            "payload_schema": CLASSIFICATION_GRAPH_SCHEMA,
            "schema_version": 1,
            "sha256": digest,
        }
    admission.write_json(relative_parts, graph)
    admission.register_artifact(
        artifact_id=artifact_id,
        relative_parts=relative_parts,
        artifact_type="classification_graph",
        step="classification",
        inputs=list(inputs),
        sha256=digest,
        payload_contract={"payload_schema": CLASSIFICATION_GRAPH_SCHEMA, "schema_version": 1},
    )
    return {
        "artifact_id": artifact_id,
        "path": "/".join(relative_parts),
        "artifact_type": "classification_graph",
        "payload_schema": CLASSIFICATION_GRAPH_SCHEMA,
        "schema_version": 1,
        "sha256": digest,
    }
