from __future__ import annotations

import copy
from pathlib import Path

import pytest

from workbench.lineage.pipeline_drafts import (
    DRAFT_SCHEMA_VERSION,
    DraftHashConflict,
    PipelineDraftStore,
    compute_executable_draft_hash,
    new_draft_id,
)


def _draft() -> dict:
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
                    "editable_schema": [{"key": "x", "kind": "columns", "label": "X"}],
                    "editable_schema_hash": "schema_hash",
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
