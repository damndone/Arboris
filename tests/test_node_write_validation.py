import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    SUPPORTED_CONTEXT_VERSION,
    compute_context_fingerprint,
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


def _valid_request(runs_root: Path, **overrides) -> NodeWriteOperationRequestV1:
    request = _request(**overrides)
    request.context_fingerprint = compute_context_fingerprint(runs_root, request)
    return request


def _write_node_index(
    runs_root: Path,
    run_id: str = "run_a",
    node_id: str = "model:ols_1",
    node_hash: str = "hash_a",
) -> None:
    (runs_root / run_id / "node_index.json").write_text(
        json.dumps({node_id: {"node_hash": node_hash}}),
        encoding="utf-8",
    )


def test_rejects_unsupported_context_version(tmp_path: Path):
    req = _request(context_version="node-operation-context/v9")
    with pytest.raises(ValueError, match="unsupported_context_version"):
        validate_rerun_operation_target(tmp_path, req)


def test_rejects_unknown_owner_resolution():
    with pytest.raises(ValidationError):
        _request(owner_resolution="runs_zero_guess")


def test_missing_owner_run_raises_invalid_operation_target(tmp_path: Path):
    req = _request(owner_run_id="missing_run")

    with pytest.raises(ValueError, match="invalid_operation_target"):
        validate_rerun_operation_target(tmp_path, req)


def test_parent_traversal_owner_run_id_raises_invalid_operation_target(tmp_path: Path):
    outside_run_id = "outside"
    _write_graph(tmp_path.parent, outside_run_id)

    with pytest.raises(ValueError, match="invalid_operation_target"):
        validate_rerun_operation_target(tmp_path, _request(owner_run_id="../outside"))


def test_absolute_owner_run_id_raises_invalid_operation_target(tmp_path: Path):
    outside_root = tmp_path.parent / "absolute_outside"
    _write_graph(outside_root.parent, outside_root.name)

    with pytest.raises(ValueError, match="invalid_operation_target"):
        validate_rerun_operation_target(tmp_path, _request(owner_run_id=str(outside_root)))


def test_op_node_not_in_owner_run_raises_invalid_operation_target(tmp_path: Path):
    _write_graph(tmp_path, "run_a", node_id="model:other")

    with pytest.raises(ValueError, match="invalid_operation_target"):
        validate_rerun_operation_target(tmp_path, _request())


def test_matching_node_index_hash_passes(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)

    validate_rerun_operation_target(tmp_path, _valid_request(tmp_path))


def test_build_rerun_operation_context_derives_canonical_target(tmp_path: Path):
    import workbench.lineage.node_write_validation as validation

    builder = getattr(validation, "build_rerun_operation_context", None)
    assert callable(builder), "canonical context builder is not registered"
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)
    run_root = tmp_path / "run_a"
    (run_root / "run_inputs.json").write_text(
        json.dumps({"rerun_of": None, "form": {"model_type": "ols"}}),
        encoding="utf-8",
    )
    (run_root / "run_manifest.json").write_text(
        json.dumps({"status": "completed", "started_at": "2026-07-14T00:00:00+00:00"}),
        encoding="utf-8",
    )

    request = builder(
        tmp_path,
        request_id="inspect-1",
        owner_run_id="run_a",
        op_node_id="model:ols_1",
        active_head_run_id="run_a",
    )

    assert request.context_version == SUPPORTED_CONTEXT_VERSION
    assert request.context_fingerprint.startswith("nocv1:")
    assert request.owner_run_id == "run_a"
    assert request.op_node_id == "model:ols_1"
    assert request.node_hash == "hash_a"
    assert request.forest_node_key == "hash_a"
    assert request.owner_resolution == "active_head_contains_node"
    assert request.active_head_run_id == "run_a"


def test_context_fingerprint_mismatch_fails_closed(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)

    with pytest.raises(ValueError, match="context_stale: context_fingerprint"):
        validate_rerun_operation_target(
            tmp_path,
            _request(context_fingerprint="bad_fingerprint"),
        )


def test_fingerprint_mismatch_error_includes_expected_code(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)

    with pytest.raises(ValueError, match="context_stale: context_fingerprint"):
        validate_rerun_operation_target(
            tmp_path,
            _request(context_fingerprint="wrong"),
        )


def test_node_index_hash_mismatch_raises_context_mismatch(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    (tmp_path / "run_a" / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": "hash_b"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="context_mismatch: node_hash"):
        validate_rerun_operation_target(tmp_path, _request())


def test_forest_node_key_mismatch_raises_context_mismatch(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    (tmp_path / "run_a" / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": "hash_a"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="context_mismatch: forest_node_key"):
        validate_rerun_operation_target(
            tmp_path,
            _request(forest_node_key="wrong_hash"),
        )


def test_composite_forest_node_key_passes_when_hash_matches(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    (tmp_path / "run_a" / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": "hash_a"}}),
        encoding="utf-8",
    )

    validate_rerun_operation_target(
        tmp_path,
        _valid_request(tmp_path, forest_node_key="hash_a::model:ols_1"),
    )


def test_missing_node_index_entry_fails_closed_for_context_write(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path, node_id="model:other", node_hash="hash_b")

    with pytest.raises(ValueError, match="context_stale: node_index"):
        validate_rerun_operation_target(tmp_path, _request())


def test_missing_node_index_file_fails_closed_for_context_write(tmp_path: Path):
    _write_graph(tmp_path, "run_a")

    with pytest.raises(ValueError, match="context_stale: node_index"):
        validate_rerun_operation_target(tmp_path, _request())


def test_active_head_run_id_never_overrides_owner_run_id(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)
    _write_graph(tmp_path, "run_active", node_id="model:other")
    _write_node_index(tmp_path, run_id="run_active", node_id="model:other")

    validate_rerun_operation_target(
        tmp_path,
        _valid_request(
            tmp_path,
            active_head_run_id="run_active",
            owner_run_id="run_a",
            owner_resolution="manual_candidate_selection",
        ),
    )


def test_active_head_contains_node_requires_owner_active_match(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)
    _write_graph(tmp_path, "run_active")
    _write_node_index(tmp_path, run_id="run_active")

    with pytest.raises(ValueError, match="context_mismatch: active_head_run_id"):
        validate_rerun_operation_target(
            tmp_path,
            _request(active_head_run_id="run_active", owner_run_id="run_a"),
        )


def test_missing_active_head_run_fails_closed(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)

    with pytest.raises(ValueError, match="context_stale: active_head_run_id"):
        validate_rerun_operation_target(
            tmp_path,
            _request(
                active_head_run_id="missing_active",
                owner_resolution="manual_candidate_selection",
            ),
        )
