"""Declaration-driven reachability registry for the remaining NL gaps."""

from __future__ import annotations

import pytest


def test_live_gap_declarations_have_one_generic_workflow_entry_each() -> None:
    """The denominator is derived from live capability sources, not a copied ID list."""

    from workbench.agent.workflow_capability_registry import (
        declared_workflow_capability_ids,
        workflow_capability_registry,
    )

    declared = declared_workflow_capability_ids()
    registry = workflow_capability_registry()

    assert len(declared) == 18
    assert set(registry.operation_ids()) == set(declared)
    for operation_id in declared:
        operation = registry.require(operation_id)
        assert operation.operation_id == operation_id
        assert operation.adapter_key
        assert operation.input_mode == "frame"
        assert operation.request_schema
        assert callable(operation.validate_request)
        assert callable(operation.execute)
        assert callable(operation.validate_result)


def test_registry_rejects_an_entry_without_a_typed_adapter() -> None:
    """A declaration cannot publish a path whose runtime hook is absent."""

    from workbench.agent.workflow_capability_registry import (
        WorkflowCapabilityOperation,
        WorkflowCapabilityRegistryError,
    )

    with pytest.raises(WorkflowCapabilityRegistryError, match="adapter"):
        WorkflowCapabilityOperation(
            operation_id="test.missing_adapter",
            kind="statistical_test",
            summary="test",
            adapter_key="missing.adapter",
            request_schema={"required": (), "fields": {}},
        )


def test_operation_constructor_does_not_accept_overwritten_callable_hooks() -> None:
    """Adapter behavior comes only from adapter_key, not ignored constructor hooks."""

    from workbench.agent.workflow_capability_registry import WorkflowCapabilityOperation

    with pytest.raises(TypeError, match="validate_request"):
        WorkflowCapabilityOperation(
            operation_id="test.correlations",
            kind="statistical_test",
            summary="test",
            adapter_key="statistical_test",
            request_schema={"required": (), "fields": {}},
            output_schema_ref="test/v1",
            validate_request=lambda request: dict(request),
        )


def test_execute_with_context_validates_request_and_result_exactly_once(monkeypatch) -> None:
    """The operation owns one normalization and one result-validation boundary."""

    from workbench.agent import workflow_capability_adapters as adapters
    from workbench.agent.workflow_capability_adapters import WorkflowCapabilityExecution
    from workbench.agent.workflow_capability_registry import WorkflowCapabilityOperation

    calls = {"request": 0, "execute": 0, "result": 0}

    class CountingAdapter:
        def validate_request(self, operation_id, request):
            calls["request"] += 1
            return dict(request)

        def execute(self, frame, request):
            calls["execute"] += 1
            return WorkflowCapabilityExecution(
                payload={"operation_id": "test.counted", "assumptions": ["test"]}
            )

        def validate_result(self, operation_id, result):
            calls["result"] += 1

    monkeypatch.setattr(
        adapters,
        "get_workflow_capability_adapter",
        lambda adapter_key: CountingAdapter(),
    )
    operation = WorkflowCapabilityOperation(
        operation_id="test.counted",
        kind="statistical_test",
        summary="test",
        adapter_key="counted",
        request_schema={"required": (), "fields": {}},
        output_schema_ref="test/v1",
    )

    normalized, execution = operation.execute_with_context(
        object(),
        {
            "operation_id": "test.counted",
            "input_mode": "frame",
            "column_bindings": {},
            "options": {},
        },
    )

    assert normalized["operation_id"] == "test.counted"
    assert execution.payload["operation_id"] == "test.counted"
    assert calls == {"request": 1, "execute": 1, "result": 1}


