"""v1.8.9 step 7 — a declared data operation is offered everywhere, correctly.

These tests are the registry's contract: for every declaration, the Agent's
workflow vocabulary offers it, the HTTP route admits it, its worked example
passes validation and executes, and the output columns the compile step
projects are the ones execution actually produces. A new declaration that
breaks any surface fails here, not in a user's session.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow import compile_workflow
from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS, workflow_step_vocabulary
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.api import app
from workbench.data_operation_registry import data_operation_declarations
from workbench.data_operations import DataTransformSpecV1

DECLARATIONS = data_operation_declarations()
IDS = [declaration.operation for declaration in DECLARATIONS]


def test_every_data_operation_is_declared() -> None:
    assert set(IDS) == {
        "aggregate", "append", "dedupe", "fill_missing", "lag", "merge", "recode",
        "rename", "reshape", "subset", "tsset",
    }


@pytest.mark.parametrize("declaration", DECLARATIONS, ids=IDS)
def test_the_agent_and_the_route_both_offer_it(declaration) -> None:
    contract = WORKFLOW_STEP_SPEC_CONTRACTS[declaration.workflow_operation_id]
    assert contract.natural_language_enabled is declaration.natural_language_enabled
    assert tuple(contract.required) == declaration.required
    assert "Example spec:" in contract.summary
    assert declaration.workflow_operation_id in str(workflow_step_vocabulary())
    example = dict(declaration.example)
    DataTransformSpecV1(
        source_run_id="r", source_node_id="n", source_artifact_id="a",
        operation=declaration.operation, parameters=declaration.parameters_of(example),
        secondary_run_id=example.get("secondary_run_id"),
        secondary_node_id=example.get("secondary_node_id"),
        secondary_artifact_id=example.get("secondary_artifact_id"),
    )


@pytest.mark.parametrize("declaration", DECLARATIONS, ids=IDS)
def test_the_example_executes_and_the_projection_matches_execution(declaration) -> None:
    frame = declaration.example_frame()
    declaration.validate(declaration.example)
    assert declaration.referenced_columns(declaration.example) <= set(frame.columns)
    secondary = declaration.example_secondary_frame() if declaration.secondary_input else None
    result = declaration.run(frame, declaration.example, secondary)
    projected = declaration.output_columns(declaration.example, set(frame.columns))
    if declaration.secondary_input:
        # The secondary dataset's columns are bound at runtime; the projection
        # promises only what the primary side and the spec determine.
        assert projected <= set(result.columns)
    else:
        assert set(result.columns) == projected


@pytest.mark.parametrize("declaration", DECLARATIONS, ids=IDS)
def test_it_reads_as_a_sentence_with_labels(declaration) -> None:
    labels = {column: f"label of {column}" for column in declaration.example_frame().columns}
    sentence = declaration.sentence(declaration.example, labels)
    assert declaration.describe is not None
    assert sentence and "{" not in sentence and "[" not in sentence
    referenced = declaration.referenced_columns(declaration.example)
    assert all(f"{column} (label of {column})" in sentence for column in referenced), sentence


@pytest.mark.parametrize("declaration", DECLARATIONS, ids=IDS)
def test_the_agent_workflow_runs_it_and_records_what_it_read(tmp_path: Path, declaration) -> None:
    """The same lineage guard as legacy data steps (test_workflow_seam): run the
    declared step on a DERIVED dataset and require every durable record to
    name that dataset, never the workflow's original target."""

    if declaration.secondary_input:
        pytest.skip("two-input lineage is covered by test_workflow_seam with a real secondary dataset")

    from tests.test_workflow_seam import _data_management_claims, _numeric_step

    frame = declaration.example_frame().assign(size=1.0, weight=3.0)
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id=f"wf_{declaration.operation}",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "sha256:fixture"},
        steps=[
            _numeric_step("first", "doubled"),
            {
                "step_id": "declared",
                "operation_id": declaration.workflow_operation_id,
                "spec": {**dict(declaration.example), "source": {"from_step": "first", "output": "produced_dataset"}},
            },
        ],
        available_columns=list(frame.columns),
    )
    executor = build_workflow_step_executor(project, draft)
    results = {}
    for step in draft.steps:
        results[step.step_id] = executor(step, results)
    binding = results["first"].payload["produced_dataset"]
    claims = _data_management_claims(project, draft, "declared", results["declared"])
    assert claims["declared:artifact-input"]["artifact_id"] == str(binding["artifact_id"])
    assert claims["declared:recipe"]["sha256"] == str(binding["content_sha256"])
    assert claims["declared:graph"]["node_ref"] == str(binding["node_ref"])
    assert str(binding["artifact_id"]) != artifact_id
    produced = results["declared"].payload["produced_dataset"]
    assert produced["artifact_id"] != str(binding["artifact_id"])


