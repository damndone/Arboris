import json
from pathlib import Path

import pytest

from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    validate_rerun_operation_target,
)


def _write_graph(runs_root: Path, run_id: str, node_id: str = "model:ols_1") -> None:
    node = Node(
        id=node_id,
        kind=NodeKind.MODEL,
        display_label="OLS",
        created_at="2026-06-27T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        stage=Stage.MODEL,
    )
    GraphStore(runs_root).write(
        Graph(
            schema_version=3,
            run_id=run_id,
            nodes={node_id: node},
            edges={},
            branches={},
        )
    )


def _request(**overrides) -> NodeWriteOperationRequestV1:
    data = {
        "request_id": "req_1",
        "operation": "rerun",
        "context_version": "node-operation-context/v1",
        "context_fingerprint": "fingerprint_a",
        "owner_run_id": "run_a",
        "op_node_id": "model:ols_1",
        "node_hash": "hash_a",
        "forest_node_key": "hash_a",
        "owner_resolution": "active_head_contains_node",
        "active_head_run_id": "run_a",
    }
    data.update(overrides)
    return NodeWriteOperationRequestV1(**data)


def test_rejects_unsupported_context_version(tmp_path: Path):
    req = _request(context_version="node-operation-context/v9")
    with pytest.raises(ValueError, match="unsupported_context_version"):
        validate_rerun_operation_target(tmp_path, req)


def test_missing_owner_run_raises_invalid_operation_target(tmp_path: Path):
    req = _request(owner_run_id="missing_run")

    with pytest.raises(ValueError, match="invalid_operation_target"):
        validate_rerun_operation_target(tmp_path, req)


def test_op_node_not_in_owner_run_raises_invalid_operation_target(tmp_path: Path):
    _write_graph(tmp_path, "run_a", node_id="model:other")

    with pytest.raises(ValueError, match="invalid_operation_target"):
        validate_rerun_operation_target(tmp_path, _request())


def test_matching_node_index_hash_passes(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    (tmp_path / "run_a" / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": "hash_a"}}),
        encoding="utf-8",
    )

    validate_rerun_operation_target(tmp_path, _request())


def test_node_index_hash_mismatch_raises_context_mismatch(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    (tmp_path / "run_a" / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": "hash_b"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="context_mismatch: node_hash"):
        validate_rerun_operation_target(tmp_path, _request())


def test_missing_node_index_entry_keeps_graph_only_validation(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    (tmp_path / "run_a" / "node_index.json").write_text(
        json.dumps({"model:other": {"node_hash": "hash_b"}}),
        encoding="utf-8",
    )

    validate_rerun_operation_target(tmp_path, _request())


def test_active_head_run_id_never_overrides_owner_run_id(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_graph(tmp_path, "run_active", node_id="model:other")

    validate_rerun_operation_target(
        tmp_path,
        _request(active_head_run_id="run_active", owner_run_id="run_a"),
    )
