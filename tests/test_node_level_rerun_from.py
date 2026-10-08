"""Node-level rerun provenance (v1.6.3 spec §3.2, completed in v1.8.12).

Run-level ``rerun_from`` (run_inputs.json) says where a rerun *request* came
from. Node-level ``rerun_from`` belongs to the one node the rerun produced and
is what "Compare with source" reads. It is persisted in the child run's
node_index entry for that node, so it survives the node being shared by other
runs in the forest -- the case where the run-level fallback has to fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_rerun_endpoint import (
    _context_fingerprint,
    _create_terminal_run,
    _model_node_id,
    _wait_terminal,
    _write_node_index,
)
from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _context_rerun(project_root: Path, owner: str, node_id: str, node_hash: str, request_id: str) -> str:
    fingerprint = _context_fingerprint(
        project_root,
        owner_run_id=owner,
        op_node_id=node_id,
        node_hash=node_hash,
        forest_node_key=node_hash,
        owner_resolution="active_head_contains_node",
        active_head_run_id=owner,
    )
    response = client.post(
        f"/runs/{owner}/rerun",
        params={"project_root": str(project_root)},
        json={
            "request_id": request_id,
            "operation": "rerun",
            "context_version": "node-operation-context/v1",
            "context_fingerprint": fingerprint,
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": node_hash,
            "forest_node_key": node_hash,
            "owner_resolution": "active_head_contains_node",
            "active_head_run_id": owner,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )
    assert response.status_code == 200, response.text
    child = response.json()["run_id"]
    assert _wait_terminal(project_root, child) == "completed"
    return child


def _node_index(project_root: Path, run_id: str) -> dict:
    return json.loads((project_root / "runs" / run_id / "node_index.json").read_text(encoding="utf-8"))


def _forest_node(project_root: Path, node_id: str, node_hash: str) -> dict:
    """The node in the project forest, which spans every run family."""
    body = client.get("/graph", params={"project_root": str(project_root)}).json()
    return body["nodes"][f"{node_hash}::{node_id}"]


def _rerun_child(tmp_path: Path) -> tuple[Path, str, str, str]:
    project = create_project(tmp_path, "demo")
    owner = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, owner)
    _write_node_index(project.root, owner, node_id, "hash_owner_model")
    child = _context_rerun(project.root, owner, node_id, "hash_owner_model", "req_node_level")
    return project.root, owner, child, node_id


def test_context_rerun_records_node_level_rerun_from_on_the_produced_node(tmp_path: Path) -> None:
    root, _owner, child, node_id = _rerun_child(tmp_path)
    run_level = json.loads((root / "runs" / child / "run_inputs.json").read_text(encoding="utf-8"))["rerun_from"]

    index = _node_index(root, child)
    assert index[node_id]["rerun_from"] == run_level
    assert [key for key, entry in index.items() if "rerun_from" in entry] == [node_id]

    produced = _forest_node(root, node_id, index[node_id]["node_hash"])
    assert produced["rerun_from"] == run_level


def test_a_shared_produced_node_keeps_its_node_level_rerun_from(tmp_path: Path) -> None:
    root, _owner, child, node_id = _rerun_child(tmp_path)
    produced_hash = _node_index(root, child)[node_id]["node_hash"]
    other = _create_terminal_run(root)
    _write_node_index(root, other, node_id, produced_hash)

    produced = _forest_node(root, node_id, produced_hash)

    assert sorted(produced["runs"]) == sorted([child, other])
    # The run-level fallback cannot attribute a node shared by two runs ...
    assert "produced_by_rerun_request_id" not in produced
    # ... the node-level record still can.
    assert produced["rerun_from"]["rerun_request_id"] == "req_node_level"


def test_conflicting_node_level_rerun_from_on_a_shared_node_fails_closed(tmp_path: Path) -> None:
    root, owner, child, node_id = _rerun_child(tmp_path)
    produced_hash = _node_index(root, child)[node_id]["node_hash"]
    other = _create_terminal_run(root)
    index = _node_index(root, other)
    index[node_id] = {
        "node_hash": produced_hash,
        "producing_stage": "estimation",
        "cas_ref": {"node_hash": produced_hash, "artifact": f"model_results/{node_id.split(':', 1)[1]}.json"},
        "rerun_from": {
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "context_fingerprint": "nocv1:a-different-source-context",
            "rerun_request_id": "req_other",
        },
    }
    (root / "runs" / other / "node_index.json").write_text(json.dumps(index), encoding="utf-8")

    produced = _forest_node(root, node_id, produced_hash)

    assert "rerun_from" not in produced
    assert sorted(item["rerun_request_id"] for item in produced["rerun_from_conflicts"]) == [
        "req_node_level",
        "req_other",
    ]
