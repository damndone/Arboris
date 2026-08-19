"""Persistence bridge for typed prediction graph node identities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts import read_json, write_json
from .contracts import ContractError


def persist_prediction_node_index(
    run_root: Path,
    entries: dict[str, dict[str, Any]],
) -> None:
    """Merge prediction node hashes into the run's Graph persistence index."""

    path = Path(run_root) / "node_index.json"
    try:
        index = read_json(path) if path.is_file() else {}
    except (OSError, TypeError, ValueError) as exc:
        raise ContractError(
            "PREDICTION_GRAPH_NODE_INDEX_INVALID",
            "prediction graph node_index.json is not valid JSON",
        ) from exc
    if not isinstance(index, dict):
        raise ContractError(
            "PREDICTION_GRAPH_NODE_INDEX_INVALID",
            "prediction graph node_index.json must be an object",
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
    write_json(path, index)


def classification_graph_nodes(
    *,
    task_ref: str,
    split_ref: str,
    preprocessing_ref: str,
    candidate_refs: tuple[str, ...],
    comparison_ref: str,
    selected_model_ref: str,
    policy_ref: str,
    holdout_ref: str,
) -> dict[str, Any]:
    """Build a typed, data-free Graph projection for a classification run.

    The projection contains references and operation records only.  In
    particular, selection and sealed holdout evaluation are distinct graph
    operations so a downstream consumer cannot mistake holdout evidence for a
    candidate-selection input.
    """

    refs = {
        "task": task_ref,
        "split": split_ref,
        "preprocessing": preprocessing_ref,
        "comparison": comparison_ref,
        "selected_model": selected_model_ref,
        "policy": policy_ref,
        "holdout": holdout_ref,
    }
    if not candidate_refs:
        raise ContractError(
            "CLASSIFICATION_GRAPH_CANDIDATES_REQUIRED",
            "classification Graph projection requires at least one candidate",
        )
    for name, value in {**refs, **{f"candidate_{i}": ref for i, ref in enumerate(candidate_refs)}}.items():
        if not isinstance(value, str) or not value.strip():
            raise ContractError(
                "CLASSIFICATION_GRAPH_REF_INVALID",
                f"classification Graph reference {name!r} must be a non-empty string",
            )
    if len(set(candidate_refs)) != len(candidate_refs):
        raise ContractError(
            "CLASSIFICATION_GRAPH_CANDIDATES_DUPLICATE",
            "classification Graph candidate references must be unique",
        )

    return {
        "schema_version": 1,
        "node_refs": {"candidates": list(candidate_refs), **refs},
        "edges": [
            ("classification:task", "classification:split"),
            ("classification:split", "classification:preprocessing"),
            ("classification:preprocessing", "classification:candidates"),
            ("classification:candidates", "classification:comparison"),
            ("classification:comparison", "classification:selected_model"),
            ("classification:selected_model", "classification:policy"),
            ("classification:selected_model", "classification:holdout_evaluation"),
        ],
        "operations": {
            "selection": {
                "operation_kind": "selection",
                "input_refs": [*candidate_refs, comparison_ref],
                "output_ref": selected_model_ref,
                "holdout_ref": None,
            },
            "holdout": {
                "operation_kind": "holdout_evaluation",
                "input_refs": [selected_model_ref, policy_ref],
                "output_ref": holdout_ref,
                "selection_ref": comparison_ref,
            },
        },
    }