def test_generic_registry_publishes_typed_adapter_request_schema() -> None:
    """Agent vocabulary must expose the binding and option shapes each adapter accepts."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    registry = workflow_capability_registry()
    statistical = registry.require("test.correlations").request_schema
    prediction = registry.require("prediction.prediction_ridge").request_schema
    time_series = registry.require("model.time_series.ets").request_schema

    assert statistical["properties"]["column_bindings"]["required"] == ["columns"]
    assert statistical["properties"]["column_bindings"]["properties"]["columns"]["type"] == "array"
    assert prediction["properties"]["column_bindings"]["required"] == ["outcome", "features"]
    assert prediction["properties"]["options"]["properties"]["cv_folds"]["type"] == "integer"
    assert time_series["properties"]["column_bindings"]["required"] == ["time", "value"]
    assert time_series["properties"]["options"]["properties"]["time_index_semantics"]["enum"]


def test_registry_rejects_adapter_output_that_violates_dataset_declaration(monkeypatch) -> None:
    """A producer declaration cannot be bypassed by an adapter result shape."""
    from workbench.agent import workflow_capability_adapters as adapters
    from workbench.agent.workflow_capability_adapters import WorkflowCapabilityExecution
    from workbench.agent.workflow_capability_registry import (
        WorkflowCapabilityRegistryError,
        workflow_capability_registry,
    )

    operation = workflow_capability_registry().require("resample.smote")

    class MissingDatasetAdapter:
        def validate_request(self, operation_id, request):
            return dict(request)

        def execute(self, frame, request):
            return WorkflowCapabilityExecution(
                payload={
                    "operation_id": operation.operation_id,
                    "assumptions": ["test"],
                }
            )

        def validate_result(self, operation_id, result):
            return None

    monkeypatch.setattr(
        adapters,
        "get_workflow_capability_adapter",
        lambda adapter_key: MissingDatasetAdapter(),
    )
    request = operation.validate(
        {
            "operation_id": operation.operation_id,
            "input_mode": "frame",
            "column_bindings": {"outcome": "y", "features": ["x"]},
            "options": {"random_seed": 7},
        }
    )

    with pytest.raises(WorkflowCapabilityRegistryError, match="declares a dataset"):
        operation.execute_with_context(object(), request)


def test_new_workflow_declarations_project_into_agent_and_capability_surfaces() -> None:
    """One live declaration must reach the contract and inventory consumers."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.workflow_contracts import (
        WORKFLOW_STEP_SPEC_CONTRACTS,
        workflow_step_vocabulary,
    )
    from workbench.agent.workflow_capability_registry import (
        declared_workflow_capability_ids,
        workflow_capability_registry,
    )

    operation_id = sorted(declared_workflow_capability_ids())[0]
    entry = workflow_capability_registry().require(operation_id)
    contract = WORKFLOW_STEP_SPEC_CONTRACTS[operation_id]
    definition = OperationRegistry().require(operation_id)
    inventory_entry = next(
        item for item in capability_inventory() if item.capability_id == operation_id
    )

    assert contract.dispatcher_key == "workbench.agent.workflow_runtime.workflow_capability"
    assert operation_id in workflow_step_vocabulary()["step_operations"]
    assert definition.editable_schema == contract.to_schema()
    assert inventory_entry.composable_as == (operation_id,)
    assert inventory_entry.reachability_exempt_reason is None
    assert entry.output_schema_ref == contract.output_schema_ref


def test_prediction_training_dataset_cannot_feed_inference_model() -> None:
    """Dataset roles are server-owned; resampling cannot become inference data."""

    from workbench.agent.operations import OperationValidationError
    from workbench.agent.workflow_contracts import validate_workflow_steps

    steps = [
        {
            "step_id": "resample",
            "operation_id": "resample.smote",
            "spec": {
                "input_mode": "frame",
                "column_bindings": {"outcome": "y", "features": ["x"]},
                "options": {},
            },
        },
        {
            "step_id": "auto",
            "operation_id": "model.auto",
            "spec": {
                "input_mode": "frame",
                "column_bindings": {"outcome": "y", "features": ["x"]},
                "options": {},
                "source": {"from_step": "resample", "output": "produced_dataset"},
            },
        },
    ]

    with pytest.raises(OperationValidationError, match="dataset role.*prediction_training_data"):
        validate_workflow_steps(steps)


def test_prediction_training_dataset_can_feed_prediction_adapter() -> None:
    """The same producer is accepted by the prediction-only consumer."""

    from workbench.agent.workflow_contracts import validate_workflow_steps

    steps = [
        {
            "step_id": "resample",
            "operation_id": "resample.smote",
            "spec": {
                "input_mode": "frame",
                "column_bindings": {"outcome": "y", "features": ["x"]},
                "options": {},
            },
        },
        {
            "step_id": "prediction",
            "operation_id": "prediction.prediction_ridge",
            "spec": {
                "input_mode": "frame",
                "column_bindings": {"outcome": "y", "features": ["x"]},
                "options": {},
                "source": {"from_step": "resample", "output": "produced_dataset"},
            },
        },
    ]

    normalized = validate_workflow_steps(steps)
    assert [item["step_id"] for item in normalized] == ["resample", "prediction"]


def test_prediction_training_dataset_cannot_feed_a_p7_inference_pack() -> None:
    """Prediction-only resampling must not become P7 inference input."""

    from workbench.agent.operations import OperationValidationError
    from workbench.agent.workflow_contracts import validate_workflow_steps

    steps = [
        {
            "step_id": "resample",
            "operation_id": "resample.smote",
            "spec": {
                "input_mode": "frame",
                "column_bindings": {"outcome": "y", "features": ["x"]},
                "options": {},
            },
        },
        {
            "step_id": "p7",
            "operation_id": "categorical.cramers_v",
            "spec": {
                "input_mode": "typed",
                "column_bindings": {"row": "x", "column": "y"},
                "options": {"correction": False},
                "source": {"from_step": "resample", "output": "produced_dataset"},
            },
        },
    ]

    with pytest.raises(OperationValidationError, match="dataset role.*prediction_training_data"):
        validate_workflow_steps(steps)