def test_the_agent_compile_step_refuses_a_malformed_recode(tmp_path: Path) -> None:
    frame = pd.DataFrame({"age": [20.0, 45.0]})
    _project, run_id, artifact_id = _source_project(tmp_path, frame)
    with pytest.raises(OperationValidationError, match="else rule must come last"):
        compile_workflow(
            workflow_id="wf_bad",
            target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
            preconditions={"context_fingerprint": "sha256:fixture"},
            steps=[
                {
                    "step_id": "bad",
                    "operation_id": "data.recode",
                    "spec": {"column": "age", "output": "g", "rules": [{"from": "else", "to": 1}, {"from": 1, "to": 2}]},
                }
            ],
            available_columns=["age"],
        )


def test_the_agent_compile_step_refuses_a_recode_of_an_absent_column(tmp_path: Path) -> None:
    frame = pd.DataFrame({"age": [20.0, 45.0]})
    _project, run_id, artifact_id = _source_project(tmp_path, frame)
    with pytest.raises(OperationValidationError, match="salary"):
        compile_workflow(
            workflow_id="wf_absent",
            target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
            preconditions={"context_fingerprint": "sha256:fixture"},
            steps=[
                {
                    "step_id": "absent",
                    "operation_id": "data.recode",
                    "spec": {"column": "salary", "output": "g", "rules": [{"from": "else", "to": 1}]},
                }
            ],
            available_columns=["age"],
        )


def test_an_undeclared_operation_is_refused_by_the_route(tmp_path: Path) -> None:
    response = TestClient(app).post(
        "/data-operations/transform/preview",
        params={"project_root": str(tmp_path)},
        json={
            "source_run_id": "r", "source_node_id": "n", "source_artifact_id": "a",
            "operation": "not_an_operation", "parameters": {},
        },
    )
    assert response.status_code == 422, response.text
    assert "operation must be one of" in response.json()["error"]["message"]


def test_every_operation_offered_to_the_agent_directly_can_execute() -> None:
    """Offered-but-unexecutable is the worst proposal: it fails after the user
    confirms. Direct proposals must have a dedicated executor; step identities
    are reached through operation.multi_step."""

    from workbench.agent.operations import OperationRegistry

    # The executor branches in WorkbenchOrchestrator's operation executor.
    dedicated = {"model.rerun", "graph.fork", "data.column.cast", "data.columns.cast", "code.execute", "operation.multi_step"}
    registry = OperationRegistry()
    offered = registry.natural_language_operation_ids(scope_requirements=("chain", "active_head"))
    assert "operation.multi_step" in offered
    for operation_id in offered:
        assert registry.require(operation_id).executor_key in dedicated, operation_id
    assert set(registry.proposal_tool_schema()["properties"]["operation_id"]["enum"]) == set(
        registry.natural_language_operation_ids()
    )


def test_natural_language_steps_are_composable_in_a_plan() -> None:
    vocabulary = str(workflow_step_vocabulary())
    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items():
        if contract.natural_language_enabled:
            assert operation_id in vocabulary, operation_id
