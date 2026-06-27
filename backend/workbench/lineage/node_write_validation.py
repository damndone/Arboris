from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from workbench.graph_store import GraphStore
from workbench.lineage.family import scan_family
from workbench.lineage.headset import build_headset
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

    if request.active_head_run_id is not None:
        if not _is_simple_run_id(request.active_head_run_id):
            raise ValueError("invalid_operation_target: active_head_run_id")
        active_head_root = runs_root / request.active_head_run_id
        if not active_head_root.exists():
            raise ValueError("context_stale: active_head_run_id")
        if (
            request.owner_resolution == "active_head_contains_node"
            and request.active_head_run_id != request.owner_run_id
        ):
            raise ValueError("context_mismatch: active_head_run_id")

    graph = GraphStore(runs_root=runs_root).read(request.owner_run_id)
    if request.op_node_id not in graph.nodes:
        raise ValueError("invalid_operation_target: op_node_id")

    indexed_hash = _read_indexed_node_hash(run_root, request.op_node_id)
    if indexed_hash is None:
        raise ValueError("context_stale: node_index")
    if indexed_hash != request.node_hash:
        raise ValueError("context_mismatch: node_hash")
    valid_forest_keys = {
        request.node_hash,
        f"{request.node_hash}::{request.op_node_id}",
    }
    if request.forest_node_key not in valid_forest_keys:
        raise ValueError("context_mismatch: forest_node_key")

    expected_fingerprint = compute_context_fingerprint(runs_root, request)
    if request.context_fingerprint != expected_fingerprint:
        raise ValueError("context_stale: context_fingerprint")


def compute_context_fingerprint(
    runs_root: Path,
    request: NodeWriteOperationRequestV1,
) -> str:
    family = scan_family(runs_root, request.owner_run_id)
    headset = build_headset(runs_root, family)
    node_key, node = _find_headset_node(headset, request)
    if node is None:
        raise ValueError("context_stale: node_index")

    runs = [str(run_id) for run_id in node.get("runs") or []]
    candidate_run_refs = [
        {
            "run_id": run_id,
            "op_node_id": request.op_node_id,
            "node_hash": request.node_hash,
            "is_active_head": run_id == request.active_head_run_id,
            "path_contains_node": True,
        }
        for run_id in runs
    ]
    owner_head = next(
        (
            head
            for head in headset.get("heads", [])
            if head.get("run_id") == request.owner_run_id
        ),
        {},
    )
    owner_head_created_at = owner_head.get("created_at") or ""

    parts = [
        request.forest_node_key or node_key,
        request.node_hash,
        request.owner_run_id,
        request.op_node_id,
        request.active_head_run_id or "",
        str(headset.get("schema_version")),
        owner_head_created_at,
        _stable_fingerprint_input(
            candidate_run_refs=candidate_run_refs,
            shared_by_run_ids=runs,
            owner_head_created_at=owner_head_created_at,
        ),
    ]
    return _fingerprint_parts(parts)


def _find_headset_node(
    headset: dict,
    request: NodeWriteOperationRequestV1,
) -> tuple[str, dict | None]:
    nodes = headset.get("nodes") or {}
    direct = nodes.get(request.forest_node_key)
    if (
        isinstance(direct, dict)
        and direct.get("id") == request.op_node_id
        and direct.get("node_hash") == request.node_hash
    ):
        return request.forest_node_key, direct
    for key, node in nodes.items():
        if (
            isinstance(node, dict)
            and node.get("id") == request.op_node_id
            and node.get("node_hash") == request.node_hash
        ):
            return str(key), node
    return request.forest_node_key, None


def _stable_fingerprint_input(
    *,
    candidate_run_refs: list[dict],
    shared_by_run_ids: list[str],
    owner_head_created_at: str,
) -> str:
    stable_refs = [
        {
            "run_id": ref["run_id"],
            "op_node_id": ref["op_node_id"],
            "node_hash": ref["node_hash"],
            "is_active_head": ref["is_active_head"],
            "path_contains_node": ref["path_contains_node"],
        }
        for ref in sorted(candidate_run_refs, key=lambda item: item["run_id"])
    ]
    return json.dumps(
        {
            "candidate_run_refs": stable_refs,
            "shared_by_run_ids": sorted(shared_by_run_ids),
            "owner_head_created_at": owner_head_created_at,
        },
        separators=(",", ":"),
    )


def _fingerprint_parts(parts: list[str]) -> str:
    payload = json.dumps(parts, separators=(",", ":"))
    hash_value = 2166136261
    for char in payload:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return f"nocv1:{hash_value:08x}"


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
