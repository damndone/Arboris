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
