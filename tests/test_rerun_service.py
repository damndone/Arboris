from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.graph_store import GraphStore
from workbench.projects import create_project
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)
from workbench.services.rerun_service import (
    RerunService,
    RerunReconciliationRequest,
    RerunServiceError,
    RerunSubmissionRequest,
)


client = TestClient(app)


def _csv_with_two_x() -> bytes:
    rows = "\n".join(f"{1 + 2 * i},{i},{i * 3}" for i in range(35))
    return ("y,x1,x2\n" + rows + "\n").encode()


def _wait_terminal(project_root: Path, run_id: str, tries: int = 100) -> str:
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    body: dict = {}
    for _ in range(tries):
        body = client.get(
            f"/runs/{run_id}", params={"project_root": str(project_root)}
        ).json()
        if body.get("status") in terminal:
            return str(body["status"])
        time.sleep(0.1)
    return str(body.get("status"))


def _create_terminal_run(project_root: Path) -> str:
    response = client.post(
        "/runs",
        data={
            "project_root": str(project_root),
            "mode": "auto",
            "model_type": "ols",
            "y": "y",
            "x": "x1,x2",
        },
        files={"file": ("d.csv", io.BytesIO(_csv_with_two_x()), "text/csv")},
    )
    response.raise_for_status()
    run_id = response.json()["run_id"]
    assert _wait_terminal(project_root, run_id) == "completed"
    return run_id


def _workbench_context(project_root: Path, run_id: str, node_id: str) -> dict:
    node_index = json.loads(
        (project_root / "runs" / run_id / "node_index.json").read_text()
    )
    node_hash = node_index[node_id]["node_hash"]
    context = {
        "operation_id": "model.rerun",
        "operation_version": "v1",
        "operation_record_id": "oprec_test",
        "proposal_id": "proposal_test",
        "source_chain_id": "chain-a",
        "source_session_id": "session-a",
        "source_run_id": run_id,
        "source_node_ref": node_id,
        "fork_id": "fork-test",
        "child_chain_id": "chain-b",
        "child_session_id": "session-b",
        "context_version": "node-operation-context/v1",
        "context_fingerprint": "pending",
        "owner_run_id": run_id,
        "op_node_id": node_id,
        "node_hash": node_hash,
        "forest_node_key": node_hash,
        "owner_resolution": "active_head_contains_node",
        "active_head_run_id": run_id,
    }
    request = NodeWriteOperationRequestV1(
        request_id="oprec_test",
        operation="rerun",
        context_version=context["context_version"],
        context_fingerprint=context["context_fingerprint"],
        owner_run_id=context["owner_run_id"],
        op_node_id=context["op_node_id"],
        node_hash=context["node_hash"],
        forest_node_key=context["forest_node_key"],
        owner_resolution=context["owner_resolution"],
        active_head_run_id=context["active_head_run_id"],
    )
    context["context_fingerprint"] = compute_context_fingerprint(
        project_root / "runs", request
    )
    return context


def test_rerun_service_submits_child_with_wire_format_and_workbench_context(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "demo")
    parent_run_id = _create_terminal_run(project.root)
    graph = GraphStore(project.root / "runs").read(parent_run_id)
    model_node_id = next(
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    )
    context = _workbench_context(project.root, parent_run_id, model_node_id)

    result = RerunService(project.root).submit(
        RerunSubmissionRequest(
            source_run_id=parent_run_id,
            from_node=model_node_id,
            op_overrides={"x": ["x1"]},
            rerun_reason="agent_confirmed",
            rerun_from={
                "owner_run_id": parent_run_id,
                "op_node_id": model_node_id,
            },
            workbench_context=context,
        )
    )

    assert result.run_id != parent_run_id
    assert result.status == "running"
    child_inputs = json.loads(
        (project.root / "runs" / result.run_id / "run_inputs.json").read_text()
    )
    assert child_inputs["form"]["x"] == "x1"
    assert child_inputs["rerun_of"] == parent_run_id
    assert child_inputs["rerun_from"]["op_node_id"] == model_node_id
    assert child_inputs["workbench_context"] == context
    assert _wait_terminal(project.root, result.run_id) == "completed"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("node_hash", "tampered-node-hash", "context_mismatch"),
        ("forest_node_key", "tampered-forest-key", "context_mismatch"),
        ("context_fingerprint", "tampered-fingerprint", "context_stale"),
    ],
)
def test_rerun_service_rejects_tampered_workbench_context_before_dispatch(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    project = create_project(tmp_path, "demo")
    parent_run_id = _create_terminal_run(project.root)
    graph = GraphStore(project.root / "runs").read(parent_run_id)
    model_node_id = next(
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    )
    context = _workbench_context(project.root, parent_run_id, model_node_id)
    context[field] = value
    run_ids_before = {
        entry.name for entry in (project.root / "runs").iterdir() if entry.is_dir()
    }

    result_or_error: object
    try:
        result_or_error = RerunService(project.root).submit(
            RerunSubmissionRequest(
                source_run_id=parent_run_id,
                from_node=model_node_id,
                op_overrides={"x": ["x1"]},
                workbench_context=context,
            )
        )
    except RerunServiceError as exc:
        result_or_error = exc

    if not isinstance(result_or_error, RerunServiceError):
        _wait_terminal(project.root, result_or_error.run_id)
        pytest.fail("tampered workbench context was accepted")

    assert isinstance(result_or_error, RerunServiceError)
    assert result_or_error.code == expected_code
    run_ids_after = {
        entry.name for entry in (project.root / "runs").iterdir() if entry.is_dir()
    }
    assert run_ids_after == run_ids_before


def test_rerun_service_reconciles_terminal_child_and_rejects_tampered_context(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "demo")
    parent_run_id = _create_terminal_run(project.root)
    graph = GraphStore(project.root / "runs").read(parent_run_id)
    model_node_id = next(
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    )
    context = _workbench_context(project.root, parent_run_id, model_node_id)
    service = RerunService(project.root)
    result = service.submit(
        RerunSubmissionRequest(
            source_run_id=parent_run_id,
            from_node=model_node_id,
            op_overrides={"x": ["x1"]},
            workbench_context=context,
        )
    )
    assert _wait_terminal(project.root, result.run_id) == "completed"

    reconciliation_request = RerunReconciliationRequest(
        source_run_id=parent_run_id,
        target_run_id=result.run_id,
        from_node=model_node_id,
        op_overrides={"x": ["x1"]},
        workbench_context=context,
    )
    reconciled = service.reconcile_submission(reconciliation_request)
    assert reconciled.status == "completed"
    assert reconciled.verification["passed"] is True
    assert reconciled.diff_ref["changed_fields"] == ["x"]

    tampered = service.reconcile_submission(
        RerunReconciliationRequest(
            **{
                **reconciliation_request.__dict__,
                "workbench_context": {**context, "fork_id": "fork-tampered"},
            }
        )
    )
    assert tampered.status == "failed"
    assert tampered.error == {"type": "VerificationFailed"}
    assert tampered.verification["passed"] is False
