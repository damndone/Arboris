from __future__ import annotations

import copy
from pathlib import Path

import pytest

from workbench.lineage.pipeline_drafts import (
    DRAFT_SCHEMA_VERSION,
    DraftHashConflict,
    DraftLockedForExecution,
    PipelineDraftStore,
    compute_executable_draft_hash,
    new_draft_id,
    schema_hash,
    validate_draft_for_execution,
)


def _draft() -> dict:
    editable_schema = [{"key": "x", "kind": "columns", "label": "X"}]
    return {
        "draft_id": "draft_abc123",
        "schema_version": DRAFT_SCHEMA_VERSION,
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:00Z",
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": "run_source",
            "source_model_node_id": "model_node",
            "source_op_node_id": "model_op",
            "source_node_hash": "h_source",
            "source_context_fingerprint": "ctx_source",
            "source_input_fingerprint": "input_source",
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": "run_source",
                    "schema_fingerprint": "schema_1",
                    "input_fingerprint": "input_source",
                    "row_count": 10,
                    "column_count": 3,
                    "columns_summary": [{"name": "y"}, {"name": "x1"}, {"name": "x2"}],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": "ols",
                    "schema_id": "ols@v1",
                    "editable_schema": editable_schema,
                    "editable_schema_hash": schema_hash(editable_schema),
                    "source_ref": {
                        "source_run_id": "run_source",
                        "source_model_node_id": "model_node",
                        "source_op_node_id": "model_op",
                        "source_node_hash": "h_source",
                        "source_context_fingerprint": "ctx_source",
                    },
                    "source_params": {"x": ["x1"]},
                    "params": {"x": ["x1"]},
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }


def test_draft_id_is_path_safe() -> None:
    for _ in range(20):
        draft_id = new_draft_id()
        assert draft_id.startswith("draft_")
        assert "/" not in draft_id
        assert "\\" not in draft_id
        assert ".." not in draft_id


def test_hash_excludes_volatile_metadata() -> None:
    draft = _draft()
    first = compute_executable_draft_hash(draft)
    changed = copy.deepcopy(draft)
    changed["updated_at"] = "2030-01-01T00:00:00Z"
    changed["status"] = "saving"
    assert compute_executable_draft_hash(changed) == first


def test_hash_changes_when_params_change() -> None:
    draft = _draft()
    changed = copy.deepcopy(draft)
    changed["graph"]["nodes"][1]["params"] = {"x": ["x1", "x2"]}
    assert compute_executable_draft_hash(changed) != compute_executable_draft_hash(draft)


def test_store_roundtrip_and_base_hash_conflict(tmp_path: Path) -> None:
    store = PipelineDraftStore(tmp_path)
    draft = _draft()
    saved = store.create(draft)
    assert saved.draft["draft_id"] == "draft_abc123"
    loaded = store.get("draft_abc123")
    assert loaded.draft_hash == saved.draft_hash
    with pytest.raises(DraftHashConflict):
        store.update_params(
            "draft_abc123",
            model_node_id="model_1",
            base_draft_hash="stale",
            params={"x": ["x2"]},
        )


def test_store_locks_are_shared_across_instances(tmp_path: Path) -> None:
    store_a = PipelineDraftStore(tmp_path)
    store_b = PipelineDraftStore(tmp_path)
    draft = _draft()
    saved = store_a.create(draft)

    lock = store_a.execution_lock("draft_abc123")
    lock.acquire()
    try:
        with pytest.raises(DraftLockedForExecution):
            store_b.update_params(
                "draft_abc123",
                model_node_id="model_1",
                base_draft_hash=saved.draft_hash,
                params={"x": ["x2"]},
            )
    finally:
        lock.release()


def test_validate_passes_exact_input_to_model_shape() -> None:
    result = validate_draft_for_execution(_draft(), execution_mode="rerun_child")
    assert result["ok"] is True
    assert result["status"] == "valid"
    assert result["executable"] is True
    assert result["validated_draft_hash"] == compute_executable_draft_hash(_draft())
    assert result["validated_execution_mode"] == "rerun_child"


