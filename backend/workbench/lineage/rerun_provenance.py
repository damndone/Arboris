from __future__ import annotations

from typing import Any


def run_rerun_from_from_context(
    *,
    request_id: str,
    owner_run_id: str,
    op_node_id: str,
    node_hash: str,
    context_fingerprint: str,
    patch_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "owner_run_id": owner_run_id,
        "op_node_id": op_node_id,
        "node_hash": node_hash,
        "context_fingerprint": context_fingerprint,
        "rerun_request_id": request_id,
    }
    if patch_id:
        body["patch_id"] = patch_id
    return body


def pending_produced_lineage(
    *, produced_owner_run_id: str, rerun_from: dict[str, Any]
) -> dict[str, Any]:
    return {
        "produced_owner_run_id": produced_owner_run_id,
        "produced_op_node_id": None,
        "produced_node_hash": None,
        "rerun_request_id": str(rerun_from["rerun_request_id"]),
        "rerun_from": rerun_from,
        "status": "pending_index",
    }


def indexed_produced_lineage(
    *,
    produced_owner_run_id: str,
    produced_op_node_id: str,
    produced_node_hash: str,
    rerun_from: dict[str, Any],
) -> dict[str, Any]:
    return {
        "produced_owner_run_id": produced_owner_run_id,
        "produced_op_node_id": produced_op_node_id,
        "produced_node_hash": produced_node_hash,
        "rerun_request_id": str(rerun_from["rerun_request_id"]),
        "rerun_from": rerun_from,
        "status": "indexed",
    }
