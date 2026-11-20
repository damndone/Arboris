"""A native frame consumer publishes the identity of the dataset it read."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_contracts import validate_workflow_steps
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.artifacts import read_json, sha256_file
from workbench.contracts.common.errors import OperationValidationError
from workbench.exploration_log import ExplorationLog
from workbench.graph_store import GraphStore
from workbench.native_build import default_output, manifest_path


def _derive(step_id: str, output: str) -> dict:
    return {
        "step_id": step_id,
        "operation_id": "statistical.derive_numeric",
        "spec": {"recipes": [{"operator": "multiply", "input_columns": ["ret", "scale"], "output_name": output}]},
    }


def _risk(*depends_on: str) -> dict:
    return {
        "step_id": "risk", "operation_id": "quant.rolling_risk", "depends_on": list(depends_on),
        "spec": {"input_mode": "frame", "column_bindings": {"time_col": "t", "return_columns": ["scaled_ret"]},
                 "options": {"window": 3}},
    }


def test_native_result_binds_to_the_real_derived_dataset(tmp_path: Path) -> None:
    module = Path(__file__).resolve().parents[1] / "native" / "quant_replay"
    if not manifest_path(default_output(module)).is_file():
        pytest.skip("Explicit quant replay native build required")
    frame = pd.DataFrame({"t": range(5), "ret": range(5), "scale": [2] * 5})
    project, run_id, source_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="native-derived-source",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": source_id},
        preconditions={"context_fingerprint": "sha256:source-binding"},
        steps=[_derive("scale_returns", "scaled_ret"), _risk("scale_returns")],
        available_columns=list(frame.columns),
    )
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == "completed"

    binding = state.steps["scale_returns"].produced_dataset
    assert binding is not None
    artifact_id, = state.steps["risk"].artifact_ids
    run_root = project / "runs" / run_id
    index = read_json(run_root / "artifacts_index.json")["artifacts"]
    saved = next(entry for entry in index if entry["artifact_id"] == artifact_id)
    data = next(entry for entry in index if entry["artifact_id"] == binding["artifact_id"])
    envelope = read_json(run_root / saved["path"])
    assert envelope["source"]["artifact_id"] == binding["artifact_id"]
    assert envelope["source"]["sha256"] == binding["content_sha256"] == sha256_file(run_root / data["path"])
    assert envelope["source"]["node_ref"] == binding["node_ref"]
    assert saved["inputs"] == [binding["artifact_id"]]
    assert envelope["local_detail"]["latest_covariance"]["matrix"] == [[4.0]]
    graph = GraphStore(project / "runs").read(run_id)
    result_node = f"native-result:{artifact_id}"
    assert graph.nodes[result_node].parent_stage_id == binding["node_ref"]
    assert any(edge.source_id == binding["node_ref"] and edge.target_id == result_node for edge in graph.edges.values())
    events = ExplorationLog(project, workflow_id=draft.workflow_id).read_events()
    assert {
        (event["workflow_step_id"], event["status"]): event["source_artifact_ids"]
        for event in events
    } == {
        ("scale_returns", "running"): [source_id],
        ("scale_returns", "completed"): [source_id],
        ("risk", "running"): [binding["artifact_id"]],
        ("risk", "completed"): [binding["artifact_id"]],
    }
    assert draft.target["artifact_id"] == source_id


def test_blocked_native_consumer_does_not_claim_the_workflow_target_as_source(tmp_path: Path) -> None:
    frame = pd.DataFrame({"t": range(5), "ret": range(5)})
    project, run_id, source_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="native-unresolved-source",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": source_id},
        preconditions={"context_fingerprint": "sha256:source-binding"},
        steps=[_derive("scale_returns", "scaled_ret"), _risk("scale_returns")],
        available_columns=[*frame.columns, "scale"],
    )
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.steps["scale_returns"].status == "failed"
    assert state.steps["risk"].status == "blocked"
    events = ExplorationLog(project, workflow_id=draft.workflow_id).read_events()
    risk_event, = (event for event in events if event["workflow_step_id"] == "risk")
    assert risk_event["status"] == "blocked"
    assert risk_event["source_artifact_ids"] == []


def test_multiple_replayable_branches_cannot_be_implicit_native_input() -> None:
    with pytest.raises(OperationValidationError, match=r"risk.*source\.from_step"):
        validate_workflow_steps([
            _derive("scale_returns", "scaled_ret"), _derive("other_returns", "other_ret"),
            _risk("scale_returns", "other_returns"),
        ], available_columns=["t", "ret", "scale"])


def test_legacy_frame_consumer_keeps_recipe_replay_without_a_source_binding() -> None:
    correlation = {
        "step_id": "correlation", "operation_id": "test.correlations", "depends_on": ["scale_returns"],
        "spec": {"input_mode": "frame", "column_bindings": {"columns": ["ret", "scaled_ret"]}, "options": {}},
    }
    steps = validate_workflow_steps([_derive("scale_returns", "scaled_ret"), correlation],
                                    available_columns=["t", "ret", "scale"])
    assert "source" not in steps[-1]["spec"]
