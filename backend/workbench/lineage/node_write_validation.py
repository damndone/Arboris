from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from workbench.graph_store import GraphStore
from workbench.lineage.node_index import NODE_INDEX_FILENAME

SUPPORTED_CONTEXT_VERSION = "node-operation-context/v1"


class NodeWriteOperationRequestV1(BaseModel):
    request_id: str
    operation: Literal["rerun"]
    context_version: str
    context_fingerprint: str
    owner_run_id: str
    op_node_id: str
    node_hash: str
    forest_node_key: str
    owner_resolution: str
    active_head_run_id: str | None = None


class AcceptedContext(BaseModel):
    context_version: Literal["node-operation-context/v1"]
    context_fingerprint: str
    owner_run_id: str
    op_node_id: str
    node_hash: str
    validated_at: str


def accepted_context_from(request: NodeWriteOperationRequestV1) -> AcceptedContext:
    return AcceptedContext(
        context_version=SUPPORTED_CONTEXT_VERSION,
        context_fingerprint=request.context_fingerprint,
        owner_run_id=request.owner_run_id,
        op_node_id=request.op_node_id,
        node_hash=request.node_hash,
        validated_at=datetime.now(timezone.utc).isoformat(),
    )


def validate_rerun_operation_target(
    runs_root: Path,
    request: NodeWriteOperationRequestV1,
) -> None:
    if request.context_version != SUPPORTED_CONTEXT_VERSION:
        raise ValueError("unsupported_context_version")
    if not _is_simple_run_id(request.owner_run_id):
        raise ValueError("invalid_operation_target: owner_run_id")

    run_root = runs_root / request.owner_run_id
    if not run_root.exists():
        raise ValueError("invalid_operation_target: owner_run_id")

    graph = GraphStore(runs_root=runs_root).read(request.owner_run_id)
    if request.op_node_id not in graph.nodes:
        raise ValueError("invalid_operation_target: op_node_id")

    indexed_hash = _read_indexed_node_hash(run_root, request.op_node_id)
    if indexed_hash is not None and indexed_hash != request.node_hash:
        raise ValueError("context_mismatch: node_hash")
    if indexed_hash is not None:
        valid_forest_keys = {
            request.node_hash,
            f"{request.node_hash}::{request.op_node_id}",
        }
        if request.forest_node_key not in valid_forest_keys:
            raise ValueError("context_mismatch: forest_node_key")


def _is_simple_run_id(run_id: str) -> bool:
    if not run_id or "/" in run_id or "\\" in run_id:
        return False
    path = Path(run_id)
    return not path.is_absolute() and path.parts == (run_id,) and run_id not in {".", ".."}


def _read_indexed_node_hash(run_root: Path, op_node_id: str) -> str | None:
    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return None
    try:
        with index_path.open("r", encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_operation_target: node_index") from exc

    entry = index.get(op_node_id)
    if not isinstance(entry, dict):
        return None
    node_hash = entry.get("node_hash")
    return node_hash if isinstance(node_hash, str) else None
