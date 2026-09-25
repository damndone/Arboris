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


def _clustered_ols_csv() -> bytes:
    rows = ["y,x,firm"]
    for firm in range(12):
        for period in range(3):
            x = firm + period / 10
            y = 2 + 1.5 * x + (firm % 3) / 10
            rows.append(f"{y},{x},firm-{firm}")
    return ("\n".join(rows) + "\n").encode()


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


def _create_terminal_unadjusted_ols_run(project_root: Path) -> str:
    response = client.post(
        "/runs",
        data={
            "project_root": str(project_root),
            "mode": "auto",
            "model_type": "ols",
            "y": "y",
            "x": "x",
            "focal_x": "x",
            "covariance": "unadjusted",
        },
        files={
            "file": (
                "clustered.csv",
                io.BytesIO(_clustered_ols_csv()),
                "text/csv",
            )
        },
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


def test_rerun_service_accepts_cluster_variable_for_ols_clustered_covariance(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "clustered-ols")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)
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
            op_overrides={
                "covariance": "clustered",
                "entity_col": "firm",
            },
            rerun_reason="agent_confirmed",
            rerun_from={
                "owner_run_id": parent_run_id,
                "op_node_id": model_node_id,
            },
            workbench_context=context,
        )
    )

    child_inputs = json.loads(
        (project.root / "runs" / result.run_id / "run_inputs.json").read_text()
    )
    assert child_inputs["form"]["covariance"] == "clustered"
    assert child_inputs["form"]["entity_col"] == "firm"
    assert _wait_terminal(project.root, result.run_id) == "completed"
    child_inputs = json.loads(
        (project.root / "runs" / result.run_id / "run_inputs.json").read_text()
    )
    assert child_inputs["confirmed_payload"] == child_inputs["executed_payload"]

    model_result = json.loads(
        (
            project.root
            / "runs"
            / result.run_id
            / "model_results"
            / "ols_1.json"
        ).read_text()
    )
    assert model_result["covariance"] == "clustered"
    assert model_result["entity_col"] == "firm"
    assert model_result["x_columns"] == ["x"]


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


def _model_node(project_root: Path, run_id: str) -> str:
    graph = GraphStore(project_root / "runs").read(run_id)
    return next(
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    )


def _submit_levels(project_root: Path, run_id: str, levels: dict) -> object:
    node_id = _model_node(project_root, run_id)
    return RerunService(project_root).submit(
        RerunSubmissionRequest(
            source_run_id=run_id,
            from_node=node_id,
            op_overrides={"labels": {"measurement_level": levels}},
            rerun_reason="agent_confirmed",
            rerun_from={"owner_run_id": run_id, "op_node_id": node_id},
            workbench_context=_workbench_context(project_root, run_id, node_id),
        )
    )


def test_a_rerun_that_only_declares_columns_outside_the_model_is_refused(
    tmp_path: Path,
) -> None:
    """Declaring `firm` nominal does not put `firm` into `y ~ x`.

    Accepting it produced a child run identical to its parent while the Agent's
    proposal said the column had been added as dummies -- a completed operation
    that silently did not do what the user confirmed.
    """

    project = create_project(tmp_path, "outside-model")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)
    runs_before = set((project.root / "runs").iterdir())

    with pytest.raises(RerunServiceError) as caught:
        _submit_levels(project.root, parent_run_id, {"firm": "nominal"})

    assert caught.value.code == "RERUN_HAS_NO_MODEL_EFFECT"
    message = str(caught.value)
    assert "firm" in message
    assert "model.genesis" in message
    assert set((project.root / "runs").iterdir()) == runs_before


def test_the_agent_rerun_path_refuses_a_declaration_for_an_absent_column(
    tmp_path: Path,
) -> None:
    """The v1.8.7 anti-fabrication guard must hold on the Agent path too."""

    project = create_project(tmp_path, "absent-column")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)

    with pytest.raises(RerunServiceError) as caught:
        _submit_levels(project.root, parent_run_id, {"x": "scale", "not_a_column": "nominal"})

    assert caught.value.code == "MEASUREMENT_LEVEL_UNKNOWN_COLUMN"
    assert "not_a_column" in str(caught.value)


def test_a_rerun_declaring_a_model_column_alongside_others_is_accepted(
    tmp_path: Path,
) -> None:
    """Batch declaration stays legal once any declared column is in the model."""

    project = create_project(tmp_path, "batch-levels")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)

    result = _submit_levels(project.root, parent_run_id, {"y": "scale", "firm": "nominal"})

    assert result.run_id != parent_run_id
    assert _wait_terminal(project.root, result.run_id) == "completed"