def test_validate_blocks_new_run() -> None:
    result = validate_draft_for_execution(_draft(), execution_mode="new_run")
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["executable"] is False
    assert result["checks"][0]["code"] == "NEW_RUN_EXECUTION_NOT_ENABLED"
    assert "validated_draft_hash" not in result


def test_validate_blocks_missing_created_from_for_rerun_child() -> None:
    draft = _draft()
    draft.pop("created_from")
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "CREATED_FROM_REQUIRED_FOR_RERUN_CHILD" for c in result["checks"])


def test_validate_blocks_source_ref_mismatch() -> None:
    draft = _draft()
    draft["graph"]["nodes"][1]["source_ref"]["source_node_hash"] = "different"
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "MODEL_SOURCE_REF_MISMATCH" for c in result["checks"])


def test_validate_blocks_invalid_graph_shape() -> None:
    draft = _draft()
    draft["graph"]["edges"] = []
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "INVALID_DRAFT_GRAPH_SHAPE" for c in result["checks"])


def test_validate_blocks_invalid_editable_schema_hash() -> None:
    draft = _draft()
    draft["graph"]["nodes"][1]["editable_schema_hash"] = "tampered"
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "EDITABLE_SCHEMA_HASH_MISMATCH" for c in result["checks"])


def test_validate_blocks_invalid_select_option() -> None:
    draft = _draft()
    schema = [
        {
            "key": "covariance",
            "kind": "select",
            "label": "Covariance",
            "options": ["robust", "clustered"],
        }
    ]
    draft["graph"]["nodes"][1]["editable_schema"] = schema
    draft["graph"]["nodes"][1]["editable_schema_hash"] = schema_hash(schema)
    draft["graph"]["nodes"][1]["source_params"] = {"covariance": "robust"}
    draft["graph"]["nodes"][1]["params"] = {"covariance": "not_allowed"}

    result = validate_draft_for_execution(draft, execution_mode="rerun_child")

    assert result["ok"] is False
    assert any(c["code"] == "INVALID_PARAM_OPTION" for c in result["checks"])


def _make_draft(draft_id: str, status: str = "draft", model_type: str = "ols") -> dict:
    return {
        "draft_id": draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "status": status,
        "created_from": {
            "source_type": "run",
            "source_run_id": "run_a",
            "source_model_node_id": "model#0",
            "source_op_node_id": "model#0",
            "source_node_hash": "hash_a",
            "source_context_fingerprint": "ctx_a",
            "source_input_fingerprint": "in_a",
        },
        "graph": {
            "nodes": [
                {"node_type": "model", "node_id": "model#0", "model_type": model_type,
                 "editable_schema": []},
            ],
            "edges": [],
        },
        "default_execution_mode": "rerun_child",
    }


def test_list_empty_returns_empty(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    assert store.list() == []


def test_list_returns_summaries(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("draft_aaaaaaaa"))
    store.create(_make_draft("draft_bbbbbbbb", model_type="logit"))
    summaries = {s["draft_id"]: s for s in store.list()}
    assert set(summaries) == {"draft_aaaaaaaa", "draft_bbbbbbbb"}
    assert summaries["draft_bbbbbbbb"]["model_type"] == "logit"
    assert summaries["draft_aaaaaaaa"]["status"] == "draft"
    assert summaries["draft_aaaaaaaa"]["source_node_hash"] == "hash_a"
    assert "draft_hash" in summaries["draft_aaaaaaaa"]


def test_list_skips_corrupt_json(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("draft_aaaaaaaa"))
    (store.drafts_dir / "draft_corrupt.json").write_text("{not json", encoding="utf-8")
    ids = {s["draft_id"] for s in store.list()}
    assert ids == {"draft_aaaaaaaa"}


def test_delete_removes_json_and_dedupe(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("draft_aaaaaaaa"))
    # a stray dedupe file for this draft must also go
    dedupe = store.drafts_dir / "draft_aaaaaaaa.deadbeef.execution.json"
    dedupe.write_text("{}", encoding="utf-8")
    assert store._path("draft_aaaaaaaa").exists()

    store.delete("draft_aaaaaaaa")

    assert not store._path("draft_aaaaaaaa").exists()
    assert not dedupe.exists()


def test_delete_missing_is_idempotent(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    # must not raise
    store.delete("draft_missing0")
