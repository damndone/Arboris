from __future__ import annotations

import pytest

from workbench.agent.operations import OperationRegistry, OperationValidationError
from workbench.agent.workflow_contracts import (
    WORKFLOW_STEP_SPEC_CONTRACTS,
    _validate_step_spec,
    validate_workflow_steps,
    workflow_dispatcher_key,
    workflow_step_vocabulary,
)


def test_step_contract_publishes_validation_and_dispatch_metadata() -> None:
    payload = workflow_step_vocabulary()["step_operations"]["model.custom"]

    assert payload["required"] == ["capability_ref", "binding_ref", "operation"]
    assert payload["optional"] == [
        "consumer_slots",
        "expected_artifacts",
        "input_handle",
        "parameters",
    ]
    assert payload["risk_class"] == "high"
    assert payload["confirmation_policy"] == "proposal_authorization"
    assert payload["dispatcher_key"] == "capability_factory.custom_dispatcher"
    assert payload["output_schema_ref"] == "capability_factory.artifact_contract/v1.1"


def test_contract_required_fields_are_checked_before_operation_specific_validation() -> None:
    with pytest.raises(
        OperationValidationError,
        match=r"model.custom spec is missing required field\(s\): binding_ref, operation",
    ):
        _validate_step_spec(
            "model.custom",
            {"capability_ref": "capability:example"},
        )


def test_model_custom_is_a_typed_proposal_step_and_not_an_executor_bypass() -> None:
    steps = validate_workflow_steps(
        [
            {
                "step_id": "custom-model",
                "operation_id": "model.custom",
                "spec": {
                    "capability_ref": "capability:example",
                    "binding_ref": "sha256:binding",
                    "operation": "fit",
                    "input_handle": "graph:dataset",
                    "parameters": {"family": "count"},
                    "consumer_slots": ["report_projection"],
                    "expected_artifacts": ["model_summary"],
                },
            }
        ]
    )

    assert steps[0]["operation_id"] == "model.custom"
    assert WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"].confirmation_policy == (
        "proposal_authorization"
    )


def test_each_registered_step_publishes_one_dispatcher_key() -> None:
    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items():
        assert contract.dispatcher_key
        assert workflow_dispatcher_key(operation_id) == contract.dispatcher_key


def test_workflow_step_registry_projection_is_derived_from_contracts() -> None:
    registry = OperationRegistry()

    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items():
        if operation_id in {"model.genesis", "model.custom"}:
            # These identities have deliberately distinct direct-operation and
            # composable-workflow policy envelopes. The workflow validator and
            # vocabulary remain the source for the child-step envelope; the
            # direct registry identities preserve their existing API contract.
            continue
        definition = registry.require(operation_id)
        schema = definition.editable_schema

        assert set(schema["properties"]) == set(contract.fields)
        assert schema["required"] == list(contract.required)
        assert definition.executor_key == contract.dispatcher_key
        assert definition.confirmation_policy == contract.confirmation_policy