def test_the_agent_hears_why_before_the_user_is_asked_to_confirm(tmp_path: Path) -> None:
    """The proposal tool applies the same check, so the Agent can re-plan."""

    from types import SimpleNamespace

    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.orchestrator import WorkbenchOrchestrator

    project = create_project(tmp_path, "proposal-preflight")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)
    host = SimpleNamespace(context_provider=NodeOperationContextProvider(project.root))

    def preflight(levels: dict) -> None:
        WorkbenchOrchestrator._preflight_model_rerun_declarations(
            host,
            {
                "target": {"run_id": parent_run_id},
                "changes": {"labels": {"measurement_level": levels}},
            },
        )

    from workbench.agent.tools import ToolVisibleError

    # ToolVisibleError, not a bare ValueError: only its message reaches the model.
    with pytest.raises(ToolVisibleError, match=r"RERUN_HAS_NO_MODEL_EFFECT.*firm.*model\.genesis"):
        preflight({"firm": "nominal"})
    preflight({"y": "scale", "firm": "nominal"})


def test_an_agent_rerun_can_relabel_and_declare_missing_codes(tmp_path: Path) -> None:
    """Metadata edits ride model.rerun: labels reach the child run's inputs."""

    project = create_project(tmp_path, "relabel")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)
    node_id = _model_node(project.root, parent_run_id)
    labels = {
        "variable_labels": {"x": "Exposure"},
        "value_labels": {"firm": {"firm-0": "First firm"}},
        "user_missing_values": {"x": [-99]},
    }
    result = RerunService(project.root).submit(
        RerunSubmissionRequest(
            source_run_id=parent_run_id,
            from_node=node_id,
            op_overrides={"labels": labels},
            rerun_reason="agent_confirmed",
            rerun_from={"owner_run_id": parent_run_id, "op_node_id": node_id},
            workbench_context=_workbench_context(project.root, parent_run_id, node_id),
        )
    )
    assert _wait_terminal(project.root, result.run_id) == "completed"
    child_form = json.loads(
        (project.root / "runs" / result.run_id / "run_inputs.json").read_text()
    )["form"]
    assert child_form["labels"]["variable_labels"] == {"x": "Exposure"}
    assert child_form["labels"]["user_missing_values"] == {"x": [-99]}


def test_a_rerun_aimed_at_a_data_node_is_redirected_before_confirmation(tmp_path: Path) -> None:
    """The Agent targets the data node for label edits; tell it which node reruns."""

    from types import SimpleNamespace

    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.orchestrator import WorkbenchOrchestrator

    project = create_project(tmp_path, "data-node-target")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)
    model_node = _model_node(project.root, parent_run_id)
    host = SimpleNamespace(context_provider=NodeOperationContextProvider(project.root))

    def preflight(node_ref: str) -> None:
        WorkbenchOrchestrator._preflight_model_rerun_declarations(
            host,
            {
                "target": {"run_id": parent_run_id, "node_ref": node_ref},
                "changes": {"labels": {"variable_labels": {"x": "Exposure"}}},
            },
        )

    from workbench.agent.tools import ToolVisibleError

    with pytest.raises(ToolVisibleError, match=rf"MODEL_RERUN_TARGET_NOT_EDITABLE.*{model_node}"):
        preflight("stage:cleaned")
    preflight(model_node)



@pytest.mark.parametrize("incremental_cache", ["0", "1"])
def test_a_rerun_declaring_missing_codes_changes_the_estimation_sample(
    tmp_path: Path, monkeypatch, incremental_cache: str
) -> None:
    """Declared codes are applied at the source stage, so a rerun from the
    model node must not reuse a cached upstream that never saw them."""

    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", incremental_cache)
    project = create_project(tmp_path, f"missing-rerun-{incremental_cache}")
    parent_run_id = _create_terminal_unadjusted_ols_run(project.root)
    node_id = _model_node(project.root, parent_run_id)
    result = RerunService(project.root).submit(
        RerunSubmissionRequest(
            source_run_id=parent_run_id,
            from_node=node_id,
            op_overrides={"labels": {"user_missing_values": {"x": [{"low": 0, "high": 2.5}]}}},
            rerun_reason="agent_confirmed",
            rerun_from={"owner_run_id": parent_run_id, "op_node_id": node_id},
            workbench_context=_workbench_context(project.root, parent_run_id, node_id),
        )
    )
    assert _wait_terminal(project.root, result.run_id) == "completed"

    def nobs(run_id: str) -> int:
        return json.loads(
            (project.root / "runs" / run_id / "model_results" / "ols_1.json").read_text()
        )["nobs"]

    applied = json.loads(
        (project.root / "runs" / result.run_id / "measurement" / "user_missing.json").read_text()
    )
    assert applied["columns"]["x"]["converted"] == 9
    assert nobs(result.run_id) == nobs(parent_run_id) - 9
