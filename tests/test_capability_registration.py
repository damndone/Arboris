"""P3 registration seam tests for declaration-derived capability surfaces."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.agent.capability_contract import capability_inventory
from workbench.agent.context_tools import (
    InspectOperationContractRequest,
    NodeOperationContextProvider,
)
from workbench.agent.notebook.planning_agent import NotebookPlanningAgent
from workbench.agent.operations import OperationRegistry
from workbench.agent import workflow_contracts
from workbench.agent.workflow_contracts import (
    WORKFLOW_STEP_SPEC_CONTRACTS,
    StepSpecContract,
    pack_step_contract,
    workflow_proposal_schema,
    workflow_step_operations,
    workflow_step_vocabulary,
)
from workbench.http.agent_routes import _step_vocabulary_lines

from tests.test_agent_data_cast_proposal import _seed_node_index
from tests.test_data_column_cast import _source_project


P7_OPERATION_ID = "repeated_measures_anova.repeated_only"
P7_CORRECTIONS = ("greenhouse_geisser", "huynh_feldt", "none")
P7_EXPOSURE_NOTE = (
    "This pack is composable through operation.multi_step; it is not a top-level proposal."
)
P7_FIELDS = {
    "response_column": "Numeric response column.",
    "subject_column": "Subject identifier column.",
    "within_factor_columns": "One or more within-subject factor columns.",
    "between_factor_column": "Optional between-subject factor column.",
    "correction": "Sphericity correction policy.",
}


def _p7_repeated_only_contract() -> StepSpecContract:
    return pack_step_contract(
        summary="Repeated-measures ANOVA with a repeated-only design.",
        fields=P7_FIELDS,
        required=("response_column", "subject_column", "within_factor_columns", "correction"),
        field_types={
            "response_column": "string",
            "subject_column": "string",
            "within_factor_columns": "list",
            "between_factor_column": "nullable_string",
            "correction": "string",
        },
        field_enums={"correction": P7_CORRECTIONS},
        dispatcher_key="test.p7.repeated_measures_anova.repeated_only",
        output_schema_ref="repeated_measures_anova.result",
        top_level_exposure_note=P7_EXPOSURE_NOTE,
    )


def test_step_spec_payload_and_schema_publish_closed_metadata() -> None:
    contract = _p7_repeated_only_contract()
    payload = contract.to_payload()
    schema = contract.to_schema()

    assert payload["fields"] == P7_FIELDS
    assert payload["field_enums"] == {"correction": list(P7_CORRECTIONS)}
    assert payload["capability_kind"] == "pack"
    assert payload["top_level_exposure_note"] == P7_EXPOSURE_NOTE
    assert payload["produces_dataset"] is False
    assert payload["consumes_input_frame"] is True
    assert payload["replayable_by_recipe"] is False
    assert schema["properties"]["correction"]["enum"] == list(P7_CORRECTIONS)
    assert schema["properties"]["between_factor_column"]["type"] == ["string", "null"]
    assert schema["additionalProperties"] is False


def test_one_registered_capability_reaches_all_hookup_points(monkeypatch) -> None:
    """A single injected P7 declaration must populate every registration surface."""

    monkeypatch.setitem(
        WORKFLOW_STEP_SPEC_CONTRACTS,
        P7_OPERATION_ID,
        _p7_repeated_only_contract(),
    )

    vocabulary = workflow_step_vocabulary()
    assert P7_OPERATION_ID in workflow_step_operations()
    assert P7_OPERATION_ID in workflow_contracts.WORKFLOW_STEP_OPERATIONS
    assert P7_OPERATION_ID in workflow_contracts.STEP_CONSUMES_INPUT_FRAME
    assert P7_OPERATION_ID not in workflow_contracts.STEP_PRODUCES_DATASET
    assert P7_OPERATION_ID not in workflow_contracts.STEP_REPLAYABLE_BY_RECIPE
    assert P7_OPERATION_ID in vocabulary["step_operations"]

    definition = OperationRegistry().require(P7_OPERATION_ID)
    assert (
        definition.editable_schema["properties"]["correction"]["enum"]
        == list(P7_CORRECTIONS)
    )

    proposal_schema = workflow_proposal_schema()
    assert (
        P7_OPERATION_ID
        in proposal_schema["properties"]["changes"]["properties"]["steps"]["items"][
            "properties"
        ]["operation_id"]["enum"]
    )

    inventory_entries = [
        entry
        for entry in capability_inventory()
        if entry.capability_id == P7_OPERATION_ID
    ]
    assert len(inventory_entries) == 1
    assert inventory_entries[0].kind == "pack"
    assert inventory_entries[0].proposed_by == ()
    assert inventory_entries[0].composable_as == (P7_OPERATION_ID,)
    assert inventory_entries[0].reachability_exempt_reason is None
    assert inventory_entries[0].top_level_exposure_note == P7_EXPOSURE_NOTE

    assert vocabulary["step_operations"][P7_OPERATION_ID]["fields"] == P7_FIELDS
    assert (
        vocabulary["step_operations"][P7_OPERATION_ID]["field_enums"]["correction"]
        == list(P7_CORRECTIONS)
    )
    assert P7_OPERATION_ID in _step_vocabulary_lines()


def test_planning_agent_reads_the_injected_shared_vocabulary(monkeypatch) -> None:
    monkeypatch.setitem(
        WORKFLOW_STEP_SPEC_CONTRACTS,
        P7_OPERATION_ID,
        _p7_repeated_only_contract(),
    )

    def _workflow_pins(_context: object) -> dict[str, object]:
        return {
            "genesis_preconditions": {},
            "rerun_preconditions": {},
            "rerun_preconditions_by_target": [],
            "workflow_source": {
                "target": {
                    "run_id": "run_source",
                    "node_ref": "stage:source",
                    "artifact_id": "source_data",
                },
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": "sha256:source",
                    "active_head_run_id": "run_source",
                    "owner_resolution": "single_candidate",
                },
            }
        }

    monkeypatch.setattr(
        NotebookPlanningAgent,
        "_execution_pins",
        staticmethod(_workflow_pins),
    )

    contracts = NotebookPlanningAgent._typed_operation_contracts(object())
    step_operations = contracts["operation.multi_step"]["step_vocabulary"][
        "step_operations"
    ]
    assert P7_OPERATION_ID in step_operations
    assert step_operations[P7_OPERATION_ID]["field_enums"]["correction"] == list(
        P7_CORRECTIONS
    )


def test_context_inspection_reads_the_injected_shared_vocabulary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setitem(
        WORKFLOW_STEP_SPEC_CONTRACTS,
        P7_OPERATION_ID,
        _p7_repeated_only_contract(),
    )
    project, run_id, _artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"response": [1.0], "subject": ["s"], "within": ["a"]}),
    )
    _seed_node_index(project, run_id)

    result = NodeOperationContextProvider(project).inspect_operation_contract(
        InspectOperationContractRequest(
            request_id="request-1",
            owner_run_id=run_id,
            op_node_id="stage:source",
            active_head_run_id=run_id,
            operation_id="operation.multi_step",
        ),
        operation_registry=OperationRegistry(),
    )

    step_operations = result["contract"]["step_vocabulary"]["step_operations"]
    assert P7_OPERATION_ID in step_operations
    assert step_operations[P7_OPERATION_ID]["fields"] == P7_FIELDS
