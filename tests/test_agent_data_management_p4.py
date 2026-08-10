"""P4 red-to-green coverage for natural-language data management."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.operations import OperationRegistry, OperationValidationError
from workbench.agent.tools import ToolContext, ToolVisibleError
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent import workflow_contracts
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.agent.workflow_contracts import (
    StepSpecContract,
    WORKFLOW_STEP_SPEC_CONTRACTS,
    _validate_step_spec,
    register_workflow_step,
    validate_workflow_steps,
    workflow_step_operations,
    workflow_step_vocabulary,
)
from workbench.data_operations import (
    DataColumnCastValidationError,
    DataTransformSpecV1,
    apply_data_transform,
    preview_data_transform,
)
from workbench.graph_store import GraphStore
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes
from workbench.lineage.pipeline_drafts import PipelineDraftStore


DATA_OPERATIONS = (
    "data.merge",
    "data.append",
    "data.reshape",
    "data.subset",
    "data.feature_recipe",
    "data.dedupe",
    "data.rename",
    "data.aggregate",
    "data.fill_missing",
    "data.tsset",
    "data.lag",
)

DIRECT_DATA_OPERATIONS = {
    "data.merge",
    "data.append",
    "data.reshape",
    "data.subset",
    "data.feature_recipe",
}


def _apply(project: Path, spec: DataTransformSpecV1) -> pd.DataFrame:
    preview = preview_data_transform(project, spec)
    assert preview.status == "ready"
    effect = apply_data_transform(project, spec, preview)
    return pd.read_csv(project / "runs" / spec.source_run_id / effect.artifact_path)


def _secondary_project(project: Path, run_id: str, frame: pd.DataFrame, artifact_id: str) -> None:
    run_root = project / "runs" / run_id
    run_root.mkdir(parents=True)
    path = run_root / "data.csv"
    frame.to_csv(path, index=False)
    from workbench.artifacts import sha256_file, write_json
    from workbench.graph_model import BranchRef, Graph, Node, NodeKind, Stage

    write_json(
        run_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(path),
                    "inputs": [],
                }
            ],
        },
    )
    node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Secondary data",
        created_at="2026-08-08T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary=f"Secondary: {len(frame)} rows",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=run_id,
            nodes={node.id: node},
            edges={},
            branches={"main": BranchRef("main", None, (node.id,))},
        )
    )


def test_p4_operations_are_registered_with_operation_specific_closed_schemas() -> None:
    registry = OperationRegistry()

    assert set(DATA_OPERATIONS) <= set(registry.operation_ids())
    assert set(DATA_OPERATIONS) <= set(workflow_step_operations())
    assert set(DATA_OPERATIONS) <= set(workflow_step_vocabulary()["step_operations"])
    assert "data.sort" not in registry.operation_ids()
    assert "data.sort" not in workflow_step_operations()

    for operation_id in DATA_OPERATIONS:
        definition = registry.require(operation_id)
        assert definition.editable_schema["additionalProperties"] is False
        assert definition.proposal_schema["properties"]["changes"]["additionalProperties"] is False
        assert definition.executor_key == "workbench.agent.workflow_runtime.data_operation"
        assert definition.natural_language_enabled is (operation_id in DIRECT_DATA_OPERATIONS)
        contract = WORKFLOW_STEP_SPEC_CONTRACTS[operation_id]
        assert contract.produces_dataset is True
        assert contract.consumes_input_frame is True
        assert contract.replayable_by_recipe is False

    merge_changes = registry.require("data.merge").proposal_schema["properties"]["changes"]
    assert {
        "secondary_run_id",
        "secondary_node_id",
        "secondary_artifact_id",
        "keys",
    } <= set(merge_changes["required"])
    append_changes = registry.require("data.append").proposal_schema["properties"]["changes"]
    assert {
        "secondary_run_id",
        "secondary_node_id",
        "secondary_artifact_id",
    } <= set(append_changes["required"])


def test_p4_nested_field_schemas_are_closed_and_recipe_vocabulary_is_derived() -> None:
    vocabulary = workflow_step_vocabulary()["step_operations"]
    assert set(vocabulary["data.feature_recipe"]["field_enums"]["recipe_operation_id"]) == {
        "interaction",
        "log",
        "ratio",
        "recode",
        "derived_variable",
    }
    filters = OperationRegistry().require("data.subset").editable_schema["properties"]["filters"]
    assert filters["items"]["additionalProperties"] is False
    assert set(filters["items"]["properties"]["op"]["enum"]) == {
        "eq",
        "ne",
        "gt",
        "ge",
        "lt",
        "le",
        "in",
        "not_in",
        "between",
        "is_missing",
        "not_missing",
    }


def test_declaration_injection_updates_every_projection_and_is_not_a_hardcoded_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    injected = StepSpecContract(
        summary="P4 declaration-injection test operation.",
        fields={"value": "A test value."},
        required=("value",),
        field_types={"value": "string"},
        dispatcher_key="workbench.agent.workflow_runtime.data_operation",
        output_schema_ref="workbench.test.p4/v1",
        ui_description="P4 declaration-injection test operation.",
        capability_kind="data_operation",
        produces_dataset=True,
        consumes_input_frame=True,
        replayable_by_recipe=False,
    )
    monkeypatch.setitem(WORKFLOW_STEP_SPEC_CONTRACTS, "p4_test.injected", injected)

    registry = OperationRegistry()
    assert "p4_test.injected" in workflow_step_operations()
    assert "p4_test.injected" in registry.operation_ids()
    assert "p4_test.injected" in workflow_step_vocabulary()["step_operations"]
    assert "p4_test.injected" in workflow_contracts.STEP_PRODUCES_DATASET
    assert any(item.capability_id == "p4_test.injected" for item in __import__(
        "workbench.agent.capability_contract", fromlist=["capability_inventory"]
    ).capability_inventory())


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("eq", 2020, [1]),
        ("ne", 2020, [0, 3]),
        ("gt", 2020, [3]),
        ("ge", 2020, [1, 3]),
        ("lt", 2020, [0]),
        ("le", 2020, [0, 1]),
        ("in", [2019, 2020], [0, 1]),
        ("not_in", [2019, 2020], [3]),
        ("between", [2020, 2022], [1, 3]),
        ("is_missing", None, [2]),
        ("not_missing", None, [0, 1, 3]),
    ],
)
def test_subset_closed_comparison_operators_filter_before_column_projection(
    tmp_path: Path,
    operator: str,
    value: object,
    expected: list[int],
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"year": [2019, 2020, None, 2022], "value": [10, 20, 30, 40]}),
    )
    filter_spec = {"column": "year", "op": operator}
    if operator not in {"is_missing", "not_missing"}:
        filter_spec["value"] = value
    result = _apply(
        project,
        DataTransformSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            operation="subset",
            parameters={"columns": ["value"], "filters": [filter_spec]},
        ),
    )
    assert result["value"].tolist() == [[10, 20, 30, 40][i] for i in expected]


def test_subset_rejects_unknown_operator_and_conflicting_legacy_filter(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path, pd.DataFrame({"year": [2020], "value": [1]})
    )
    for parameters in (
        {"columns": ["value"], "filters": [{"column": "year", "op": "contains", "value": 2020}]},
        {"columns": ["value"], "filters": [{"column": "missing", "op": "eq", "value": 1}]},
        {
            "columns": ["value"],
            "equals": {"year": 2020},
            "filters": [{"column": "year", "op": "eq", "value": 2019}],
        },
    ):
        with pytest.raises(DataColumnCastValidationError):
            preview_data_transform(
                project,
                DataTransformSpecV1(
                    source_run_id=run_id,
                    source_node_id="stage:source",
                    source_artifact_id=artifact_id,
                    operation="subset",
                    parameters=parameters,
                ),
            )


@pytest.mark.parametrize(
    ("operation", "frame", "parameters", "columns", "expected"),
    [
        (
            "dedupe",
            {"id": [1, 1, 2], "value": [10, 11, 20]},
            {"columns": ["id"], "keep": "last"},
            ["id", "value"],
            {"id": [1, 2], "value": [11, 20]},
        ),
        (
            "rename",
            {"old": [1, 2], "value": [10, 20]},
            {"mapping": {"old": "new"}},
            ["new", "value"],
            {"new": [1, 2], "value": [10, 20]},
        ),
        (
            "aggregate",
            {"group": ["a", "a", "b"], "value": [1.0, 3.0, 10.0]},
            {
                "group_by": ["group"],
                "aggregations": [
                    {"column": "value", "func": "sum", "output": "value_sum"},
                    {"column": "value", "func": "mean", "output": "value_mean"},
                ],
            },
            ["group", "value_sum", "value_mean"],
            {"group": ["a", "b"], "value_sum": [4.0, 10.0], "value_mean": [2.0, 10.0]},
        ),
        (
            "fill_missing",
            {"value": [1.0, None, 3.0]},
            {"strategies": [{"column": "value", "strategy": "mean"}]},
            ["value"],
            {"value": [1.0, 2.0, 3.0]},
        ),
        (
            "tsset",
            {"time": ["2024-01-02", "2024-01-01"], "value": [2, 1]},
            {"time_column": "time", "frequency": "D"},
            ["time", "value"],
            {"time": ["2024-01-01", "2024-01-02"], "value": [1, 2]},
        ),
        (
            "lag",
            {"time": [1, 2, 3], "value": [10.0, 20.0, 30.0]},
            {"columns": ["value"], "lags": [1, 2]},
            ["time", "value", "value_lag1", "value_lag2"],
            {"value_lag1": [None, 10.0, 20.0], "value_lag2": [None, None, 10.0]},
        ),
    ],
)
def test_atomic_data_operations_return_declaration_derived_values(
    tmp_path: Path,
    operation: str,
    frame: dict[str, list[object]],
    parameters: dict,
    columns: list[str],
    expected: dict[str, list[object]],
) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame(frame))
    result = _apply(
        project,
        DataTransformSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            operation=operation,
            parameters=parameters,
        ),
    )
    assert list(result.columns) == columns
    for column, values in expected.items():
        actual = result[column].tolist()
        assert len(actual) == len(values)
        for actual_value, expected_value in zip(actual, values):
            if expected_value is None:
                assert pd.isna(actual_value)
            else:
                assert actual_value == expected_value


def test_atomic_data_operations_reject_invalid_shapes_and_collisions(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 1], "value": [1.0, None], "time": ["bad", "bad"]}),
    )
    invalid = [
        ("dedupe", {"columns": ["missing"], "keep": "first"}),
        ("rename", {"mapping": {"id": "value"}}),
        ("aggregate", {"group_by": ["id"], "aggregations": [{"column": "value", "func": "sum", "output": "id"}]}),
        ("fill_missing", {"strategies": [{"column": "value", "strategy": "constant"}]}),
        ("tsset", {"time_column": "time", "frequency": "D"}),
        ("lag", {"columns": ["missing"], "lags": [1]}),
    ]
    for operation, parameters in invalid:
        with pytest.raises(DataColumnCastValidationError):
            preview_data_transform(
                project,
                DataTransformSpecV1(
                    source_run_id=run_id,
                    source_node_id="stage:source",
                    source_artifact_id=artifact_id,
                    operation=operation,
                    parameters=parameters,
                ),
            )


def test_transform_and_model_genesis_compile_in_one_multi_step_plan() -> None:
    steps = [
        {
            "step_id": "renamed",
            "operation_id": "data.rename",
            "spec": {"mapping": {"x": "x_renamed"}},
        },
        {
            "step_id": "model",
            "operation_id": "model.genesis",
            "depends_on": ["renamed"],
            "spec": {
                "source": {"from_step": "renamed", "output": "produced_dataset"},
                "model_family": "ols",
                "branches": [
                    {"branch_id": "m1", "outcome": "y", "predictors": ["x_renamed"]}
                ],
            },
        },
    ]
    draft = compile_workflow(
        workflow_id="p4-transform-model",
        target={"run_id": "run_source", "node_ref": "stage:source", "artifact_id": "source_data"},
        preconditions={"context_fingerprint": "fp"},
        steps=steps,
        available_columns=["x", "y"],
    )
    assert [step.operation_id for step in draft.steps] == ["data.rename", "model.genesis"]
    assert draft.steps[1].spec["source"] == {
        "from_step": "renamed",
        "output": "produced_dataset",
    }


def test_transform_and_model_genesis_execute_on_real_persisted_child(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "x": [float(index) for index in range(30)],
            "y": [1.0 + 2 * index + (index % 3) * 0.1 for index in range(30)],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project, frame.to_csv(index=False).encode("utf-8"), filename="fixture.csv"
    )
    write_run_inputs(
        project / "runs" / run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "fixture.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="p4-fixture",
    )
    steps = [
        {
            "step_id": "renamed",
            "operation_id": "data.rename",
            "spec": {"mapping": {"x": "x_renamed"}},
        },
        {
            "step_id": "model",
            "operation_id": "model.genesis",
            "depends_on": ["renamed"],
            "spec": {
                "source": {"from_step": "renamed", "output": "produced_dataset"},
                "model_family": "ols",
                "covariance": "unadjusted",
                "branches": [
                    {"branch_id": "m1", "outcome": "y", "predictors": ["x_renamed"]}
                ],
            },
        },
    ]
    draft = compile_workflow(
        workflow_id="p4-transform-model-execution",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        steps=steps,
        available_columns=["x", "y"],
    )
    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )
    assert state.status == "completed"
    binding = state.steps["renamed"].produced_dataset
    assert binding is not None
    child_frame = pd.read_csv(
        project / "runs" / run_id / "derived" / "data_operations" / "rename" / binding["node_ref"].split(":", 1)[1] / "data.csv"
    )
    assert list(child_frame.columns) == ["x_renamed", "y"]
    graph = GraphStore(project / "runs").read(run_id)
    assert graph.nodes[binding["node_ref"]].parent_stage_id == "stage:source"
    assert any(
        edge.source_id == "stage:source" and edge.target_id == binding["node_ref"]
        for edge in graph.edges.values()
    )
    node_index = json.loads((project / "runs" / run_id / "node_index.json").read_text())
    assert binding["node_ref"] in node_index
    artifact_index = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text()
    )
    assert any(
        item["artifact_id"] == binding["artifact_id"]
        for item in artifact_index["artifacts"]
    )
    stored_contexts = [
        PipelineDraftStore(project).get(item["draft_id"]).draft.get(
            "exploration_context", {}
        )
        for item in PipelineDraftStore(project).list()
    ]
    assert any(
        context.get("source_node_id") == binding["node_ref"]
        and context.get("source_artifact_id") == binding["artifact_id"]
        for context in stored_contexts
    )


def test_list_project_datasets_is_a_real_chain_scoped_read_only_tool(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path, pd.DataFrame({"id": [1, 2], "label": ["a", "b"]})
    )
    _secondary_project(project, "run_secondary", pd.DataFrame({"id": [1], "extra": [9]}), "secondary_data")
    provider = NodeOperationContextProvider(project)
    definitions = provider.tool_definitions(chain_id="chain-a", session_id="chain-session")
    definition = next(item for item in definitions if item.tool_id == "list_project_datasets")
    assert definition.side_effect == "none"
    assert definition.input_schema["additionalProperties"] is False
    result = definition.handler(
        {"detail_for": [{"run_id": run_id, "node_id": "stage:source"}]},
        ToolContext(session_id="chain-session"),
    )
    datasets = result["datasets"]
    identities = {(item["run_id"], item["node_id"], item["artifact_id"]) for item in datasets}
    assert (run_id, "stage:source", artifact_id) in identities
    assert ("run_secondary", "stage:source", "secondary_data") in identities
    detailed = next(item for item in datasets if item["run_id"] == run_id)
    assert detailed["column_details"]
    assert detailed["column_details"][0]["dtype"]
    assert "unique_count" in detailed["column_details"][0]
    assert result["datasets_omitted"] == 0


def test_list_project_datasets_does_not_silently_drop_unknown_detail_identity(
    tmp_path: Path,
) -> None:
    project, _run_id, _artifact_id = _source_project(
        tmp_path, pd.DataFrame({"id": [1], "label": ["a"]})
    )
    provider = NodeOperationContextProvider(project)
    definition = next(
        item
        for item in provider.tool_definitions(chain_id="chain-a", session_id="chain-session")
        if item.tool_id == "list_project_datasets"
    )
    with pytest.raises(ToolVisibleError, match="PROJECT_DATASET_DETAIL_UNAVAILABLE"):
        definition.handler(
            {"detail_for": [{"run_id": "run_missing", "node_id": "stage:source"}]},
            ToolContext(session_id="chain-session"),
        )
